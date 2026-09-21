"""What decides a vector, gathered into one value.

A vector is a function of the text it was computed from, the parameters that
cut that text into chunks, and the model that embedded them. The **binding**
is all of it, and the cache keys on its digest.

Carrying the whole binding rather than the obvious shorter key prevents a
failure that is entirely silent. Key on content and model alone, then change
the chunk size: every document is a cache *hit*, so the dense index is reused
over the old chunk boundaries while BM25 is rebuilt over the new ones. The two
indexes then disagree about what chunk number seven is, and every offset, read
span and fused rank is computed against mismatched lists. Nothing raises. The
results are merely wrong, and plausibly so.

This is also what step 4 records in `index/binding.json`, so that a later
`corpus status` can report that the configuration and the index disagree
rather than silently recomputing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final

from kennis.engine.rag.chunking import ChunkParameters
from kennis.engine.rag.embedding import ModelBinding

_DIGEST_BYTES: Final = 16


def document_digest(text: str) -> str:
    """A stable digest of a document's text.

    Of the text exactly as it is, with no normalisation: whitespace is
    content to a chunker, because it decides where blocks begin and end, so a
    digest that folded it would claim two different chunk lists are the same.
    """
    return hashlib.blake2b(text.encode("utf-8"), digest_size=_DIGEST_BYTES).hexdigest()


@dataclass(frozen=True, slots=True)
class Binding:
    """Everything about how a vector is derived, apart from the text itself."""

    chunking: ChunkParameters
    model: ModelBinding

    @property
    def digest(self) -> str:
        """The cache key for this binding.

        Computed from the recorded form with sorted keys, so it depends on
        the values and not on field order or on anything the interpreter
        chooses per process - a cache written by one run has to be readable
        by the next.
        """
        payload = {
            key: value for key, value in self.recorded().items() if key != "digest"
        }
        return hashlib.blake2b(
            json.dumps(payload, sort_keys=True).encode("utf-8"),
            digest_size=_DIGEST_BYTES,
        ).hexdigest()

    def recorded(self) -> dict[str, Any]:
        """The binding as it is written to disk.

        Named fields rather than one opaque digest, because a person looking
        at an index directory to find out why it was rebuilt should be able
        to read it. The digest is included so that comparing two recorded
        bindings does not mean reimplementing the hash.

        **`host` and `max_async` are deliberately absent.** Where a model was
        reached from does not change what it computes, and how many requests
        were in flight is not part of what a vector is; keying on either
        would miss the cache every time a daemon moved port.
        """
        payload: dict[str, Any] = {
            "chunk_size": self.chunking.size,
            "chunk_overlap": self.chunking.overlap,
            "chunker_version": self.chunking.version,
            "embedding_backend": self.model.kind,
            "embedding_model": self.model.model,
            "embedding_dim": self.model.dim,
            "normalise": self.model.normalise,
        }
        payload["digest"] = hashlib.blake2b(
            json.dumps(payload, sort_keys=True).encode("utf-8"),
            digest_size=_DIGEST_BYTES,
        ).hexdigest()
        return payload

    @classmethod
    def from_recorded(cls, recorded: dict[str, Any]) -> Binding:
        """A binding read back from what `recorded` wrote."""
        return cls(
            chunking=ChunkParameters(
                size=int(recorded["chunk_size"]),
                overlap=int(recorded["chunk_overlap"]),
                version=int(recorded["chunker_version"]),
            ),
            model=ModelBinding(
                kind=str(recorded["embedding_backend"]),
                model=str(recorded["embedding_model"]),
                dim=int(recorded["embedding_dim"]),
                normalise=bool(recorded["normalise"]),
            ),
        )
