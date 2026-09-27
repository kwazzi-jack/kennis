"""`list_corpus`: what is held, rather than what matches a query.

The tool an agent calls before filtering a search - which docs projects
exist, whether a paper is present at all - and the only one that answers
without an index, because it walks the collections directly.

**Counts by default, handles on request.** A corpus of several hundred
documents listed in full is most of a context window spent on something
the caller did not ask for, so `detail="summary"` answers with the shape
and `detail="documents"` answers with the rows.
"""

from __future__ import annotations

from typing import Literal

from kennis.context import existing_corpus
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.schema import COLLECTION_NAMES

type Detail = Literal["summary", "documents"]


def list_corpus(collection: str | None = None, detail: Detail = "summary") -> str:
    """What the corpus holds, by collection.

    Call this to learn what exists before searching for it: which docs
    projects are present, whether a paper was ever added, how much is in
    each collection. It needs no index, so it answers on a corpus that
    has never been indexed.

    `collection` narrows to one of `notes`, `literature` or `docs`.
    `detail="documents"` adds a row per document with the `document_id`
    a `read_*` tool takes - copy one from here, never construct it.

    The `context` bundle is not listed: it lives in the project's
    repository and its files are read with native file tools.
    """
    context = existing_corpus()
    wanted = [collection] if collection else list(COLLECTION_NAMES)
    unknown = [name for name in wanted if name not in COLLECTION_NAMES]
    if unknown:
        # Named rather than silently empty: an agent that mistyped a
        # collection and got "0 documents" would conclude the corpus is
        # empty rather than that it asked the wrong question.
        return (
            f"no collection called '{unknown[0]}'. "
            f"The collections are {', '.join(COLLECTION_NAMES)}."
        )

    lines: list[str] = []
    for name in wanted:
        contents = Collection(root=context.corpus_root, name=name).contents()
        held = contents.documents
        lines.append(f"{name}: {len(held)} document{'' if len(held) == 1 else 's'}")
        if detail == "documents":
            lines.extend(
                f"  {document.id}  {document.md_path.name}" for document in held
            )
        if contents.unreadable:
            # The other half of `contents`, which exists so a caller
            # cannot take the documents without seeing it. An agent told
            # a collection holds twelve when it holds thirteen, one of
            # them broken, has been told something false.
            lines.append(
                f"  ({len(contents.unreadable)} could not be read; "
                f"run `kennis corpus status`)"
            )
    return "\n".join(lines)


__all__ = ["list_corpus"]
