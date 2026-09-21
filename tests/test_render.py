"""Turning engine values into words.

The engine names things; this is where they are phrased. The separation is
not decoration: the command line wants a path it can put in its own theme
role and wrap for a narrow terminal, and the MCP server wants the same facts
without having to parse English out of its own engine.
"""

from __future__ import annotations

from kennis.engine.history.freshness import Freshness
from kennis.engine.history.outofband import ChangeKind, OutOfBandChange
from kennis.render.words import (
    describe_change,
    describe_freshness,
    remedies_for,
)


def a_change(
    *,
    kind: ChangeKind = "deleted",
    path: str = "notes/A note.md",
    owner: str | None = "user",
    document_id: str | None = "aaaaaaaaaa",
    restored: bool = True,
) -> OutOfBandChange:
    return OutOfBandChange(
        path=path,
        kind=kind,
        owner=owner,
        document_id=document_id,
        restored=restored,
    )


# ---------------------------------------------------------------------------
# Out-of-band changes
# ---------------------------------------------------------------------------


def test_a_restored_deletion_says_it_was_put_back():
    sentence = describe_change(a_change(kind="deleted", restored=True))

    assert "deleted" in sentence
    assert "restored" in sentence
    assert "notes/A note.md" in sentence


def test_a_deletion_that_could_not_be_restored_says_so_instead():
    """The two are opposite news and the engine reports the difference as a
    field, so the words must not flatten it. Asserted as a difference rather
    than as a phrase: what matters is that the reader can tell them apart,
    not which words do it."""
    put_back = describe_change(a_change(kind="deleted", restored=True))
    lost = describe_change(a_change(kind="deleted", restored=False))

    assert put_back != lost
    assert "not" in lost


def test_an_edit_to_the_users_own_document_is_only_noted():
    sentence = describe_change(a_change(kind="edited", owner="user"))

    assert "index" in sentence.lower()


def test_an_edit_to_a_pack_owned_document_names_its_owner():
    sentence = describe_change(a_change(kind="edited", owner="pack:boepie"))

    assert "pack:boepie" in sentence


def test_a_created_file_is_described_as_not_a_document():
    sentence = describe_change(a_change(kind="created", owner=None, document_id=None))

    assert "not a document" in sentence


# ---------------------------------------------------------------------------
# Remedies are commands, not prose
# ---------------------------------------------------------------------------


def test_a_deletion_names_the_command_that_removes_properly():
    assert remedies_for(a_change(kind="deleted")) == ("kennis corpus remove",)


def test_a_pack_owned_edit_offers_both_ways_forward_as_commands():
    """Two commands rather than one sentence containing two commands, so a
    front end can list them, number them, or offer them as choices."""
    remedies = remedies_for(a_change(kind="edited", owner="pack:boepie"))

    assert remedies == (
        "kennis corpus restore aaaaaaaaaa",
        "kennis corpus claim aaaaaaaaaa",
    )


def test_a_users_own_edit_offers_reindexing():
    assert remedies_for(a_change(kind="edited", owner="user")) == ("kennis index",)


def test_a_created_file_offers_adding_it():
    remedies = remedies_for(a_change(kind="created", owner=None, document_id=None))

    assert remedies == ("kennis corpus add 'notes/A note.md'",)


def test_every_remedy_is_a_command_rather_than_a_sentence():
    """The test that keeps this honest: a remedy is something a user can
    paste, so it starts with the program's name and contains no prose."""
    kinds: tuple[ChangeKind, ...] = ("deleted", "edited", "created")
    for kind in kinds:
        for remedy in remedies_for(a_change(kind=kind)):
            assert remedy.startswith("kennis ")
            assert " to " not in remedy
            assert ", or " not in remedy


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


def test_an_index_in_step_says_so():
    assert "in step" in describe_freshness(Freshness(state="in step"), "notes")


def test_an_incomplete_index_reports_what_is_missing_without_calling_it_stale():
    """Incomplete is not wrong: between a `corpus add` and the `corpus index`
    that follows, the index holds nothing false."""
    sentence = describe_freshness(Freshness(state="in step", added=3), "notes")

    assert "3" in sentence
    assert "stale" not in sentence


def test_a_stale_index_names_the_counts_that_made_it_stale():
    sentence = describe_freshness(
        Freshness(state="stale", changed=2, gone=1), "literature"
    )

    assert "2 documents changed" in sentence
    assert "1 document gone" in sentence
    assert "literature" in sentence
    assert "stale" in sentence


def test_an_unverifiable_index_says_which_reason_applies():
    """The engine reports the reason as a value, so the words can differ
    without the engine knowing how they differ."""
    unrecorded = describe_freshness(
        Freshness(state="unverifiable", unverifiable="no commit recorded"), "notes"
    )
    elsewhere = describe_freshness(
        Freshness(state="unverifiable", unverifiable="commit not in this corpus"),
        "notes",
    )

    assert unrecorded != elsewhere
    # Both say the question cannot be answered; only one says why it is
    # someone else's index.
    assert "cannot be checked" in unrecorded
    assert "somewhere else" in elsewhere


def test_a_count_of_one_is_not_written_as_a_plural():
    sentence = describe_freshness(Freshness(state="stale", changed=1), "notes")

    assert "1 document" in sentence
    assert "1 documents" not in sentence
