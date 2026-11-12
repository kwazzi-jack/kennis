"""The `search` tool, and the property that ties it to the CLI.

**Design section 20's one deliberate exception.** Every other front end
renders for itself; search hits are shared byte-for-byte, so a hit
printed by `kennis search` and one returned by `search` carry the
same text, one wearing ANSI. It is load-bearing rather than tidy: the
byte-identical property is what makes command-line output a faithful
proxy for what an agent sees, so someone debugging retrieval at a
terminal is looking at the thing the model looked at.

The first test holds that property directly. The rest cover the one
tool that was four (#643): every scope when none is named, the named
ones otherwise, and the difference between the two - a named scope with
no index is an error, an unnamed one a line in the answer.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.errors import ContextNotFound, InputError, NothingToIndex
from kennis.mcp.tools.search import Searched, search


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
    answered = search("antenna gains", ["notes"])

    # **Whole lines, compared for equality.** Substring containment is
    # not the property: a tool that dropped the relevance band would
    # still produce a handle that is a substring of the command line's
    # richer one, and an injection proved exactly that passes.
    assert _lines_with(answered, "[") == _lines_with(printed.output, "[")
    assert _lines_with(answered, "id=") == _lines_with(printed.output, "id=")


def test_the_read_handle_is_the_same_pair_both_ways(
    corpus: Path, isolated: Path, run: CliRunner
):
    """The handle is what an agent copies into `read` and what a
    person copies into `kennis read`. If the two front ends derived it
    separately they could disagree about the chunk."""
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")

    answered = search("antenna gains", ["notes"])
    printed = run.invoke(main, ["search", "antenna gains", "--collection", "notes"])

    assert _lines_with(answered, "id=") == _lines_with(printed.output, "id=")


# ---------------------------------------------------------------------------
# A named collection is a promise
# ---------------------------------------------------------------------------


def test_a_named_scope_with_no_index_is_an_error_not_an_empty_answer(corpus: Path):
    """Answering "no matching passages" for an index that was never built
    would be false, when the agent asked about that collection by name."""
    with pytest.raises(NothingToIndex):
        search("anything", ["notes"])


def test_a_miss_is_a_sentence_rather_than_an_empty_string(
    corpus: Path, isolated: Path, run: CliRunner
):
    """An agent handed "" cannot tell a miss from a broken tool."""
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")

    assert search("zzzzz nothing matches this", ["notes"]) == "no matching passages"


def test_context_named_outside_a_project_says_there_is_no_bundle(corpus: Path):
    with pytest.raises(ContextNotFound):
        search("anything", ["context"])


def test_each_collection_searches_its_own_scope(
    corpus: Path, isolated: Path, run: CliRunner
):
    """A note must not surface from a search of the literature."""
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")

    assert "Antenna" in search("antenna gains", ["notes"])
    with pytest.raises(NothingToIndex):
        search("antenna gains", ["literature"])
    with pytest.raises(NothingToIndex):
        search("antenna gains", ["docs"])


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

    assert search("antenna gains", ["notes"], top_k=0).count("id=") == 1
    assert search("antenna gains", ["notes"], top_k=1000).count("id=") == 3


def test_a_hit_carries_a_snippet_a_reader_can_judge(
    corpus: Path, isolated: Path, run: CliRunner
):
    indexed_notes(run, isolated, calibration="Calibration solves for antenna gains.")

    answered = search("antenna gains", ["notes"])

    assert "Calibration solves for antenna gains" in answered


def test_a_context_hit_is_a_path_and_no_snippet(
    corpus: Path, isolated: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """Section 11: a bundle lives in the user's own repository, so a hit
    is a file location the agent opens with its native tools. A snippet
    would be a second copy of text it is about to read in full, and
    `read` does not expand one."""
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

    answered = search("sub-bands", ["context"])

    assert "path=.context/" in answered
    assert "id=" not in answered
    # The group's heading, then two lines per hit - a headline and its
    # handle - and no third. The path is derived from the title, so it
    # carries the query's words itself; counting lines is what actually
    # says "no body".
    lines = [line for line in answered.splitlines() if line.strip()]
    assert len(lines) == 3, lines
    assert lines[0].startswith("Context")


def test_a_context_search_gives_a_declared_pack_s_copy_as_a_path(
    corpus: Path, isolated: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """A pack's context is copied into the project by its sync (#624), so
    an agent opens it with its own file tools, as any context hit."""
    provider = isolated / "provider"
    (provider / "content").mkdir(parents=True)
    (provider / "content" / "imaging.md").write_text(
        "Image in 2 GHz sub-bands and join them afterwards.\n", encoding="utf-8"
    )
    manifest = provider / "alpha.ken.yml"
    manifest.write_text(
        "kennis:\n  schema_version: 1\n"
        'pack:\n  id: alpha\n  name: n\n  version: "1.0.0"\n'
        "context:\n  - source: content/\n",
        encoding="utf-8",
    )
    assert run.invoke(main, ["pack", "update", str(manifest)]).exit_code == 0
    assert run.invoke(main, ["pack", "install", str(manifest)]).exit_code == 0
    project = isolated / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert run.invoke(main, ["context", "init", "--pack", "alpha"]).exit_code == 0
    assert run.invoke(main, ["context", "sync"]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0

    answered = search("sub-bands", ["context"])

    assert "path=.context/imaging.md" in answered
    assert "pack=" not in answered


# ---------------------------------------------------------------------------
# One tool, the collections an argument (#643)
# ---------------------------------------------------------------------------


def a_project_note(
    isolated: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    project = isolated / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert run.invoke(main, ["context", "init"]).exit_code == 0
    assert run.invoke(main, ["remember", "--context", text]).exit_code == 0
    assert run.invoke(main, ["context", "index"]).exit_code == 0


def headings_of(answered: str) -> list[str]:
    """The first word of each group's heading, in the answer's order."""
    return [
        block.splitlines()[0].split(" ")[0]
        for block in answered.split("\n\n")
        if not block.startswith("not searched")
    ]


def test_all_searches_every_indexed_scope(
    corpus: Path, isolated: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """And the ones with no index are named with the command that builds
    one, rather than refused or passed over in silence."""
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")
    a_project_note(isolated, run, monkeypatch, "This project solves antenna gains.")

    answered = search("antenna gains", ["all"])

    # Written by hand: the order a report lists scopes in, context first.
    assert headings_of(answered) == ["Context", "Notes"]
    assert "path=.context/" in answered
    assert "id=" in answered
    assert "not searched" not in answered


def test_a_scope_swept_into_with_no_index_is_named_with_its_command(
    corpus: Path, isolated: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """Not refused, because the agent did not ask for it, and not passed
    over in silence, because then a project's notes would seem not to
    exist. Named, the same scope is an error."""
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")
    project = isolated / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert run.invoke(main, ["context", "init"]).exit_code == 0
    assert run.invoke(main, ["remember", "--context", "Antenna gains."]).exit_code == 0

    answered = search("antenna gains", ["all"])

    assert headings_of(answered) == ["Notes"]
    # Written by hand: the line, with the command for a bundle.
    assert answered.endswith(
        "\n\nnot searched, no index yet: context. Run `kennis context index`."
    )
    # Beside a collection that is indexed, so that the refusal is for the
    # scope named and not for there being nothing to search at all.
    with pytest.raises(NothingToIndex):
        search("antenna gains", ["notes", "context"])


def test_only_the_collections_named_are_searched(
    corpus: Path, isolated: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")
    a_project_note(isolated, run, monkeypatch, "This project solves antenna gains.")

    assert headings_of(search("antenna gains", ["notes"])) == ["Notes"]
    assert headings_of(search("antenna gains", ["context"])) == ["Context"]
    # In the report's order whatever order they were named in.
    assert headings_of(search("antenna gains", ["notes", "context"])) == [
        "Context",
        "Notes",
    ]
    assert "not searched" not in search("antenna gains", ["notes"])


def test_each_group_s_heading_is_the_command_line_s(
    corpus: Path, isolated: Path, run: CliRunner
):
    """A relevance band is never shown without its scale, and the scale's
    words are the ones `kennis search` prints above the same group."""
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")

    printed = run.invoke(main, ["search", "antenna gains", "--collection", "notes"])
    answered = search("antenna gains", ["notes"])

    heading = answered.splitlines()[0]
    # Written by hand: what the heading of a keywords-only group says.
    assert heading == "Notes keywords as a fraction of the best match here"
    assert heading in [line.strip() for line in printed.output.splitlines()]


def test_top_k_is_how_many_each_collection_gives(
    corpus: Path, isolated: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    indexed_notes(run, isolated, one="Antenna gains alpha.", two="Antenna gains beta.")
    a_project_note(isolated, run, monkeypatch, "This project solves antenna gains.")

    answered = search("antenna gains", ["all"], top_k=1)

    assert answered.count("id=") == 1
    assert answered.count("path=") == 1


def test_with_nothing_to_search_anywhere_the_search_is_refused(corpus: Path):
    """An empty corpus: "no matching passages" would read as a search that
    looked and found nothing. The sweep's own refusal, with its command."""
    with pytest.raises(NothingToIndex, match="nothing to search"):
        search("anything", ["all"])


def test_a_miss_in_every_scope_is_one_sentence(
    corpus: Path, isolated: Path, run: CliRunner
):
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")

    assert search("zzzzz nothing matches this", ["all"]) == "no matching passages"


@pytest.mark.parametrize("collections", [["elsewhere"], ["notes", "paper"], []])
def test_a_collection_that_does_not_exist_is_refused_with_the_ones_that_do(
    corpus: Path, collections: list[str]
):
    with pytest.raises(InputError, match="all or one or more of context, literature"):
        # Past the schema, as a direct caller or a lenient client gets.
        search("anything", cast("list[Searched]", collections))


def test_the_collections_must_be_said(corpus: Path):
    """No default (Brian, 2026-11-12): an agent that gave it no thought
    got every scope's hits. `all` is a choice it has to make."""
    parameter = inspect.signature(search).parameters["collections"]

    assert parameter.default is inspect.Parameter.empty


def test_all_beside_a_name_is_all(
    corpus: Path, isolated: Path, run: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    """And swept, not promised: literature has no index and is no error."""
    indexed_notes(run, isolated, calibration="Antenna gains and sky models.")
    a_project_note(isolated, run, monkeypatch, "This project solves antenna gains.")

    answered = search("antenna gains", ["literature", "all"])

    assert headings_of(answered) == ["Context", "Notes"]
