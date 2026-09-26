"""`kennis context sync`: converging a bundle with every installed pack.

Milestone 7 unit 7, first half. This is the destination with no network in
it, so everything the resolution table decides can be exercised end to end
here - including the two rows that cost the user something if they are
wrong: a file they edited is never overwritten, and a file they own is
never touched and always reported.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from kennis.engine.context.bundle import init_bundle
from kennis.engine.context.notes import remember_in_bundle
from kennis.engine.context.sync import sync_bundle
from kennis.engine.errors import DocumentInvalid, PackInvalid
from kennis.engine.events import Outcome, Recorder
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.pack.store import install_pack, pack_root
from kennis.engine.pack.update import update_pack


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    return root


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    root = tmp_path / "project" / ".context"
    root.parent.mkdir(parents=True)
    init_bundle(root)
    return root


def a_pack(
    root: Path,
    *,
    identifier: str = "alpha",
    files: dict[str, str] | None = None,
    group: str | None = None,
    source: str = "content/",
) -> Path:
    """A pack shipping context content, installed the way a provider does.

    The source tree is rebuilt from scratch each time, so a second call
    with fewer files really ships fewer files - leaving the directory
    alone would make "the provider dropped a file" untestable, because
    `pack update` re-globs what is there.
    """
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for relative, text in (files or {"content/one.md": "One.\n"}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    grouped = f"    group: {group}\n" if group else ""
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: n\n  version: "1.0.0"\n'
        f"context:\n  - source: {source}\n{grouped}",
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
    source: str = "content/",
) -> None:
    install_pack(
        corpus,
        a_pack(
            tmp_path / identifier,
            identifier=identifier,
            files=files,
            group=group,
            source=source,
        ),
    )


def body_of(path: Path) -> str:
    _, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return body


def header_of(path: Path) -> dict[str, object]:
    frontmatter, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    return frontmatter


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_a_declared_file_appears_in_the_bundle(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)

    sync_bundle(bundle, corpus)

    assert (bundle / "one.md").is_file()


def test_the_body_is_the_pack_content_verbatim(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Verbatim, because the digest recorded beside it is the store's
    digest of that content - the user-edit check is the two agreeing."""
    installed(corpus, tmp_path, files={"content/one.md": "Exactly this.\n"})

    sync_bundle(bundle, corpus)

    assert body_of(bundle / "one.md") == "Exactly this.\n"


def test_the_file_is_owned_by_the_pack_that_shipped_it(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """`owner` is what makes the resolution table decidable, and what
    makes `pack remove` possible at all."""
    installed(corpus, tmp_path)

    sync_bundle(bundle, corpus)

    assert header_of(bundle / "one.md")["owner"] == "pack:alpha"


def test_a_group_puts_the_file_in_a_subdirectory(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path, group="decisions")

    sync_bundle(bundle, corpus)

    assert (bundle / "decisions" / "one.md").is_file()


def test_a_packs_own_frontmatter_supplies_the_title(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """A pack shipping a titled file should not lose the title, and the
    file must not end up with two frontmatter blocks."""
    installed(
        corpus,
        tmp_path,
        files={"content/one.md": "---\ntitle: Calibration\n---\n\nBody.\n"},
    )

    sync_bundle(bundle, corpus)

    written = (bundle / "one.md").read_text()
    assert header_of(bundle / "one.md")["title"] == "Calibration"
    assert written.count("---\n") == 2


def test_a_second_sync_changes_nothing(corpus: Path, bundle: Path, tmp_path: Path):
    """The common case on every run, and the one that must cost nothing."""
    installed(corpus, tmp_path)
    sync_bundle(bundle, corpus)
    before = (bundle / "one.md").read_bytes()

    result = sync_bundle(bundle, corpus)

    assert (bundle / "one.md").read_bytes() == before
    assert result.counts.get("keep") == 1


def test_a_pack_file_with_its_own_frontmatter_settles_after_one_sync(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Found by running the command, not by the suite. A pack file that
    carries its own header is not written verbatim - the header is read
    and replaced - so the body kennis writes and the file in the store
    have different digests. With one recorded digest, every such file
    reads as changed on every run and is rewritten forever."""
    installed(
        corpus,
        tmp_path,
        files={"content/one.md": "---\ntitle: Solver\n---\n\nBody.\n"},
    )
    sync_bundle(bundle, corpus)

    result = sync_bundle(bundle, corpus)

    assert result.counts.get("keep") == 1
    assert result.counts.get("rewrite") is None


def test_an_edit_to_a_file_that_had_its_own_frontmatter_is_still_caught(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """The other half of the same pair: recording the store's digest
    alone would make a user edit invisible."""
    installed(
        corpus,
        tmp_path,
        files={"content/one.md": "---\ntitle: Solver\n---\n\nBody.\n"},
    )
    sync_bundle(bundle, corpus)
    edited = (bundle / "one.md").read_text().replace("Body.", "Mine now.")
    (bundle / "one.md").write_text(edited, encoding="utf-8")

    result = sync_bundle(bundle, corpus)

    assert result.counts.get("edited") == 1
    assert "Mine now." in (bundle / "one.md").read_text()


def test_content_the_provider_changed_is_rewritten(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"content/one.md": "First.\n"})
    sync_bundle(bundle, corpus)

    installed(corpus, tmp_path, files={"content/one.md": "Second.\n"})
    result = sync_bundle(bundle, corpus)

    assert body_of(bundle / "one.md") == "Second.\n"
    assert result.counts.get("rewrite") == 1


# ---------------------------------------------------------------------------
# The two rows that cost the user something
# ---------------------------------------------------------------------------


def test_a_file_the_user_edited_is_not_overwritten(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Section 5 step 4a. Open a pack-shipped note, fix an error, save -
    and the next provider release must not destroy it."""
    installed(corpus, tmp_path, files={"content/one.md": "First.\n"})
    sync_bundle(bundle, corpus)
    edited = (bundle / "one.md").read_text().replace("First.\n", "Mine now.\n")
    (bundle / "one.md").write_text(edited, encoding="utf-8")

    installed(corpus, tmp_path, files={"content/one.md": "Second.\n"})
    result = sync_bundle(bundle, corpus)

    assert "Mine now." in (bundle / "one.md").read_text()
    assert result.counts.get("edited") == 1


def test_a_file_the_user_owns_is_left_alone_and_reported_every_run(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """The `yours:` row. Reported on every run, not only on the run where
    the declaration moved - the defect it exists for is a reconciler that
    passed over a user-owned document without counting it."""
    installed(corpus, tmp_path)
    (bundle / "one.md").write_text(
        "---\ntitle: Mine\nowner: user\n---\n\nMine.\n", encoding="utf-8"
    )

    first = sync_bundle(bundle, corpus)
    second = sync_bundle(bundle, corpus)

    assert body_of(bundle / "one.md") == "Mine.\n"
    assert first.counts.get("yours") == 1
    assert second.counts.get("yours") == 1


def test_a_file_no_pack_declares_any_more_is_deleted(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(
        corpus, tmp_path, files={"content/one.md": "1.\n", "content/two.md": "2.\n"}
    )
    sync_bundle(bundle, corpus)

    installed(corpus, tmp_path, files={"content/one.md": "1.\n"})
    result = sync_bundle(bundle, corpus)

    assert not (bundle / "two.md").exists()
    assert result.counts.get("delete") == 1


def test_a_dropped_file_the_user_edited_is_kept_rather_than_deleted(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """The more expensive mistake of the two: there is no next release to
    put the user's writing back. Concern #272."""
    installed(
        corpus, tmp_path, files={"content/one.md": "1.\n", "content/two.md": "2.\n"}
    )
    sync_bundle(bundle, corpus)
    text = (bundle / "two.md").read_text().replace("2.\n", "Mine.\n")
    (bundle / "two.md").write_text(text, encoding="utf-8")

    installed(corpus, tmp_path, files={"content/one.md": "1.\n"})
    sync_bundle(bundle, corpus)

    assert (bundle / "two.md").is_file()
    assert "Mine." in (bundle / "two.md").read_text()


def test_a_note_the_user_remembered_is_never_touched(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Most of a bundle is this, and none of it is a sync's business."""
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    installed(corpus, tmp_path)
    before = sorted(path.name for path in bundle.rglob("*.md"))

    sync_bundle(bundle, corpus)

    assert "one.md" in sorted(path.name for path in bundle.rglob("*.md"))
    assert set(before) <= set(path.name for path in bundle.rglob("*.md"))


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_pack_may_not_ship_a_hidden_file_into_a_bundle(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Concerns #247 and #267, settled together. A dot-prefixed path in a
    bundle is never indexed - that is the documented way a user keeps a
    file out of search - so a pack shipping one would land a file that is
    copied, never indexed, and invisible."""
    installed(corpus, tmp_path, files={"content/.hidden.md": "Invisible.\n"})

    with pytest.raises(PackInvalid) as raised:
        sync_bundle(bundle, corpus)

    assert ".hidden.md" in str(raised.value)


def test_a_hidden_destination_is_refused_before_anything_is_written(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """A half-converged bundle is worse than an unconverged one."""
    installed(
        corpus,
        tmp_path,
        files={"content/fine.md": "Fine.\n", "content/.hidden.md": "No.\n"},
    )

    with pytest.raises(PackInvalid):
        sync_bundle(bundle, corpus)

    assert not (bundle / "fine.md").exists()


def test_a_pack_may_not_overwrite_the_landing_page(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """`LANDING.md` is the entry point an agent is told to read first, and
    it is the user's to edit."""
    installed(corpus, tmp_path, files={"content/LANDING.md": "Mine.\n"})

    with pytest.raises(PackInvalid) as raised:
        sync_bundle(bundle, corpus)

    assert "LANDING.md" in str(raised.value)


def test_an_owner_kennis_does_not_recognise_refuses_the_sync(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Section 6: corruption, not a compatibility case. Named, never
    guessed at, and nothing is written."""
    installed(corpus, tmp_path)
    (bundle / "one.md").write_text(
        "---\ntitle: x\nowner: managed_by:boepie\n---\n\nx.\n", encoding="utf-8"
    )

    with pytest.raises(DocumentInvalid) as raised:
        sync_bundle(bundle, corpus)

    assert "one.md" in str(raised.value)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_every_action_reaches_the_event_stream(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Section 14: the display ignores `ItemFinished`, so this is what the
    log keeps and the terminal does not."""
    installed(
        corpus, tmp_path, files={"content/one.md": "1.\n", "content/two.md": "2.\n"}
    )
    events = Recorder()

    sync_bundle(bundle, corpus, events=events)

    assert events.outcomes() == {
        "one.md": Outcome.ADDED,
        "two.md": Outcome.ADDED,
    }


def test_a_bundle_with_no_packs_installed_does_nothing(corpus: Path, bundle: Path):
    result = sync_bundle(bundle, corpus)

    assert result.counts == {}


def test_the_sync_makes_no_commit(corpus: Path, bundle: Path, tmp_path: Path):
    """kennis does not write to the user's repository. The bundle lives in
    one kennis does not own, so committing is theirs to do."""
    project = bundle.parent
    subprocess.run(
        ["git", "init", "-q"],
        cwd=project,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    installed(corpus, tmp_path)

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


def test_a_group_directory_a_deletion_emptied_is_removed(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """An empty directory left behind is a group in `context status` with
    nothing in it, and a diff in the user's repository that says nothing."""
    installed(
        corpus,
        tmp_path,
        group="decisions",
        files={"content/one.md": "1.\n"},
    )
    sync_bundle(bundle, corpus)
    assert (bundle / "decisions").is_dir()

    installed(corpus, tmp_path, group="decisions", files={"content/two.md": "2.\n"})
    sync_bundle(bundle, corpus)

    assert (bundle / "decisions" / "two.md").is_file()
    assert (bundle / "decisions" / "one.md").exists() is False


def test_a_directory_holding_something_else_is_left_alone(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Only a directory a deletion emptied, and only when it is empty:
    a file kennis does not index is still the user's."""
    installed(corpus, tmp_path, group="decisions", files={"content/one.md": "1.\n"})
    sync_bundle(bundle, corpus)
    (bundle / "decisions" / "notes.txt").write_text("Mine.\n", encoding="utf-8")

    installed(corpus, tmp_path, group="decisions", files={"content/two.md": "2.\n"})
    sync_bundle(bundle, corpus)

    assert (bundle / "decisions" / "notes.txt").is_file()


def test_a_pack_owned_file_with_no_recorded_digest_is_not_read_as_edited(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """A file somebody wrote by hand claiming a pack owns it. There is
    nothing to compare against, so it cannot be an edit - and treating it
    as one would protect a file the pack is entitled to replace, forever
    and silently."""
    installed(corpus, tmp_path, files={"content/one.md": "Shipped.\n"})
    (bundle / "one.md").write_text(
        "---\ntitle: x\nowner: pack:alpha\n---\n\nBy hand.\n", encoding="utf-8"
    )

    result = sync_bundle(bundle, corpus)

    assert result.counts.get("edited") is None
    assert body_of(bundle / "one.md") == "Shipped.\n"


def test_a_pack_whose_stored_declaration_is_corrupt_refuses_the_sync(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """**The door the silent deletion comes in by.** An unreadable
    declaration declares nothing that can be read, and a sync that took
    that at face value would find every file the pack owns undeclared and
    delete all of them. Found by writing this test: the first
    implementation did exactly that."""
    installed(corpus, tmp_path)
    sync_bundle(bundle, corpus)
    (pack_root(corpus, "alpha") / "pack.ken.yml").write_text(
        "not: [a, pack\n", encoding="utf-8"
    )

    with pytest.raises(PackInvalid) as raised:
        sync_bundle(bundle, corpus)

    assert "alpha" in str(raised.value)
    assert (bundle / "one.md").is_file()


def test_a_pack_whose_content_is_gone_refuses_the_sync(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Section 5 step 2a from this side: "the store says N files and disk
    has 0" is corruption, never a declaration that the pack now ships
    nothing."""
    installed(corpus, tmp_path)
    sync_bundle(bundle, corpus)
    (pack_root(corpus, "alpha") / "content" / "one.md").unlink()

    with pytest.raises(PackInvalid) as raised:
        sync_bundle(bundle, corpus)

    assert raised.value.resolution == "kennis pack status"
    assert (bundle / "one.md").is_file()
