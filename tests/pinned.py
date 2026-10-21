"""A scratch corpus whose output does not vary between runs, and the one
transformation applied to what cannot be held still.

Shared by `test_cli_baseline.py` and `test_mcp_baseline.py`, which compare
what each front end says today with what it said before milestone 14 moved
the work into a service (14a). Both pass their output through `normalised`
and compare it with files under `tests/baseline/`, so the transformation is
the same on both sides of every comparison.

What would vary and is not kennis's behaviour is pinned: document
identifiers come from a counter, git's dates are fixed, the terminal is 100
columns. What cannot be pinned is replaced by a placeholder: the temporary
folder, elapsed times, commit hashes, dates kennis takes from the clock, an
archive's size and entry count.
"""

from __future__ import annotations

import difflib
import itertools
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from kennis.cli import display

BASELINE = Path(__file__).parent / "baseline"
REGENERATE = os.environ.get("KENNIS_REGENERATE_BASELINE") == "1"

SOURCES: dict[str, str] = {
    "sources/calibration.md": (
        "# Calibration\n\nCalibration solves for antenna gains and phase.\n\n"
        "## Gains\n\nThe gain of each antenna is solved per interval.\n\n"
        "## Phase\n\nPhase calibration follows the bandpass.\n"
    ),
    "sources/imaging.md": "# Imaging\n\nImaging grids visibilities and inverts them.\n",
    "sources/beams.md": (
        "# Beams\n\nThe primary beam attenuates sources far from the centre.\n"
    ),
    "sources/page.md": "# Tool\n\nThe tool's reference page.\n",
    "provider/notes/convention.md": "# Convention\n\nPhase centres are in J2000.\n",
    "provider/provider.ken.yml": (
        "kennis:\n  schema_version: 1\npack:\n  id: provider\n"
        '  name: "a provider"\n  version: "0.1.0"\n'
        "corpus:\n  notes:\n    - source: notes/\n"
    ),
}


def counted_identifiers() -> Iterator[str]:
    for number in itertools.count(1):
        yield f"doc{number:07d}"


def pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Hold still everything that would differ between two runs, and lay
    out the sources, a git repository for a project, and empty folders for
    a pack scaffold and backups. Returns the scratch folder."""
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    # 100 columns as drawn. rich takes one off `COLUMNS` on a Windows console
    # without virtual-terminal support, which is what CI gives a job, and
    # two answers then wrapped a word earlier there (#532).
    monkeypatch.setenv("COLUMNS", str(100 + int(display.console.legacy_windows)))
    for variable in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
        monkeypatch.setenv(variable, "2026-01-02T03:04:05+00:00")
    identifiers = counted_identifiers()
    monkeypatch.setattr(
        "kennis.engine.corpus.ids.generate_id", lambda: next(identifiers)
    )
    for relative, text in SOURCES.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    for folder in ("project", "scaffold", "backups"):
        (tmp_path / folder).mkdir()
    subprocess.run(
        ["git", "init", "-q", str(tmp_path / "project")],
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    return tmp_path


_INSIDE_SCRATCH = re.compile(r"<scratch>\S*")
_HASH = re.compile(r"\b[0-9a-f]{7,40}\b")
_ELAPSED = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s)\b")
# An encrypted archive's size depends on what git compressed, which depends
# on the dates inside each document's frontmatter.
_SIZE = re.compile(r"\b\d+(?:\.\d+)?\s(?:B|kB|MB|GB)\b")
# And its entry count includes git's object folders, one per distinct first
# two hex digits of a hash, so it moves with the hashes.
_ENTRIES = re.compile(r"\b\d+ entries\b")
_DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[+-]\d{2}:?\d{2}|Z)?)?\b"
)


def normalised(text: str, scratch: Path) -> str:
    """The output with what cannot be pinned replaced by a placeholder.

    The folder first, because it contains digits the other patterns match.
    """
    for spelling in {str(scratch), scratch.as_posix(), str(scratch.resolve())}:
        text = text.replace(spelling, "<scratch>")
    # A path inside the folder is spelled with the platform's separator.
    text = _INSIDE_SCRATCH.sub(lambda found: found[0].replace("\\", "/"), text)
    # And so is one relative to it, as `backups\kennis-corpus.7z` on
    # Windows. Only there, because elsewhere a backslash is not a separator
    # and nothing the scenario prints holds one (#532).
    if os.sep != "/":
        text = text.replace(os.sep, "/")
    text = _DATE.sub("<date>", text)
    text = _HASH.sub("<commit>", text)
    text = _SIZE.sub("<size>", text)
    text = _ENTRIES.sub("<count> entries", text)
    return _ELAPSED.sub("<elapsed>", text)


def compared_with_baseline(produced: dict[str, str], folder: Path) -> None:
    """Fail naming every file whose text differs from what was produced, or
    write them all when `KENNIS_REGENERATE_BASELINE=1`.

    A difference is either a regression or a change somebody meant; the
    second is made by regenerating and reading the diff before committing.
    """
    if REGENERATE:
        folder.mkdir(parents=True, exist_ok=True)
        for stale in folder.glob("*.txt"):
            stale.unlink()
        for name, text in produced.items():
            (folder / name).write_text(text, encoding="utf-8", newline="\n")
        pytest.skip("the baseline was regenerated; read its diff before committing")
    stored = sorted(path.name for path in folder.glob("*.txt"))
    assert stored == sorted(produced), "the scenario and the stored files disagree"
    differing = [
        name
        for name, text in produced.items()
        if (folder / name).read_text(encoding="utf-8") != text
    ]
    # The differences themselves, because the run that finds them may be a
    # CI job on a system nobody here can regenerate on (#532).
    shown = "".join(
        "".join(
            difflib.unified_diff(
                (folder / name).read_text(encoding="utf-8").splitlines(keepends=True),
                produced[name].splitlines(keepends=True),
                fromfile=f"stored/{name}",
                tofile=f"produced/{name}",
            )
        )
        for name in differing
    )
    assert not differing, (
        f"{len(differing)} answers are now something else: {differing}. "
        "Regenerate into a copy and compare with `git diff --no-index`.\n" + shown
    )
