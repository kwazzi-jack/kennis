"""Fixtures shared across test modules.

Only the ones more than one module needs. A fixture used by a single file
stays in that file, where its reason for existing sits next to its use.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

# A fake MinerU. It parses the flags the converter passes, writes one markdown
# file per staged input in the nested layout the real tool produces, and can
# be told to fail one document or all of them.
FAKE_MINERU = r"""#!/bin/sh
set -e
while [ $# -gt 0 ]; do
    case "$1" in
        -p) input_dir="$2"; shift 2 ;;
        -o) output_dir="$2"; shift 2 ;;
        -b) backend="$2"; shift 2 ;;
        -s|-e) shift 2 ;;
        *) shift ;;
    esac
done
echo "backend=$backend" >> "$MINERU_FAKE_LOG"
echo "device=${MINERU_DEVICE_MODE-unset} source=${MINERU_MODEL_SOURCE-unset}" \
    >> "$MINERU_FAKE_LOG"
for staged in "$input_dir"/*; do
    stem=$(basename "$staged")
    stem=${stem%.*}
    case "$stem" in
        *$MINERU_FAKE_SKIP*) continue ;;
    esac
    mkdir -p "$output_dir/$stem/auto"
    printf '# %s\n\nConverted body.\n' "$stem" > "$output_dir/$stem/auto/$stem.md"
    printf 'tiny\n' > "$output_dir/$stem/auto/${stem}_small.md"
    printf '[{"type":"page_aside_text","page_idx":0,' > "$tmp_json"
    printf '"text":"arXiv:1101.1764v2 [astro-ph.IM]"}]' >> "$tmp_json"
    cp "$tmp_json" "$output_dir/$stem/auto/${stem}_content_list.json"
done
exit "${MINERU_FAKE_EXIT-0}"
"""


@pytest.fixture(autouse=True)
def offline_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches Hugging Face unless it asks to.

    `retrieval.corpus_method` defaults to `hybrid`, so `kennis corpus index`
    builds a dense index; `embed_texts` builds an embedder when the caller
    supplied none, and building one downloads the model. A test that drives
    the command line supplies none, so this setting is the only thing
    between the default suite and a 65 MB download.

    It was set per module in seven files and missing from an eighth, which
    nothing here could notice: the model is cached in
    `~/.cache/kennis/models` on a developer machine, so the download happens
    once, invisibly, and never again. It took a fresh CI runner to show it
    (concern #253). Autouse makes the safe case the default; a module that
    wants a real backend sets its own value, which runs after this and wins.
    """
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")


@pytest.fixture
def fake_mineru(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a fake `mineru` first on PATH and return the log it writes."""
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    script = binary_dir / "mineru"
    log = tmp_path / "mineru.log"
    script.write_text(
        FAKE_MINERU.replace("$tmp_json", str(tmp_path / "content.json")),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{binary_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("MINERU_FAKE_LOG", str(log))
    monkeypatch.setenv("MINERU_FAKE_SKIP", "__never_matches__")
    return log


@pytest.fixture
def no_mineru(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment with no `mineru` anywhere kennis looks.

    Both places, not just PATH. kennis falls back to the directory of the
    interpreter it is running on, because `uv tool install "kennis[mineru]"`
    puts mineru there and never on PATH - and this checkout's own `.venv/bin`
    holds a real mineru, so emptying PATH alone left four tests asserting
    absence while the real converter ran.
    """
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    interpreter = empty / "python"
    interpreter.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(interpreter))
