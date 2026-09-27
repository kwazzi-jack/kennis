"""The `instructions=` block, half written and half generated.

Design section 11. The generic half explains the collections and how the
tools relate; the generated half names what *this* installation holds,
from each installed pack's `name` and `description`. Two properties are
worth more than the prose and are what these tests hold to:

- the block adapts to the machine rather than claiming knowledge that is
  not there, so a bare install must not read as though it has packs;
- the holdings lines are the same bytes `kennis pack list` prints, so
  what a user reads and what a model reads cannot drift.

It costs tokens on every session, so its shape is a deliberate decision
rather than something folded into an unrelated change - which is the
reason the length is asserted at all.
"""

from __future__ import annotations

from kennis.engine.pack.installed import InstalledPack
from kennis.engine.pack.schema import KennisHeader, Pack, PackIdentity
from kennis.engine.pack.store import PackState
from kennis.mcp.instructions import instructions_for
from kennis.render.packs import describe_holdings

DIGEST = "a" * 64


def holding(
    identifier: str, name: str, description: str | None = None
) -> InstalledPack:
    return InstalledPack(
        state=PackState(
            pack_id=identifier,
            pack_version="1.0.0",
            schema_version=1,
            file_sha256=DIGEST,
            files={"notes/one.md": DIGEST},
            first_applied_at="2026-01-01T00:00:00Z",
            applied_at="2026-01-01T00:00:00Z",
            applied_by="0.3",
            source_path="/provider/p.ken.yml",
        ),
        declaration=Pack(
            kennis=KennisHeader(schema_version=1),
            pack=PackIdentity(
                id=identifier, name=name, version="1.0.0", description=description
            ),
        ),
        verified=True,
    )


def test_a_bare_install_says_it_holds_nothing():
    """The failure this exists to catch is a block that describes packs
    in the abstract on a machine that has none, which invites an agent to
    search a corpus that cannot answer."""
    said = instructions_for(())

    assert "holds no packs" in said
    assert "stimela" not in said


def test_an_installed_pack_is_named_in_the_block():
    said = instructions_for(
        (holding("boepie", "stimela pipelines", "Radio interferometry reduction."),)
    )

    assert "## What this kennis holds" in said
    assert "  stimela pipelines - Radio interferometry reduction." in said


def test_the_holdings_are_the_bytes_pack_list_prints():
    """Section 11's claim, as a test rather than as a sentence in a
    design document. Both sides call `describe_holdings`; if one ever
    grows its own formatting this fails."""
    packs = (
        holding("boepie", "stimela pipelines", "Radio interferometry."),
        holding("alpha", "Alpha", None),
    )

    said = instructions_for(packs)

    for line in describe_holdings(packs):
        assert line in said


def test_every_generic_claim_survives_having_no_packs():
    """The generic half is about kennis itself - the collections, the
    surrogate ids, what `search_context` returns - and none of it depends
    on a pack being installed."""
    bare = instructions_for(())

    for claim in ("notes", "literature", "docs", "context", "list_corpus"):
        assert claim in bare


def test_the_block_says_an_id_is_copied_and_never_constructed():
    """A surrogate id is opaque. An agent that builds one from a title or
    a citekey gets a miss it cannot diagnose, so the block says so."""
    said = instructions_for(())

    assert "document_id" in said
    assert "never construct" in said.lower()


def test_the_block_stays_within_its_token_budget():
    """It is sent on every session. This is not a style rule: the number
    is a budget, and a change that doubles it should be a decision
    someone took rather than a diff nobody measured."""
    said = instructions_for(
        tuple(holding(f"p{index}", f"Pack {index}", "x" * 500) for index in range(5))
    )

    assert len(said) < 8000, f"the block is {len(said)} characters"
