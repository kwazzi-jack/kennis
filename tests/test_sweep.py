"""The multi-scope sweep, now that both front ends run it.

It lived privately in `cli/commands/search.py` and concern #314
recorded that as a parallel implementation: `retrieval.mode_for`
stated the mode rule once and the sweep stated it again, they agreed,
and the thing that would make them disagree is a change to one edited
through the other. The window needs the same sweep, so it moved
rather than being copied a third time.

**What this file guards is the behaviour that was easy to lose in the
move**, which is not the return value. `--quiet` crossed a port with
all six of its guards missing and nothing noticed for five milestones
(#88), so:

- the *ordering* of groups is fixed and never by best hit, because
  ranking collections against each other is the comparison
  `basis_phrase` exists to refuse;
- a scope the reader *named* fails when it has no index, and a scope
  swept into is skipped quietly - the same absence, two answers;
- a skipped scope carries the command that fixes **it**, not a
  generic one, because `kennis corpus index` on a machine with no
  corpus is a line that runs and does nothing;
- nothing at all searchable is a refusal rather than an empty answer.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import ContextNotFound, KennisError, NothingToIndex
from kennis.retrieval import SCOPE_NAMES, Skipped, sweep


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return tmp_path


def a_note(tmp_path: Path, name: str, body: str) -> None:
    run = CliRunner()
    source = tmp_path / "sources" / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0


def a_doc(tmp_path: Path, name: str, body: str) -> None:
    run = CliRunner()
    source = tmp_path / "sources" / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    assert (
        run.invoke(
            main, ["corpus", "add", "-d", str(source), "--project", "stimela"]
        ).exit_code
        == 0
    )


def a_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """A project bundle, indexed, standing in it.

    Used where a test needs *something* to answer while two corpus
    collections stay unindexed. A third corpus collection cannot play
    that part: literature refuses a document with no bibliographic
    identity, and supplying one fetches its metadata over the network.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    run = CliRunner()
    assert run.invoke(main, ["context", "init"]).exit_code == 0
    assert (
        run.invoke(main, ["remember", "--context", "--title", "Gains", body]).exit_code
        == 0
    )
    assert run.invoke(main, ["context", "index"]).exit_code == 0


def indexed(tmp_path: Path) -> None:
    assert CliRunner().invoke(main, ["corpus", "index"]).exit_code == 0


# ---------------------------------------------------------------------------
# What the sweep returns
# ---------------------------------------------------------------------------


def test_a_sweep_searches_every_scope_that_has_an_index(corpus: Path):
    a_note(corpus, "gains", "Antenna gains drift on long tracks.")
    a_doc(corpus, "solver", "The solver applies antenna gains per interval.")
    indexed(corpus)

    found = sweep("antenna gains", scopes=SCOPE_NAMES, named=False)

    assert set(found.groups) == {"notes", "docs"}
    assert found.searched == ("docs", "notes")


def test_the_groups_keep_scope_order_whatever_order_they_were_asked_in(
    corpus: Path,
):
    """Ordering groups by anything the hits carry would put the
    cross-collection comparison back in through the layout: a band in
    one collection and a band in another are measured on different
    scales, which is what `basis_phrase` says out loud.

    **Asked for in the reverse order**, because that is the form of
    the property that can fail. A first version asserted against
    `SCOPE_NAMES` while also passing `SCOPE_NAMES`, so iterating the
    caller's order would have satisfied it.

    It cannot be written against the scores instead. Search fuses by
    reciprocal rank, `sum 1 / (60 + rank)`, so the best hit of every
    group scores exactly 1/61 and sorting groups by best hit is
    inert - measured, not assumed. Concern #342."""
    a_note(corpus, "gains", "Gains, gains, gains and more gains everywhere.")
    a_doc(corpus, "solver", "A passing mention of gains.")
    indexed(corpus)

    found = sweep("gains", scopes=("notes", "docs"), named=False)

    assert list(found.groups) == ["docs", "notes"]


def test_a_scope_with_no_index_is_skipped_with_its_own_command(corpus: Path):
    a_note(corpus, "gains", "Antenna gains drift on long tracks.")
    a_doc(corpus, "solver", "The solver applies gains.")
    assert (
        CliRunner().invoke(main, ["corpus", "index", "--collection", "notes"]).exit_code
        == 0
    )

    found = sweep("gains", scopes=SCOPE_NAMES, named=False)

    assert "notes" in found.groups
    skipped = {entry.name: entry for entry in found.skipped}
    assert "docs" in skipped
    assert skipped["docs"].resolution == "kennis corpus index --collection docs"


def test_a_named_scope_with_no_index_raises_instead_of_being_skipped(corpus: Path):
    """The same absence, two answers. A reader who asked for `docs`
    and is handed hits from somewhere else has been answered a
    different question than the one they put."""
    a_note(corpus, "gains", "Antenna gains drift.")
    a_doc(corpus, "solver", "The solver applies gains.")
    assert (
        CliRunner().invoke(main, ["corpus", "index", "--collection", "notes"]).exit_code
        == 0
    )

    with pytest.raises((NothingToIndex, KennisError)):
        sweep("gains", scopes=("docs",), named=True)


def test_a_named_context_with_no_bundle_raises(corpus: Path):
    with pytest.raises(ContextNotFound):
        sweep("gains", scopes=("context",), named=True)


def test_a_swept_context_with_no_bundle_is_not_even_mentioned(corpus: Path):
    """Most searches run outside any project. A line about a bundle
    the reader does not have, above every answer, is noise about a
    feature they are not using."""
    a_note(corpus, "gains", "Antenna gains drift.")
    indexed(corpus)

    found = sweep("gains", scopes=SCOPE_NAMES, named=False)

    assert "context" not in {entry.name for entry in found.skipped}


def test_nothing_searchable_at_all_is_a_refusal(corpus: Path):
    """Not an empty answer. "No passages matched" for a corpus that
    was never indexed tells the reader their corpus is empty, which
    is a different and wrong conclusion."""
    a_note(corpus, "gains", "Antenna gains drift.")

    with pytest.raises(KennisError) as refused:
        sweep("gains", scopes=SCOPE_NAMES, named=False)

    assert refused.value.resolution is not None


def test_a_skipped_scope_carries_no_sentence(corpus: Path):
    """`Skipped` names the scope and the command. The words are
    `render/`'s, because a value that already carries the facts as
    fields must not also carry a sentence built from them - that
    sentence is what a front end reaches for, and then the command
    line cannot group two skips onto one line. Concern #81."""
    fields = {field for field in Skipped.__dataclass_fields__}

    assert fields == {"name", "resolution"}


# ---------------------------------------------------------------------------
# The command line still prints what it printed
# ---------------------------------------------------------------------------


def test_every_collection_that_answered_is_named_in_the_summary(corpus: Path):
    a_note(corpus, "gains", "Antenna gains drift on long tracks.")
    a_doc(corpus, "solver", "The solver applies antenna gains per interval.")
    indexed(corpus)

    printed = CliRunner().invoke(main, ["search", "antenna gains"])

    assert printed.exit_code == 0
    assert "notes" in printed.output and "docs" in printed.output


def test_two_skipped_collections_share_one_line_and_one_command(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """A warning per collection is two thirds of the output before
    the answer, so scopes a single command would fix share a line.

    **Two corpus collections unindexed, which is the only shape that
    can fail.** The version this replaces left one scope to skip, so
    it passed for a report that grouped nothing - and the extraction
    had in fact stopped grouping, by giving every collection a
    resolution naming itself. Concern #341.

    The command has to be the shared one: `kennis corpus index`
    builds both, where `--collection docs` leaves the next search
    warning about literature."""
    a_note(corpus, "gains", "Antenna gains drift.")
    a_doc(corpus, "solver", "The solver applies gains.")
    a_bundle(corpus, monkeypatch, "Antenna gains drift on long tracks.")

    printed = CliRunner().invoke(main, ["search", "gains"])

    assert printed.exit_code == 0
    assert printed.output.count("not searched") == 1
    assert "docs" in printed.output and "notes" in printed.output
    assert "--collection" not in printed.output


def test_the_command_line_output_is_unchanged_by_the_extraction(corpus: Path):
    """The guard #88 exists for.

    Every function can cross and a behaviour still be lost. What
    matters is not that `sweep` returns the right values but that
    `kennis search` prints what it printed before, so this asserts
    the whole shape of a report rather than one line of it."""
    a_note(corpus, "gains", "Antenna gains drift on long tracks.")
    indexed(corpus)

    printed = CliRunner().invoke(main, ["search", "gains"])
    lines = [line for line in printed.output.splitlines() if line.strip()]

    # The *order* of the parts, not the first line: a warning about a
    # lexical fallback legitimately precedes the summary, which is
    # what the first version of this test tripped over. What must
    # hold is that the count comes before the groups and the groups
    # before their hits.
    def first(what: str, matches: Callable[[str], bool]) -> int:
        # An index, or a failure that says which part was missing.
        # `next` on an exhausted generator raises StopIteration, which
        # reports as an error with no indication of what was looked for.
        found = [i for i, line in enumerate(lines) if matches(line)]
        assert found, f"no {what} line in:\n" + "\n".join(lines)
        return found[0]

    summary = first("count", lambda line: line.startswith("Found "))
    # The group heading names the scale its levels are on. It used to
    # carry the word "relevance"; it now names each leg. Concern #379.
    scale = first("scale", lambda line: "as a fraction of the best match here" in line)
    detail = first("handle", lambda line: "id=" in line and "chunk=" in line)

    assert summary < scale < detail


@pytest.mark.slow
def test_the_real_command_reports_the_same_scopes_it_searched(corpus: Path):
    """Through a real process, because `CliRunner` shares this
    interpreter and a report assembled at import time would look
    right here and be wrong in a terminal."""
    a_note(corpus, "gains", "Antenna gains drift on long tracks.")
    indexed(corpus)

    finished = subprocess.run(
        ["uv", "run", "kennis", "search", "gains"],
        capture_output=True,
        text=True,
        timeout=300,
        stdin=subprocess.DEVNULL,
        cwd=Path(__file__).resolve().parents[1],
        env={**_environment(corpus)},
    )

    assert finished.returncode == 0, finished.stderr
    assert "Found 1 in notes" in finished.stdout + finished.stderr


def _environment(corpus: Path) -> dict[str, str]:
    import os

    return {
        **os.environ,
        "KENNIS_CONFIG_DIR": str(corpus / "config"),
        "KENNIS_LOG_DIR": str(corpus / "state"),
        "KENNIS_CORPUS_ROOT": str(corpus / "corpus"),
        "KENNIS_EMBEDDING_BACKEND": "none",
        "PYTHONUNBUFFERED": "1",
    }


def test_the_sweep_covers_every_collection_the_corpus_has(corpus: Path):
    """A fourth collection added to the schema and not to `SCOPE_NAMES`
    would be silently unsearchable."""
    assert set(COLLECTION_NAMES) <= set(SCOPE_NAMES)
