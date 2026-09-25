"""Building an index, and publishing it atomically.

Every piece of the retrieval stack meets here. The loader reads a collection,
the chunker cuts it, the cache answers for the documents that have not
changed, the backend embeds the rest, and the result is staged and swapped
into place.

**The ordering is the design, and all of it is about being interrupted.**

1. The collection is refused before anything is written if there is nothing
   in it to index.
2. Vectors are asked of the cache per document and **written back per
   document**, so an interrupt costs the in-flight document rather than the
   run. A build that aborts leaves cached vectors for an index that was never
   published; that is harmless, and it is what makes the next attempt cheap.
3. Everything is staged into a temporary directory and swapped in at the end.
   Embedding a corpus takes minutes, and deleting the previous index first
   meant an interrupt left the collection with no index at all - strictly
   worse than never having run the command.
4. The pointer is written **after** the swap, never before. It is what makes
   an index findable, so writing it over a directory that is still being
   built is the one ordering that could serve a half-built index.
5. The cache is pruned last, because only a build that completed knows which
   documents are current.

The vector cache is a **sibling** of the index directory rather than a child.
The swap replaces what it stages, so a cache inside the index would be
destroyed by the build it exists to make cheap.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np

from kennis.engine._atomic import replace_file, replacing_directory
from kennis.engine.errors import NothingToIndex
from kennis.engine.events import (
    EventSink,
    OperationFinished,
    Outcome,
    Progress,
)
from kennis.engine.history.repository import Repository
from kennis.engine.rag.binding import Binding, document_digest
from kennis.engine.rag.bm25 import Bm25Index
from kennis.engine.rag.cache import VectorCache
from kennis.engine.rag.chunking import chunk_document
from kennis.engine.rag.embedding import Embedder, embed_texts, embedder_for
from kennis.engine.rag.loaders import Loader
from kennis.engine.rag.models import Chunk, Document

_CHUNKS_FILE: Final = "chunks.jsonl"
_BM25_DIR: Final = "bm25"
_VECTORS_FILE: Final = "embeddings.npy"
_BINDING_FILE: Final = "binding.json"
_MANIFEST_FILE: Final = "manifest.json"
_POINTER_FILE: Final = "latest.json"
_CACHE_DIR: Final = "vectors"

# The index directory name for a collection built without a dense leg.
_LEXICAL_ONLY: Final = "bm25"

# One document, its digest, and the chunks it produced - carried together
# because every later step needs all three and recomputing any of them
# would be a second source of truth.
type _Chunked = tuple[Document, str, list[Chunk]]


@dataclass(frozen=True, slots=True)
class BuildReport:
    """What one build did."""

    collection: str
    index_id: str
    index_dir: Path
    document_count: int
    chunk_count: int
    # Documents whose vectors had to be computed. The rest came from the
    # cache, which is the whole point of having one.
    embedded_count: int
    pruned_count: int
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class LoadedIndex:
    """An index read back from disk, ready to be searched."""

    collection: str
    chunks: list[Chunk]
    bm25: Bm25Index
    binding: Binding
    # None for a lexical-only index.
    matrix: np.ndarray | None


def index_id_for(binding: Binding) -> str:
    """The directory name an index built with `binding` lives in.

    Derived from the embedding model alone, deliberately, so that switching
    model and switching back does not destroy either index. It does **not**
    encode the chunk parameters: `binding.json` is what detects that kind of
    disagreement, and putting the whole binding in a directory name would
    accumulate one directory per experiment.
    """
    if binding.model is None:
        return _LEXICAL_ONLY
    slug = re.sub(r"[^a-z0-9]+", "-", binding.model.model.lower()).strip("-")
    return f"{binding.model.kind}-{slug}"


def build_index(
    loader: Loader,
    *,
    index_root: Path,
    binding: Binding,
    embedder: Embedder | None = None,
    events: EventSink | None = None,
    embed_batch_size: int = 64,
    repository: Repository | None = None,
) -> BuildReport:
    """Build and publish the index for one collection.

    `embedder` is supplied by the caller so a test hands over something that
    never downloads a model; left out, one is resolved from the binding, and
    for a lexical-only binding none is needed at all.

    `repository` is the corpus's git repository, whose current commit is
    recorded as what this index was built from. Left out - by a test, or by
    a caller indexing something that is not a corpus - the manifest records
    no commit and freshness reads as unverifiable rather than as fresh.
    """
    started_at = time.monotonic()
    collection_root = index_root / loader.name

    documents = loader.documents(events=events)
    chunked = [
        (
            document,
            document_digest(document.text),
            chunk_document(
                document, collection=loader.name, parameters=binding.chunking
            ),
        )
        for document in documents
    ]
    chunks = [chunk for _, _, produced in chunked for chunk in produced]
    _refuse_if_empty(loader.name, documents, chunks)

    cache = VectorCache(root=collection_root / _CACHE_DIR, binding=binding)
    matrix, embedded = _vectors_for(
        chunked, binding, cache, embedder, embed_batch_size, events
    )

    index_id = index_id_for(binding)
    index_dir = collection_root / index_id
    with replacing_directory(index_dir) as staging:
        _write_chunks(staging / _CHUNKS_FILE, chunks)
        Bm25Index.build([chunk.text for chunk in chunks]).save(staging / _BM25_DIR)
        if matrix is not None:
            np.save(staging / _VECTORS_FILE, matrix)
        replace_file(staging / _BINDING_FILE, json.dumps(binding.recorded(), indent=2))
        replace_file(
            staging / _MANIFEST_FILE,
            json.dumps(
                {
                    "collection": loader.name,
                    "index_id": index_id,
                    "chunk_count": len(chunks),
                    # The commit this index was built from. Freshness is a
                    # diff between it and HEAD, which is O(changed files)
                    # rather than O(corpus).
                    "built_from": repository.head() if repository else None,
                    "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    # The digests a later staleness check compares against
                    # the corpus: there is one notion of "this document's
                    # current text" in the system.
                    #
                    # **Keyed by source path, not by identifier.** Freshness
                    # starts from the paths git reports as changed, and a
                    # corpus identifier is a surrogate that no path carries -
                    # so a map keyed by it could not be looked up from a
                    # diff. For a bundle the two are the same string anyway.
                    "documents": {
                        document.source_path: digest for document, digest, _ in chunked
                    },
                },
                indent=2,
            ),
        )

    # After the swap, never before.
    replace_file(
        collection_root / _POINTER_FILE, json.dumps({"index_id": index_id}, indent=2)
    )

    pruned = cache.prune(
        keep={document.id for document, _, _ in chunked},
        digests={document.id: digest for document, digest, _ in chunked},
    )

    report = BuildReport(
        collection=loader.name,
        index_id=index_id,
        index_dir=index_dir,
        document_count=len(documents),
        chunk_count=len(chunks),
        embedded_count=embedded,
        pruned_count=pruned,
        elapsed_seconds=time.monotonic() - started_at,
    )
    if events is not None:
        events.emit(
            OperationFinished(
                operation="index",
                elapsed_seconds=report.elapsed_seconds,
                counts={Outcome.CHANGED: report.chunk_count},
            )
        )
    return report


@dataclass(frozen=True, slots=True)
class IndexManifest:
    """What a published index records about how it was made.

    `built_from` is the commit freshness diffs against. **None is not an
    error**: an index built outside a repository records no commit, and the
    honest answer about such an index is that it is unverifiable rather than
    that it is fresh.
    """

    collection: str
    index_id: str
    chunk_count: int
    built_from: str | None
    built_at: str
    documents: dict[str, str]


def read_manifest(index_root: Path, collection: str) -> IndexManifest | None:
    """The manifest of the published index for `collection`, or None.

    None means there is no index, which is the state a fresh corpus is in and
    is not a fault. A caller that needs the index itself uses `load_index`,
    which refuses; this exists for the callers that need to ask whether there
    is one - `corpus status` above all, which must be answerable on a corpus
    that has never been indexed.

    A pointer that names a directory which is not there returns None too: the
    pointer is written after the swap, so the only way to see that pairing is
    a corpus somebody deleted a directory out of, and the truthful answer is
    still that there is no index to report on.
    """
    collection_root = index_root / collection
    pointer_path = collection_root / _POINTER_FILE
    if not pointer_path.is_file():
        return None

    index_id = str(json.loads(pointer_path.read_text(encoding="utf-8"))["index_id"])
    manifest_path = collection_root / index_id / _MANIFEST_FILE
    if not manifest_path.is_file():
        return None

    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    built_from = recorded.get("built_from")
    return IndexManifest(
        collection=str(recorded["collection"]),
        index_id=str(recorded["index_id"]),
        chunk_count=int(recorded["chunk_count"]),
        built_from=str(built_from) if built_from else None,
        built_at=str(recorded["built_at"]),
        documents={
            str(key): str(value)
            for key, value in dict(recorded.get("documents", {})).items()
        },
    )


def load_index(index_root: Path, collection: str) -> LoadedIndex:
    """Read back the published index for `collection`."""
    collection_root = index_root / collection
    pointer_path = collection_root / _POINTER_FILE
    if not pointer_path.is_file():
        raise NothingToIndex(
            f"the '{collection}' collection has no index yet",
            resolution=f"kennis corpus index --collection {collection}",
        )
    index_id = str(json.loads(pointer_path.read_text(encoding="utf-8"))["index_id"])
    index_dir = collection_root / index_id

    chunks = [
        Chunk.model_validate_json(line)
        for line in (index_dir / _CHUNKS_FILE).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    binding = Binding.from_recorded(
        json.loads((index_dir / _BINDING_FILE).read_text(encoding="utf-8"))
    )
    vectors_path = index_dir / _VECTORS_FILE
    matrix = (
        np.load(vectors_path, allow_pickle=False) if vectors_path.is_file() else None
    )
    return LoadedIndex(
        collection=collection,
        chunks=chunks,
        bm25=Bm25Index.load(index_dir / _BM25_DIR, count=len(chunks)),
        binding=binding,
        matrix=matrix,
    )


def _refuse_if_empty(
    collection: str, documents: Sequence[Document], chunks: Sequence[Chunk]
) -> None:
    """Refuse before anything is written, with the reason that is true.

    Two distinct conditions that deserve different messages: a collection
    with no documents, and a collection whose documents hold no text. Both
    would otherwise surface from inside bm25s's vocabulary build.
    """
    if not documents:
        raise NothingToIndex(
            f"the '{collection}' collection is empty, so there is nothing to index"
        )
    if not chunks:
        raise NothingToIndex(
            f"the '{collection}' collection has {len(documents)} documents and no "
            "text in any of them"
        )


def _vectors_for(
    chunked: Sequence[_Chunked],
    binding: Binding,
    cache: VectorCache,
    embedder: Embedder | None,
    batch_size: int,
    events: EventSink | None,
) -> tuple[np.ndarray | None, int]:
    """The matrix for every chunk, in chunk order, and how much was computed.

    **Row `i` belongs to chunk `i`**, whatever mixture of cache hits and
    misses produced it. Documents are walked in order and each contributes
    either its cached block or a freshly computed one, so the two can never
    interleave wrongly.

    Embedding is per document rather than one call for the whole batch. That
    is what makes the per-document cache write meaningful: vectors that exist
    only inside a pending call cannot be kept when it is interrupted.
    """
    if binding.model is None:
        return None, 0

    active = (
        embedder if embedder is not None else embedder_for(binding.model, events=events)
    )
    blocks: list[np.ndarray] = []
    embedded = 0
    total = sum(len(produced) for _, _, produced in chunked)
    done = 0
    if events is not None:
        events.emit(Progress(operation="index", completed=0, total=total))

    for document, digest, produced in chunked:
        cached = cache.get(document.id, digest)
        # A stored block whose height does not match this document's chunk
        # count is treated as a miss. It should be impossible - the digest
        # and the parameters are both in the key - but what it prevents is
        # the silent misalignment of every row after it.
        if cached is not None and cached.shape[0] == len(produced):
            blocks.append(cached)
        else:
            block = embed_texts(
                binding.model,
                [chunk.text for chunk in produced],
                embedder=active,
                batch_size=batch_size,
                events=events,
            )
            cache.put(document.id, digest, block)
            blocks.append(block)
            embedded += 1
        done += len(produced)
        if events is not None:
            events.emit(Progress(operation="index", completed=done, total=total))

    stacked = (
        np.vstack(blocks)
        if blocks
        else np.zeros((0, binding.model.dim), dtype=np.float32)
    )
    return stacked, embedded


def _write_chunks(path: Path, chunks: Sequence[Chunk]) -> None:
    """One JSON object per line, in chunk order.

    Line-delimited rather than one array so that the file can be read back
    without holding the whole of it as a parsed structure twice.
    """
    path.write_text(
        "".join(f"{chunk.model_dump_json()}\n" for chunk in chunks), encoding="utf-8"
    )
