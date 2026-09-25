"""The commands that read a corpus, and the one that makes one.

The plan asks that every command be exercised through the engine in one test
and through the command line in another, and that they agree. These are the
command-line half: what a person sees, and what the exit status says.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A corpus, a config and a log, all of them this test's own."""
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    return tmp_path / "corpus"


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


def initialised(run: CliRunner) -> None:
    result = run.invoke(main, ["corpus", "init"])
    assert result.exit_code == 0, result.output


def a_source(corpus: Path, name: str = "trees.md", body: str = "Body.") -> Path:
    """A file outside the corpus, for `corpus add` to take.

    Beside the corpus rather than in it: `add` converts and files it, which
    is the supported route in, and the route whose commit lands before the
    index is built.
    """
    path = corpus.parent / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {name.removesuffix('.md')}\n\n{body}\n", encoding="utf-8")
    return path


def a_note(corpus: Path, name: str, body: str = "Body.") -> Path:
    """A note written as kennis writes one.

    `source` is required by the schema, so a fixture that omits it produces
    a document the lenient reader reports and the strict one refuses - which
    is a different test from the one most of these are.
    """
    path = corpus / "notes" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\n"
        f"id: {name[:10].replace('.', 'x').ljust(10, 'a')}\n"
        f"title: {name}\n"
        f"owner: user\n"
        f"source:\n"
        f"  from: 'path:/tmp/{name}'\n"
        f"  via: verbatim\n"
        f"  format: markdown\n"
        f"---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def committed(corpus: Path) -> None:
    """Record what is on disk, so a later edit reads as an edit rather than
    as a file kennis has never seen."""
    from kennis.engine.history.repository import Repository

    Repository(corpus).commit("add", scope="notes", summary="added by a test")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_creates_a_corpus(run: CliRunner, isolated: Path):
    result = run.invoke(main, ["corpus", "init"])

    assert result.exit_code == 0
    assert (isolated / ".git").is_dir()
    assert (isolated / "notes").is_dir()


def test_init_says_where_the_corpus_is(run: CliRunner, isolated: Path):
    result = run.invoke(main, ["corpus", "init"])

    assert str(isolated) in result.output


def test_init_twice_fails_with_a_message_rather_than_a_traceback(run: CliRunner):
    initialised(run)

    result = run.invoke(main, ["corpus", "init"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "already" in result.output


def test_init_without_git_fails_and_leaves_nothing(
    run: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch
):
    """The plan's first test for milestone 4, now reachable from a terminal."""
    monkeypatch.setattr("shutil.which", lambda _name: None)

    result = run.invoke(main, ["corpus", "init"])

    assert result.exit_code != 0
    assert not isolated.exists()
    assert "git" in result.output


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_on_a_fresh_corpus_reports_it_is_empty(run: CliRunner):
    initialised(run)

    result = run.invoke(main, ["corpus", "status"])

    assert result.exit_code == 0
    assert "0" in result.output


def test_status_counts_documents_per_collection(run: CliRunner, isolated: Path):
    initialised(run)
    a_note(isolated, "one.md")
    a_note(isolated, "two.md")

    result = run.invoke(main, ["corpus", "status"])

    assert "notes" in result.output
    assert "2" in result.output


def test_status_survives_a_document_it_cannot_read(run: CliRunner, isolated: Path):
    """Concern #21. `DocumentInvalid` names this command as its resolution,
    so it must be written against the lenient reader - or it dies on exactly
    the corpus it exists to diagnose."""
    initialised(run)
    a_note(isolated, "good.md")
    (isolated / "notes" / "broken.md").write_text(
        "---\n: : not yaml : :\n---\n\nBody.\n", encoding="utf-8"
    )

    result = run.invoke(main, ["corpus", "status"])

    assert result.exit_code == 0, result.output
    assert "broken.md" in result.output


def test_status_reports_a_change_made_outside_kennis(run: CliRunner, isolated: Path):
    initialised(run)
    note = a_note(isolated, "one.md")
    committed(isolated)
    note.write_text(note.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")

    result = run.invoke(main, ["corpus", "status"])

    assert "outside kennis" in result.output


def test_status_on_a_corpus_that_does_not_exist_says_how_to_make_one(
    run: CliRunner,
):
    result = run.invoke(main, ["corpus", "status"])

    assert result.exit_code != 0
    assert "corpus init" in result.output
    assert "Traceback" not in result.output


def test_status_says_there_is_no_index_yet_rather_than_failing(
    run: CliRunner, isolated: Path
):
    """A corpus holding documents and no index. That is not an error and must
    not read like one - it is the state every corpus is in between its first
    `corpus add` and its first `corpus index`, and the answer is the command
    that changes it."""
    initialised(run)
    a_note(isolated, "trees.md")

    result = run.invoke(main, ["corpus", "status"])

    assert result.exit_code == 0
    assert "no index yet" in result.output
    assert "kennis corpus index" in result.output


def test_status_names_the_command_that_refreshes_a_stale_index(
    run: CliRunner, isolated: Path
):
    """An index reported as stale used to be left without a command. The
    project rule is that an error names what resolves it, and a warning a
    reader can act on is no different - they were told something was wrong
    and not what to type. Concern #244."""
    initialised(run)
    # Two things this route avoids. A hand-written document is committed by
    # the *index* command, after `build_index` recorded the head it was
    # built from, so it reads as "not yet indexed" even though it was
    # (concern #245). And a hand-*edited* one is an out-of-band change,
    # which `status` already ends by naming a remedy for - so the hint would
    # appear whether or not the freshness line carried one, and the test
    # would pass with its subject removed. Removing a document through
    # kennis leaves the index stale and the working tree clean.
    for name in ("trees.md", "rivers.md"):
        added = run.invoke(main, ["corpus", "add", "-n", str(a_source(isolated, name))])
        assert added.exit_code == 0, added.output
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    removed = run.invoke(main, ["corpus", "remove", "trees", "--yes"])
    assert removed.exit_code == 0, removed.output

    result = run.invoke(main, ["corpus", "status"])

    assert result.exit_code == 0, result.output
    assert "stale" in result.output
    assert "kennis corpus index" in result.output


def test_status_names_the_command_when_documents_are_not_yet_indexed(
    run: CliRunner, isolated: Path
):
    """`in step, with 1 document not yet indexed` is not a fault - the index
    holds less rather than something false - but it is still something to
    act on, so it carries the command and is not printed as good news."""
    initialised(run)
    assert (
        run.invoke(main, ["corpus", "add", "-n", str(a_source(isolated))]).exit_code
        == 0
    )
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    assert (
        run.invoke(
            main, ["corpus", "add", "-n", str(a_source(isolated, "rivers.md"))]
        ).exit_code
        == 0
    )

    result = run.invoke(main, ["corpus", "status"])

    assert result.exit_code == 0, result.output
    assert "not yet indexed" in result.output
    assert "kennis corpus index" in result.output


def test_status_says_nothing_to_do_when_every_index_is_current(
    run: CliRunner, isolated: Path
):
    initialised(run)
    assert (
        run.invoke(main, ["corpus", "add", "-n", str(a_source(isolated))]).exit_code
        == 0
    )
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    result = run.invoke(main, ["corpus", "status"])

    assert result.exit_code == 0, result.output
    assert "in step" in result.output
    assert "kennis corpus index" not in result.output


def test_status_on_an_empty_corpus_does_not_mention_the_index(run: CliRunner):
    """The next step there is to add documents, not to index nothing. Saying
    both would make the one that matters harder to see."""
    initialised(run)

    result = run.invoke(main, ["corpus", "status"])

    assert result.exit_code == 0
    assert "no index" not in result.output


# ---------------------------------------------------------------------------
# list and tree
# ---------------------------------------------------------------------------


def test_list_names_every_document(run: CliRunner, isolated: Path):
    initialised(run)
    a_note(isolated, "one.md")
    a_note(isolated, "two.md")

    result = run.invoke(main, ["corpus", "list"])

    assert result.exit_code == 0
    assert "one.md" in result.output
    assert "two.md" in result.output


def test_list_can_be_restricted_to_one_collection(run: CliRunner, isolated: Path):
    initialised(run)
    a_note(isolated, "one.md")

    result = run.invoke(main, ["corpus", "list", "--collection", "literature"])

    assert result.exit_code == 0
    assert "one.md" not in result.output


def test_list_of_an_empty_collection_says_so(run: CliRunner):
    initialised(run)

    result = run.invoke(main, ["corpus", "list"])

    assert result.exit_code == 0
    assert "no documents" in result.output.lower()


def test_tree_shows_the_groups(run: CliRunner, isolated: Path):
    initialised(run)
    grouped = isolated / "notes" / "calibration"
    grouped.mkdir(parents=True)
    a_note(grouped.parent, "loose.md")
    (grouped / "gains.md").write_text(
        "---\nid: gainsaaaaa\ntitle: Gains\nowner: user\n---\n\n# Gains\n",
        encoding="utf-8",
    )

    result = run.invoke(main, ["corpus", "tree"])

    assert result.exit_code == 0
    assert "calibration" in result.output


def test_tree_names_each_document_by_its_identifier(run: CliRunner, isolated: Path):
    """Every other command takes an identifier, so the one view of the whole
    corpus must be one something can be done from. Concern #188."""
    initialised(run)
    a_note(isolated, "one.md")

    result = run.invoke(main, ["corpus", "tree"])

    assert result.exit_code == 0
    line = next(line for line in result.output.splitlines() if "one.md" in line)
    assert "onexmdaaaa" in line


def test_tree_shows_a_document_it_cannot_read(run: CliRunner, isolated: Path):
    """A tree is a picture of what is on disk. A document with broken
    frontmatter is on disk, and omitting it is how a corpus comes to hold a
    file nobody knows about."""
    initialised(run)
    broken = isolated / "notes" / "broken.md"
    broken.write_text("---\nnot: valid\n---\n\n# Broken\n", encoding="utf-8")

    result = run.invoke(main, ["corpus", "tree"])

    assert result.exit_code == 0
    assert "broken.md" in result.output


def test_tree_shows_a_wrapped_document_as_one_line(run: CliRunner, isolated: Path):
    """A document with assets is a directory holding `content.md`. It is one
    document, and walking into it would put `content.md` under every title
    that happens to have a figure in it."""
    initialised(run)
    wrapper = isolated / "notes" / "Wrapped"
    (wrapper / "images").mkdir(parents=True)
    (wrapper / "images" / "figure.png").write_bytes(b"")
    (wrapper / "content.md").write_text(
        "---\nid: wrappedaaa\ntitle: Wrapped\nowner: user\n"
        "source:\n  from: 'path:x'\n  via: verbatim\n  format: markdown\n"
        "---\n\n# Wrapped\n",
        encoding="utf-8",
    )

    result = run.invoke(main, ["corpus", "tree"])

    assert result.exit_code == 0, result.output
    assert "content.md" not in result.output
    assert "figure.png" not in result.output
    line = next(line for line in result.output.splitlines() if "Wrapped" in line)
    assert "wrappedaaa" in line


def test_tree_distinguishes_a_group_from_a_document(run: CliRunner, isolated: Path):
    """Brian: groups should not look the same as the leaf nodes. A trailing
    slash is the whole of the current difference. Concern #193."""
    initialised(run)
    grouped = isolated / "notes" / "calibration"
    grouped.mkdir(parents=True)
    (grouped / "gains.md").write_text(
        "---\nid: gainsaaaaa\ntitle: Gains\nowner: user\n"
        "source:\n  from: 'path:x'\n  via: verbatim\n  format: markdown\n"
        "---\n\n# Gains\n",
        encoding="utf-8",
    )

    result = run.invoke(main, ["corpus", "tree"])

    assert result.exit_code == 0
    group_line = next(
        line for line in result.output.splitlines() if "calibration" in line
    )
    document_line = next(
        line for line in result.output.splitlines() if "gains.md" in line
    )
    # A group carries no identifier, because nothing addresses one; a
    # document carries its own.
    assert "gainsaaaaa" not in group_line
    assert "gainsaaaaa" in document_line
    assert group_line.strip().endswith("/")


# ---------------------------------------------------------------------------
# Output discipline
# ---------------------------------------------------------------------------


def test_colour_disappears_when_output_is_not_a_terminal(
    run: CliRunner, isolated: Path
):
    """The plan names this. `CliRunner` captures rather than attaching a
    terminal, so any escape sequence here would reach a pipe or a file."""
    initialised(run)
    a_note(isolated, "one.md")

    result = run.invoke(main, ["corpus", "list"])

    assert "\x1b[" not in result.output


def test_quiet_prints_nothing_on_success(run: CliRunner, isolated: Path):
    initialised(run)
    a_note(isolated, "one.md")

    result = run.invoke(main, ["--quiet", "corpus", "status"])

    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_a_command_writes_its_events_to_the_log(run: CliRunner, tmp_path: Path):
    """The report says what happened; the log says why and with what."""
    initialised(run)

    log = tmp_path / "state" / "kennis.log"
    assert log.is_file()
    assert "init" in log.read_text(encoding="utf-8")
