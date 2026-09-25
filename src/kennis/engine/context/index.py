"""Reading a `.context/` bundle into the retrieval engine, and indexing it.

`rag/loaders.py` states the seam this module fits into: everything
downstream of a `Loader` works on `rag.Document` and knows nothing about
where the text came from, "which is what will let the context bundle use the
same engine without a second implementation". So this is one loader and a
thin call to `build_index`, and no retrieval code is duplicated.

Three things a bundle index does differently from a corpus one, all of them
consequences of the bundle being the user's own directory:

- **A document's identity is its path.** There are no surrogate
  identifiers to mint and none should be minted: a context hit's handle is
  the file the reader opens.
- **There is no repository to record.** kennis does not commit to the
  user's repository, so the manifest carries no `built_from` commit and
  freshness is a digest comparison rather than a commit diff.
- **There is no embedding leg.** Design section 13: a hybrid bundle index
  would turn `context init` from an offline scaffold into a model download.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from kennis.engine.context.bundle import index_root_for
from kennis.engine.context.notes import bundle_documents
from kennis.engine.errors import NothingToIndex
from kennis.engine.events import Diagnostic, EventSink, Severity
from kennis.engine.frontmatter import Frontmatter, split_frontmatter
from kennis.engine.rag.binding import Binding
from kennis.engine.rag.chunking import ChunkParameters
from kennis.engine.rag.index import (
    BuildReport,
    LoadedIndex,
    build_index,
    load_index,
)
from kennis.engine.rag.models import Document, Metadata

CONTEXT_COLLECTION = "context"

_FRONTMATTER_DELIMITER = "---"


class BundleLoader:
    """One `.context/` bundle, as retrievable documents."""

    def __init__(self, bundle: Path) -> None:
        self._bundle = bundle

    @property
    def name(self) -> str:
        return CONTEXT_COLLECTION

    def documents(self, *, events: EventSink | None = None) -> list[Document]:
        """Every file in the bundle that counts as knowledge.

        **A header that will not parse costs its metadata and not the file.**
        `CollectionLoader` reports a document it cannot read and does not
        index it, because a corpus document without its frontmatter has no
        identity. A bundle file has one regardless - its path - so the
        stricter rule would throw away text the user wanted found over a
        header they can fix in place.
        """
        return [
            self._document(path, events=events)
            for path in bundle_documents(self._bundle)
        ]

    def _document(self, path: Path, *, events: EventSink | None) -> Document:
        relative = path.relative_to(self._bundle).as_posix()
        text = path.read_text(encoding="utf-8")
        frontmatter, body = self._split(relative, text, events=events)
        metadata: Metadata = dict(frontmatter)
        metadata.setdefault("title", path.stem)
        # Recorded rather than derived at query time, for the reason
        # `CollectionLoader` records it: a filter written against one
        # collection should reach the same key in the other.
        directory = path.parent.relative_to(self._bundle).as_posix()
        metadata["group"] = "" if directory == "." else directory
        return Document(
            id=relative,
            text=body,
            source_path=relative,
            metadata=metadata,
        )

    def _split(
        self, relative: str, text: str, *, events: EventSink | None
    ) -> tuple[Frontmatter, str]:
        """The header and the body, and a diagnostic if the header was lost.

        Three ways to end up with nothing - unterminated, parsing to
        something that is not a mapping, and not being YAML at all, which
        `split_frontmatter` raises for because the corpus path wants it
        fatal. One statement covers all three, and it is the one a reader
        can act on: something here looks like frontmatter and none of it was
        read.

        A file with no `---` line at all is not any of those. It is a file
        without metadata, which is allowed.
        """
        try:
            frontmatter, body = split_frontmatter(text)
        except yaml.YAMLError:
            frontmatter, body = {}, text
        looks_like_frontmatter = text.lstrip().startswith(_FRONTMATTER_DELIMITER)
        if frontmatter or not looks_like_frontmatter:
            return frontmatter, body
        # The body `split_frontmatter` returned in these cases is the whole
        # file, and the diagnostic below returns it unchanged rather than
        # re-deriving it - so that a future change to what it returns on
        # failure is a change in behaviour here too, and not silently
        # discarded by a second copy of the same answer.
        if events is not None:
            events.emit(
                Diagnostic(
                    severity=Severity.WARNING,
                    message=(
                        f"{relative} opens with a frontmatter block that could "
                        "not be read; it is indexed without its metadata"
                    ),
                    resolution="kennis context status",
                )
            )
        return frontmatter, body


def load_bundle_index(bundle: Path) -> LoadedIndex:
    """The bundle's published index, or the error naming what builds one.

    A thin wrapper for one reason: `load_index` names
    `kennis corpus index --collection <name>` when there is no index, which
    is right for a corpus collection and is not a runnable command for a
    bundle - `context` is not one of the three values that option takes.
    Rule 4.4 says a printed command runs as printed, so the translation
    happens here rather than in every caller.
    """
    try:
        return load_index(index_root_for(bundle), CONTEXT_COLLECTION)
    except NothingToIndex as error:
        raise NothingToIndex(
            "this project's context bundle has not been indexed yet",
            resolution="kennis context index",
        ) from error


def index_bundle(
    bundle: Path,
    *,
    chunking: ChunkParameters | None = None,
    events: EventSink | None = None,
) -> BuildReport:
    """Build and publish the bundle's BM25 index.

    `chunking` defaults to the same parameters a corpus uses. Passing
    `model=None` is not a fallback here but the design: `retrieval.
    context_method` will name it explicitly, and until it exists a bundle is
    lexical-only either way.

    Takes no lock and makes no commit. `build_index` stages into a temporary
    directory and writes the pointer only after the swap, so the worst a
    concurrent build can do is waste itself. Concern #236.
    """
    try:
        return build_index(
            BundleLoader(bundle),
            index_root=index_root_for(bundle),
            binding=Binding(chunking=chunking or ChunkParameters(), model=None),
            events=events,
        )
    except NothingToIndex as error:
        # Translated rather than pre-empted by a second emptiness check:
        # `build_index` refuses before it writes anything, and asking the
        # loader for its documents first would read every file twice to
        # learn what it is about to be told. What is added here is the
        # wording, because "the 'context' collection is empty" describes a
        # corpus and a bundle is not one.
        raise NothingToIndex(
            "this project's context bundle has nothing in it to index yet",
            resolution="kennis remember --help",
        ) from error


__all__ = [
    "CONTEXT_COLLECTION",
    "BundleLoader",
    "index_bundle",
    "load_bundle_index",
]
