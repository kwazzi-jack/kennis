"""Emptying a bundle of everything kennis put there.

The property that matters is the one that is hardest to get back if it is
wrong: a file the user wrote is never removed. Everything else here - the
index, a pack's document - is derived or replaceable, and a bundle sits in
a repository kennis has no history of, so a wrong deletion has no undo
inside kennis at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.context import (
    index_bundle,
    init_bundle,
    remember_in_bundle,
    reset_bundle,
)


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    return init_bundle(tmp_path / "project").path


def a_file(bundle: Path, relative: str, text: str) -> Path:
    path = bundle / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def a_pack_file(bundle: Path, relative: str) -> Path:
    """What a pack will write once packs exist: a document kennis owns.

    Nothing produces one yet, which is exactly why it is written by hand
    here - the behaviour `reset` exists for has to be tested before the
    thing that triggers it is built, or it lands untested with packs.
    """
    return a_file(
        bundle,
        relative,
        "---\ntitle: From a pack\nowner: pack\n---\n\nPack prose.\n",
    )


def test_a_users_own_file_is_never_removed(bundle: Path):
    note = remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")

    reset_bundle(bundle)

    assert note.path.is_file()


def test_a_file_kennis_owns_is_removed(bundle: Path):
    applied = a_pack_file(bundle, "conventions/naming.md")

    report = reset_bundle(bundle)

    assert not applied.exists()
    assert report.removed == ("conventions/naming.md",)


def test_a_file_with_no_frontmatter_is_treated_as_the_users(bundle: Path):
    """The likeliest thing to lack a header is something written by hand,
    and the two mistakes do not cost the same: keeping a pack file costs a
    stale file the next sync overwrites, deleting a user's costs their
    writing."""
    plain = a_file(bundle, "jotting.md", "# Jotting\n\nNames are lowercase.\n")

    reset_bundle(bundle)

    assert plain.is_file()


def test_a_file_whose_header_will_not_parse_is_treated_as_the_users(bundle: Path):
    broken = a_file(bundle, "broken.md", "---\ntitle: [unclosed\n---\n\nMine.\n")

    reset_bundle(bundle)

    assert broken.is_file()


def test_the_index_is_removed(bundle: Path):
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")
    index_bundle(bundle)

    report = reset_bundle(bundle)

    assert not (bundle / ".index").exists()
    assert report.index_removed


def test_the_scaffolding_is_left_alone(bundle: Path):
    """`LANDING.md` holds a table the file itself tells the reader to keep
    current, and `.skeleton.md` is a template a project adapts. Both are
    kennis-written and user-maintained, and `context init` restores either
    one on its own if that is what was wanted.

    Both are marked `owner: pack` here, which they never are in practice.
    Without that the test passes for the wrong reason: the ownership rule
    protects them anyway, so it could not tell whether the exclusion rule
    was doing anything. Marked this way, only the exclusion stands between
    them and deletion - and it is the exclusion this test is about.
    """
    (bundle / "LANDING.md").write_text(
        "---\nowner: pack\n---\n\n# My own map\n", encoding="utf-8"
    )
    (bundle / ".skeleton.md").write_text(
        "---\nowner: pack\n---\n\nA template.\n", encoding="utf-8"
    )

    reset_bundle(bundle)

    assert "My own map" in (bundle / "LANDING.md").read_text(encoding="utf-8")
    assert (bundle / ".skeleton.md").is_file()
    assert (bundle / "bundle.json").is_file()


def test_resetting_a_bundle_with_nothing_to_remove_removes_nothing(bundle: Path):
    remember_in_bundle(bundle, "Calibration runs in four-minute chunks.")

    report = reset_bundle(bundle)

    assert report.removed == ()
    assert report.index_removed is False


def test_an_emptied_directory_is_removed_with_its_last_file(bundle: Path):
    """A pack's directory left standing and empty is litter a reader cannot
    tell from a directory they made themselves and have not filled."""
    a_pack_file(bundle, "conventions/naming.md")

    reset_bundle(bundle)

    assert not (bundle / "conventions").exists()


def test_a_directory_holding_a_users_file_survives(bundle: Path):
    a_pack_file(bundle, "conventions/naming.md")
    remember_in_bundle(bundle, "Mine.", group="conventions")

    reset_bundle(bundle)

    assert (bundle / "conventions").is_dir()


def test_a_pack_file_the_user_hid_is_still_removed(bundle: Path):
    """Renaming a pack's file to a dot-prefixed name keeps it out of the
    index; it does not make it the user's. A reset that could not see it
    left pack content behind in a bundle it reported as clean. Concern
    #247."""
    hidden = a_pack_file(bundle, ".naming.md")

    report = reset_bundle(bundle)

    assert not hidden.exists()
    assert report.removed == (".naming.md",)


def test_a_hidden_pack_file_in_a_group_is_removed_with_its_directory(bundle: Path):
    a_pack_file(bundle, "conventions/.naming.md")

    reset_bundle(bundle)

    assert not (bundle / "conventions").exists()


def test_a_skeleton_below_the_root_is_left_alone(bundle: Path):
    """Each directory may carry its own template, so the exclusion is by
    name at any depth and not only at the bundle root. Marked `owner:
    pack` for the reason the root scaffolding test gives: otherwise the
    ownership rule would protect it and the exclusion would go
    untested."""
    skeleton = a_pack_file(bundle, "conventions/.skeleton.md")

    reset_bundle(bundle)

    assert skeleton.is_file()
