"""Conversions kept for a day, so a failed add run again converts nothing
again (14e, #507).

An add is prepared in a mirror that is discarded when it fails
(`engine/staging.py`), and its conversions went with it: a retry paid
again for minutes of MinerU, or for money with a hosted converter.
`KeptConversions` wraps the converter an add uses and keeps each result
under `.git/kennis-conversions/` - inside `.git` so no commit stages it -
named by the converter and the source's sha256, since two converters write
different markdown for one PDF and a renamed file is the same document.
The service forgets an entry a day after it was written, at its start
(`staging.recover`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from kennis.engine.atomic import remove_file, replace_file
from kennis.engine.corpus.converters import ConversionBatch, Converter
from kennis.engine.corpus.intake import sha256_of
from kennis.engine.corpus.layout import published_corpus
from kennis.engine.corpus.schema import SourceFormat

_DIRNAME: Final = "kennis-conversions"
KEPT_SECONDS: Final = 24 * 3600


def conversions_root(corpus_root: Path) -> Path:
    """Where the corpus at `corpus_root` keeps conversions - the real
    corpus's, when asked from a mirror an add is preparing in."""
    return published_corpus(corpus_root) / ".git" / _DIRNAME


class KeptConversions:
    """A converter that answers from what was kept, and keeps what it
    converts."""

    def __init__(self, inner: Converter, folder: Path) -> None:
        self.name: str = inner.name
        self.formats: frozenset[SourceFormat] = inner.formats
        self._inner = inner
        self._folder = folder

    def is_available(self) -> bool:
        return self._inner.is_available()

    def install_hint(self) -> str:
        return self._inner.install_hint()

    def convert(self, paths: Sequence[Path]) -> ConversionBatch:
        entries = {path: self._entry_for(path) for path in paths}
        kept = {
            path: json.loads(entry.read_text(encoding="utf-8"))
            for path, entry in entries.items()
            if entry.is_file()
        }
        unknown = [path for path in paths if path not in kept]
        batch = self._inner.convert(unknown) if unknown else ConversionBatch({})
        for path in unknown:
            markdown = batch.markdown.get(path)
            if markdown is None:
                continue
            replace_file(
                entries[path],
                json.dumps(
                    {
                        "markdown": markdown,
                        "front_page": batch.front_page.get(path, ""),
                        "repairs": batch.repairs.get(path, 0),
                    }
                ),
            )
        return ConversionBatch(
            markdown={
                **{path: str(entry["markdown"]) for path, entry in kept.items()},
                **batch.markdown,
            },
            front_page={
                **{path: str(entry["front_page"]) for path, entry in kept.items()},
                **batch.front_page,
            },
            failure_reason=batch.failure_reason,
            cost_cents=batch.cost_cents,
            repairs={
                **{path: int(entry["repairs"]) for path, entry in kept.items()},
                **batch.repairs,
            },
        )

    def _entry_for(self, path: Path) -> Path:
        return self._folder / f"{self.name}-{sha256_of(path.read_bytes())}.json"


def forget_old_conversions(corpus_root: Path, *, now: float | None = None) -> int:
    """Remove what was kept more than a day ago. How many went."""
    folder = conversions_root(corpus_root)
    if not folder.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - KEPT_SECONDS
    forgotten = 0
    for entry in folder.iterdir():
        if entry.stat().st_mtime < cutoff:
            remove_file(entry, missing_ok=True)
            forgotten += 1
    return forgotten


__all__ = [
    "KEPT_SECONDS",
    "KeptConversions",
    "conversions_root",
    "forget_old_conversions",
]
