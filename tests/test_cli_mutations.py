"""The commands that write, through the command line.

The plan asks that every command be exercised through the engine in one test
and through the command line in another, and that they agree. The engine half
of `add`, `index`, `history` and `restore` is already covered by the
milestone 2 to 4 suites; these are the properties that only appear once there
is a command: the lock, the commit that follows a write, and what a person
sees.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.history.git import git
from kennis.engine.history.repository import Repository
from kennis.engine.locking import corpus_lock, lock_path


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A corpus, a config, a log and a lexical-only index, all this test's own.

    `KENNIS_EMBEDDING_BACKEND=none` through the environment rather than a
    test-only argument: a dense index would download a model, and the way a
    user turns that off is the way a test should.
    """
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    return tmp_path / "corpus"


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def corpus(isolated: Path, run: CliRunner) -> Path:
    result = run.invoke(main, ["corpus", "init"])
    assert result.exit_code == 0, result.output
    return isolated


def a_source(tmp_path: Path, name: str, body: str = "Some words about trees.") -> Path:
    """A file outside the corpus, of the kind `corpus add` is given."""
    path = tmp_path / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {name}\n\n{body}\n", encoding="utf-8")
    return path


def added(run: CliRunner, path: Path, *extra: str) -> str:
    """Add one file as a note and return the identifier it was given."""
    result = run.invoke(main, ["corpus", "add", "-n", str(path), *extra])
    assert result.exit_code == 0, result.output
    return result.output


def only_document(corpus: Path, collection: str = "notes") -> Path:
    found = sorted((corpus / collection).rglob("*.md"))
    assert len(found) == 1, found
    return found[0]


def identifier_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("id:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no identifier in {path}")


def manifest_of(corpus: Path, collection: str) -> dict[str, object]:
    """The published index's manifest, read the way a person would find it."""
    root = corpus / "index" / collection
    pointer = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    return dict(
        json.loads(
            (root / str(pointer["index_id"]) / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
    )


def tracked(corpus: Path) -> list[str]:
    """Every path the corpus repository holds."""
    return git(["ls-files"], cwd=corpus).lines()


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def test_add_writes_the_document_and_reports_it(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    output = added(run, a_source(tmp_path, "trees.md"))
    assert only_document(corpus).is_file()
    assert "trees" in output


def test_add_commits_what_it_wrote(corpus: Path, run: CliRunner, tmp_path: Path):
    """Milestone 4 built `Repository.commit` and nothing has called it from a
    user action until now. A corpus whose documents are not committed has no
    history to read and nothing for `restore` to reach."""
    before = Repository(corpus).head()
    added(run, a_source(tmp_path, "trees.md"))
    after = Repository(corpus).head()
    assert after is not None and after != before
    assert Repository(corpus).is_clean()


def test_adding_the_same_file_twice_makes_no_second_commit(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`commit` returns None when the tree was already clean, which is what a
    duplicate add looks like. An empty commit would fill history with noise."""
    source = a_source(tmp_path, "trees.md")
    added(run, source)
    first = Repository(corpus).head()
    added(run, source)
    assert Repository(corpus).head() == first


def test_add_without_a_collection_says_which_ones_exist(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    result = run.invoke(main, ["corpus", "add", str(a_source(tmp_path, "t.md"))])
    assert result.exit_code != 0
    assert "notes" in result.output and "literature" in result.output


def test_two_collections_named_differently_is_an_error(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """Not a precedence puzzle. Someone who typed both meant one of them and
    kennis cannot tell which."""
    result = run.invoke(
        main,
        [
            "corpus",
            "add",
            "-n",
            "--collection",
            "literature",
            str(a_source(tmp_path, "t.md")),
        ],
    )
    assert result.exit_code != 0
    assert "literature" in result.output


def test_an_option_that_means_nothing_here_is_refused(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`--citekey` on a notes add is someone expecting a citekey to come out
    the other end. Silence would let them find that out from the corpus."""
    result = run.invoke(
        main,
        [
            "corpus",
            "add",
            "-n",
            "--citekey",
            "welman2024",
            str(a_source(tmp_path, "t.md")),
        ],
    )
    assert result.exit_code != 0
    assert "--citekey" in result.output and "literature" in result.output


# ---------------------------------------------------------------------------
# remove and move
# ---------------------------------------------------------------------------


def test_remove_deletes_the_document_and_commits(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    added(run, a_source(tmp_path, "trees.md"))
    handle = identifier_of(only_document(corpus))
    before = Repository(corpus).head()

    result = run.invoke(main, ["corpus", "remove", handle, "--yes"])
    assert result.exit_code == 0, result.output
    assert not list((corpus / "notes").rglob("*.md"))
    assert Repository(corpus).head() != before


def test_remove_asks_first_and_a_refusal_keeps_the_document(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    added(run, a_source(tmp_path, "trees.md"))
    handle = identifier_of(only_document(corpus))

    result = run.invoke(main, ["corpus", "remove", handle], input="n\n")
    assert only_document(corpus).is_file()
    # 130, the shell's convention for an interrupted command, and kennis's
    # own wording rather than click's "Aborted!". Nothing went wrong, so the
    # line must not read as an error.
    assert result.exit_code == 130
    assert "Cancelled" in result.output
    assert "Aborted" not in result.output


def test_removing_an_unknown_handle_names_where_to_look(corpus: Path, run: CliRunner):
    result = run.invoke(main, ["corpus", "remove", "nosuchdoc", "--yes"])
    assert result.exit_code != 0
    assert "kennis corpus list" in result.output


def test_move_relocates_the_document_and_keeps_its_identifier(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The surrogate identifier is what makes a move safe: every handle that
    pointed at the document still does, because none addresses it by path."""
    added(run, a_source(tmp_path, "trees.md"))
    handle = identifier_of(only_document(corpus))

    result = run.invoke(main, ["corpus", "move", handle, "--group", "botany"])
    assert result.exit_code == 0, result.output

    moved = only_document(corpus)
    assert moved.parent.name == "botany"
    assert identifier_of(moved) == handle


def test_retitling_alone_leaves_the_document_where_it_is(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`--group` and `--title` are independent. A rename that silently moved
    the document to the collection root would undo the filing the user did
    when they added it."""
    added(run, a_source(tmp_path, "trees.md"), "--group", "botany")
    handle = identifier_of(only_document(corpus))

    result = run.invoke(main, ["corpus", "move", handle, "--title", "Deciduous Trees"])

    assert result.exit_code == 0, result.output
    moved = only_document(corpus)
    assert moved.parent.name == "botany"
    assert "Deciduous" in moved.name


def test_regrouping_alone_keeps_the_filename(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    added(run, a_source(tmp_path, "trees.md"))
    before = only_document(corpus).name
    handle = identifier_of(only_document(corpus))

    result = run.invoke(main, ["corpus", "move", handle, "--group", "botany"])

    assert result.exit_code == 0, result.output
    assert only_document(corpus).name == before


def test_a_wrapped_document_moves_with_its_assets(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The unit that moves is the wrapper directory. A move that took the
    bare `content.md` would rename the document to "content" and strand the
    assets where they were."""
    source = tmp_path / "sources" / "paper.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Paper\n\nWords.\n", encoding="utf-8")
    result = run.invoke(main, ["corpus", "add", "-n", "--keep-original", str(source)])
    assert result.exit_code == 0, result.output

    # Located by `content.md` rather than by globbing `*.md`: the retained
    # original is markdown too, so a glob finds the asset as well as the
    # document.
    leaf = next((corpus / "notes").rglob("content.md"))
    wrapper = leaf.parent
    kept = sorted(item.name for item in wrapper.iterdir() if item.name != "content.md")
    assert kept, sorted(wrapper.iterdir())
    handle = identifier_of(leaf)

    moved = run.invoke(main, ["corpus", "move", handle, "--group", "papers"])
    assert moved.exit_code == 0, moved.output

    landed = next((corpus / "notes").rglob("content.md")).parent
    assert landed.parent.name == "papers"
    assert landed.name == wrapper.name
    assert not wrapper.exists()
    assert (
        sorted(item.name for item in landed.iterdir() if item.name != "content.md")
        == kept
    )


def test_retitling_a_wrapped_document_does_not_nest_it(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """A wrapped document is filed where its *wrapper* sits, not where its
    `content.md` sits. Reading the leaf's parent as the group would put the
    renamed wrapper inside the old one."""
    source = tmp_path / "sources" / "paper.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("# Paper\n\nWords.\n", encoding="utf-8")
    assert (
        run.invoke(
            main, ["corpus", "add", "-n", "--keep-original", str(source)]
        ).exit_code
        == 0
    )

    wrapper = next((corpus / "notes").rglob("content.md")).parent
    assert wrapper.parent == corpus / "notes"
    handle = identifier_of(wrapper / "content.md")

    result = run.invoke(main, ["corpus", "move", handle, "--title", "Renamed Paper"])
    assert result.exit_code == 0, result.output

    landed = next((corpus / "notes").rglob("content.md")).parent
    assert landed.parent == corpus / "notes"
    assert "Renamed" in landed.name


def test_a_docs_page_cannot_be_regrouped(corpus: Path, run: CliRunner):
    """Its directory is its project, and its identifier is derived from
    `(project, page)`. Moving the file alone would leave the directory, the
    `docs.project` field and the identifier disagreeing."""
    page = corpus / "docs" / "numpy" / "Indexing.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\n"
        "id: docsnumpy1\n"
        "title: Indexing\n"
        "owner: user\n"
        "id_from: 'docs:numpy/indexing'\n"
        "source:\n"
        "  from: 'url:https://numpy.org/doc/indexing'\n"
        "  via: html\n"
        "  format: html\n"
        "docs:\n"
        "  project: numpy\n"
        "  page: indexing\n"
        "---\n\n# Indexing\n\nHow indexing works.\n",
        encoding="utf-8",
    )

    result = run.invoke(main, ["corpus", "move", "docsnumpy1", "--group", "scipy"])

    assert result.exit_code != 0
    assert "project" in result.output
    assert page.is_file()


def test_a_docs_page_can_still_be_retitled(corpus: Path, run: CliRunner):
    """The filename is derived from the title and the identifier is not, so
    renaming one changes neither the project nor the page key."""
    page = corpus / "docs" / "numpy" / "Indexing.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\n"
        "id: docsnumpy1\n"
        "title: Indexing\n"
        "owner: user\n"
        "id_from: 'docs:numpy/indexing'\n"
        "source:\n"
        "  from: 'url:https://numpy.org/doc/indexing'\n"
        "  via: html\n"
        "  format: html\n"
        "docs:\n"
        "  project: numpy\n"
        "  page: indexing\n"
        "---\n\n# Indexing\n\nHow indexing works.\n",
        encoding="utf-8",
    )

    result = run.invoke(
        main, ["corpus", "move", "docsnumpy1", "--title", "Fancy Indexing"]
    )

    assert result.exit_code == 0, result.output
    moved = only_document(corpus, "docs")
    assert moved.parent.name == "numpy"
    assert identifier_of(moved) == "docsnumpy1"


def test_move_between_collections_is_refused_for_now(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The design allows it; the engine's `move_document` keeps the collection
    fixed, so v0.1 says so rather than half-doing it."""
    added(run, a_source(tmp_path, "trees.md"))
    handle = identifier_of(only_document(corpus))

    result = run.invoke(
        main, ["corpus", "move", handle, "--to-collection", "literature"]
    )
    assert result.exit_code != 0
    assert "collection" in result.output


# ---------------------------------------------------------------------------
# index, and the status that reads it
# ---------------------------------------------------------------------------


def test_index_builds_and_status_then_reads_it(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    added(run, a_source(tmp_path, "trees.md"))

    built = run.invoke(main, ["corpus", "index", "--collection", "notes"])
    assert built.exit_code == 0, built.output
    assert (corpus / "index" / "notes" / "latest.json").is_file()

    status = run.invoke(main, ["corpus", "status"])
    assert status.exit_code == 0, status.output
    assert "in step" in status.output


def test_status_does_not_claim_an_unindexed_corpus_is_indexed(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """Step 2 answered this with a constant, which was true the day it was
    written and false the moment `corpus index` existed."""
    added(run, a_source(tmp_path, "trees.md"))
    status = run.invoke(main, ["corpus", "status"])
    assert status.exit_code == 0, status.output
    assert "in step" not in status.output


def test_status_reports_a_stale_index_after_an_edit(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    added(run, a_source(tmp_path, "trees.md"))
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    document = only_document(corpus)
    document.write_text(
        document.read_text(encoding="utf-8") + "\nAn edit made by hand.\n",
        encoding="utf-8",
    )

    status = run.invoke(main, ["corpus", "status"])
    assert status.exit_code == 0, status.output
    assert "stale" in status.output


def test_index_says_what_it_would_embed_with(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """A dense build downloads a model on a machine that has never run one.
    The command names the backend before it starts, so a long pause has an
    explanation already on screen."""
    added(run, a_source(tmp_path, "trees.md"))
    built = run.invoke(main, ["corpus", "index"])
    assert built.exit_code == 0, built.output
    assert "lexical" in built.output.lower()


def test_index_records_what_it_built_in_the_history(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`index(corpus): 2 documents, 2 chunks`, not `index(corpus): nothing`.
    An index has no outcome tally, so the subject carries what it built."""
    added(run, a_source(tmp_path, "trees.md"))
    added(run, a_source(tmp_path, "rivers.md"))
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    result = run.invoke(main, ["corpus", "history"])
    assert result.exit_code == 0, result.output
    assert "2 documents" in result.output
    assert "chunk" in result.output


def test_indexing_an_empty_corpus_says_so_rather_than_failing(
    corpus: Path, run: CliRunner
):
    """`build_index` refuses an empty collection by design, and two of the
    three are empty on most corpora. Asking for all of them must not fail on
    that account."""
    result = run.invoke(main, ["corpus", "index"])

    assert result.exit_code == 0, result.output
    assert "nothing to index" in result.output


def test_a_move_is_not_reported_as_a_loss(corpus: Path, run: CliRunner, tmp_path: Path):
    """Git's rename detection is a heuristic, so freshness reads a move as
    one document gone and one added. Naming only the departure would tell a
    person their document had vanished."""
    added(run, a_source(tmp_path, "trees.md"))
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    handle = identifier_of(only_document(corpus))
    assert run.invoke(main, ["corpus", "move", handle, "--group", "x"]).exit_code == 0

    status = run.invoke(main, ["corpus", "status"])
    assert "gone" in status.output
    assert "added" in status.output


# ---------------------------------------------------------------------------
# history and restore
# ---------------------------------------------------------------------------


def test_history_lists_what_the_commands_did_newest_first(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    added(run, a_source(tmp_path, "trees.md"))
    handle = identifier_of(only_document(corpus))
    assert run.invoke(main, ["corpus", "remove", handle, "--yes"]).exit_code == 0

    result = run.invoke(main, ["corpus", "history"])
    assert result.exit_code == 0, result.output
    assert result.output.index("remove") < result.output.index("add")


def test_restore_brings_back_a_removed_document(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    added(run, a_source(tmp_path, "trees.md"))
    handle = identifier_of(only_document(corpus))
    removed_at = Repository(corpus).head()
    assert run.invoke(main, ["corpus", "remove", handle, "--yes"]).exit_code == 0
    assert removed_at is not None

    result = run.invoke(main, ["corpus", "restore", handle, "--commit", removed_at])
    assert result.exit_code == 0, result.output
    assert identifier_of(only_document(corpus)) == handle


# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------


def test_a_second_writer_is_told_the_corpus_is_busy(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """`timeout=0`, so this reports rather than waits. Written so that a
    regression is a failure and not a hung suite: if the lock ever blocks,
    this test stops rather than passing late - concern #86."""
    source = a_source(tmp_path, "trees.md")
    with corpus_lock(corpus):
        result = run.invoke(main, ["corpus", "add", "-n", str(source)])
    assert result.exit_code != 0
    assert "busy" in result.output.lower() or "using the corpus" in result.output


def test_a_reader_is_not_blocked_by_a_held_lock(corpus: Path, run: CliRunner):
    """`status` is the command you most want when something is stuck, so it
    must not be the one that waits for whatever is stuck."""
    with corpus_lock(corpus):
        result = run.invoke(main, ["corpus", "status"])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# The report is not the log
# ---------------------------------------------------------------------------


def test_the_log_holds_the_per_item_detail_the_report_summarises(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """Section 14's requirement, and the whole argument for an event stream
    over a progress callback: the display filters, the log does not."""
    added(run, a_source(tmp_path, "trees.md"))
    logged = (tmp_path / "state" / "kennis.log").read_text(encoding="utf-8")
    assert "trees" in logged
    assert "added" in logged


def test_a_diagnostic_from_the_stream_reaches_the_person(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """A document kennis cannot read is reported by the loader as a
    `Diagnostic`. It must arrive while the command runs, not only in the
    log."""
    added(run, a_source(tmp_path, "trees.md"))
    broken = corpus / "notes" / "broken.md"
    broken.write_text("---\nid: nope\n---\n\nNo title, no source.\n", encoding="utf-8")

    result = run.invoke(main, ["corpus", "index"])
    assert "broken.md" in result.output or "searchable" in result.output


def test_quiet_suppresses_the_report_but_not_the_failure(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    quiet = run.invoke(
        main, ["--quiet", "corpus", "add", "-n", str(a_source(tmp_path, "t.md"))]
    )
    assert quiet.exit_code == 0, quiet.output
    assert quiet.output.strip() == ""

    failed = run.invoke(main, ["--quiet", "corpus", "remove", "nosuchdoc", "--yes"])
    assert failed.exit_code != 0
    assert failed.output.strip() != ""


# ---------------------------------------------------------------------------
# The index manifest, read back
# ---------------------------------------------------------------------------


def test_the_manifest_records_the_commit_it_was_built_from(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The commit the *corpus* was at when the build started, which is not
    HEAD afterwards: the index is tracked, so committing it advances HEAD
    past the build. Freshness is a diff scoped to the collection, and that
    later commit touches `index/` alone, which is why it reads in step."""
    added(run, a_source(tmp_path, "trees.md"))
    content_at = Repository(corpus).head()
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    assert manifest_of(corpus, "notes")["built_from"] == content_at
    assert Repository(corpus).head() != content_at


def test_the_lock_is_never_committed(corpus: Path, run: CliRunner, tmp_path: Path):
    """It lives inside the corpus because that is what it guards, and it is
    not part of it. A committed lock file travels to every clone and reports
    a corpus that was busy on another machine three weeks ago."""
    added(run, a_source(tmp_path, "trees.md"))
    assert lock_path(corpus).is_file()
    assert ".kennis.lock" not in tracked(corpus)


def test_the_vector_cache_is_never_committed(
    corpus: Path, run: CliRunner, tmp_path: Path
):
    """The published index already holds every vector once. Committing the
    cache beside it would store them twice for a saving that only helps the
    machine that built them."""
    added(run, a_source(tmp_path, "trees.md"))
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0

    cache = corpus / "index" / "notes" / "vectors"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "somedocument.npy").write_bytes(b"not really a matrix")
    assert Repository(corpus).is_clean()


def test_the_index_itself_is_committed(corpus: Path, run: CliRunner, tmp_path: Path):
    """Tracked deliberately, so a clone is searchable immediately with no
    rebuild and no model download."""
    added(run, a_source(tmp_path, "trees.md"))
    assert run.invoke(main, ["corpus", "index"]).exit_code == 0
    assert any(path.startswith("index/notes/") for path in tracked(corpus))


# ---------------------------------------------------------------------------
# A document deleted outside kennis
# ---------------------------------------------------------------------------
#
# design.md, "Changes made outside kennis": a deletion is restored rather than
# honoured, because an out-of-band delete carries no record of intent and
# treating an accident as an instruction is the more expensive mistake.
# `restore_deletions` implemented that and nothing called it (concern #128).
# Brian's decision: the reporting command reports, and the commands that
# already take the lock and write are the ones that put the file back.


def test_status_reports_a_hand_deletion_without_restoring_it(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    """`status` is a diagnostic. It must not write to the corpus, and it must
    not claim a restore it did not attempt."""
    added(run, a_source(tmp_path, "Trees.md"))
    document = only_document(corpus)
    document.unlink()

    result = run.invoke(main, ["corpus", "status"])

    assert result.exit_code == 0, result.output
    assert not document.exists()
    assert "deleted outside kennis" in result.output
    assert "could not be restored" not in result.output


def test_indexing_restores_a_document_deleted_outside_kennis(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    added(run, a_source(tmp_path, "Trees.md"))
    document = only_document(corpus)
    body = document.read_text(encoding="utf-8")
    document.unlink()

    result = run.invoke(main, ["corpus", "index"])

    assert result.exit_code == 0, result.output
    assert document.exists(), result.output
    assert document.read_text(encoding="utf-8") == body
    assert "restored" in result.output.lower()


def test_adding_restores_a_document_deleted_outside_kennis(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    """The addition must not be what buries the loss: a document deleted by
    hand is put back before the new one is written."""
    added(run, a_source(tmp_path, "Trees.md"))
    document = only_document(corpus)
    document.unlink()

    added(run, a_source(tmp_path, "Rivers.md"))

    assert document.exists()
    # `a_source` writes `# <name>` as the heading, so a source called
    # `Trees.md` is titled `Trees.md` and lands as `Trees.md.md`.
    assert sorted(path.name for path in (corpus / "notes").rglob("*.md")) == [
        "Rivers.md.md",
        "Trees.md.md",
    ]


def test_a_restored_document_leaves_the_tree_clean(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    """`git checkout <commit> -- <path>` writes the index as well as the work
    tree, so the restore needs no commit of its own. If it did, the tree
    would be dirty and the next command would commit someone else's change."""
    added(run, a_source(tmp_path, "Trees.md"))
    only_document(corpus).unlink()

    run.invoke(main, ["corpus", "index"])

    assert Repository(corpus).is_clean()


def test_an_edit_made_by_hand_is_never_reverted_by_a_write(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    """Only deletions are undone. Reverting an edit is a resolution the user
    chooses, not something a later command does to them."""
    added(run, a_source(tmp_path, "Trees.md"))
    document = only_document(corpus)
    edited = document.read_text(encoding="utf-8") + "\nA line added by hand.\n"
    document.write_text(edited, encoding="utf-8")

    run.invoke(main, ["corpus", "index"])

    assert document.read_text(encoding="utf-8") == edited


def test_status_names_the_command_for_every_change_it_reports(
    run: CliRunner, corpus: Path, tmp_path: Path
):
    """design.md: every out-of-band change is reported *alongside the command
    that would have done it properly*. `remedies_for` produced those commands
    and no command printed them, so the sentence arrived without the way out.
    """
    added(run, a_source(tmp_path, "Trees.md"))
    only_document(corpus).unlink()
    (corpus / "notes" / "dropped-in.md").write_text(
        "no frontmatter\n", encoding="utf-8"
    )

    result = run.invoke(main, ["corpus", "status"])

    assert result.exit_code == 0, result.output
    assert "kennis corpus restore" in result.output, result.output
    # The hand-created file gets words rather than a command, because no
    # command adopts it in place (#129).
    assert "Move it outside the corpus" in result.output, result.output
