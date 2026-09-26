"""The pack store: `kennis pack add`. Milestone 7 unit 5.

Design sections 5 (steps 1, 2, 2a and 5) and 8. The property most of this
file is about is the fourth fast-path condition - that a store which does
not verify is not believed - because the failure it prevents is silent
deletion of the user's documents on the next sync.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kennis.engine.errors import PackInvalid
from kennis.engine.pack.store import (
    STATE_FILENAME,
    install_pack,
    pack_root,
    packs_root,
    read_state,
)
from kennis.engine.pack.update import update_pack

HEADER = """
kennis:
  schema_version: 1
pack:
  id: boepie
  name: "stimela pipelines"
  version: "0.1.0"
"""

SOURCES = "corpus:\n  notes:\n    - source: notes/\ncontext:\n  - source: content/\n"


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    return root


@pytest.fixture
def provider(tmp_path: Path) -> Path:
    """A pack as a provider ships it: a file, its content, and an update."""
    root = tmp_path / "provider"
    (root / "notes").mkdir(parents=True)
    (root / "content").mkdir(parents=True)
    (root / "notes" / "conventions.md").write_text("Recipes.\n", encoding="utf-8")
    (root / "content" / "index.md").write_text("Entry.\n", encoding="utf-8")
    (root / "p.ken.yml").write_text(HEADER + SOURCES, encoding="utf-8")
    update_pack(root / "p.ken.yml")
    return root


# ---------------------------------------------------------------------------
# What a first install leaves on disk
# ---------------------------------------------------------------------------


def test_the_content_is_copied_under_the_packs_directory(corpus: Path, provider: Path):
    install_pack(corpus, provider / "p.ken.yml")

    root = pack_root(corpus, "boepie")
    assert (root / "notes" / "conventions.md").read_text() == "Recipes.\n"
    assert (root / "content" / "index.md").read_text() == "Entry.\n"


def test_the_declaration_is_kept_verbatim(corpus: Path, provider: Path):
    """Section 8: "the declaration as last applied, verbatim". The next add
    diffs against it, so a reformatted copy would make every add a change."""
    install_pack(corpus, provider / "p.ken.yml")

    kept = pack_root(corpus, "boepie") / "pack.ken.yml"
    assert kept.read_bytes() == (provider / "p.ken.yml").read_bytes()


def test_the_state_records_what_the_fast_path_compares(corpus: Path, provider: Path):
    install_pack(corpus, provider / "p.ken.yml")

    state = read_state(corpus, "boepie")
    assert state is not None
    assert state.pack_id == "boepie"
    assert state.pack_version == "0.1.0"
    assert state.schema_version == 1
    assert state.source_path == str(provider / "p.ken.yml")
    assert set(state.files) == {"notes/conventions.md", "content/index.md"}


def test_first_applied_at_survives_a_later_install(corpus: Path, provider: Path):
    """Section 5: it is the tie-break when two packs declare the same thing,
    and `applied_at` cannot be, because a provider calls `pack add` on every
    run and most-recent-wins would flip ownership in a loop and rewrite the
    same documents forever.

    **Asserted against a planted value, not against the first run's.** The
    first version of this test compared the two recorded timestamps, and
    passed with `first_applied_at=now` injected: both installs happen inside
    one second and the stamp has second resolution, so the two strings were
    equal for a reason that had nothing to do with the code. Concern #264.
    """
    planted = "2020-01-01T00:00:00Z"
    install_pack(corpus, provider / "p.ken.yml")
    state_file = pack_root(corpus, "boepie") / STATE_FILENAME
    document = json.loads(state_file.read_text(encoding="utf-8"))
    document["first_applied_at"] = planted
    state_file.write_text(json.dumps(document), encoding="utf-8")

    # Changed content, so the add takes the slow path and rewrites the state
    # file. A fast-pathed add would preserve it by not writing at all, which
    # would be a weaker thing to have shown.
    (provider / "notes" / "conventions.md").write_text("Edited.\n", encoding="utf-8")
    update_pack(provider / "p.ken.yml")
    install_pack(corpus, provider / "p.ken.yml")

    second = read_state(corpus, "boepie")
    assert second is not None
    assert second.first_applied_at == planted
    assert second.applied_at != planted


def test_the_store_is_not_committed_with_the_corpus(corpus: Path, provider: Path):
    """Section 19's table: "pack store | no - re-derivable". Fifty-seven
    copied files sweeping into the corpus history on the next `corpus add`
    is easy to do and tedious to undo."""
    install_pack(corpus, provider / "p.ken.yml")

    ignored = (corpus / ".gitignore").read_text(encoding="utf-8")
    assert "packs/" in ignored


def test_an_existing_gitignore_is_added_to_rather_than_replaced(
    corpus: Path, provider: Path
):
    (corpus / ".gitignore").write_text(".kennis.lock\n", encoding="utf-8")

    install_pack(corpus, provider / "p.ken.yml")

    ignored = (corpus / ".gitignore").read_text(encoding="utf-8")
    assert ".kennis.lock" in ignored
    assert "packs/" in ignored


def test_the_ignore_line_is_written_once_however_often_add_runs(
    corpus: Path, provider: Path
):
    install_pack(corpus, provider / "p.ken.yml")
    install_pack(corpus, provider / "p.ken.yml")

    ignored = (corpus / ".gitignore").read_text(encoding="utf-8")
    assert ignored.count("packs/") == 1


# ---------------------------------------------------------------------------
# The fast path, and its four conditions
# ---------------------------------------------------------------------------


def test_a_second_add_of_the_same_pack_does_nothing(corpus: Path, provider: Path):
    install_pack(corpus, provider / "p.ken.yml")

    again = install_pack(corpus, provider / "p.ken.yml")

    assert again.outcome == "unchanged"


def test_a_changed_pack_file_is_installed_again(corpus: Path, provider: Path):
    install_pack(corpus, provider / "p.ken.yml")
    (provider / "notes" / "conventions.md").write_text("Edited.\n", encoding="utf-8")
    update_pack(provider / "p.ken.yml")

    again = install_pack(corpus, provider / "p.ken.yml")

    assert again.outcome == "installed"
    assert (
        pack_root(corpus, "boepie") / "notes" / "conventions.md"
    ).read_text() == "Edited.\n"


def test_an_emptied_store_is_repaired_rather_than_believed(
    corpus: Path, provider: Path
):
    """**The condition the design spends its length on.** Without it a
    partial restore or an interrupted add leaves the content gone and
    `state.json` intact, the next add fast-paths out, and the next sync sees
    a pack declaring nothing and deletes every document it owns."""
    install_pack(corpus, provider / "p.ken.yml")
    for path in (pack_root(corpus, "boepie") / "notes").iterdir():
        path.unlink()

    again = install_pack(corpus, provider / "p.ken.yml")

    assert again.outcome == "repaired"
    assert (
        pack_root(corpus, "boepie") / "notes" / "conventions.md"
    ).read_text() == "Recipes.\n"


def test_a_corrupted_file_in_the_store_is_repaired(corpus: Path, provider: Path):
    install_pack(corpus, provider / "p.ken.yml")
    (pack_root(corpus, "boepie") / "notes" / "conventions.md").write_text(
        "Truncated", encoding="utf-8"
    )

    again = install_pack(corpus, provider / "p.ken.yml")

    assert again.outcome == "repaired"
    assert (
        pack_root(corpus, "boepie") / "notes" / "conventions.md"
    ).read_text() == "Recipes.\n"


def test_a_store_written_by_an_older_kennis_is_installed_again(
    corpus: Path, provider: Path
):
    """Section 5: a kennis upgrade can change how content is materialised
    without the pack file moving, so the file hash alone would leave the
    store holding what the old kennis wrote, forever."""
    install_pack(corpus, provider / "p.ken.yml")
    state = json.loads(
        (pack_root(corpus, "boepie") / STATE_FILENAME).read_text(encoding="utf-8")
    )
    state["applied_by"] = "0.0"
    (pack_root(corpus, "boepie") / STATE_FILENAME).write_text(
        json.dumps(state), encoding="utf-8"
    )

    again = install_pack(corpus, provider / "p.ken.yml")

    assert again.outcome == "installed"


def test_a_patch_release_still_takes_the_fast_path(corpus: Path, provider: Path):
    """major.minor, not the full version: `0.2.1` reading a store written by
    `0.2.0` has not changed how anything is materialised."""
    install_pack(corpus, provider / "p.ken.yml")
    path = pack_root(corpus, "boepie") / STATE_FILENAME
    state = json.loads(path.read_text(encoding="utf-8"))
    recorded = state["applied_by"]
    path.write_text(json.dumps(state), encoding="utf-8")

    assert recorded.count(".") == 1
    assert install_pack(corpus, provider / "p.ken.yml").outcome == "unchanged"


# ---------------------------------------------------------------------------
# What it refuses, and what survives a failure
# ---------------------------------------------------------------------------


def test_an_invalid_pack_is_refused_before_the_store_is_touched(
    corpus: Path, provider: Path
):
    install_pack(corpus, provider / "p.ken.yml")
    before = (pack_root(corpus, "boepie") / "notes" / "conventions.md").read_bytes()
    (provider / "p.ken.yml").write_text(
        "kennis:\n  schema_version: 9\n", encoding="utf-8"
    )

    with pytest.raises(PackInvalid):
        install_pack(corpus, provider / "p.ken.yml")

    assert (
        pack_root(corpus, "boepie") / "notes" / "conventions.md"
    ).read_bytes() == before


def test_a_pack_whose_digests_disagree_with_its_content_is_refused(
    corpus: Path, provider: Path
):
    """`pack validate` is the provider's check and nothing makes them run
    it, so the installing side checks too - section 3: the digests are
    re-verified on the slow path, where walking the tree is free against the
    copy that is about to happen anyway."""
    (provider / "notes" / "conventions.md").write_text("Edited.\n", encoding="utf-8")

    with pytest.raises(PackInvalid):
        install_pack(corpus, provider / "p.ken.yml")

    assert not pack_root(corpus, "boepie").exists()


def test_the_state_file_is_written_after_the_content(corpus: Path, provider: Path):
    """Section 5 step 5, and the reason the order is specified: `state.json`
    is this subsystem's `latest.json`, a pointer that must never be
    published before what it points at. A failed copy must leave no state
    file claiming content that is not there."""
    root = pack_root(corpus, "boepie")
    (provider / "notes" / "conventions.md").write_text("Edited.\n", encoding="utf-8")

    with pytest.raises(PackInvalid):
        install_pack(corpus, provider / "p.ken.yml")

    assert not (root / STATE_FILENAME).exists()


def test_reading_the_state_of_a_pack_that_was_never_added_is_none(corpus: Path):
    assert read_state(corpus, "never-added") is None


def test_two_packs_live_side_by_side(corpus: Path, provider: Path, tmp_path: Path):
    other = tmp_path / "other"
    (other / "notes").mkdir(parents=True)
    (other / "notes" / "theirs.md").write_text("Theirs.\n", encoding="utf-8")
    (other / "p.ken.yml").write_text(
        HEADER.replace("boepie", "quartical")
        + "corpus:\n  notes:\n    - source: notes/\n",
        encoding="utf-8",
    )
    update_pack(other / "p.ken.yml")

    install_pack(corpus, provider / "p.ken.yml")
    install_pack(corpus, other / "p.ken.yml")

    assert sorted(path.name for path in packs_root(corpus).iterdir()) == [
        "boepie",
        "quartical",
    ]
