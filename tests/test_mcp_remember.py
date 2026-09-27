"""`remember`: the one tool in this server that changes the machine.

Design section 12 - "an agent must be able to write, to both notes and
context". Everything else here answers a question; this writes a file
into a machine-global corpus, commits it, and rebuilds an index.

Two properties carry most of the weight. The corpus write must reach
git, because the corpus is kennis's own repository and an uncommitted
write is one `corpus restore` cannot undo. And the bundle write must
**not** reach git, because a bundle lives in the user's repository and
committing there would take over their version control.

The plan's sentence for this unit is that the server has no interactive
path, so anything unresolved has to have been an argument. The tests
for the failures - no bundle, empty text, oversized text - are that
sentence: each one is an answer the agent can act on rather than a
prompt nobody is there to read.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.errors import ContextNotFound, InputError
from kennis.mcp.tools.read import ReadRequest, read_notes
from kennis.mcp.tools.remember import remember
from kennis.mcp.tools.search import search_notes


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)
    return tmp_path


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def corpus(isolated: Path, run: CliRunner) -> Path:
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    return isolated / "corpus"


@pytest.fixture
def workspace(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project directory that is its own git repository.

    Its own repository on purpose: the test that kennis does not commit
    to it is worthless against a directory where a commit would fail
    anyway.
    """
    root = isolated / "project"
    root.mkdir()
    monkeypatch.chdir(root)
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
    ):
        subprocess.run(command, cwd=root, check=True, stdin=subprocess.DEVNULL)
    return root


def commits_in(root: Path) -> int:
    finished = subprocess.run(
        ["git", "rev-list", "--count", "--all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    return int(finished.stdout.strip())


# ---------------------------------------------------------------------------
# Writing to notes
# ---------------------------------------------------------------------------


def test_a_remembered_note_is_findable_without_a_second_call(
    corpus: Path, isolated: Path, run: CliRunner
):
    """Section 12's second promise: `remember` indexes its own write.

    The collection is indexed first because that is the precondition
    the engine imposes - see the test below - and this test is about
    the promise, not the precondition.
    """
    seed = isolated / "seed.md"
    seed.write_text("# seed\n\nSomething already in the corpus.\n", encoding="utf-8")
    assert run.invoke(main, ["corpus", "add", "-n", str(seed)]).exit_code == 0
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    answered = remember("QuartiCal needs a tuned time chunk for long tracks")

    assert "QuartiCal" in answered
    assert "indexed" in answered
    assert "QuartiCal" in search_notes("time chunk long tracks")


def test_an_unindexed_collection_is_said_so_rather_than_silently_unsearchable(
    corpus: Path,
):
    """`remember` will not build a *first* index for one line - section
    15 measures that at 50s for 1942 chunks, which is a remembered
    sentence paying for the whole corpus.

    So on a fresh corpus the note is written and is not findable, and
    the agent has to be told: otherwise it reports success to the user
    and a later search comes back empty with no explanation.
    """
    answered = remember("QuartiCal needs a tuned time chunk for long tracks")

    assert "not searchable yet" in answered
    assert "kennis corpus index" in answered
    # And says it once. `index_state` also has a word for this outcome,
    # and printing both puts one fact on two adjacent lines.
    assert "not indexed" not in answered


def test_the_answer_carries_the_handle_a_read_tool_takes(corpus: Path):
    """An agent's next act is to pass the handle on, so the identifier
    is in the answer - which the command line's report does not print,
    because a person's next act is to open the file."""
    answered = remember("Sky models are fitted per sub-band")

    identifier = next(
        word.strip("()") for word in answered.split() if word.startswith("(")
    )
    assert "Sky models are fitted per sub-band" in read_notes(
        [ReadRequest(document_id=identifier)]
    )


def test_the_corpus_write_is_committed(corpus: Path):
    """The corpus is kennis's own repository. A write that never reaches
    git is one `corpus history` cannot show and `corpus restore` cannot
    undo."""
    before = commits_in(corpus)

    remember("Antenna gains drift over a long track")

    assert commits_in(corpus) == before + 1


def test_saying_the_same_thing_twice_writes_one_note(corpus: Path):
    """An agent repeating itself is the expected case, and two identical
    notes would both come back from every search that matched either."""
    first = remember("Deconvolution needs a mask for extended emission")
    second = remember("Deconvolution needs a mask for extended emission")

    assert "already" in second.lower()
    identifiers = {answer.split("(")[1].split(")")[0] for answer in (first, second)}
    assert len(identifiers) == 1


def test_a_title_and_a_group_are_honoured(corpus: Path):
    answered = remember(
        "Phase-only calibration first, then amplitude",
        title="Calibration order",
        group="decisions",
    )

    assert "Calibration order" in answered
    assert "decisions/" in answered


def test_the_path_in_the_answer_is_relative_to_the_corpus(corpus: Path):
    """The addressing invariant from concern #299 and #300, which the
    `remember` report had not been held to."""
    answered = remember("Weighting is Briggs with robust zero")

    assert "notes/" in answered
    assert str(existing_corpus().corpus_root) not in answered


# ---------------------------------------------------------------------------
# Writing to the bundle
# ---------------------------------------------------------------------------


def test_a_context_note_lands_in_the_bundle(
    corpus: Path, workspace: Path, run: CliRunner
):
    assert run.invoke(main, ["context", "init", "--here"]).exit_code == 0

    answered = remember("This project images in 2 GHz sub-bands", to_context=True)

    written = list((workspace / ".context").rglob("*.md"))
    assert any(
        "2 GHz sub-bands" in path.read_text(encoding="utf-8") for path in written
    )
    assert ".context/" in answered


def test_kennis_does_not_commit_to_the_users_repository(
    corpus: Path, workspace: Path, run: CliRunner
):
    """The bundle sits inside a repository kennis does not own. Writing
    a file there is the request; committing it is taking over the user's
    version control, and the design leaves the wanting to them."""
    assert run.invoke(main, ["context", "init", "--here"]).exit_code == 0
    before = commits_in(workspace)

    remember("Sub-band imaging, 2 GHz", to_context=True)

    assert commits_in(workspace) == before


def test_no_bundle_is_refused_rather_than_written_to_notes(
    corpus: Path, workspace: Path
):
    """Silently writing a project decision into a machine-global store
    is a worse answer than none: the agent was asked to record something
    about *this* project and would be told it had."""
    with pytest.raises(ContextNotFound):
        remember("This project images in 2 GHz sub-bands", to_context=True)


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


def test_empty_text_is_refused(corpus: Path):
    with pytest.raises(InputError):
        remember("   \n  ")


def test_an_oversized_note_is_refused_rather_than_written(corpus: Path):
    """A person typing prose is self-limiting and `--from` is a
    deliberate act. A model emitting a large blob into a machine-global
    corpus is an accident, and one that git then keeps forever."""
    with pytest.raises(InputError):
        remember("word " * 40_000)

    assert "0 documents" in _notes_count()


def test_a_note_just_under_the_cap_is_written(corpus: Path):
    """The other side of the cap, so the test above cannot pass by the
    tool refusing everything."""
    remember("word " * 100)

    assert "1 document" in _notes_count()


def _notes_count() -> str:
    from kennis.mcp.tools.corpus import list_corpus

    return list_corpus(collection="notes")
