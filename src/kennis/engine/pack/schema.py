"""The `.ken.yml` schema, version 1. Design section 7.

**The models are the single declaration.** The published JSON Schema is
generated from them with `model_json_schema()` and committed as
`src/kennis/schema/ken-1.json`, so there is no second source to drift. A test
regenerates it and compares.

**No aliases anywhere.** The YAML key is the field name, spelled out, so
reading the file and reading the model are the same act. `schema_version`
rather than `schema` also sidesteps pydantic warning that a field named
`schema` shadows a `BaseModel` attribute.

**`extra="forbid"` on every model, including the nested ones.** With
pydantic's default an unknown key is dropped in silence, so a pack using a
section a newer kennis understands would install cleanly on an older one and
be quietly missing content. Section 7 states this for the outer models; the
reason applies to every nested one, and a nested model left on the default
is the same silent drop one level down.

**What this module does not do.** It does not read a pack file from a path,
compare `min_version` against this kennis, check a digest against disk, or
touch a store. Those are the later units of milestone 7, and they are all
stated in terms of these models. In particular `load_pack` accepts a
`schema_version` it does not understand: refusing that is a different
failure with a different fix ("upgrade kennis"), and deciding it here would
mean the models could not be used to read a file in order to report what is
wrong with it.
"""

from __future__ import annotations

import re
from collections.abc import Hashable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from yaml.nodes import MappingNode, ScalarNode

from kennis.engine.docs.versions import checked_version, version_in_address
from kennis.engine.errors import InputError, PackInvalid
from kennis.engine.groups import (
    group_problem,
    project_problem,
    spaces_trimmed,
    tidied,
)
from kennis.engine.literature.identifiers import (
    PaperIdentifier,
    identifier_if_reference,
)
from kennis.engine.pack.versions import SCHEMA_VERSION

type JsonSchema = dict[str, Any]

# Section 7. A trailing dash is permitted by the design's own pattern; the id
# names a directory in the store and appears in `owner: pack:<id>`, and
# neither cares.
_PACK_ID: Final = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def is_pack_id(value: str) -> bool:
    """Whether `value` could name a pack: the rule a pack's own `id` obeys."""
    return _PACK_ID.match(value) is not None


_FORBID: Final = ConfigDict(extra="forbid")


def _inside_the_pack(value: str, *, named: str) -> str:
    """A path a pack declares, relative to the pack file and inside it.

    Both flavours, not the host's `Path`: a pack is written on one platform
    and installed on another. `/etc/passwd` has no drive and is relative to
    Windows; `C:\\x` and `..\\x` are one filename to Linux. An anchor is a
    drive, a root, or both (#385, #403).
    """
    flavours = (PurePosixPath(value), PureWindowsPath(value))
    if any(path.anchor for path in flavours):
        raise ValueError(f"'{value}' is absolute; a {named} is relative to the pack")
    if value.startswith("~"):
        raise ValueError(f"'{value}' names a home directory, not the pack")
    if any(".." in path.parts for path in flavours):
        raise ValueError(f"'{value}' leaves the pack root")
    return value


def _checked_group(value: str | None) -> str | None:
    """A group as every writer applies the rule, so a pack is refused when
    it is read rather than part way through a sync (#435)."""
    if value is None:
        return None
    trimmed = spaces_trimmed(value)
    problem = group_problem(trimmed)
    if problem is not None:
        raise ValueError(f"the group '{value}' {problem}")
    return tidied(trimmed)


class KennisHeader(BaseModel):
    """The two fields that decide whether this kennis may read the file."""

    model_config = _FORBID

    schema_version: int
    # Optional, and an author who forgets it sees no error on their own
    # machine - which is why `extra="forbid"` exists rather than relying on
    # this field alone.
    min_version: str | None = None


class PackIdentity(BaseModel):
    """Who the pack is. `id` is the dedupe key and is stable forever."""

    model_config = _FORBID

    id: str
    name: str = Field(max_length=80)
    version: str
    # Capped because section 11 puts this string into an MCP server's
    # instructions, where its length is a budget rather than a formality.
    description: str | None = Field(default=None, max_length=500)
    homepage: str | None = None

    @field_validator("id")
    @classmethod
    def _is_a_slug(cls, value: str) -> str:
        if not is_pack_id(value):
            raise ValueError(
                f"'{value}' is not a pack id: lowercase letters, digits and "
                "dashes, starting with a letter or a digit"
            )
        return value


class LiteratureEntry(BaseModel):
    """A paper the pack declares, fetched over the network rather than copied.

    The citekey is a handle for humans - it goes in a `.bib`, in prose and in
    a read call. The **identifier** is the identity, which is why one is
    required and why section 5 keys the diff on it: correcting a citekey
    against an unchanged identifier is a rename, not a delete and a refetch.
    It may be left out when `url` names the paper, as an arXiv address does.

    **Only the identifier is required**, as `corpus add 1101.1764` needs
    nothing else (#459). `kennis pack update` derives what an entry leaves
    out - citekey, title, authors, year - as the add would, and writes it
    into the entry, as `uv add` writes into `pyproject.toml` (Brian,
    2026-10-26); a field the entry gives is never overridden.

    **One identifier field**, which takes an arXiv identifier, a DOI or an
    ADS bibcode and is read as whichever it is. Three fields, one per kind,
    asked an author which kind a paper's identifier was and then which wins
    when two were given.

    `url` is where the text is, when the identifier alone does not reach it.
    The document found there must not name a different paper.

    `group` is a folder inside the pack's own, `literature/<pack id>/`,
    and may hold folders of its own.
    """

    model_config = _FORBID

    citekey: str | None = None
    title: str | None = None
    identifier: str | None = None
    url: str | None = None
    # The paper's document shipped in the pack, relative to the pack file:
    # for a paper whose text no address reaches, such as one behind a
    # publisher (Brian, 2026-10-26). Excludes `url`.
    file: str | None = None
    group: str | None = None
    authors: str | None = None
    # An int, because `year_min` filtering compares numerically and a string
    # year invites a lexicographic comparison bug at the filter.
    year: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _one_identifier_field(cls, data: object) -> object:
        """Name the replacement for the three fields packs used to have.

        No compatibility before 1.0, so they are refused - but with the
        field to write instead, not "extra inputs are not permitted".
        """
        if isinstance(data, dict):
            for retired in _RETIRED_IDENTIFIER_FIELDS:
                if retired in data:
                    raise ValueError(
                        f"'{retired}' is now 'identifier', one field that takes "
                        "an arXiv identifier, a DOI or an ADS bibcode"
                    )
        return data

    @field_validator("identifier")
    @classmethod
    def _an_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if identifier_if_reference(value) is None:
            raise ValueError(
                f"'{value}' is not an arXiv identifier, a DOI or an ADS bibcode"
            )
        return value.strip()

    @field_validator("group")
    @classmethod
    def _stays_inside_the_packs_folder(cls, value: str | None) -> str | None:
        return _checked_group(value)

    @field_validator("url")
    @classmethod
    def _an_address(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError(f"'{value}' is not an http or https address")
        return value

    @field_validator("file")
    @classmethod
    def _a_file_in_the_pack(cls, value: str | None) -> str | None:
        return None if value is None else _inside_the_pack(value, named="file")

    @model_validator(mode="after")
    def _names_a_paper(self) -> LiteratureEntry:
        if self.url is not None and self.file is not None:
            raise ValueError(
                "give `url` or `file`, not both: each says where the paper's text is"
            )
        if self.file is not None and self.identifier is None:
            raise ValueError(
                "a paper shipped as a file needs `identifier`, an arXiv "
                "identifier, a DOI or an ADS bibcode, which says which paper "
                "it is"
            )
        if self.identifier is None and (
            self.url is None or identifier_if_reference(self.url) is None
        ):
            named = f"'{self.url}' names no paper" if self.url else "nothing names it"
            raise ValueError(
                f"{named}: give `identifier`, an arXiv identifier, a DOI or an "
                "ADS bibcode"
            )
        return self

    @property
    def paper(self) -> PaperIdentifier:
        """The identifier, read as the kind it is, or the one `url` names."""
        parsed = identifier_if_reference(self.identifier or self.url or "")
        # Checked when the entry was made, so there is always one.
        assert parsed is not None
        return parsed

    @property
    def key(self) -> str:
        """What a sync diffs this declaration on: the identifier with its
        kind, never the citekey. The kind is part of it so a DOI and an
        arXiv identifier that happen to share a string cannot collide."""
        return f"{self.paper.kind}:{self.paper.value}"


_RETIRED_IDENTIFIER_FIELDS: Final = ("arxiv_id", "doi", "bibcode")


class DocsEntry(BaseModel):
    """A documentation site the pack declares, crawled from `base_url`."""

    model_config = _FORBID

    project: str
    # The site, crawled from here; or `pages`, files shipped in the pack and
    # filed into the project as `corpus add -d <file>` files one. Exactly
    # one of the two.
    base_url: str | None = None
    pages: list[str] = Field(default_factory=list)
    # Which version of the documentation, filed as `docs/<project>/<version>/`
    # (#489). Read from `base_url` when it is left out; a pack whose address
    # names none must say.
    version: str | None = None
    exclude: list[str] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _names_a_folder(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            return checked_version(value)
        except InputError as error:
            raise ValueError(str(error)) from error

    @field_validator("pages")
    @classmethod
    def _pages_in_the_pack(cls, value: list[str]) -> list[str]:
        return [_inside_the_pack(page, named="page") for page in value]

    @model_validator(mode="after")
    def _has_a_version(self) -> DocsEntry:
        if (self.base_url is None) == (not self.pages):
            raise ValueError(
                "give `base_url`, the site to crawl, or `pages`, files in the "
                "pack - exactly one of the two"
            )
        if self.base_url is None:
            if self.version is None:
                raise ValueError(
                    "local pages name no version of the documentation: add "
                    "`version:`, such as `version: latest`"
                )
            return self
        if self.version is None and version_in_address(self.base_url) is None:
            raise ValueError(
                f"'{self.base_url}' names no version of the documentation: "
                "add `version:`, such as `version: latest`"
            )
        return self

    @field_validator("project")
    @classmethod
    def _names_a_folder_inside_docs(cls, value: str) -> str:
        # A project is the directory its pages are written to: a group by
        # another name, and one folder deep.
        trimmed = spaces_trimmed(value)
        problem = project_problem(trimmed)
        if problem is not None:
            raise ValueError(f"the project '{value}' {problem}")
        return tidied(trimmed) or trimmed


class ContentSource(BaseModel):
    """A directory of markdown the pack ships, copied verbatim.

    `source` is validated here only as far as a string can be: relative, no
    parent segments, no home reference. Whether a file *discovered* under it
    resolves inside the pack root is a filesystem question, and it is asked
    by the walk rather than by the model - a symlink is invisible to this
    check by construction.
    """

    model_config = _FORBID

    source: str
    group: str | None = None
    include: list[str] = Field(default_factory=lambda: ["**/*.md"])
    exclude: list[str] = Field(default_factory=list)

    @field_validator("source")
    @classmethod
    def _stays_under_the_pack_root(cls, value: str) -> str:
        return _inside_the_pack(value, named="source")

    @field_validator("group")
    @classmethod
    def _stays_inside_its_collection(cls, value: str | None) -> str | None:
        # The same rule every writer applies, so a pack is refused when it
        # is read rather than part way through a sync.
        return _checked_group(value)


class NoteLink(BaseModel):
    """A note the pack declares by its address, fetched at `corpus sync`.

    Converted as `corpus add -n <url>` converts it, so a pack can declare
    whatever a person can add (#459). Told apart from a `ContentSource` by
    its required key: each forbids the other's, so an entry naming both is
    neither.

    `title` names the note when given; otherwise the page's own title does.
    `group` is a folder inside the pack's own, `notes/<pack id>/`.
    """

    model_config = _FORBID

    url: str
    title: str | None = None
    group: str | None = None

    @field_validator("url")
    @classmethod
    def _an_address(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError(f"'{value}' is not an http or https address")
        return value

    @field_validator("group")
    @classmethod
    def _stays_inside_the_packs_folder(cls, value: str | None) -> str | None:
        return _checked_group(value)

    @property
    def key(self) -> str:
        """What a sync diffs this declaration on, and the address recorded in
        the note's `source.from`: the address, marked as one so it cannot
        collide with a file's path in the store."""
        return f"url:{self.url}"


class NoteFile(BaseModel):
    """One note the pack ships as a file, converted at `corpus sync` as
    `corpus add -n <file>` converts it (Brian, 2026-10-26).

    A `source:` folder ships a tree; this ships one file and may name it.
    Each of the three notes models forbids the others' keys, so an entry is
    exactly one of them. `group` is a folder inside `notes/<pack id>/`.
    """

    model_config = _FORBID

    file: str
    title: str | None = None
    group: str | None = None

    @field_validator("file")
    @classmethod
    def _a_file_in_the_pack(cls, value: str) -> str:
        return _inside_the_pack(value, named="file")

    @field_validator("group")
    @classmethod
    def _stays_inside_the_packs_folder(cls, value: str | None) -> str | None:
        return _checked_group(value)

    @property
    def key(self) -> str:
        """What a sync diffs this declaration on: the path, marked as a
        file so it cannot collide with an address inside a `source:`."""
        return f"file:{self.file}"


class CorpusSection(BaseModel):
    """The three corpus collections a pack may declare."""

    model_config = _FORBID

    literature: list[LiteratureEntry] = Field(default_factory=list)
    docs: list[DocsEntry] = Field(default_factory=list)
    notes: list[ContentSource | NoteLink | NoteFile] = Field(default_factory=list)

    @property
    def note_sources(self) -> list[ContentSource]:
        """The folders of notes the pack ships, copied into the store."""
        return [entry for entry in self.notes if isinstance(entry, ContentSource)]

    @property
    def note_links(self) -> list[NoteLink]:
        """The notes the pack declares by address, fetched at sync."""
        return [entry for entry in self.notes if isinstance(entry, NoteLink)]

    @property
    def note_files(self) -> list[NoteFile]:
        """The notes the pack ships one file at a time."""
        return [entry for entry in self.notes if isinstance(entry, NoteFile)]


class GeneratedSource(BaseModel):
    """The digests of one source's files, keyed by path relative to it."""

    model_config = _FORBID

    source: str
    files: dict[str, str] = Field(default_factory=dict)


class GeneratedContent(BaseModel):
    """Digests nested by section and source.

    Nested rather than a flat map because section 5 keys content on its
    **destination**: the same relative path under `notes/` and under
    `content/` is two different documents, and a bare path could belong to
    either.
    """

    model_config = _FORBID

    context: list[GeneratedSource] = Field(default_factory=list)
    notes: list[GeneratedSource] = Field(default_factory=list)


class GeneratedBlock(BaseModel):
    """Written by `pack update`; never hand-edited. Checksums alone, which
    are a lock file's job: what a person might want to read or change - a
    paper's citekey - is written into its entry instead.

    `at` and `by` are restamped only when a digest actually changed, so a
    provider rebuild that altered nothing leaves the file byte-identical and
    the fast path of section 5 step 2 keeps its short circuit.
    """

    model_config = _FORBID

    @model_validator(mode="before")
    @classmethod
    def _no_paper_records(cls, data: object) -> object:
        """Name what to do with a block written before papers were described
        in their entries. No compatibility before 1.0, so it is refused,
        with the way out rather than "extra inputs are not permitted"."""
        if isinstance(data, dict) and "literature" in data:
            raise ValueError(
                "'generated.literature' is no longer kept: `kennis pack "
                "update` writes each paper's citekey, title, authors and year "
                "into its entry. Delete the block's `literature:` and run "
                "`kennis pack update`"
            )
        return data

    at: str
    by: str
    content: GeneratedContent = Field(default_factory=GeneratedContent)
    # The checksum of every file a `file:` or `pages:` names, by its path
    # relative to the pack file.
    files: dict[str, str] = Field(default_factory=dict)


class Pack(BaseModel):
    """A complete, self-describing declaration of what a provider ships."""

    model_config = _FORBID

    kennis: KennisHeader
    pack: PackIdentity
    corpus: CorpusSection = Field(default_factory=CorpusSection)
    context: list[ContentSource] = Field(default_factory=list)
    # Absent until `pack update` has run, so nothing downstream may assume it.
    generated: GeneratedBlock | None = None

    @property
    def shipped_files(self) -> tuple[str, ...]:
        """Every path a `file:` or `pages:` names, in declaration order:
        papers, then notes, then documentation pages."""
        return (
            *(entry.file for entry in self.corpus.literature if entry.file),
            *(entry.file for entry in self.corpus.note_files),
            *(page for entry in self.corpus.docs for page in entry.pages),
        )


class _RepeatedKey(yaml.YAMLError):
    def __init__(self, key: Hashable, first_line: int, second_line: int) -> None:
        super().__init__(f"{key!r} is given twice")
        self.key = key
        self.first_line = first_line
        self.second_line = second_line


class _UniqueKeyLoader(yaml.SafeLoader):
    """`safe_load`'s loader, refusing a mapping that gives a key twice.

    PyYAML keeps the last of two equal keys in silence (#547), and YAML 1.2
    requires them unique. The keys are compared as written, before
    `flatten_mapping` expands `<<`, so a merged key overridden once is YAML's
    override and not a repeat; `<<` itself is passed over because it has no
    constructor of its own, being only an instruction to `flatten_mapping`.
    """

    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[Hashable, Any]:
        seen: dict[Hashable, int] = {}
        for key_node, _ in node.value:
            if not isinstance(key_node, ScalarNode) or key_node.value == "<<":
                continue
            key = self.construct_object(key_node)
            line = key_node.start_mark.line + 1
            if key in seen:
                raise _RepeatedKey(key, seen[key], line)
            seen[key] = line
        return super().construct_mapping(node, deep=deep)


def read_yaml(text: str) -> object:
    """The YAML document `text` holds, refusing a key given twice."""
    return yaml.load(text, Loader=_UniqueKeyLoader)


def load_pack(text: str) -> Pack:
    """Parse and validate the text of a `.ken.yml` file.

    Raises `PackInvalid` naming the field path, for every failure: YAML that
    does not parse, a document that is not a mapping, and a model that does
    not validate all reach the author the same way. A `yaml.YAMLError`
    escaping the engine would make the caller handle two exception families
    for one question.
    """
    try:
        document = read_yaml(text)
    except _RepeatedKey as repeated:
        raise PackInvalid(
            f"`{repeated.key}` is given twice in one mapping, on lines "
            f"{repeated.first_line} and {repeated.second_line}; YAML allows a "
            "key once, so delete the one you do not mean"
        ) from repeated
    except yaml.YAMLError as error:
        raise PackInvalid(f"this is not YAML: {error}") from error
    if not isinstance(document, dict):
        kind = type(document).__name__
        raise PackInvalid(f"a pack file is a mapping of sections, not a {kind}")
    try:
        return Pack.model_validate(document)
    except ValidationError as error:
        raise PackInvalid(_field_paths(error)) from error


def schema_path() -> Path:
    """The JSON Schema kennis ships, inside the installed package.

    Section 18: `pack validate` uses this local copy, so validation is
    authoritative and never needs the network. The path is versioned, so
    schema 1 never changes meaning and schema 2 is a new file beside it.
    """
    return Path(__file__).resolve().parents[2] / "schema" / f"ken-{SCHEMA_VERSION}.json"


def schema_document() -> JsonSchema:
    """The JSON Schema as the models define it, regenerated."""
    return Pack.model_json_schema()


def _field_paths(error: ValidationError) -> str:
    """Every failure as `section.field: reason`, one per line."""
    lines = [
        f"{'.'.join(str(part) for part in failure['loc'])}: {failure['msg']}"
        for failure in error.errors()
    ]
    return "\n".join(lines)


__all__ = [
    "ContentSource",
    "CorpusSection",
    "DocsEntry",
    "GeneratedBlock",
    "GeneratedContent",
    "GeneratedSource",
    "JsonSchema",
    "KennisHeader",
    "LiteratureEntry",
    "NoteFile",
    "NoteLink",
    "Pack",
    "PackIdentity",
    "is_pack_id",
    "load_pack",
    "read_yaml",
    "schema_document",
    "schema_path",
]
