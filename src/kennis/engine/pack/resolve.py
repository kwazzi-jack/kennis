"""Section 5 step 4: what to do with one item, given what is on disk.

A diff says what a declaration did; it does not say what to do. This
module is the table that does, and it is a **pure function over values**:
nothing here opens a file. That is what makes all of it testable, and the
design's insistence that the table has no fall-through row is only worth
having if every row can be exercised.

**The declarations arriving here are already a union** (step 6). Two packs
declaring one address were resolved to the incumbent - the earliest
`first_applied_at` - before this function sees them, so "declared" here
means "declared by whichever pack owns the address", never "declared by
the pack we happen to be installing".

**Leaving something alone is reported, never silent.** An item the user
owns is reported on every run, not only on the run where the declaration
moved. The archived defect this exists for: both reconcilers used to
`continue` past a user-owned document without counting it, so a manifest
entry the machine owned appeared nowhere - `sync` said nothing and
`status` called the project "not fetched yet".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from kennis.engine.corpus.schema import pack_id_of

type Verdict = Literal[
    # Declared and not there.
    "write",
    # Declared, ours, and nothing moved.
    "keep",
    # Declared, ours, the pack shipped a change, the body is untouched.
    "rewrite",
    # Declared, and the file belongs to a pack that no longer declares it.
    "adopt",
    # The body is not what kennis wrote. Never overwritten, never deleted.
    "edited",
    # Declared, and the user owns it.
    "yours",
    # No longer declared by anyone, and a pack owns it.
    "delete",
    # An `owner` kennis does not recognise. Corruption, not a case.
    "refuse",
]

# Verdicts that change the destination. Named so a caller can ask "is
# there anything to do" without listing them again and getting it wrong.
ACTING: frozenset[Verdict] = frozenset({"write", "rewrite", "adopt", "delete"})


@dataclass(frozen=True, slots=True)
class Declaration:
    """One item the union of installed packs declares, and where to read it.

    `digest` is the pack file's digest **in the store**, which is what
    `state.json` recorded when the pack was added. Comparing it against
    the digest the destination file records is how a pack change is told
    from a user edit.
    """

    address: str
    pack_id: str
    digest: str
    # Where to read the content from, for a section the store holds.
    # None for a declaration a fetch resolves - a paper or a
    # documentation project - where the digest is of the declaration's
    # own fields and there are no bytes until something is fetched.
    store_path: Path | None


@dataclass(frozen=True, slots=True)
class Existing:
    """One item already at the destination, as the file describes itself.

    No state file is involved, and that is deliberate: a bundle lives in a
    repository kennis does not own, so anything kennis needs to know about
    a file it wrote has to be in the file.

    **Three digests, because there are two independent questions and one
    of them needs both sides.**

    - `body_digest` is the body on disk, digested now, and
      `written_digest` is what kennis recorded writing. The two apart
      mean the user has typed.
    - `pack_digest` is the store file this was built from. It apart from
      the declaration's digest means the provider shipped a change.

    Two fields cannot do it. A pack file carrying its own frontmatter is
    not written verbatim - its header is read and replaced - so the body
    kennis wrote and the file the store holds have different digests, and
    a single recorded value would compare correctly against one of them
    and wrongly against the other. Recording only the body's digest makes
    every such file read as changed on every run and rewrites it forever;
    recording only the store's makes a user edit invisible.

    `owner` is None when the frontmatter could not be read at all. The two
    recorded digests are None for a file kennis did not write as a pack's
    - a note the user remembered, for instance - and are never consulted
    for one, because `owner` has already decided the row.
    """

    address: str
    owner: str | None
    body_digest: str
    written_digest: str | None
    pack_digest: str | None


@dataclass(frozen=True, slots=True)
class Action:
    """One address, and what converging it means.

    Both sides are carried rather than only the verdict, because the
    caller writes from `declaration` and reports from `existing`, and a
    renderer asking "who owned it before" would otherwise have to look it
    up again.
    """

    address: str
    verdict: Verdict
    declaration: Declaration | None
    existing: Existing | None


def resolve(
    declared: dict[str, Declaration], present: dict[str, Existing]
) -> tuple[Action, ...]:
    """One action per address on either side, ordered by address.

    Exactly one: two actions for an address would make the order of writes
    decide the outcome, and none would leave a file nobody looked at.
    Ordered so that two runs doing the same thing print the same report.
    """
    addresses = sorted(set(declared) | set(present))
    actions = [
        _action(address, declared.get(address), present.get(address))
        for address in addresses
    ]
    return tuple(action for action in actions if action is not None)


def _action(
    address: str, declaration: Declaration | None, existing: Existing | None
) -> Action | None:
    """The row of section 5 step 4 that this combination falls in.

    Returns None for the one combination that is not kennis's business: a
    file the user owns that no pack declares, which is most of a bundle.
    Reporting those as "left alone" would bury the line that matters.
    """
    if existing is None:
        # `declaration` cannot also be None: the address came from one of
        # the two maps.
        assert declaration is not None
        return Action(address, "write", declaration, None)

    owner = _owner_of(existing)
    if owner is None:
        return Action(address, "refuse", declaration, existing)

    if owner == "user":
        if declaration is None:
            return None
        return Action(address, "yours", declaration, existing)

    if _was_edited(existing):
        # Before every other pack-owned row, and before the delete in
        # particular. The design writes step 4a's protection only for a
        # `changed` item; a `removed` one is the more expensive mistake,
        # because there is no next release to put the file back. Concern
        # #272.
        return Action(address, "edited", declaration, existing)

    if declaration is None:
        return Action(address, "delete", None, existing)
    if owner != declaration.pack_id:
        return Action(address, "adopt", declaration, existing)
    if existing.pack_digest != declaration.digest:
        return Action(address, "rewrite", declaration, existing)
    return Action(address, "keep", declaration, existing)


def _owner_of(existing: Existing) -> str | None:
    """`user`, a pack id, or None when the value is not one kennis knows.

    Section 6: an unrecognised value is corruption rather than a
    compatibility case. A document carrying the old `managed_by:
    boepie`, or an `owner` from a newer vocabulary, is refused with the
    document named - kennis does not guess, does not silently treat it as
    `user`, and ships no migration.
    """
    if existing.owner is None:
        return None
    if existing.owner == "user":
        return "user"
    return pack_id_of(existing.owner)


def _was_edited(existing: Existing) -> bool:
    """Whether the body is something other than what kennis last wrote.

    The body on disk against the body kennis recorded writing. Equal
    until somebody types.
    """
    if existing.written_digest is None:
        return False
    return existing.body_digest != existing.written_digest


__all__ = [
    "ACTING",
    "Action",
    "Declaration",
    "Existing",
    "Verdict",
    "resolve",
]
