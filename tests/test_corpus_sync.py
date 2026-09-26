"""`kennis corpus sync` for notes, and claiming a document.

Milestone 7 unit 7, second half. The same resolution table as
`context sync`, against a destination that differs in three ways that
matter: a document's filename comes from its title rather than from its
address, its identity is a minted identifier every read handle depends
on, and the corpus is kennis's own repository, so the sync commits.

The address is therefore recorded in the document rather than read off
its location. A sync that could not find the document it wrote last time
would write a second one.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from kennis.engine.corpus.add import Uniqueness, write_note
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document
from kennis.engine.corpus.intake import Converted
from kennis.engine.corpus.sync import claim_document, disown_document, sync_corpus
from kennis.engine.errors import DocumentInvalid, PackInvalid
from kennis.engine.events import Outcome, Recorder
from kennis.engine.history.repository import initialise_corpus
from kennis.engine.pack.store import install_pack, pack_root
from kennis.engine.pack.update import update_pack


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    initialise_corpus(root)
    return root


def a_pack(
    root: Path,
    *,
    identifier: str = "alpha",
    files: dict[str, str] | None = None,
    group: str | None = None,
) -> Path:
    """A pack shipping notes, rebuilt from scratch each call so a second
    one with fewer files really ships fewer."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for relative, text in (files or {"notes/one.md": "One.\n"}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    grouped = f"      group: {group}\n" if group else ""
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: n\n  version: "1.0.0"\n'
        f"corpus:\n  notes:\n    - source: notes/\n{grouped}",
        encoding="utf-8",
    )
    update_pack(path)
    return path


def installed(
    corpus: Path,
    tmp_path: Path,
    *,
    identifier: str = "alpha",
    files: dict[str, str] | None = None,
    group: str | None = None,
) -> None:
    install_pack(
        corpus,
        a_pack(tmp_path / identifier, identifier=identifier, files=files, group=group),
    )


def notes_in(corpus: Path) -> list[Document]:
    return list(Collection(root=corpus, name="notes").contents().documents)


def only_note(corpus: Path) -> Document:
    documents = notes_in(corpus)
    assert len(documents) == 1, [one.frontmatter.title for one in documents]
    return documents[0]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_a_declared_note_becomes_a_corpus_document(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, files={"notes/one.md": "# Setup\n\nRun it.\n"})

    sync_corpus(corpus)

    assert only_note(corpus).body.strip() == "# Setup\n\nRun it.".strip()


def test_the_document_is_owned_by_the_pack(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path)

    sync_corpus(corpus)

    assert only_note(corpus).frontmatter.owner == "pack:alpha"


def test_the_document_records_the_address_it_came_from(corpus: Path, tmp_path: Path):
    """Its filename comes from its title, so the address cannot be read
    off its location - a sync that could not find it again would write a
    second document on every run."""
    installed(corpus, tmp_path, group="install")

    sync_corpus(corpus)

    source = only_note(corpus).frontmatter.source
    assert source.origin == "pack:alpha/install/one.md"
    assert source.via == "pack"


def test_the_title_comes_from_the_packs_own_frontmatter(corpus: Path, tmp_path: Path):
    installed(
        corpus,
        tmp_path,
        files={"notes/one.md": "---\ntitle: Solver choice\n---\n\nQuartical.\n"},
    )

    sync_corpus(corpus)

    assert only_note(corpus).frontmatter.title == "Solver choice"


def test_a_second_sync_writes_nothing(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path)
    sync_corpus(corpus)
    before = only_note(corpus).md_path.read_bytes()

    result = sync_corpus(corpus)

    assert only_note(corpus).md_path.read_bytes() == before
    assert result.counts.get("keep") == 1


def test_a_pack_note_with_its_own_frontmatter_settles_after_one_sync(
    corpus: Path, tmp_path: Path
):
    """The defect that cost `context sync` a rewrite loop: the body kennis
    writes is not the bytes the store holds when the pack ships a
    header."""
    installed(
        corpus,
        tmp_path,
        files={"notes/one.md": "---\ntitle: Solver\n---\n\nQuartical.\n"},
    )
    sync_corpus(corpus)

    result = sync_corpus(corpus)

    assert result.counts.get("keep") == 1
    assert result.counts.get("rewrite") is None


def test_the_identifier_does_not_move_when_the_pack_ships_a_change(
    corpus: Path, tmp_path: Path
):
    """Every read handle depends on it. A rewrite changes the body of an
    existing document; it does not mint a new one."""
    installed(corpus, tmp_path, files={"notes/one.md": "First.\n"})
    sync_corpus(corpus)
    before = only_note(corpus).id

    installed(corpus, tmp_path, files={"notes/one.md": "Second.\n"})
    result = sync_corpus(corpus)

    assert only_note(corpus).id == before
    assert only_note(corpus).body.strip() == "Second."
    assert result.counts.get("rewrite") == 1


def test_a_note_the_pack_dropped_is_removed(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, files={"notes/one.md": "1.\n", "notes/two.md": "2.\n"})
    sync_corpus(corpus)

    installed(corpus, tmp_path, files={"notes/one.md": "1.\n"})
    result = sync_corpus(corpus)

    assert len(notes_in(corpus)) == 1
    assert result.counts.get("delete") == 1


# ---------------------------------------------------------------------------
# What the user owns
# ---------------------------------------------------------------------------


def test_a_note_the_user_wrote_is_never_touched(corpus: Path, tmp_path: Path):
    """A user's note is at no pack's address, so it is not a sync's
    business at all - not even to report."""
    collection = Collection(root=corpus, name="notes")
    write_note(
        collection,
        Uniqueness.of(collection),
        converted=Converted(
            markdown="Mine.\n", via="remember", format="markdown", origin="inline:"
        ),
        title="Mine",
        group=None,
    )
    installed(corpus, tmp_path)

    result = sync_corpus(corpus)

    assert len(notes_in(corpus)) == 2
    assert result.counts.get("yours") is None


def test_a_pack_note_the_user_edited_is_not_rewritten(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, files={"notes/one.md": "First.\n"})
    sync_corpus(corpus)
    path = only_note(corpus).md_path
    path.write_text(path.read_text().replace("First.", "Mine now."), encoding="utf-8")

    installed(corpus, tmp_path, files={"notes/one.md": "Second.\n"})
    result = sync_corpus(corpus)

    assert "Mine now." in only_note(corpus).body
    assert result.counts.get("edited") == 1
    # The identifier, because `corpus claim` is the only handle on a
    # corpus document and the report has to be able to name it.
    assert result.edited == (only_note(corpus).id,)


def test_a_claimed_document_is_reported_under_yours_every_run(
    corpus: Path, tmp_path: Path
):
    """The one way the `yours:` row is reachable in a corpus, and the
    reason `claim` exists: without it section 5's protective rows can
    never fire for a document that started life in a pack."""
    installed(corpus, tmp_path)
    sync_corpus(corpus)
    claim_document(corpus, only_note(corpus).id)

    first = sync_corpus(corpus)
    second = sync_corpus(corpus)

    assert first.counts.get("yours") == 1
    assert second.counts.get("yours") == 1


def test_a_claimed_document_is_not_rewritten_when_the_pack_changes(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"notes/one.md": "First.\n"})
    sync_corpus(corpus)
    claim_document(corpus, only_note(corpus).id)

    installed(corpus, tmp_path, files={"notes/one.md": "Second.\n"})
    sync_corpus(corpus)

    assert only_note(corpus).body.strip() == "First."


def test_a_claimed_document_is_not_deleted_when_the_pack_drops_it(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"notes/one.md": "1.\n", "notes/two.md": "2.\n"})
    sync_corpus(corpus)
    kept = next(
        one
        for one in notes_in(corpus)
        if one.frontmatter.source.origin.endswith("two.md")
    )
    claim_document(corpus, kept.id)

    installed(corpus, tmp_path, files={"notes/one.md": "1.\n"})
    sync_corpus(corpus)

    assert len(notes_in(corpus)) == 2


# ---------------------------------------------------------------------------
# claim and disown
# ---------------------------------------------------------------------------


def test_claim_moves_ownership_to_the_user(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path)
    sync_corpus(corpus)

    claim_document(corpus, only_note(corpus).id)

    assert only_note(corpus).frontmatter.owner == "user"


def test_claim_leaves_the_source_alone(corpus: Path, tmp_path: Path):
    """What keeps the document at its address. A claim that erased the
    origin would make the next sync write a second copy of the same
    note."""
    installed(corpus, tmp_path)
    sync_corpus(corpus)
    before = only_note(corpus).frontmatter.source.origin

    claim_document(corpus, only_note(corpus).id)

    assert only_note(corpus).frontmatter.source.origin == before


def test_disown_hands_it_back_to_the_pack_it_came_from(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path)
    sync_corpus(corpus)
    claim_document(corpus, only_note(corpus).id)

    disown_document(corpus, only_note(corpus).id)

    assert only_note(corpus).frontmatter.owner == "pack:alpha"


def test_disowning_a_note_the_user_wrote_is_refused(corpus: Path):
    """There is no pack to hand it to, and inventing one would be a claim
    about provenance that is not true."""
    collection = Collection(root=corpus, name="notes")
    document_id, _ = write_note(
        collection,
        Uniqueness.of(collection),
        converted=Converted(
            markdown="Mine.\n", via="remember", format="markdown", origin="inline:"
        ),
        title="Mine",
        group=None,
    )

    with pytest.raises(DocumentInvalid):
        disown_document(corpus, document_id)


def test_claiming_a_document_the_user_already_owns_is_harmless(
    corpus: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    sync_corpus(corpus)
    claim_document(corpus, only_note(corpus).id)

    claim_document(corpus, only_note(corpus).id)

    assert only_note(corpus).frontmatter.owner == "user"


# ---------------------------------------------------------------------------
# Refusals and reporting
# ---------------------------------------------------------------------------


def test_a_damaged_pack_stops_the_sync_rather_than_emptying_the_corpus(
    corpus: Path, tmp_path: Path
):
    """Concern #274, carried across. "The store says N files and disk has
    0" is corruption, never a declaration that the pack ships nothing."""
    installed(corpus, tmp_path)
    sync_corpus(corpus)
    (pack_root(corpus, "alpha") / "notes" / "one.md").unlink()

    with pytest.raises(PackInvalid) as raised:
        sync_corpus(corpus)

    assert raised.value.resolution == "kennis pack status"
    assert len(notes_in(corpus)) == 1


def test_every_action_reaches_the_event_stream(corpus: Path, tmp_path: Path):
    installed(corpus, tmp_path, files={"notes/one.md": "1.\n", "notes/two.md": "2.\n"})
    events = Recorder()

    sync_corpus(corpus, events=events)

    assert sorted(events.outcomes().values(), key=str) == [
        Outcome.ADDED,
        Outcome.ADDED,
    ]


def test_a_corpus_with_no_packs_installed_does_nothing(corpus: Path):
    result = sync_corpus(corpus)

    assert result.counts == {}


def test_the_sync_does_not_commit_by_itself(corpus: Path, tmp_path: Path):
    """The engine writes; the command decides what history records. Every
    other corpus mutation is committed by its command, once per
    invocation, with a summary of its counts."""
    installed(corpus, tmp_path)

    sync_corpus(corpus)

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=corpus,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    assert "sync" not in log.stdout
