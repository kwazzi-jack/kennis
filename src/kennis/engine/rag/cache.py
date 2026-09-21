"""Vectors kept between builds, so a rebuild embeds only what changed.

A dict persisted to disk, keyed on the full derivation binding. Design
section 15 argues at length that this should not be a vector database at this
scale, and that argument is not reopened here: what is being stored is a
cache keyed by a digest, and the similarity search over it is brute force
across a few tens of thousands of rows.

Three properties are load-bearing, and all three are about interruption.

**It lives outside the index directory.** A build stages into a temporary
directory and swaps it into place, so anything inside that directory is
replaced wholesale - a cache kept there would be destroyed by the very build
it exists to make cheap.

**It is written per document.** An interrupt costs the in-flight document's
vectors, not the run.

**A build that aborts leaves vectors for an index that was never published.**
That is harmless, and it is the point: the next attempt starts from them.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from kennis.engine._atomic import replace_file
from kennis.engine.rag.binding import Binding


class VectorCache:
    """Vectors for one binding, on disk under `root`.

    Entries for different bindings sit in sibling directories rather than
    overwriting each other, so switching model and switching back does not
    cost the work a second time.
    """

    def __init__(self, *, root: Path, binding: Binding) -> None:
        self._directory = root / binding.digest
        self._binding = binding

    def get(self, document_id: str, digest: str) -> np.ndarray | None:
        """The vectors for this document at this text, or None.

        An entry that cannot be read is a miss rather than a failure: a
        half-written file from an interrupted run should cost one
        recomputation, not the whole build.
        """
        path = self._path_for(document_id, digest)
        if not path.is_file():
            return None
        try:
            loaded = np.load(path, allow_pickle=False)
        except (OSError, ValueError):
            return None
        return np.asarray(loaded, dtype=np.float32)

    def put(self, document_id: str, digest: str, vectors: np.ndarray) -> None:
        """Record the vectors for this document at this text."""
        self._directory.mkdir(parents=True, exist_ok=True)
        self._write_binding()
        path = self._path_for(document_id, digest)
        # Through a temporary file, so a reader never sees a partial array:
        # the interrupt this survives is the one it exists for.
        staging = path.with_suffix(".npy.writing")
        with staging.open("wb") as handle:
            np.save(handle, vectors, allow_pickle=False)
        staging.replace(path)

    def prune(self, *, keep: set[str], digests: dict[str, str] | None = None) -> int:
        """Drop entries for documents not in `keep`, and superseded versions.

        Two kinds of growth, and both are unbounded without this. A document
        removed from the corpus leaves its vectors behind; a document edited
        several times leaves one entry per version it ever had. `digests`
        names the current text of each kept document, so everything else it
        ever was can go.

        Returns how many entries were dropped. Nothing calls this yet - the
        set of current documents is known to the build, which is step 4.
        """
        dropped = 0
        for path in self._directory.glob("*.npy"):
            document_id, _, digest = path.stem.rpartition(".")
            if not document_id:
                continue
            current = (digests or {}).get(document_id)
            if document_id not in keep or (current is not None and digest != current):
                path.unlink(missing_ok=True)
                dropped += 1
        return dropped

    def _path_for(self, document_id: str, digest: str) -> Path:
        return self._directory / f"{_safe(document_id)}.{digest}.npy"

    def _write_binding(self) -> None:
        """Record which binding this directory holds.

        For a person looking at a cache directory, not for kennis: the
        directory is named by the digest, and a pile of hex says nothing
        about which model or chunk size produced it.
        """
        marker = self._directory / "binding.json"
        if not marker.exists():
            replace_file(marker, json.dumps(self._binding.recorded(), indent=2))


def _safe(document_id: str) -> str:
    """A document identifier as a filename component.

    Identifiers are ten characters of `[a-z0-9]` by construction, so this
    changes nothing today. It is here because the cache would otherwise be a
    path traversal waiting for the first identifier that is not.
    """
    return "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in document_id
    )
