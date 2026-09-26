"""The frontmatter schema every corpus document carries, declared once.

One base model (`DocumentFrontmatter`) holds what is true of any document in
any collection: its surrogate `id`, the `id_from` key that identifier was
derived from, its `title`, the `owner` guard that decides who may overwrite
it, and a nested `source` block recording where the bytes came from and how
they were converted. Each collection extends the base with exactly one
namespaced block of its own - `bib` for literature, `docs` for documentation
pages, nothing at all for notes, which is the base case.

Nesting is deliberate. A flat layout spells one concept several ways
(`fetched_via`/`fetched_from` on one collection, `source_kind`/`source_path`
on another) and collides with the provenance block, which wants the name
`source` for itself. Namespacing gives every collection one vocabulary.

**`extra="forbid"` on every model.** With pydantic's default an unknown key is
silently dropped, so a document written by a newer kennis - or a pack using a
block an older kennis does not know - would read cleanly and be quietly
missing content. The failure is invisible exactly where it matters.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from kennis.engine.errors import UnknownCollection

# The three corpus collections. `notes` is the base case of ingestion;
# `literature` is notes plus bibliographic processing and `docs` is notes plus
# site-structure processing, which is why a document can sensibly be moved
# between them.
type CollectionName = Literal["literature", "docs", "notes"]

COLLECTION_NAMES: Final[tuple[str, ...]] = ("literature", "docs", "notes")

# How a document's markdown was produced from its source bytes. Distinct from
# `format`: a PDF and a DOCX both arrive via "mineru", and an arXiv paper's
# HTML arrives via "arxiv-html" or "ar5iv" depending on which renderer served
# it.
#
# `remember` is the one value that is not a conversion at all: the markdown
# was given directly rather than produced from source bytes. It is here
# because this is the field that says how a document came to hold the text it
# holds, and "the user told kennis" is an answer to that question which no
# other value gives. Design section 12.
type ConversionVia = Literal[
    "verbatim",
    "html",
    "mineru",
    "arxiv-html",
    "ar5iv",
    "sphinx",
    "crawl",
    "remember",
    # Copied out of the pack store by `corpus sync`. Not a conversion at
    # all - a pack ships markdown - but `via` answers "how did this get
    # here", and "a pack put it there" is a different answer from "a
    # person typed it".
    "pack",
]

# The shape of the source bytes themselves, before conversion.
type SourceFormat = Literal[
    "pdf", "docx", "pptx", "xlsx", "html", "markdown", "text", "code"
]

# Who may overwrite or delete a document: `user` means yours, never touched by
# anything; `pack:<id>` means the named pack's, and is what makes
# `pack remove <id>` possible at all.
#
# An unrecognised value is corruption, not a compatibility case. A document
# carrying an older field's vocabulary is refused with the document named:
# kennis does not guess, does not silently treat it as `user`, and ships no
# migration. Leaving this unstated is how one implementer picks "leave alone,
# leak orphans forever" and another picks "treat as ours, overwrite on
# upgrade".
_OWNER_PATTERN: Final = r"^(?:user|pack:[a-z0-9][a-z0-9._-]*)$"

type Owner = Annotated[str, StringConstraints(pattern=_OWNER_PATTERN)]

_PACK_OWNER = re.compile(r"^pack:(?P<pack_id>[a-z0-9][a-z0-9._-]*)$")


def pack_id_of(owner: str) -> str | None:
    """The pack that owns a document, or None when the owner is the user."""
    matched = _PACK_OWNER.match(owner)
    return matched.group("pack_id") if matched else None


def utc_now() -> datetime:
    """Timezone-aware ingestion timestamp. A module-level function rather than
    an inline lambda so a test can substitute it."""
    return datetime.now(UTC)


class Source(BaseModel):
    """Where a document came from and how it got here.

    `origin` is written to disk as `from`, which is a Python keyword and so
    cannot be a field name. The alias is what makes the design's own spelling
    - `source.from` - expressible, rather than a deviation from it.

    Whether a document is recoverable is read off this field and no other:
    `url:`, `arxiv:` and `doi:` can be refetched, `path:` cannot, because the
    file may be gone or changed. That makes "how bad is it if this document is
    lost" a per-document question rather than a per-collection one.
    """

    # `populate_by_name` so the field name works as well as the alias: a
    # caller constructing a Source in Python writes `origin=`, and only what
    # is read from or written to disk uses `from`.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    origin: str = Field(
        # `validation_alias` and `serialization_alias` rather than one
        # `alias`. A plain `alias` renames the field in the `__init__` that
        # pydantic's `dataclass_transform` advertises, so a type checker
        # demands a keyword argument named `from` - which is a Python keyword
        # and therefore unwritable. Splitting the two keeps the on-disk
        # spelling `from` and leaves the constructor taking `origin`.
        validation_alias="from",
        serialization_alias="from",
        description="url:, path:, arxiv: or doi:, with its value.",
    )
    via: ConversionVia
    format: SourceFormat
    # Absent for documents whose source is not a fixed byte sequence (a live
    # site crawl re-renders per page), present for everything ingested from a
    # file or a single fetched resource.
    sha256: str | None = None
    at: datetime = Field(default_factory=utc_now)
    # Filename of the retained source bytes inside this document's wrapper
    # directory, when the setting to keep originals was on at ingestion time.
    original: str | None = None
    # The digest of the file in the pack store that this document was
    # written from. Present only for `via: pack`, and it is not the same
    # thing as `sha256`: that one is the body kennis wrote, which a user
    # edit moves, and this one is what the provider shipped, which a
    # release moves. One value cannot answer both questions, because a
    # pack file carrying its own frontmatter has that header read and
    # replaced rather than copied.
    pack_sha256: str | None = None


class DocumentFrontmatter(BaseModel):
    """The frontmatter fields every corpus document carries."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    title: str
    owner: Owner
    source: Source
    # The natural key the surrogate identifier was derived from, recorded so
    # the derivation is auditable rather than guessable: a checker can
    # re-derive and compare. Absent means the identifier was minted at random,
    # which is the note case and the only case - a note has no natural key by
    # definition. Frozen with the identifier: if later enrichment finds a
    # higher-precedence key, it is recorded as an ordinary field and this one
    # does not move, because re-minting would break every handle.
    id_from: str | None = None


class NoteFrontmatter(DocumentFrontmatter):
    """A note adds nothing to the base.

    Notes have no natural key by design, so a surrogate identifier and a
    content digest are the whole of their identity.
    """


class Bibliography(BaseModel):
    """Bibliographic facts about a paper.

    None of it is the paper's own text, which is why a pack may ship these
    fields for a paper whose converted markdown may never be redistributed.
    """

    model_config = ConfigDict(extra="forbid")

    citekey: str
    authors: str | None = None
    year: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    # ADS bibcode. The astronomy-native identifier, and the only one a
    # pre-arXiv paper reliably has - recorded so such a paper can still be
    # deduplicated, never resolved, since that needs the ADS API and a key.
    bibcode: str | None = None


class LiteratureFrontmatter(DocumentFrontmatter):
    """Notes plus bibliographic processing.

    Literature refuses a document whose identity it cannot establish, which is
    why `bib` is required rather than optional: an invented citekey cites
    nothing.
    """

    bib: Bibliography


class CrawlScope(BaseModel):
    """How a docs project's pages were discovered.

    Carried on every page rather than in a project-level side file: it is the
    one thing a page cannot otherwise reconstruct about its own project, so
    recording it here keeps a re-crawl from needing the original flags typed
    again, without introducing a second source of truth.
    """

    model_config = ConfigDict(extra="forbid")

    discovery: str | None = None
    exclude: list[str] = Field(default_factory=list)
    path_prefix: str | None = None


class DocsPage(BaseModel):
    """Notes plus site structure: which project a page belongs to, and which
    page of it this is."""

    model_config = ConfigDict(extra="forbid")

    project: str
    page: str
    base_url: str | None = None
    version: str | None = None
    crawl: CrawlScope | None = None


class DocsFrontmatter(DocumentFrontmatter):
    docs: DocsPage


_MODELS: Final[dict[str, type[DocumentFrontmatter]]] = {
    "literature": LiteratureFrontmatter,
    "docs": DocsFrontmatter,
    "notes": NoteFrontmatter,
}


def frontmatter_model_for(collection: str) -> type[DocumentFrontmatter]:
    """The model `collection`'s documents validate against."""
    model = _MODELS.get(collection)
    if model is None:
        raise UnknownCollection(
            f"unknown collection '{collection}'; "
            f"expected one of {', '.join(COLLECTION_NAMES)}"
        )
    return model


def collection_of(frontmatter: DocumentFrontmatter) -> str:
    """Which collection a frontmatter model belongs to.

    The model is the authority on this, so a writer takes the collection from
    the frontmatter it was handed rather than from a separate argument that
    could disagree with it.
    """
    for name, model in _MODELS.items():
        if type(frontmatter) is model:
            return name
    raise UnknownCollection(f"{type(frontmatter).__name__} belongs to no collection")


def unparse_frontmatter(frontmatter: DocumentFrontmatter) -> dict[str, Any]:
    """Serialise a model into the mapping written to disk.

    `mode="json"` renders the timestamp as an ISO string rather than a
    `datetime`, which `yaml.safe_dump` would refuse. `exclude_none` keeps
    optional fields out of the file entirely instead of writing nulls - a note
    ingested from a local file has no `original`, and saying so by omission is
    both smaller and honest.
    """
    return frontmatter.model_dump(mode="json", by_alias=True, exclude_none=True)


def parse_frontmatter(
    collection: str, frontmatter: dict[str, Any]
) -> DocumentFrontmatter:
    """Validate an on-disk mapping against `collection`'s model.

    Raises `pydantic.ValidationError` naming the offending field, which is
    what a corrupted or hand-broken document should produce - loudly, rather
    than by silently sorting under a degenerate key. `document.read_document`
    is what turns that into a domain exception carrying the path.
    """
    return frontmatter_model_for(collection).model_validate(frontmatter)


__all__ = [
    "COLLECTION_NAMES",
    "Bibliography",
    "CollectionName",
    "ConversionVia",
    "CrawlScope",
    "DocsFrontmatter",
    "DocsPage",
    "DocumentFrontmatter",
    "LiteratureFrontmatter",
    "NoteFrontmatter",
    "Owner",
    "Source",
    "SourceFormat",
    "ValidationError",
    "collection_of",
    "frontmatter_model_for",
    "pack_id_of",
    "parse_frontmatter",
    "unparse_frontmatter",
    "utc_now",
]
