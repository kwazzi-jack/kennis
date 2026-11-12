"""Reading what kennis did, and putting a document back as it was.

The commit messages were given a structure in step 1 - `add(notes): 3 added`
rather than "update" - precisely so this step could read them back.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from kennis.engine.errors import DocumentNotFound
from kennis.engine.events import Outcome
from kennis.engine.history.freshness import index_freshness
from kennis.engine.history.history import (
    commit_summary,
    document_at,
    document_path_at,
    last_point_holding,
    outcome_summary,
    read_history,
    restore_document,
)
from kennis.engine.history.repository import Repository, initialise_corpus
from platforms import needs_unportable_filenames


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    initialise_corpus(root)
    return root


def a_document(
    corpus: Path,
    name: str,
    *,
    collection: str = "notes",
    identifier: str = "aaaaaaaaaa",
    body: str = "Body.",
) -> Path:
    path = corpus / collection / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {identifier}\ntitle: A note\nowner: user\n---\n"
        f"\n# A note\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def recorded(
    corpus: Path, operation: str = "add", scope: str = "notes", summary: str = "1 added"
) -> str:
    commit = Repository(corpus).commit(operation, scope=scope, summary=summary)
    assert commit is not None
    return commit


# ---------------------------------------------------------------------------
# Reading history
# ---------------------------------------------------------------------------


def test_history_reads_back_what_each_command_did(corpus: Path):
    a_document(corpus, "one.md")
    recorded(corpus, "add", "notes", "1 added")

    entries = read_history(Repository(corpus))

    assert entries[0].operation == "add"
    assert entries[0].scope == "notes"
    assert entries[0].summary == "1 added"


def test_history_is_newest_first(corpus: Path):
    a_document(corpus, "one.md")
    recorded(corpus, "add", "notes", "1 added")
    a_document(corpus, "two.md", identifier="bbbbbbbbbb")
    recorded(corpus, "add", "notes", "2 added")

    summaries = [entry.summary for entry in read_history(Repository(corpus))]

    assert summaries[:2] == ["2 added", "1 added"]


def test_history_includes_the_corpus_being_created(corpus: Path):
    entries = read_history(Repository(corpus))

    assert entries[-1].operation == "init"
    assert entries[-1].scope == "corpus"


def test_each_entry_carries_its_commit_and_time(corpus: Path):
    a_document(corpus, "one.md")
    commit = recorded(corpus)

    entry = read_history(Repository(corpus))[0]

    assert entry.commit == commit
    assert isinstance(entry.when, datetime)
    assert entry.when.tzinfo is not None


def test_history_can_be_limited(corpus: Path):
    for number in range(5):
        a_document(corpus, f"note{number}.md", identifier=f"{number}aaaaaaaa")
        recorded(corpus)

    assert len(read_history(Repository(corpus), limit=3)) == 3


def test_history_can_be_filtered_to_one_collection(corpus: Path):
    """Git decides which commits touched those paths, rather than kennis
    inferring it from the scope in the message - a single commit can touch
    two collections, and git's answer is the true one."""
    a_document(corpus, "one.md", collection="notes")
    recorded(corpus, "add", "notes", "1 added")
    a_document(corpus, "paper.md", collection="literature", identifier="bbbbbbbbbb")
    recorded(corpus, "add", "literature", "1 added")

    entries = read_history(Repository(corpus), collection="literature")

    # The corpus's own creation touched `literature/` too, because each
    # collection holds a `.gitkeep` so git keeps the directory. That is git
    # answering truthfully rather than a filter leaking, so what the filter
    # must exclude is the commit that touched only `notes/`.
    assert "notes" not in [entry.scope for entry in entries]
    assert "literature" in [entry.scope for entry in entries]


def test_a_message_that_does_not_parse_is_kept(corpus: Path):
    """A corpus may hold a commit someone made by hand. A history that
    silently omits what it cannot categorise invents a history in which that
    did not happen."""
    a_document(corpus, "one.md")
    from kennis.engine.history.git import git

    git(["add", "--all", "."], cwd=corpus)
    git(["commit", "-m", "did something by hand"], cwd=corpus)

    entry = read_history(Repository(corpus))[0]

    assert entry.operation is None
    assert entry.summary == "did something by hand"


# ---------------------------------------------------------------------------
# Restoring
# ---------------------------------------------------------------------------


def test_a_document_is_returned_to_a_previous_state(corpus: Path):
    """The plan's test: `corpus restore` returns a document to a previous
    state."""
    note = a_document(corpus, "one.md", body="First body.")
    before = recorded(corpus)
    note.write_text(
        note.read_text(encoding="utf-8").replace("First body.", "Second body."),
        encoding="utf-8",
    )
    recorded(corpus, "add", "notes", "1 changed")

    restore_document(Repository(corpus), "aaaaaaaaaa", commit=before)

    assert "First body." in note.read_text(encoding="utf-8")


def test_restoring_reports_the_path_and_the_commit(corpus: Path):
    a_document(corpus, "one.md", body="First body.")
    before = recorded(corpus)
    a_document(corpus, "one.md", body="Second body.")
    recorded(corpus, "add", "notes", "1 changed")

    restored = restore_document(Repository(corpus), "aaaaaaaaaa", commit=before)

    assert restored.path == "notes/one.md"
    assert restored.commit == before


def test_a_deleted_document_can_be_restored_by_its_identifier(corpus: Path):
    """The path cannot be found by walking the corpus, because the document
    is not there. It is resolved against history instead."""
    note = a_document(corpus, "one.md")
    before = recorded(corpus)
    note.unlink()
    recorded(corpus, "remove", "notes", "1 removed")

    restore_document(Repository(corpus), "aaaaaaaaaa", commit=before)

    assert note.is_file()


def test_restoring_an_unknown_identifier_is_refused(corpus: Path):
    a_document(corpus, "one.md")
    commit = recorded(corpus)

    with pytest.raises(DocumentNotFound):
        restore_document(Repository(corpus), "zzzzzzzzzz", commit=commit)


def test_restoring_does_not_disturb_another_document(corpus: Path):
    a_document(corpus, "one.md", identifier="aaaaaaaaaa", body="First.")
    a_document(corpus, "two.md", identifier="bbbbbbbbbb", body="Other.")
    before = recorded(corpus, "add", "notes", "2 added")
    a_document(corpus, "one.md", identifier="aaaaaaaaaa", body="Changed.")
    a_document(corpus, "two.md", identifier="bbbbbbbbbb", body="Also changed.")
    recorded(corpus, "add", "notes", "2 changed")

    restore_document(Repository(corpus), "aaaaaaaaaa", commit=before)

    assert "Also changed." in (corpus / "notes" / "two.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# And the index notices
# ---------------------------------------------------------------------------


def test_the_index_notices_a_restore(corpus: Path):
    """The plan's last test for this milestone. Nothing new is needed - a
    restore changes a file in the collection - but it is a claim about two
    parts fitting together, and those are the claims that quietly stop being
    true."""
    a_document(corpus, "one.md", body="First body.")
    before = recorded(corpus)
    a_document(corpus, "one.md", body="Second body.")
    built_at = recorded(corpus, "index", "notes", "1 indexed")

    assert (
        index_freshness(
            Repository(corpus), collection="notes", built_from=built_at
        ).state
        == "in step"
    )

    restore_document(Repository(corpus), "aaaaaaaaaa", commit=before)

    report = index_freshness(
        Repository(corpus), collection="notes", built_from=built_at
    )
    assert report.state == "stale"
    assert report.changed == 1


# ---------------------------------------------------------------------------
# A count of one is singular (#637)
# ---------------------------------------------------------------------------


def test_a_count_of_one_names_its_noun_in_the_singular():
    """`remember` committed as `remember(notes): 1 documents`."""
    assert commit_summary({"documents": 1}) == "1 document"
    assert commit_summary({"documents": 1, "chunks": 1}) == "1 document, 1 chunk"


def test_other_counts_keep_the_plural():
    assert commit_summary({"documents": 4, "chunks": 7}) == "4 documents, 7 chunks"
    assert commit_summary({"documents": 1, "chunks": 3}) == "1 document, 3 chunks"


def test_a_participle_is_the_same_for_one_and_for_many():
    assert commit_summary({"added": 1, "tagged": 1}) == "1 added, 1 tagged"
    assert outcome_summary({Outcome.ADDED: 1, Outcome.CHANGED: 2}) == (
        "1 added, 2 changed"
    )


def test_no_outcome_is_a_word_ending_in_s():
    """The rule drops a final `s` for a count of one, which is right only
    because every key is a plural noun or a participle. An outcome that
    ended in `s` would be cut short."""
    assert not [outcome.value for outcome in Outcome if outcome.value.endswith("s")]


# ---------------------------------------------------------------------------
# Finding the document to put back, wherever it is in the tree (#647)
# ---------------------------------------------------------------------------

# More documents than the 200 tree entries the search once stopped after.
MANY: int = 230


def many_documents_and_a_last_one(corpus: Path) -> str:
    """`MANY` notes, then one that sorts after all of them; the commit."""
    for number in range(MANY):
        a_document(
            corpus, f"a-{number:04}.md", identifier=f"filler{number:04}", body="Filler."
        )
    a_document(corpus, "z-last.md", identifier="aaaaaaaaaa", body="The last one.")
    return recorded(corpus, "add", "notes", f"{MANY + 1} added")


def test_a_document_is_found_wherever_it_is_in_the_tree(corpus: Path):
    """Brian's corpus held 532 files and the search read the first 200, so
    no paper and no note could be put back."""
    commit = many_documents_and_a_last_one(corpus)

    assert document_path_at(Repository(corpus), commit, "aaaaaaaaaa") == (
        "notes/z-last.md"
    )


def test_finding_a_document_reads_only_the_files_naming_its_identifier(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
):
    """One process finds the candidates. A process per file is what the
    limit of 200 was there to bound."""
    commit = many_documents_and_a_last_one(corpus)
    read: list[str] = []
    show = Repository.show

    def counted(self: Repository, commit: str, path: str) -> str | None:
        read.append(path)
        return show(self, commit, path)

    monkeypatch.setattr(Repository, "show", counted)

    assert document_path_at(Repository(corpus), commit, "aaaaaaaaaa") is not None
    assert read == ["notes/z-last.md"]


@pytest.mark.parametrize("identifier", ["", "..........", "filler"])
def test_an_identifier_is_text_and_never_a_pattern(
    corpus: Path, monkeypatch: pytest.MonkeyPatch, identifier: str
):
    """Ten dots match every ten characters as a pattern, the empty string
    matches every line, and `filler` begins 230 identifiers and is none."""
    commit = many_documents_and_a_last_one(corpus)
    read: list[str] = []
    show = Repository.show

    def counted(self: Repository, commit: str, path: str) -> str | None:
        read.append(path)
        return show(self, commit, path)

    monkeypatch.setattr(Repository, "show", counted)

    assert document_path_at(Repository(corpus), commit, identifier) is None
    if identifier != "filler":
        assert read == []


def test_an_identifier_beginning_with_a_dash_is_not_an_option(corpus: Path):
    """The identifier is whatever was typed after `corpus restore`, and git
    grep has an option that runs a program."""
    a_document(corpus, "one.md", identifier="-Otouch")
    commit = recorded(corpus)

    assert document_path_at(Repository(corpus), commit, "-Otouch") == "notes/one.md"


def test_a_document_mentioning_an_identifier_is_not_the_document(corpus: Path):
    """A note about a paper names the paper's identifier in its text, and
    sorts first here."""
    a_document(
        corpus,
        "about.md",
        identifier="bbbbbbbbbb",
        body="See aaaaaaaaaa.\n\nid: aaaaaaaaaa",
    )
    a_document(corpus, "the-one.md", identifier="aaaaaaaaaa")
    commit = recorded(corpus, "add", "notes", "2 added")

    assert document_path_at(Repository(corpus), commit, "aaaaaaaaaa") == (
        "notes/the-one.md"
    )
    assert document_path_at(Repository(corpus), commit, "bbbbbbbbbb") == (
        "notes/about.md"
    )


def test_a_document_is_found_in_any_folder_and_under_any_name(corpus: Path):
    """Groups nest, a title holds spaces and accents, and a document with
    figures is `content.md` inside a folder."""
    accented = "Caf\u00e9 a study - Author et al - 2020"
    a_document(
        corpus,
        f"tron/transients/deep/{accented}.md",
        collection="literature",
        identifier="aaaaaaaaaa",
    )
    a_document(
        corpus,
        "tron/With figures/content.md",
        collection="literature",
        identifier="bbbbbbbbbb",
    )
    commit = recorded(corpus, "add", "literature", "2 added")

    assert document_path_at(Repository(corpus), commit, "aaaaaaaaaa") == (
        f"literature/tron/transients/deep/{accented}.md"
    )
    assert document_path_at(Repository(corpus), commit, "bbbbbbbbbb") == (
        "literature/tron/With figures/content.md"
    )


def test_a_document_is_found_at_a_point_named_by_an_expression(corpus: Path):
    """`corpus restore --commit HEAD~1`: git writes the point back before
    each path exactly as it was given."""
    note = a_document(corpus, "one.md")
    recorded(corpus)
    note.unlink()
    recorded(corpus, "remove", "notes", "1 removed")
    repository = Repository(corpus)

    assert document_path_at(repository, "HEAD~1", "aaaaaaaaaa") == "notes/one.md"
    assert document_path_at(repository, "HEAD@{1}", "aaaaaaaaaa") == "notes/one.md"
    assert document_path_at(repository, "HEAD", "aaaaaaaaaa") is None
    assert document_path_at(repository, "no-such-point", "aaaaaaaaaa") is None


@needs_unportable_filenames
def test_a_colon_in_the_point_or_the_path_does_not_move_the_cut(corpus: Path):
    """git answers `<point>:<path>`, and a point named by a commit's message
    holds a colon as a title may."""
    titled = "Calibration: a study.md"
    note = a_document(corpus, titled)
    recorded(corpus)
    note.unlink()
    recorded(corpus, "remove", "notes", "1 removed")
    point = "HEAD^{/: 1 removed}~1"

    assert document_path_at(Repository(corpus), point, "aaaaaaaaaa") == (
        f"notes/{titled}"
    )


# ---------------------------------------------------------------------------
# Restoring without naming a point, and by the names a paper has (#667)
# ---------------------------------------------------------------------------


def a_paper(corpus: Path, name: str, *, identifier: str, arxiv_id: str) -> Path:
    path = corpus / "literature" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {identifier}\ntitle: A paper\nowner: user\n"
        f"bib:\n  citekey: key{identifier}\n  arxiv_id: '{arxiv_id}'\n"
        "  doi: 10.1000/example\n---\n\n# A paper\n\nBody.\n",
        encoding="utf-8",
    )
    return path


def test_a_removed_document_is_restored_without_naming_a_point(corpus: Path):
    """Brian's report: after a removal the document is not at HEAD, which
    was the default, so the plain command could not undo a removal."""
    note = a_document(corpus, "one.md")
    held_at = recorded(corpus)
    note.unlink()
    recorded(corpus, "remove", "notes", "1 removed")

    restored = restore_document(Repository(corpus), "aaaaaaaaaa", commit=None)

    assert note.is_file()
    assert restored.commit == held_at


def test_the_last_point_holding_a_document_is_the_newest_one(corpus: Path):
    note = a_document(corpus, "one.md", body="First body.")
    recorded(corpus)
    note.unlink()
    recorded(corpus, "remove", "notes", "1 removed")
    a_document(corpus, "one.md", body="Second body.")
    second = recorded(corpus)
    note.unlink()
    recorded(corpus, "remove", "notes", "1 removed")

    assert last_point_holding(Repository(corpus), "aaaaaaaaaa") == second
    restore_document(Repository(corpus), "aaaaaaaaaa", commit=None)
    assert "Second body." in note.read_text(encoding="utf-8")


def test_a_document_still_held_is_restored_from_the_latest_point(corpus: Path):
    """Not from the commit that added it: an edit recorded since changes no
    count of the identifier, so no search of the history proposes it."""
    note = a_document(corpus, "one.md", body="First body.")
    recorded(corpus)
    a_document(corpus, "one.md", body="Recorded body.")
    latest = recorded(corpus, "edit", "notes", "by hand")
    note.write_text("damaged by hand", encoding="utf-8")

    restored = restore_document(Repository(corpus), "aaaaaaaaaa", commit=None)

    assert restored.commit == latest
    assert "Recorded body." in note.read_text(encoding="utf-8")


def test_a_removed_document_comes_back_as_it_was_last_recorded(corpus: Path):
    """The point is the removal's parent, not the commit that added the
    document, which holds it as it was before every edit since; and a
    removal may be followed by any number of unrelated commits."""
    note = a_document(corpus, "one.md", body="First body.")
    recorded(corpus)
    a_document(corpus, "one.md", body="Edited body.")
    held_at = recorded(corpus, "edit", "notes", "by hand")
    note.unlink()
    recorded(corpus, "remove", "notes", "1 removed")
    a_document(corpus, "two.md", identifier="bbbbbbbbbb")
    recorded(corpus)

    assert last_point_holding(Repository(corpus), "aaaaaaaaaa") == held_at


def test_a_document_never_recorded_has_no_point_and_is_refused(corpus: Path):
    a_document(corpus, "one.md")
    recorded(corpus)

    assert last_point_holding(Repository(corpus), "zzzzzzzzzz") is None
    with pytest.raises(DocumentNotFound) as refused:
        restore_document(Repository(corpus), "zzzzzzzzzz", commit=None)
    assert "HEAD" not in str(refused.value)


def test_a_name_beginning_with_a_dash_is_looked_for_and_not_obeyed(corpus: Path):
    note = a_document(corpus, "one.md", identifier="-Otouch")
    held_at = recorded(corpus)
    note.unlink()
    recorded(corpus, "remove", "notes", "1 removed")

    assert last_point_holding(Repository(corpus), "-Otouch") == held_at


@pytest.mark.parametrize(
    "name", ["2604.25345", "keypppppppppp", "10.1000/example"], ids=str
)
def test_a_removed_paper_is_restored_by_a_name_remove_took(corpus: Path, name: str):
    """`corpus remove 2604.25345` worked and `corpus restore 2604.25345`
    did not. The report names the identifier, whatever was typed."""
    paper = a_paper(corpus, "paper.md", identifier="pppppppppp", arxiv_id="2604.25345")
    held_at = recorded(corpus, "add", "literature")
    paper.unlink()
    recorded(corpus, "remove", "literature", "1 removed")

    restored = restore_document(Repository(corpus), name, commit=None)

    assert paper.is_file()
    assert (restored.document_id, restored.commit) == ("pppppppppp", held_at)


def test_an_identifier_wins_over_another_document_s_name(corpus: Path):
    a_paper(corpus, "named.md", identifier="pppppppppp", arxiv_id="qqqqqqqqqq")
    a_paper(corpus, "identified.md", identifier="qqqqqqqqqq", arxiv_id="2604.00001")
    commit = recorded(corpus, "add", "literature")

    held = document_at(Repository(corpus), commit, "qqqqqqqqqq")

    assert held is not None
    assert held.path == "literature/identified.md"


def test_a_name_two_documents_share_names_neither(corpus: Path):
    """As `Collection.resolve` drops an ambiguous key: restoring one of two
    by a guess would put back the wrong paper and say it had the right one."""
    a_paper(corpus, "one.md", identifier="pppppppppp", arxiv_id="2604.25345")
    a_paper(corpus, "two.md", identifier="qqqqqqqqqq", arxiv_id="2604.25345")
    commit = recorded(corpus, "add", "literature")

    assert document_at(Repository(corpus), commit, "2604.25345") is None
    assert document_at(Repository(corpus), commit, "10.1000/example") is None
    assert document_at(Repository(corpus), commit, "pppppppppp") is not None


def test_a_title_or_a_body_naming_a_paper_is_not_the_paper(corpus: Path):
    a_paper(corpus, "paper.md", identifier="pppppppppp", arxiv_id="2604.25345")
    a_document(corpus, "note.md", body="See 2604.25345 and A paper.")
    commit = recorded(corpus)

    held = document_at(Repository(corpus), commit, "2604.25345")

    assert held is not None
    assert held.path == "literature/paper.md"
    assert document_at(Repository(corpus), commit, "A paper") is None
