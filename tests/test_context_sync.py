"""`kennis context sync`: a bundle against the packs its project declares.

A pack's context is searched in the store (14g, #513), so a sync writes no
pack content. What it still does, and what each test here holds it to:
a copy an earlier kennis wrote and nobody edited is removed; an edited
copy becomes the person's own file that replaces the pack's (#514); and a
file the person owns is never touched.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kennis.engine.context.bundle import declare_packs, init_bundle
from kennis.engine.context.notes import remember_in_bundle
from kennis.engine.context.sync import sync_bundle
from kennis.engine.errors import DocumentInvalid
from kennis.engine.events import Outcome, Recorder
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    return root


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return init_bundle(project).path


def installed(corpus: Path, tmp_path: Path, identifier: str = "alpha") -> None:
    root = tmp_path / identifier
    (root / "content").mkdir(parents=True)
    (root / "content" / "one.md").write_text("One.\n", encoding="utf-8")
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: n\n  version: "1.0.0"\n'
        "context:\n  - source: content/\n",
        encoding="utf-8",
    )
    update_pack(path)
    install_pack(corpus, path)


def a_copy(
    bundle: Path,
    relative: str = "one.md",
    *,
    body: str = "One.\n",
    written: str | None = "One.\n",
    owner: str = "pack:alpha",
) -> Path:
    """A file as the copying sync of earlier versions wrote it: `written`
    is the body it recorded a digest of, None for no digest at all."""
    digest = f"  sha256: {content_digest(written.encode())}\n" if written else ""
    path = bundle / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitle: one\nowner: {owner}\nsource:\n  via: pack\n  pack: alpha\n"
        f"  address: one.md\n{digest}---\n{body}",
        encoding="utf-8",
    )
    return path


def header_of(path: Path) -> dict[str, object]:
    frontmatter, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    return frontmatter


def body_of(path: Path) -> str:
    _, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return body


# ---------------------------------------------------------------------------
# Nothing of a pack is written


def test_a_declared_pack_s_content_is_not_written_into_the_bundle(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])

    result = sync_bundle(bundle, corpus)

    assert not (bundle / "one.md").exists()
    assert result.removed == ()
    assert result.made_yours == ()


# ---------------------------------------------------------------------------
# Copies an earlier kennis wrote


def test_an_unedited_copy_is_removed(corpus: Path, bundle: Path):
    copy = a_copy(bundle)

    result = sync_bundle(bundle, corpus)

    assert not copy.exists()
    assert result.removed == ("one.md",)


def test_a_hidden_unedited_copy_is_removed_too(corpus: Path, bundle: Path):
    """Hiding a file behind a dot keeps it out of the index, not out of
    kennis's sight (#247)."""
    copy = a_copy(bundle, ".one.md")

    sync_bundle(bundle, corpus)

    assert not copy.exists()


def test_an_edited_copy_becomes_the_person_s_and_replaces_the_pack_s(
    corpus: Path, bundle: Path
):
    copy = a_copy(bundle, body="One, and two.\n")

    result = sync_bundle(bundle, corpus)

    assert result.made_yours == ("one.md",)
    header = header_of(copy)
    assert header["owner"] == "user"
    assert header["replaces"] == "pack:alpha/one.md"
    assert "source" not in header
    assert header["title"] == "one"
    assert body_of(copy) == "One, and two.\n"


def test_a_copy_moved_elsewhere_replaces_the_address_it_was_written_for(
    corpus: Path, bundle: Path
):
    copy = a_copy(bundle, "kept/mine.md", body="Mine.\n")

    sync_bundle(bundle, corpus)

    assert header_of(copy)["replaces"] == "pack:alpha/one.md"


def test_a_copy_recording_no_digest_is_kept_as_the_person_s(corpus: Path, bundle: Path):
    """No digest is no evidence the file was left alone, and removing a
    person's writing is the one mistake a sync must not make."""
    copy = a_copy(bundle, written=None)

    sync_bundle(bundle, corpus)

    assert copy.exists()
    assert header_of(copy)["owner"] == "user"


def test_a_second_sync_changes_nothing(corpus: Path, bundle: Path):
    a_copy(bundle)
    a_copy(bundle, "two.md", body="Edited.\n")
    sync_bundle(bundle, corpus)

    again = sync_bundle(bundle, corpus)

    assert again.removed == ()
    assert again.made_yours == ()


def test_a_group_directory_a_removal_emptied_is_removed(corpus: Path, bundle: Path):
    a_copy(bundle, "decisions/one.md")

    sync_bundle(bundle, corpus)

    assert not (bundle / "decisions").exists()


def test_a_directory_holding_something_else_is_left_alone(corpus: Path, bundle: Path):
    a_copy(bundle, "decisions/one.md")
    (bundle / "decisions" / "notes.txt").write_text("mine", encoding="utf-8")

    sync_bundle(bundle, corpus)

    assert (bundle / "decisions" / "notes.txt").exists()


# ---------------------------------------------------------------------------
# What is never touched


def test_a_note_the_person_remembered_is_never_touched(corpus: Path, bundle: Path):
    remembered = remember_in_bundle(
        bundle, "Our gains drift.", title=None, group=None
    ).path
    before = remembered.read_bytes()

    sync_bundle(bundle, corpus)

    assert remembered.read_bytes() == before


def test_an_unrecognised_owner_is_refused_before_anything_is_written(
    corpus: Path, bundle: Path
):
    copy = a_copy(bundle)
    a_copy(bundle, "odd.md", owner="somebody")

    with pytest.raises(DocumentInvalid) as raised:
        sync_bundle(bundle, corpus)

    assert "odd.md" in str(raised.value)
    assert copy.exists()


# ---------------------------------------------------------------------------
# The declaration


def test_the_declared_packs_are_split_by_whether_they_are_installed(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha", "gamma"])

    result = sync_bundle(bundle, corpus)

    assert result.declared == ("alpha",)
    assert result.missing == ("gamma",)
    assert result.available == ()


def test_a_project_declaring_nothing_is_offered_the_installed_packs(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path, "beta")
    installed(corpus, tmp_path, "alpha")

    result = sync_bundle(bundle, corpus)

    assert result.available == ("alpha", "beta")


# ---------------------------------------------------------------------------
# Reporting


def test_every_change_reaches_the_event_stream(corpus: Path, bundle: Path):
    a_copy(bundle)
    a_copy(bundle, "two.md", body="Edited.\n")
    events = Recorder()

    sync_bundle(bundle, corpus, events=events)

    assert events.outcomes() == {
        "one.md": Outcome.REMOVED,
        "two.md": Outcome.CHANGED,
    }


def test_the_sync_makes_no_commit(corpus: Path, bundle: Path):
    """kennis does not write to the person's repository's history. The
    bundle lives in one kennis does not own."""
    project = bundle.parent
    subprocess.run(
        ["git", "init", "-q"],
        cwd=project,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    a_copy(bundle)

    sync_bundle(bundle, corpus)

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    assert log.stdout.strip() == ""


def test_a_project_that_chose_its_packs_is_not_offered_the_rest(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Offered on every run, the other packs would read as a fault in a
    project whose declaration is deliberate."""
    installed(corpus, tmp_path, "alpha")
    installed(corpus, tmp_path, "beta")
    declare_packs(bundle, ["alpha"])

    result = sync_bundle(bundle, corpus)

    assert result.declared == ("alpha",)
    assert result.available == ()
