"""Retrieval: chunking, lexical and dense indexes, and ranked search.

Source-agnostic by design. Nothing here knows what frontmatter is or which
collections exist - a loader turns documents into `Document` values and
everything downstream works on those, which is what will let the context
bundle use the same engine as the corpus.
"""

from __future__ import annotations

from kennis.engine.rag.binding import Binding, document_digest
from kennis.engine.rag.bm25 import Bm25Index
from kennis.engine.rag.cache import VectorCache
from kennis.engine.rag.chunking import ChunkParameters, chunk_document
from kennis.engine.rag.embedding import (
    Embedder,
    ModelBinding,
    embed_texts,
    embedder_for,
    resolve_host,
    validate_binding,
)
from kennis.engine.rag.models import (
    Chunk,
    ChunkPredicate,
    Document,
    Filter,
    FilterOp,
    Metadata,
    SearchResult,
    combine_filters,
)

__all__ = [
    "Binding",
    "Bm25Index",
    "Chunk",
    "ChunkParameters",
    "ChunkPredicate",
    "Document",
    "Embedder",
    "Filter",
    "FilterOp",
    "Metadata",
    "ModelBinding",
    "SearchResult",
    "VectorCache",
    "chunk_document",
    "combine_filters",
    "document_digest",
    "embed_texts",
    "embedder_for",
    "resolve_host",
    "validate_binding",
]
