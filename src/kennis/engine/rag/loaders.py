"""Reading a corpus collection into documents the retrieval stack can use.

**This is the only part of the retrieval stack that knows what a corpus looks
like.** Everything downstream - chunking, embedding, indexing, search - works
on `rag.Document` and knows nothing about frontmatter, which is what will let
the context bundle use the same engine without a second implementation.

boepie has three loaders, one per collection, differing in nothing: the only
thing that varies between them is the frontmatter block each collection
carries, and that passes through to `metadata` untouched for filters to reach
with dotted paths. kennis has one, taking a `Collection`. The protocol stays
because the context bundle is a genuinely different source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document as CorpusDocument
from kennis.engine.events import Diagnostic, EventSink, Severity
from kennis.engine.rag.models import Document, Metadata


class Loader(Protocol):
    """Whatever can yield the documents of one named collection."""

    @property
    def name(self) -> str: ...

    def documents(self, *, events: EventSink | None = None) -> list[Document]: ...


class CollectionLoader:
    """One corpus collection, as retrievable documents."""

    def __init__(self, collection: Collection) -> None:
        self._collection = collection

    @property
    def name(self) -> str:
        return self._collection.name

    def documents(self, *, events: EventSink | None = None) -> list[Document]:
        """Every document of the collection that can be read.

        **A document that cannot be read is reported, not skipped.** boepie
        catches the parse failure and continues in silence; milestone 2 spent
        two commits establishing that one hand-edited note must neither cost
        every other operation nor vanish without being mentioned. Indexing a
        corpus with one broken document indexes the rest and says so.
        """
        contents = self._collection.contents()
        if events is not None:
            for facts in contents.unreadable:
                events.emit(
                    Diagnostic(
                        severity=Severity.WARNING,
                        message=(
                            f"{facts.problem}: this document will not be searchable"
                            if facts.problem
                            else f"{facts.md_path} could not be read"
                        ),
                        resolution="kennis corpus status",
                    )
                )
        return [self._document(held) for held in contents.documents]

    def _document(self, held: CorpusDocument) -> Document:
        # `mode="json"` and not a plain dump. A chunk carries this metadata
        # into the index, which is written as JSON, and `source.at` is a
        # datetime in the validated model - dumping it as Python objects
        # would put something unserialisable in there that fails at write
        # time, far from the line that put it there.
        metadata: Metadata = dict(
            held.frontmatter.model_dump(mode="json", by_alias=True)
        )
        # Recorded rather than left to be re-derived from `source_path` at
        # query time: a wrapped document's group is its *wrapper's* parent
        # and not its file's parent, so deriving it would put layout
        # knowledge into the query layer.
        metadata["group"] = self._group_of(held)
        return Document(
            id=held.id,
            text=held.body,
            source_path=self._relative(held.md_path),
            base_path=str(held.wrapper_dir) if held.wrapper_dir else None,
            metadata=metadata,
        )

    def _relative(self, path: Path) -> str:
        """`path` relative to the corpus root, with forward slashes.

        Relative because an absolute path makes every chunk in the index
        point at nothing the moment the corpus is moved, cloned to another
        machine or restored from a backup, while the documents themselves are
        fine. Forward slashes because it is stored and compared as text, so
        it must not depend on which platform wrote the index.

        A path outside the corpus root cannot be made relative to it and is
        returned as it stands: that is not a case kennis can produce, and
        inventing a path would be worse than recording the true one.
        """
        try:
            return path.relative_to(self._collection.root).as_posix()
        except ValueError:
            return path.as_posix()

    def _group_of(self, held: CorpusDocument) -> str:
        """The group this document sits in, as a path below the collection.

        A wrapped document's own directory is the document, not a group, so
        the anchor is the wrapper when there is one and the file otherwise.
        `""` is the collection root.
        """
        anchor = held.wrapper_dir or held.md_path
        try:
            relative = anchor.parent.relative_to(self._collection.path)
        except ValueError:
            return ""
        return "" if relative == Path(".") else relative.as_posix()
