"""The `.ken.yml` schema, version 1. Design section 7.

**The models are the single declaration.** The published JSON Schema is
generated from them with `model_json_schema()` and committed as
`schema/ken-1.json`, so there is no second source to drift. A test
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
from pathlib import Path
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

from kennis.engine.errors import PackInvalid

type JsonSchema = dict[str, Any]

SCHEMA_VERSION: Final = 1

# Section 7. A trailing dash is permitted by the design's own pattern; the id
# names a directory in the store and appears in `owner: pack:<id>`, and
# neither cares.
_PACK_ID: Final = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_FORBID: Final = ConfigDict(extra="forbid")


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
        if _PACK_ID.match(value) is None:
            raise ValueError(
                f"'{value}' is not a pack id: lowercase letters, digits and "
                "dashes, starting with a letter or a digit"
            )
        return value


class LiteratureEntry(BaseModel):
    """A paper the pack declares, fetched over the network rather than copied.

    The citekey is a handle for humans - it goes in a `.bib`, in prose and in
    a read call. The **identifier** is the identity, which is why at least
    one is required and why section 5 keys the diff on it: correcting a
    citekey against an unchanged identifier is a rename, not a delete and a
    refetch.
    """

    model_config = _FORBID

    citekey: str
    title: str
    arxiv_id: str | None = None
    doi: str | None = None
    bibcode: str | None = None
    authors: str | None = None
    # An int, because `year_min` filtering compares numerically and a string
    # year invites a lexicographic comparison bug at the filter.
    year: int | None = None

    @model_validator(mode="after")
    def _has_an_identifier(self) -> LiteratureEntry:
        if self.arxiv_id is None and self.doi is None and self.bibcode is None:
            raise ValueError(
                f"'{self.citekey}' needs at least one of arxiv_id, doi or "
                "bibcode: a citekey invented from a title cites nothing and "
                "defeats duplicate detection"
            )
        return self


class DocsEntry(BaseModel):
    """A documentation site the pack declares, crawled from `base_url`."""

    model_config = _FORBID

    project: str
    base_url: str
    exclude: list[str] = Field(default_factory=list)


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
        path = Path(value)
        if path.is_absolute():
            raise ValueError(f"'{value}' is absolute; a source is relative to the pack")
        if value.startswith("~"):
            raise ValueError(f"'{value}' names a home directory, not the pack")
        if ".." in path.parts:
            raise ValueError(f"'{value}' leaves the pack root")
        return value


class CorpusSection(BaseModel):
    """The three corpus collections a pack may declare."""

    model_config = _FORBID

    literature: list[LiteratureEntry] = Field(default_factory=list)
    docs: list[DocsEntry] = Field(default_factory=list)
    notes: list[ContentSource] = Field(default_factory=list)


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
    """Written by `pack update`; never hand-edited.

    `at` and `by` are restamped only when a digest actually changed, so a
    provider rebuild that altered nothing leaves the file byte-identical and
    the fast path of section 5 step 2 keeps its short circuit.
    """

    model_config = _FORBID

    at: str
    by: str
    content: GeneratedContent = Field(default_factory=GeneratedContent)


class Pack(BaseModel):
    """A complete, self-describing declaration of what a provider ships."""

    model_config = _FORBID

    kennis: KennisHeader
    pack: PackIdentity
    corpus: CorpusSection = Field(default_factory=CorpusSection)
    context: list[ContentSource] = Field(default_factory=list)
    # Absent until `pack update` has run, so nothing downstream may assume it.
    generated: GeneratedBlock | None = None


def load_pack(text: str) -> Pack:
    """Parse and validate the text of a `.ken.yml` file.

    Raises `PackInvalid` naming the field path, for every failure: YAML that
    does not parse, a document that is not a mapping, and a model that does
    not validate all reach the author the same way. A `yaml.YAMLError`
    escaping the engine would make the caller handle two exception families
    for one question.
    """
    try:
        document = yaml.safe_load(text)
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
    "SCHEMA_VERSION",
    "ContentSource",
    "CorpusSection",
    "DocsEntry",
    "GeneratedBlock",
    "GeneratedContent",
    "GeneratedSource",
    "JsonSchema",
    "KennisHeader",
    "LiteratureEntry",
    "Pack",
    "PackIdentity",
    "load_pack",
    "schema_document",
    "schema_path",
]
