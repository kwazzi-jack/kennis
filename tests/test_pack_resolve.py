"""Section 5 step 4: what to do with each item, given what is on disk.

The table has eleven rows and **no fall-through case**, which is the
property worth testing: a combination with no row is how one implementer
picks "leave alone, leak orphans forever" and another picks "treat as
ours, overwrite on upgrade". So every row gets a test, and one test
asserts the set of verdicts is closed.

Pure functions over values. Nothing here opens a file, which is the reason
all eleven rows can be written at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kennis.engine.pack.resolve import (
    Action,
    Declaration,
    Existing,
    Verdict,
    resolve,
)

MINE = "pack:alpha"
THEIRS = "pack:beta"
# The store file a document was built from, and the body kennis wrote out
# of it. Deliberately different: a pack file carrying its own frontmatter
# has that header replaced, so the two are not the same bytes and one
# recorded digest cannot answer both questions.
PACK_DIGEST = "a" * 64
NEW_PACK_DIGEST = "b" * 64
WRITTEN_DIGEST = "c" * 64
EDITED_BODY_DIGEST = "d" * 64


def declared(
    address: str = "one.md",
    *,
    pack_id: str = "alpha",
    digest: str = PACK_DIGEST,
) -> dict[str, Declaration]:
    return {
        address: Declaration(
            address=address,
            pack_id=pack_id,
            digest=digest,
            store_path=Path("/store") / address,
        )
    }


def present(
    address: str = "one.md",
    *,
    owner: str | None = MINE,
    body_digest: str = WRITTEN_DIGEST,
    written_digest: str | None = WRITTEN_DIGEST,
    pack_digest: str | None = PACK_DIGEST,
) -> dict[str, Existing]:
    return {
        address: Existing(
            address=address,
            owner=owner,
            body_digest=body_digest,
            written_digest=written_digest,
            pack_digest=pack_digest,
        )
    }


def verdicts(actions: tuple[Action, ...]) -> list[str]:
    return [action.verdict for action in actions]


# ---------------------------------------------------------------------------
# The rows
# ---------------------------------------------------------------------------


def test_a_declared_item_that_is_absent_is_written():
    actions = resolve(declared(), {})

    assert verdicts(actions) == ["write"]


def test_a_declared_item_that_is_there_and_unchanged_is_kept():
    """The common case on every run of a provider that shipped nothing
    new, and the one that must cost nothing."""
    actions = resolve(declared(), present())

    assert verdicts(actions) == ["keep"]


def test_a_declared_item_whose_pack_changed_is_rewritten():
    actions = resolve(declared(digest=NEW_PACK_DIGEST), present())

    assert verdicts(actions) == ["rewrite"]


def test_a_pack_owned_item_the_user_edited_is_not_rewritten():
    """Section 5 step 4a. Without this the realistic behaviour - open a
    pack-shipped note, fix an error, save - is destroyed by the next
    provider release, with the report saying `rewrote`."""
    actions = resolve(
        declared(digest=NEW_PACK_DIGEST),
        present(body_digest=EDITED_BODY_DIGEST),
    )

    assert verdicts(actions) == ["edited"]


def test_an_edit_is_protected_even_when_the_pack_did_not_change():
    """The edit is the fact, not the coincidence of a release. Reported
    every run, so the user is not told once and then forgotten."""
    actions = resolve(declared(), present(body_digest=EDITED_BODY_DIGEST))

    assert verdicts(actions) == ["edited"]


def test_an_item_owned_by_another_pack_is_adopted_by_the_one_declaring_it():
    """Reachable only after the owner stopped declaring it or was removed:
    while both declare it, the union hands the address to the incumbent
    and the incumbent is the owner."""
    actions = resolve(declared(), present(owner=THEIRS))

    assert verdicts(actions) == ["adopt"]


def test_an_item_the_user_owns_is_skipped_and_reported():
    """`user` means yours, never touched by anything."""
    actions = resolve(declared(), present(owner="user"))

    assert verdicts(actions) == ["yours"]


def test_a_user_owned_item_is_reported_on_every_run_not_only_when_it_moves():
    """The archived defect the `yours:` row exists for: both reconcilers
    used to `continue` past a user-owned document without counting it, so
    `sync` said nothing and `status` called the project not fetched."""
    first = resolve(declared(), present(owner="user"))
    second = resolve(declared(), present(owner="user"))

    assert verdicts(first) == verdicts(second) == ["yours"]


def test_an_undeclared_pack_owned_item_is_deleted():
    actions = resolve({}, present())

    assert verdicts(actions) == ["delete"]


def test_an_undeclared_pack_owned_item_the_user_edited_is_kept():
    """Deleting the user's writing is the expensive mistake, and it costs
    more than keeping a file the provider dropped. Not in the design's
    table, which writes step 4a's protection only for `changed`. Concern
    #272."""
    actions = resolve({}, present(body_digest=EDITED_BODY_DIGEST))

    assert verdicts(actions) == ["edited"]


def test_an_undeclared_user_owned_item_is_not_our_business():
    """Most of a bundle. Reporting every file the user wrote as
    "left alone" would bury the one line that matters."""
    actions = resolve({}, present(owner="user"))

    assert actions == ()


def test_an_unreadable_owner_is_refused_and_names_the_file():
    """Section 6: an unrecognised value is corruption, not a
    compatibility case. kennis does not guess."""
    actions = resolve(declared(), present(owner=None))

    assert verdicts(actions) == ["refuse"]
    assert actions[0].address == "one.md"


def test_an_unreadable_owner_on_an_undeclared_file_is_also_refused():
    """A file kennis cannot classify is one a delete might reach."""
    actions = resolve({}, present(owner=None))

    assert verdicts(actions) == ["refuse"]


# ---------------------------------------------------------------------------
# Properties of the table as a whole
# ---------------------------------------------------------------------------


def test_the_verdicts_are_a_closed_set():
    """A combination reaching no row would return something outside this
    set, or nothing at all, and either is the fall-through the design
    forbids."""
    known: set[Verdict] = {
        "write",
        "keep",
        "rewrite",
        "adopt",
        "edited",
        "yours",
        "delete",
        "refuse",
    }
    cases = [
        (declared(), {}),
        (declared(), present()),
        (declared(digest=NEW_PACK_DIGEST), present()),
        (declared(), present(body_digest=EDITED_BODY_DIGEST)),
        (declared(), present(owner=THEIRS)),
        (declared(), present(owner="user")),
        ({}, present()),
        ({}, present(owner="user")),
        ({}, present(owner=None)),
        (declared(), present(owner=None)),
    ]
    for one, other in cases:
        for action in resolve(one, other):
            assert action.verdict in known


def test_every_address_on_either_side_gets_exactly_one_action():
    """Two actions for one address would make the order of writes decide
    the outcome, and none would leave a file nobody looked at."""
    one = {
        **declared("a.md"),
        **declared("b.md"),
    }
    other = {
        **present("b.md"),
        **present("c.md"),
    }

    actions = resolve(one, other)

    assert sorted(action.address for action in actions) == ["a.md", "b.md", "c.md"]


def test_the_actions_are_ordered_by_address():
    """A report whose order came from a dict would differ between runs
    that did the same thing."""
    one = {**declared("z.md"), **declared("a.md"), **declared("m.md")}

    actions = resolve(one, {})

    assert [action.address for action in actions] == ["a.md", "m.md", "z.md"]


def test_a_refusal_is_reported_beside_the_work_rather_than_instead_of_it():
    """`resolve` decides; refusing to act on the whole plan is the
    caller's decision, made once it can see every refusal at once."""
    one = {**declared("a.md"), **declared("b.md")}
    other = present("b.md", owner="bogus")

    actions = resolve(one, other)

    assert verdicts(actions) == ["write", "refuse"]


@pytest.mark.parametrize("owner", ["", "managed_by:boepie", "pack:", "PACK:alpha"])
def test_an_owner_kennis_does_not_recognise_is_refused(owner: str):
    """Including `managed_by`, the field this one replaced: the design
    names it as the example of a value that must not be guessed at."""
    actions = resolve(declared(), present(owner=owner))

    assert verdicts(actions) == ["refuse"]
