"""Turning engine values into words.

The engine names things; this is where they are phrased. The separation is
not decoration: the command line wants a path it can put in its own theme
role and wrap for a narrow terminal, and the MCP server wants the same facts
without having to parse English out of its own engine.
"""

from __future__ import annotations

import shlex

import click

from kennis.cli.__main__ import main
from kennis.engine.history.freshness import Freshness
from kennis.engine.history.outofband import ChangeKind, OutOfBandChange
from kennis.engine.rag.models import Chunk, SearchResult
from kennis.render.words import (
    describe_change,
    describe_freshness,
    describe_hit,
    remedies_for,
    snippet_of,
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


def test_a_deletion_names_the_command_that_puts_it_back():
    """`restore`, not `remove`: the file is already gone, so what a reader
    needs named is the way back (#128). With the handle, because the command
    takes one and the bare form fails (#124)."""
    assert remedies_for(a_change(kind="deleted")) == (
        "kennis corpus restore aaaaaaaaaa",
    )


def test_a_pack_owned_edit_names_the_command_that_undoes_it():
    """Commands rather than one sentence containing them, so a front end can
    list them, number them, or offer them as choices.

    Only `restore` for now: `kennis corpus claim` is designed and not built,
    and rules.md 4.4 forbids printing an instruction that fails.
    """
    remedies = remedies_for(a_change(kind="edited", owner="pack:boepie"))

    assert remedies == ("kennis corpus restore aaaaaaaaaa",)


def command_accepts(invocation: str) -> str:
    """Empty if the command line would accept `invocation`, else why not.

    The command is *parsed*, not run: `make_context` resolves the arguments
    and options against the command's parameters and raises if they do not
    fit, without reaching the body that would touch a corpus.

    Checking the name alone is not enough. `kennis corpus index notes` names
    a real command and still fails, because `index` takes `--collection` and
    no positional argument - which is how it was printed for half a day.
    """
    words = shlex.split(invocation)
    if words[0] != "kennis":
        return f"does not start with kennis: {invocation}"

    node: click.Command = main
    rest = words[1:]
    while rest and isinstance(node, click.Group):
        found = node.commands.get(rest[0])
        if found is None:
            return f"no command '{rest[0]}' in '{node.name}'"
        node, rest = found, rest[1:]

    try:
        with node.make_context(node.name, list(rest), resilient_parsing=False):
            return ""
    except click.ClickException as refused:
        return refused.format_message()


def test_every_remedy_names_a_command_that_exists():
    """rules.md 4.4. This is the check that was missing while `kennis index`
    was printed by three call sites, none of which had a command by that
    name to print."""
    changes = [
        a_change(kind="created", owner=None, document_id=None),
        a_change(kind="deleted"),
        a_change(kind="edited", owner="pack:boepie"),
        a_change(kind="edited", owner="user"),
    ]

    for change in changes:
        for remedy in remedies_for(change):
            assert command_accepts(remedy) == "", remedy


def test_a_users_own_edit_offers_reindexing():
    assert remedies_for(a_change(kind="edited", owner="user")) == (
        "kennis corpus index",
    )


def test_a_created_file_offers_no_command_because_none_works():
    """`corpus add` on a path inside the corpus copies it: the inert file
    stays and a second document appears beside it. Naming it would be naming
    an instruction that makes things worse (#129). The sentence carries the
    guidance instead."""
    change = a_change(kind="created", owner=None, document_id=None)

    assert remedies_for(change) == ()
    assert "Move it outside the corpus" in describe_change(change)


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


def test_a_hit_names_its_collection_title_and_identifier():
    """The identifier because `kennis read` takes it, the title because that
    is what a person recognises, the collection because a merged list is
    several lists interleaved."""
    hit = SearchResult(
        chunk=Chunk(
            id="c1",
            collection="notes",
            document_id="zrf1299xo1",
            chunk_index=0,
            text="Rivers carry sediment.",
            source_path="notes/Rivers.md",
            char_start=0,
            char_end=22,
            section="Deposition",
            metadata={"title": "Rivers"},
        ),
        score=0.5,
    )

    described = describe_hit("notes", hit)

    assert "[notes]" in described
    assert "Rivers" in described
    assert "Deposition" in described
    assert "zrf1299xo1" in described


def test_a_hit_does_not_repeat_the_title_as_its_section():
    """A short document's only heading is its title, and "Rivers - Rivers"
    reads as a stutter rather than as a location."""
    hit = SearchResult(
        chunk=Chunk(
            id="c1",
            collection="notes",
            document_id="zrf1299xo1",
            chunk_index=0,
            text="Rivers carry sediment.",
            source_path="notes/Rivers.md",
            char_start=0,
            char_end=22,
            section="Rivers",
            metadata={"title": "Rivers"},
        ),
        score=0.5,
    )

    assert describe_hit("notes", hit).count("Rivers") == 1


def test_a_snippet_is_cut_at_a_word_boundary():
    """Cutting mid-word makes a snippet look corrupted rather than
    shortened, and the partial word carries nothing."""
    text = " ".join(["sediment"] * 60)

    shortened = snippet_of(text, full=False, limit=50)

    assert shortened.endswith(" ...")
    assert "sedimen ..." not in shortened
    assert len(shortened) <= 54


def test_a_full_snippet_is_not_cut_at_all():
    text = " ".join(["sediment"] * 60)

    assert snippet_of(text, full=True) == text


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


def test_a_stale_index_names_what_was_added_as_well_as_what_left():
    """A moved document is read as one gone and one added, because git's
    rename detection is a similarity heuristic and the safe reading is the
    only one available. A sentence naming only the departure reports a move
    as a loss."""
    sentence = describe_freshness(Freshness(state="stale", gone=1, added=1), "notes")

    assert "1 document gone" in sentence
    assert "1 document added" in sentence


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


# ---------------------------------------------------------------------------
# What a hosted conversion cost
# ---------------------------------------------------------------------------
#
# The engine hands over a number of cents; the words are here. Concern #146.


def test_no_reported_cost_says_nothing():
    """A local conversion reports `None`, and kennis must not invent a
    price for it - not even a free one."""
    from kennis.render.words import conversion_cost

    assert conversion_cost(None) == ""


def test_a_free_conversion_says_so_without_claiming_why():
    """The server returns 0.0 for a document it has already converted. That
    is free, but kennis does not know whether it was a cache hit or an
    allowance, so it says only what it was told."""
    from kennis.render.words import conversion_cost

    assert conversion_cost(0.0) == "no charge"


def test_a_sub_dollar_cost_stays_in_cents():
    """A 19-page paper is 7.6 cents. Rendering that as `$0.08` would round
    away the only digits that vary."""
    from kennis.render.words import conversion_cost

    assert conversion_cost(7.6) == "7.6c"
    assert conversion_cost(0.4) == "0.4c"


def test_a_cost_of_a_dollar_or_more_is_shown_in_dollars():
    from kennis.render.words import conversion_cost

    assert conversion_cost(100.0) == "$1.00"
    assert conversion_cost(813.0) == "$8.13"


def test_a_half_cent_rounds_to_even_rather_than_up():
    """Python's format rounds half to even, so 812.5c is `$8.12` and not
    `$8.13`. Pinned rather than corrected: this is a displayed figure, and
    reaching for `Decimal` to move a half cent would be a real dependency
    bought for nothing. If kennis ever bills from this number, revisit."""
    from kennis.render.words import conversion_cost

    assert conversion_cost(812.5) == "$8.12"
    assert conversion_cost(837.5) == "$8.38"
