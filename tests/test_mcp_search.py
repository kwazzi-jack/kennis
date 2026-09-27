"""The four `search_*` tools, and the property that ties them to the CLI.

**Design section 20's one deliberate exception.** Every other front end
renders for itself; search hits are shared byte-for-byte, so a hit
printed by `kennis search` and one returned by `search_notes` carry the
same text, one wearing ANSI. It is load-bearing rather than tidy: the
byte-identical property is what makes command-line output a faithful
proxy for what an agent sees, so someone debugging retrieval at a
terminal is looking at the thing the model looked at.

The first test holds that property directly. The rest cover what a tool
does differently from a sweep: it is asked about exactly one scope, so a
scope with no index is an error rather than a line in a report.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.errors import ContextNotFound, NothingToIndex
from kennis.mcp.tools.search import (
    search_context,
    search_docs,
    search_literature,
    search_notes,
)


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    return tmp_path


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def corpus(isolated: Path, run: CliRunner) -> Path:
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return isolated / "corpus"


def indexed_notes(run: CliRunner, tmp_path: Path, **bodies: str) -> None:
    for name, body in bodies.items():
        source = tmp_path / "sources" / f"{name}.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            f"# {name}\n\n{body}\n",
            encoding="utf-8",
        )
        assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0


def _lines_with(text: str, marker: str) -> list[str]:
    """Every line carrying `marker`, stripped of leading layout.

    Indentation is the one thing the two front ends are allowed to
    differ on - the command line indents a detail under its headline
    and the server indents it by two - so it is removed before
    comparing. Everything else is the text itself and must match.
    """
    return [line.strip() for line in text.splitlines() if marker in line]


# ---------------------------------------------------------------------------
# The shared bytes
# ---------------------------------------------------------------------------


def test_a_hit_carries_the_same_text_in_both_front_ends(
    corpus: Path, isolated: Path, run: CliRunner
):
    """Section 20's exception, as a test. Not "both mention the title" -
    the headline and the handle line are compared whole, because a
    difference in either is a difference in what a person and a model
    are looking at."""
    indexed_notes(
        run,
        isolated,
        calibration="Calibration solves for antenna gains against a sky model.",
        baking="A recipe for sourdough bread at home.",
    )

    printed = run.invoke(
        main, ["search", "antenna gains", "--collection", "notes", "--snippet", "none"]
    )
    assert printed.exit_code == 0, printed.output
    answered = search_notes("antenna gains")

    # **Whole lines, compared for equality.** Substring containment is
    # not the property: a tool that dropped the relevance band would
    # still produce a handle that is a substring of the command line's
    # richer one, and an injection proved exactly that passes.
    assert _lines_with(answered, "[") == _lines_with(printed.output, "[")
    assert _lines_with(answered, "id=") == _lines_with(printed.output, "id=")


def test_the_read_handle_is_the_same_pair_both_ways(
    corpus: Path, isolated: Path, run: CliRunner
):
    """The handle is what an agent copies into `read_notes` and what a
    person copies into `kennis read`. If the two front ends derived it
    separately they could disagree about the chunk."""
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")

    answered = search_notes("antenna gains")
    printed = run.invoke(main, ["search", "antenna gains", "--collection", "notes"])

    assert _lines_with(answered, "id=") == _lines_with(printed.output, "id=")


# ---------------------------------------------------------------------------
# What a tool does differently from a sweep
# ---------------------------------------------------------------------------


def test_a_scope_with_no_index_is_an_error_not_an_empty_answer(corpus: Path):
    """The command line skips an unnamed scope and says what it searched.
    A tool is asked about exactly one, and answering "no matching
    passages" for an index that was never built would be false."""
    with pytest.raises(NothingToIndex):
        search_notes("anything")


def test_a_miss_is_a_sentence_rather_than_an_empty_string(
    corpus: Path, isolated: Path, run: CliRunner
):
    """An agent handed "" cannot tell a miss from a broken tool."""
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")

    assert search_notes("zzzzz nothing matches this") == "no matching passages"


def test_search_context_outside_a_project_says_there_is_no_bundle(corpus: Path):
    with pytest.raises(ContextNotFound):
        search_context("anything")


def test_each_collection_searches_its_own_scope(
    corpus: Path, isolated: Path, run: CliRunner
):
    """A note must not surface from `search_literature`. The collection
    is fixed by which tool was called, not by an argument."""
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")

    assert "Antenna" in search_notes("antenna gains")
    with pytest.raises(NothingToIndex):
        search_literature("antenna gains")
    with pytest.raises(NothingToIndex):
        search_docs("antenna gains")


def test_top_k_is_clamped_rather_than_trusted(
    corpus: Path, isolated: Path, run: CliRunner
):
    """An agent may pass anything. Zero would return nothing and read as
    a miss; a thousand would return the whole index as one payload."""
    indexed_notes(
        run,
        isolated,
        one="Antenna gains alpha.",
        two="Antenna gains beta.",
        three="Antenna gains gamma.",
    )

    assert search_notes("antenna gains", top_k=0).count("id=") == 1
    assert search_notes("antenna gains", top_k=1000).count("id=") == 3


def test_a_hit_carries_a_snippet_a_reader_can_judge(
    corpus: Path, isolated: Path, run: CliRunner
):
    indexed_notes(run, isolated, calibration="Calibration solves for antenna gains.")

    answered = search_notes("antenna gains")

    assert "Calibration solves for antenna gains" in answered


def test_search_context_answers_with_a_path_and_no_snippet(
    corpus: Path, isolated: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """Section 11: a bundle lives in the user's own repository, so a hit
    is a file location the agent opens with its native tools. A snippet
    would be a second copy of text it is about to read in full, and
    there is no `read_context` to expand one."""
    project = isolated / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert run.invoke(main, ["context", "init"]).exit_code == 0
    assert (
        run.invoke(
            main, ["remember", "--context", "This project images in 2 GHz sub-bands."]
        ).exit_code
        == 0
    )
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    answered = search_context("sub-bands")

    assert "path=.context/" in answered
    assert "id=" not in answered
    # Two lines per hit - a headline and its handle - and no third. The
    # path is derived from the title, so it carries the query's words
    # itself; counting lines is what actually says "no body".
    lines = [line for line in answered.splitlines() if line.strip()]
    assert len(lines) == 2, lines
