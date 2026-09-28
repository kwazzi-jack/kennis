"""Searching one scope: where the index is, which mode it can run.

Beside `context.py` and `logs.py`, and there for the same reason
concern #292 gives: these are questions every front end asks and no
front end owns. The MCP server had them privately; the graphical
interface asks exactly the same ones and may not import the server,
so keeping them there would have made one front end the other's
library - which design section 20 says none of them is.

The command line is deliberately not moved onto this. It sweeps every
scope and reports which it skipped and why, which is a different
operation from "search this one and fail if it has no index".
"""

from __future__ import annotations

from kennis.context import Context, existing_corpus, resolve_context
from kennis.engine.context.bundle import find_bundle
from kennis.engine.context.index import CONTEXT_COLLECTION, load_bundle_index
from kennis.engine.corpus.layout import index_root
from kennis.engine.errors import ContextNotFound, KennisError
from kennis.engine.rag.embedding import resolve_host
from kennis.engine.rag.index import LoadedIndex, load_index
from kennis.engine.rag.search import Mode, search
from kennis.render.hits import Hit, basis_for

# The most a caller may ask for. A ceiling rather than a validation
# error: a caller asking for 500 wants "lots", and refusing them is
# less useful than giving them the most that is sensible.
MAX_TOP_K = 20


def context_for(collection: str) -> Context:
    """The context a search of `collection` runs in.

    The bundle scope resolves a project and the others require a
    corpus, which is the one thing that differs between them.
    """
    return resolve_context() if collection == CONTEXT_COLLECTION else existing_corpus()


def search_scope(collection: str, question: str, top_k: int = 5) -> list[Hit]:
    """The best hits for `question` in exactly one scope.

    Raises `ContextNotFound` outside a project when the scope is the
    bundle, and `NothingToIndex` when the scope has no index. **A
    named scope with no index is an error here**, where the command
    line's sweep skips it: a caller asking about one scope and told
    "no hits" for an index that was never built has been told
    something false.
    """
    context = context_for(collection)
    index = index_for(context, collection)
    model = index.binding.model.model if index.binding.model else None
    running = mode_for(context, index, collection)
    results = search(
        index,
        question,
        top_k=max(1, min(top_k, MAX_TOP_K)),
        filters=None,
        mode=running,
        host=resolve_host(
            index.binding.model.kind if index.binding.model else "",
            context.settings.embedding.base_url or None,
        ),
    )
    basis = basis_for(model, dense_ran=running != "bm25")
    return [
        Hit(collection=collection, result=result, basis=basis, model=model)
        for result in results
    ]


def index_for(context: Context, collection: str) -> LoadedIndex:
    if collection == CONTEXT_COLLECTION:
        bundle = find_bundle()
        if bundle is None:
            raise ContextNotFound
        return load_bundle_index(bundle)
    return load_index(index_root(context.corpus_root), collection)


def mode_for(context: Context, index: LoadedIndex, collection: str) -> Mode:
    """The mode this index can actually run.

    A bundle has its own setting, because a dense bundle index costs
    what `retrieval.context_method` exists to avoid. Either way an
    index with no vectors runs lexically rather than failing: a fresh
    install may have no embedding backend at all.
    """
    asked = (
        context.settings.retrieval.context_method
        if collection == CONTEXT_COLLECTION
        else context.settings.retrieval.corpus_method
    )
    if index.matrix is None:
        return "bm25"
    return "bm25" if asked == "bm25" else "dense" if asked == "dense" else "hybrid"


def chunk_range(
    context: Context, collection: str, document_id: str, chunk_index: int
) -> tuple[int, int] | None:
    """Where one chunk of one document starts and ends, in characters.

    `Chunk` records `char_start` and `char_end` when the index is
    built, so this is a lookup and not a computation - which is why
    a reader can mark a passage exactly without re-chunking anything.

    `None` rather than an exception for every way of not finding it:
    an absent index, an unindexed document and a chunk number typed
    into a query string are three different situations with one
    answer for the caller, which is to show the document unmarked.
    The reader must not lose the page over the mark.

    Here rather than in a front end because it is the same question
    #292's other two were: every front end that shows a document
    beside a search result will ask it, and none of them owns it.
    """
    if chunk_index < 0:
        return None
    try:
        index = index_for(context, collection)
    except KennisError:
        return None
    for chunk in index.chunks:
        if chunk.document_id == document_id and chunk.chunk_index == chunk_index:
            return (chunk.char_start, chunk.char_end)
    return None


__all__ = [
    "MAX_TOP_K",
    "chunk_range",
    "context_for",
    "index_for",
    "mode_for",
    "search_scope",
]
