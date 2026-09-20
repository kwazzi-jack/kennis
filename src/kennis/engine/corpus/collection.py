"""One corpus collection: what is in it, and how a handle finds a document.

A document is addressed by an opaque surrogate identifier, but what people and
curated notes actually write down is a citekey, an arXiv identifier, a DOI, a
`project/page` pair or a title. Resolving those keeps such references working
without giving up the identifier's stability across renames.

Two rules make resolution safe rather than merely convenient:

- **The literal identifier is tried first**, so a real identifier is never
  shadowed by a document whose citekey happens to spell it.
- **A key that two documents share is dropped**, not resolved arbitrarily. An
  ambiguous alias addresses nothing, which is the honest answer and the one a
  reader can act on; guessing would silently hand back the wrong paper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kennis.engine.corpus.document import Document, read_document, remove_document
from kennis.engine.corpus.layout import collection_root, iter_documents
from kennis.engine.corpus.schema import (
    DocsFrontmatter,
    DocumentFrontmatter,
    LiteratureFrontmatter,
)
from kennis.engine.errors import DocumentNotFound


@dataclass(frozen=True, slots=True)
class Collection:
    """The documents under one collection of a corpus.

    Nothing is cached: `documents()` walks and re-validates on every call.
    That is the right default while a command invocation holds the corpus lock
    for its whole run, and it means a caller can never read a document that
    was deleted underneath it. An index is what makes repeated reads cheap,
    and it arrives with search.
    """

    root: Path
    name: str
    _path: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # `collection_root` is what refuses an unknown collection name, so
        # constructing a Collection is where that failure surfaces rather than
        # at the first walk.
        object.__setattr__(self, "_path", collection_root(self.root, self.name))

    @property
    def path(self) -> Path:
        """The directory this collection's documents live under."""
        return self._path

    def documents(self) -> list[Document]:
        """Every document in the collection, walked and validated.

        Raises `DocumentInvalid` on the first document that fails validation,
        naming it. A corpus with one broken document is a thing to be told
        about, not to be silently served nine tenths of.
        """
        return [
            read_document(location.md_path, collection=self.name)
            for location in iter_documents(self._path)
        ]

    def aliases(self) -> dict[str, str]:
        """Human-writable keys mapped to surrogate identifiers.

        Built from the walk in one pass. Lowercased variants are included so
        casing need not be remembered exactly. A key that would map to two
        different documents is absent entirely.
        """
        candidates: dict[str, set[str]] = {}

        def record(key: object, document_id: str) -> None:
            if not isinstance(key, str) or not key:
                return
            for variant in (key, key.lower()):
                candidates.setdefault(variant, set()).add(document_id)

        for document in self.documents():
            for key in _alias_keys(document.frontmatter):
                record(key, document.id)

        return {
            key: next(iter(identifiers))
            for key, identifiers in candidates.items()
            if len(identifiers) == 1
        }

    def resolve(self, handle: str) -> Document:
        """The document `handle` addresses, by identifier or by alias.

        Raises `DocumentNotFound` when nothing matches, and equally when the
        handle is ambiguous - two documents sharing a key make that key
        useless, and the answer is that it addresses nothing.
        """
        documents = self.documents()
        for document in documents:
            if document.id == handle:
                return document

        aliases = self.aliases()
        resolved = aliases.get(handle) or aliases.get(handle.lower())
        if resolved is not None:
            for document in documents:
                if document.id == resolved:
                    return document

        raise DocumentNotFound(f"no document '{handle}' in the {self.name} collection")

    def remove(self, document: Document) -> None:
        """Delete one document and its assets."""
        remove_document(document)


def _alias_keys(frontmatter: DocumentFrontmatter) -> list[str]:
    """Every human-writable key one document answers to.

    The title is included because it is what a reader writes down when they
    have nothing else, and it is also the key most likely to be ambiguous -
    which is exactly why ambiguity drops the key rather than picking a winner.
    """
    keys: list[str] = [frontmatter.title]
    if isinstance(frontmatter, LiteratureFrontmatter):
        keys += [
            frontmatter.bib.citekey,
            frontmatter.bib.arxiv_id or "",
            frontmatter.bib.doi or "",
            frontmatter.bib.bibcode or "",
        ]
    elif isinstance(frontmatter, DocsFrontmatter):
        keys.append(f"{frontmatter.docs.project}/{frontmatter.docs.page}")
    return [key for key in keys if key]
