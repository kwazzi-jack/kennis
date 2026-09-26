"""Reading and removing the pack store. Milestone 7 unit 6.

`pack add` writes a store nothing could look at. These are the three
questions a user has about it afterwards - what is installed, what does it
record, and how do I get rid of one - and the one question the design
insists is *persistent* state rather than a line printed inside an
automated run: which two packs declare the same item, and which of them
owns it (section 5, step 4).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kennis.engine.errors import PackNotInstalled
from kennis.engine.events import OperationFinished, Outcome, Recorder
from kennis.engine.pack.installed import (
    declared_content,
    list_installed,
    overlaps_between,
    remove_pack,
)
from kennis.engine.pack.store import (
    STATE_FILENAME,
    install_pack,
    pack_root,
    packs_root,
)
from kennis.engine.pack.update import update_pack


def a_provider(
    root: Path,
    *,
    identifier: str,
    version: str = "0.1.0",
    body: str = "corpus:\n  notes:\n    - source: notes/\n",
    files: dict[str, str] | None = None,
) -> Path:
    """A pack as a provider ships it, with its generated block written."""
    root.mkdir(parents=True, exist_ok=True)
    for relative, text in (files or {"notes/one.md": "One.\n"}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    header = (
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: n\n  version: "{version}"\n'
    )
    path = root / f"{identifier}.ken.yml"
    path.write_text(header + body, encoding="utf-8")
    update_pack(path)
    return path


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_an_empty_store_lists_nothing(corpus: Path):
    """A corpus with no packs is the ordinary state, not an error."""
    listing = list_installed(corpus)

    assert listing.packs == ()
    assert listing.unreadable == ()


def test_every_installed_pack_is_listed_with_what_it_recorded(
    corpus: Path, tmp_path: Path
):
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))
    install_pack(corpus, a_provider(tmp_path / "b", identifier="beta", version="2.0.0"))

    listing = list_installed(corpus)

    assert [one.state.pack_id for one in listing.packs] == ["alpha", "beta"]
    assert [one.state.pack_version for one in listing.packs] == ["0.1.0", "2.0.0"]


def test_the_listing_is_sorted_so_two_runs_agree(corpus: Path, tmp_path: Path):
    for identifier in ("zeta", "alpha", "mu"):
        install_pack(corpus, a_provider(tmp_path / identifier, identifier=identifier))

    listing = list_installed(corpus)

    assert [one.state.pack_id for one in listing.packs] == ["alpha", "mu", "zeta"]


def test_a_partial_install_is_named_rather_than_skipped(corpus: Path, tmp_path: Path):
    """A directory under `packs/` with no state file that parses is a half
    written store. Skipping it silently is how a user ends up with a pack
    that `add` will rewrite and `list` says is not there."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))
    (pack_root(corpus, "alpha") / STATE_FILENAME).unlink()

    listing = list_installed(corpus)

    assert listing.packs == ()
    assert listing.unreadable == ("alpha",)


def test_a_pack_whose_store_was_emptied_is_listed_as_not_verifying(
    corpus: Path, tmp_path: Path
):
    """The fourth fast-path condition, asked here for reporting rather than
    for a decision. `pack status` is where a user should learn the store is
    damaged - before a sync reads it as a pack that ships nothing."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))
    (pack_root(corpus, "alpha") / "notes" / "one.md").unlink()

    listing = list_installed(corpus)

    assert [one.verified for one in listing.packs] == [False]


def test_an_intact_pack_verifies(corpus: Path, tmp_path: Path):
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))

    listing = list_installed(corpus)

    assert [one.verified for one in listing.packs] == [True]


def test_the_stored_declaration_is_read_back(corpus: Path, tmp_path: Path):
    """`status` reports what the pack declares, so the copy kennis kept has
    to parse. It is the file `add` copied verbatim, so it should."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))

    listing = list_installed(corpus)

    declaration = listing.packs[0].declaration
    assert declaration is not None
    assert declaration.pack.name == "n"


def test_a_corrupt_stored_declaration_does_not_hide_the_pack(
    corpus: Path, tmp_path: Path
):
    """kennis copied that file itself, so a declaration that will not parse
    is corruption. The pack still has a state file and still has to be
    listed - a store you cannot see is the thing this unit exists to end."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))
    (pack_root(corpus, "alpha") / "pack.ken.yml").write_text(
        "not: [a, pack\n", encoding="utf-8"
    )

    listing = list_installed(corpus)

    assert [one.state.pack_id for one in listing.packs] == ["alpha"]
    assert listing.packs[0].declaration is None


# ---------------------------------------------------------------------------
# overlaps: the thing section 5 calls persistent state
# ---------------------------------------------------------------------------


DOCS = 'corpus:\n  docs:\n    - project: stimela\n      base_url: "https://x/"\n'
PAPER = (
    "corpus:\n  literature:\n    - citekey: kenyon2018\n"
    '      title: t\n      arxiv_id: "1712.01093"\n'
)


def test_two_packs_declaring_one_docs_project_overlap(corpus: Path, tmp_path: Path):
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha", body=DOCS))
    install_pack(corpus, a_provider(tmp_path / "b", identifier="beta", body=DOCS))

    found = overlaps_between(list_installed(corpus).packs)

    assert [one.key for one in found] == ["stimela"]
    assert found[0].kind == "docs"
    assert found[0].pack_ids == ("alpha", "beta")


def test_the_incumbent_is_the_earliest_first_applied_at(corpus: Path, tmp_path: Path):
    """Section 5 step 4: `applied_at` cannot be the tie-break, because a
    provider calls `pack add` on every run and most-recent-wins would flip
    ownership in a loop."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha", body=DOCS))
    install_pack(corpus, a_provider(tmp_path / "b", identifier="beta", body=DOCS))
    # Planted rather than slept for: two installs in the same second would
    # make this pass whatever the tie-break was.
    _restamp(corpus, "beta", first_applied_at="2020-01-01T00:00:00Z")

    found = overlaps_between(list_installed(corpus).packs)

    assert found[0].owner == "beta"


def test_the_incumbent_does_not_change_when_the_other_pack_is_re_added(
    corpus: Path, tmp_path: Path
):
    """The loop the immutable timestamp exists to prevent, run once."""
    first = a_provider(tmp_path / "a", identifier="alpha", body=DOCS)
    install_pack(corpus, first)
    _restamp(corpus, "alpha", first_applied_at="2020-01-01T00:00:00Z")
    install_pack(corpus, a_provider(tmp_path / "b", identifier="beta", body=DOCS))

    install_pack(corpus, first)

    found = overlaps_between(list_installed(corpus).packs)
    assert found[0].owner == "alpha"


def test_two_packs_declaring_one_paper_overlap_on_the_identifier(
    corpus: Path, tmp_path: Path
):
    """Keyed on the identifier and never on the citekey: section 5 step 3
    makes that the difference between a rename and a delete-then-refetch."""
    other = PAPER.replace("kenyon2018", "paperCubicalFast")
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha", body=PAPER))
    install_pack(corpus, a_provider(tmp_path / "b", identifier="beta", body=other))

    found = overlaps_between(list_installed(corpus).packs)

    assert [one.kind for one in found] == ["literature"]
    assert found[0].key == "arxiv:1712.01093"


def test_two_packs_shipping_one_note_destination_overlap(corpus: Path, tmp_path: Path):
    """Content is keyed on where it lands, not on where it came from: two
    packs whose sources are named differently still collide when the file
    ends up at the same address."""
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body="corpus:\n  notes:\n    - source: notes/\n      group: install\n",
            files={"notes/setup.md": "A.\n"},
        ),
    )
    install_pack(
        corpus,
        a_provider(
            tmp_path / "b",
            identifier="beta",
            body="corpus:\n  notes:\n    - source: shipped/\n      group: install\n",
            files={"shipped/setup.md": "B.\n"},
        ),
    )

    found = overlaps_between(list_installed(corpus).packs)

    assert [one.kind for one in found] == ["notes"]
    assert found[0].key == "install/setup.md"


def test_the_same_filename_in_two_groups_is_not_an_overlap(
    corpus: Path, tmp_path: Path
):
    """`group:` is part of the address, so it is part of the identity."""
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body="corpus:\n  notes:\n    - source: notes/\n      group: install\n",
            files={"notes/setup.md": "A.\n"},
        ),
    )
    install_pack(
        corpus,
        a_provider(
            tmp_path / "b",
            identifier="beta",
            body="corpus:\n  notes:\n    - source: notes/\n      group: running\n",
            files={"notes/setup.md": "B.\n"},
        ),
    )

    assert overlaps_between(list_installed(corpus).packs) == ()


def test_notes_and_context_are_different_destinations(corpus: Path, tmp_path: Path):
    """One tree shipped to the corpus and one to a bundle land in two
    different places, so they are not the same item."""
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body="corpus:\n  notes:\n    - source: notes/\n",
        ),
    )
    install_pack(
        corpus,
        a_provider(
            tmp_path / "b",
            identifier="beta",
            body="context:\n  - source: notes/\n",
        ),
    )

    assert overlaps_between(list_installed(corpus).packs) == ()


def test_one_pack_alone_overlaps_with_nothing(corpus: Path, tmp_path: Path):
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha", body=DOCS))

    assert overlaps_between(list_installed(corpus).packs) == ()


def test_a_pack_declaring_an_item_twice_is_not_an_overlap_with_itself(
    corpus: Path, tmp_path: Path
):
    body = (
        'corpus:\n  docs:\n    - project: stimela\n      base_url: "https://x/"\n'
        '    - project: stimela\n      base_url: "https://y/"\n'
    )
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha", body=body))

    assert overlaps_between(list_installed(corpus).packs) == ()


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


def test_remove_deletes_the_pack_directory(corpus: Path, tmp_path: Path):
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))

    remove_pack(corpus, "alpha")

    assert not pack_root(corpus, "alpha").exists()


def test_remove_leaves_the_other_packs_alone(corpus: Path, tmp_path: Path):
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))
    install_pack(corpus, a_provider(tmp_path / "b", identifier="beta"))

    remove_pack(corpus, "alpha")

    assert [one.state.pack_id for one in list_installed(corpus).packs] == ["beta"]


def test_remove_reports_how_much_it_dropped(corpus: Path, tmp_path: Path):
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            files={"notes/one.md": "1.\n", "notes/two.md": "2.\n"},
        ),
    )

    removal = remove_pack(corpus, "alpha")

    assert removal.pack_id == "alpha"
    assert removal.files == 2
    assert removal.recorded is True


def test_removing_a_pack_that_is_not_installed_refuses(corpus: Path):
    """Named rather than treated as a success: a typo in a pack id would
    otherwise report that the thing the user meant is gone."""
    with pytest.raises(PackNotInstalled) as raised:
        remove_pack(corpus, "nosuch")

    assert "nosuch" in str(raised.value)
    assert raised.value.resolution == "kennis pack list"


def test_a_partial_install_can_still_be_removed(corpus: Path, tmp_path: Path):
    """Removing is how a user gets out of the state `list` reports as
    unreadable, so it cannot be the one state removing refuses."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))
    (pack_root(corpus, "alpha") / STATE_FILENAME).unlink()

    removal = remove_pack(corpus, "alpha")

    # `recorded` and not just `files`: 0 here means nothing said what was
    # in that directory, which is a different claim from it being empty.
    assert removal.recorded is False
    assert removal.files == 0
    assert not pack_root(corpus, "alpha").exists()


def test_remove_reports_through_the_event_stream(corpus: Path, tmp_path: Path):
    """Section 14: the log holds what the report leaves out, and a removal
    is a mutation, so it goes through the stream like every other one."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))
    events = Recorder()

    remove_pack(corpus, "alpha", events=events)

    assert events.outcomes() == {"alpha": Outcome.REMOVED}
    finished = events.events_of_type(OperationFinished)
    assert [event.operation for event in finished] == ["pack-remove"]


def test_a_refused_removal_reports_nothing(corpus: Path):
    events = Recorder()

    with pytest.raises(PackNotInstalled):
        remove_pack(corpus, "nosuch", events=events)

    assert events.events == []


def _restamp(corpus: Path, pack_id: str, *, first_applied_at: str) -> None:
    """Plant a `first_applied_at` far in the past.

    Two installs in one test fall in the same second, so a test that
    relied on the real clock would pass whatever the tie-break was - which
    is how #264 was found.
    """
    path = pack_root(corpus, pack_id) / STATE_FILENAME
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["first_applied_at"] != first_applied_at, "PLANT DID NOT APPLY"
    document["first_applied_at"] = first_applied_at
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# What the walk and the keys do at their edges
# ---------------------------------------------------------------------------


def test_a_stray_file_in_the_store_is_not_reported_as_a_broken_pack(
    corpus: Path, tmp_path: Path
):
    """`packs/` holds one directory per pack. A file beside them - an
    editor's backup, a downloaded archive - is not a half-written pack,
    and reporting it as one would send the user to remove something
    `remove` cannot address."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))
    (packs_root(corpus) / "notes.tar.gz").write_bytes(b"x")
    (packs_root(corpus) / ".DS_Store").write_bytes(b"x")

    listing = list_installed(corpus)

    assert [one.state.pack_id for one in listing.packs] == ["alpha"]
    assert listing.unreadable == ()


def test_an_edited_file_in_the_store_fails_verification(corpus: Path, tmp_path: Path):
    """Not only a deleted one. A file whose bytes changed is the case the
    digest map exists for - its absence would be caught by the filesystem
    alone."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha"))
    (pack_root(corpus, "alpha") / "notes" / "one.md").write_text(
        "Edited.\n", encoding="utf-8"
    )

    assert [one.verified for one in list_installed(corpus).packs] == [False]


def test_a_pack_whose_declaration_will_not_parse_declares_nothing(
    corpus: Path, tmp_path: Path
):
    """Nothing can be said about what a pack declares when the declaration
    is unreadable, so it cannot be half of an overlap. The pack is still
    listed, and the corruption is reported on its own."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha", body=DOCS))
    install_pack(corpus, a_provider(tmp_path / "b", identifier="beta", body=DOCS))
    (pack_root(corpus, "beta") / "pack.ken.yml").write_text(
        "not: [a, pack\n", encoding="utf-8"
    )

    assert overlaps_between(list_installed(corpus).packs) == ()


DOI_PAPER = (
    "corpus:\n  literature:\n    - citekey: a\n"
    '      title: t\n      doi: "10.1000/xyz"\n'
)
BIBCODE_PAPER = (
    "corpus:\n  literature:\n    - citekey: b\n"
    '      title: t\n      bibcode: "2018MNRAS.478.2399K"\n'
)


@pytest.mark.parametrize(
    ("body", "key"),
    [(DOI_PAPER, "doi:10.1000/xyz"), (BIBCODE_PAPER, "bibcode:2018MNRAS.478.2399K")],
)
def test_a_paper_without_an_arxiv_id_falls_through_to_the_next_identifier(
    corpus: Path, tmp_path: Path, body: str, key: str
):
    """`arxiv_id`, else `doi`, else `bibcode` - the order section 5 gives,
    and the scheme is part of the key so two schemes cannot collide on a
    string they happen to share."""
    install_pack(corpus, a_provider(tmp_path / "a", identifier="alpha", body=body))
    install_pack(corpus, a_provider(tmp_path / "b", identifier="beta", body=body))

    found = overlaps_between(list_installed(corpus).packs)

    assert [one.key for one in found] == [key]


def test_one_source_does_not_claim_another_sources_files(corpus: Path, tmp_path: Path):
    """A pack shipping two trees records both in one flat digest map, so
    the addresses of one must not absorb the other's files."""
    body = (
        "corpus:\n  notes:\n    - source: notes/\n      group: first\n"
        "context:\n  - source: other/\n"
    )
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body=body,
            files={"notes/one.md": "1.\n", "other/two.md": "2.\n"},
        ),
    )
    install_pack(
        corpus,
        a_provider(
            tmp_path / "b",
            identifier="beta",
            body=body,
            files={"notes/one.md": "1.\n", "other/two.md": "2.\n"},
        ),
    )

    found = overlaps_between(list_installed(corpus).packs)

    assert [(one.kind, one.key) for one in found] == [
        ("context", "two.md"),
        ("notes", "first/one.md"),
    ]


# ---------------------------------------------------------------------------
# The union of every pack's declarations. Section 5, step 6.
# ---------------------------------------------------------------------------


def test_the_union_carries_one_declaration_per_address(corpus: Path, tmp_path: Path):
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body="context:\n  - source: content/\n",
            files={"content/one.md": "1.\n", "content/two.md": "2.\n"},
        ),
    )

    union = declared_content(corpus, list_installed(corpus).packs, "context")

    assert sorted(union.declarations) == ["one.md", "two.md"]
    assert union.declarations["one.md"].pack_id == "alpha"


def test_a_declaration_points_at_the_file_in_the_store(corpus: Path, tmp_path: Path):
    """A sync reads content from the store, never from the provider's
    checkout: the checkout may be gone, and the store is what `pack add`
    verified."""
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body="context:\n  - source: content/\n",
            files={"content/one.md": "Body.\n"},
        ),
    )

    union = declared_content(corpus, list_installed(corpus).packs, "context")

    store_path = union.declarations["one.md"].store_path
    assert store_path.read_text() == "Body.\n"
    assert pack_root(corpus, "alpha") in store_path.parents


def test_the_declared_digest_is_the_one_the_store_recorded(
    corpus: Path, tmp_path: Path
):
    """What a destination compares against to tell a pack change from a
    user edit, so it has to be the store's own record."""
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body="context:\n  - source: content/\n",
            files={"content/one.md": "Body.\n"},
        ),
    )

    union = declared_content(corpus, list_installed(corpus).packs, "context")

    state = list_installed(corpus).packs[0].state
    assert union.declarations["one.md"].digest == state.files["content/one.md"]


def test_two_packs_declaring_one_address_resolve_to_the_incumbent(
    corpus: Path, tmp_path: Path
):
    """Step 6 again: the union is what a sync converges with, so the
    address has to belong to exactly one pack before a sync sees it."""
    body = "context:\n  - source: content/\n"
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body=body,
            files={"content/one.md": "A.\n"},
        ),
    )
    install_pack(
        corpus,
        a_provider(
            tmp_path / "b",
            identifier="beta",
            body=body,
            files={"content/one.md": "B.\n"},
        ),
    )
    _restamp(corpus, "beta", first_applied_at="2020-01-01T00:00:00Z")

    union = declared_content(corpus, list_installed(corpus).packs, "context")

    assert union.declarations["one.md"].pack_id == "beta"
    assert union.deferred == (("one.md", "alpha"),)


def test_removing_the_incumbent_leaves_the_other_packs_declaration_standing(
    corpus: Path, tmp_path: Path
):
    """The sentence step 6 exists for: `pack remove A` for an item B also
    declares must not make the item vanish, because B still declares it."""
    body = "context:\n  - source: content/\n"
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body=body,
            files={"content/one.md": "A.\n"},
        ),
    )
    install_pack(
        corpus,
        a_provider(
            tmp_path / "b",
            identifier="beta",
            body=body,
            files={"content/one.md": "B.\n"},
        ),
    )

    remove_pack(corpus, "alpha")

    union = declared_content(corpus, list_installed(corpus).packs, "context")
    assert union.declarations["one.md"].pack_id == "beta"
    assert union.deferred == ()


def test_the_union_of_a_section_no_pack_declares_is_empty(corpus: Path, tmp_path: Path):
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body="corpus:\n  notes:\n    - source: notes/\n",
        ),
    )

    union = declared_content(corpus, list_installed(corpus).packs, "context")

    assert union.declarations == {}


def test_a_group_puts_the_address_in_a_subdirectory(corpus: Path, tmp_path: Path):
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body="context:\n  - source: content/\n    group: decisions\n",
            files={"content/one.md": "1.\n"},
        ),
    )

    union = declared_content(corpus, list_installed(corpus).packs, "context")

    assert sorted(union.declarations) == ["decisions/one.md"]


def test_the_union_skips_a_pack_whose_declaration_will_not_parse(
    corpus: Path, tmp_path: Path
):
    """Nothing can be said about what an unreadable declaration wanted.

    Skipping is right *here* and dangerous in a caller: a sync that read
    the resulting empty union as "this pack ships nothing" would delete
    everything the pack owns, which is #274. So the callers refuse before
    they get this far, and this function stays the honest one.
    """
    body = "context:\n  - source: content/\n"
    install_pack(
        corpus,
        a_provider(
            tmp_path / "a",
            identifier="alpha",
            body=body,
            files={"content/one.md": "A.\n"},
        ),
    )
    install_pack(
        corpus,
        a_provider(
            tmp_path / "b",
            identifier="beta",
            body=body,
            files={"content/two.md": "B.\n"},
        ),
    )
    (pack_root(corpus, "beta") / "pack.ken.yml").write_text(
        "not: [a, pack\n", encoding="utf-8"
    )

    union = declared_content(corpus, list_installed(corpus).packs, "context")

    assert sorted(union.declarations) == ["one.md"]
