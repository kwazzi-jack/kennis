"""The count `remember` reports, and the interface's fixed strings.

Two kinds of thing, and only one of them is behaviour.

**The count is a falsehood and is tested as one.** A note of known
length must report its own chunks, not its collection's. Measured
before the fix: three one-sentence notes written in a row reported 2,
3 and 4 chunks, each of them one chunk long.

**The words are tested only where a test can say something true.** A
sentence cannot be asserted to read well. It can be asserted not to
name a position on a page, because a layout moves and the reference
goes stale without anything failing - which is what happened: the
note under an add said the Index section was above it, and it is
below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.gui import words


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def _chunks_reported(output: str) -> int:
    found = re.search(r"indexed, (\d+) chunks?", output)
    assert found is not None, output
    return int(found.group(1))


# ---------------------------------------------------------------------------
# The count
# ---------------------------------------------------------------------------


def test_a_short_note_reports_one_chunk_however_full_the_collection_is(
    corpus: Path,
):
    """The defect, stated as the reader met it. `_index` returned
    `BuildReport.chunk_count`, which is the collection's total - so
    the number grew by one with every note and told the reader their
    single sentence had become four chunks."""
    run = CliRunner()
    assert run.invoke(main, ["remember", "A first short note."]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    counts = []
    for number in range(3):
        written = run.invoke(main, ["remember", f"Short note number {number}."])
        assert written.exit_code == 0, written.output
        counts.append(_chunks_reported(written.output))

    assert counts == [1, 1, 1]


def test_a_long_note_reports_more_than_one_chunk(corpus: Path):
    """The count is kept rather than dropped because it carries
    something for a note long enough to be split. A test that only
    pinned it to 1 would pass for a function returning the constant
    1."""
    run = CliRunner()
    assert run.invoke(main, ["remember", "A first short note."]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    # Comfortably past `ChunkParameters.size`, in distinct paragraphs
    # so the packer has somewhere to cut.
    long_note = "\n\n".join(
        f"Paragraph {number} discusses antenna gains, bandpass "
        f"calibration and the solver's behaviour over long tracks, at "
        f"enough length that the packer has to divide it. " * 4
        for number in range(12)
    )

    written = run.invoke(main, ["remember", long_note])

    assert written.exit_code == 0, written.output
    assert _chunks_reported(written.output) > 1


def test_the_collection_build_still_reports_the_collection(corpus: Path):
    """`BuildReport.chunk_count` was never wrong; the assignment out
    of it was. `kennis corpus index` reports a collection and must go
    on doing so."""
    run = CliRunner()
    for number in range(3):
        assert run.invoke(main, ["remember", f"Note {number} on gains."]).exit_code == 0

    built = run.invoke(main, ["corpus", "index"])

    assert built.exit_code == 0, built.output
    found = re.search(r"(\d+) chunks", built.output)
    assert found is not None, built.output
    assert int(found.group(1)) >= 3


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------

_POSITIONS = ("above", "below", "on the left", "on the right", "at the top")


def test_no_message_names_a_position_on_the_page():
    """A sentence naming a section's position goes stale when the
    page is re-laid out, and nothing fails when it does. The note
    under an add said the Index section was above it; in
    `manage.html` Add is first and Index is third."""
    named = {
        name: text
        for name in words.__all__
        if isinstance(text := getattr(words, name), str)
        if any(position in text for position in _POSITIONS)
    }

    assert named == {}


def test_the_navigation_labels_are_the_page_headings():
    """The labels were hardcoded in `base.html` in lower case while
    every heading was capitalised, so the same page was called two
    things depending on where the reader read it."""
    templates = Path(__file__).resolve().parents[1] / "src/kennis/gui/templates"
    headings = {
        "held": "holdings.html",
        "remember": "remember.html",
        "manage": "manage.html",
    }

    for label, template in headings.items():
        text = (templates / template).read_text(encoding="utf-8")
        found = re.search(r"<h1>([^<]+)</h1>", text)
        assert found is not None, template
        assert found.group(1) == words.NAV_LABELS[label], label


def test_no_message_uses_a_word_kennis_invented():
    """ "Materialise" is the design's word for what a sync does to a
    pack's declarations. It is not a word a reader brings with them,
    and the sentence it was in had to explain itself afterwards."""
    invented = {
        name
        for name in words.__all__
        if isinstance(text := getattr(words, name), str)
        if "materialis" in text.lower()
    }

    assert invented == set()


def test_every_fixed_string_is_exported():
    """`__all__` is what the two tests above iterate, so a message
    left out of it is a message they do not check."""
    module = Path(words.__file__).read_text(encoding="utf-8")
    defined = set(re.findall(r"^([A-Z][A-Z_]+) = ", module, re.MULTILINE))

    assert defined <= set(words.__all__), defined - set(words.__all__)
