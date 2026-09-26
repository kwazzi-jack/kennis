"""Reading the pack store, and removing from it. Design sections 5, 8 and 9.

`pack add` writes a store and nothing could look at it. This module is the
reading half: what is installed, what each pack recorded, whether the
store still holds what it says it holds, and which two packs declare the
same item.

**The overlap is persistent state, not a line printed once.** Section 5
step 4 is explicit about it: an overlap mentioned inside an automated
`provider sync` that nobody is reading is close to silence, so it belongs
to `pack status`, which a user runs when they want to know. The incumbent
is the pack with the earliest `first_applied_at`, which is immutable -
`applied_at` cannot serve, because a provider calls `pack add` on every
run and most-recent-wins would flip ownership in a loop.

**Removing reaches the store and nothing else.** Section 9: kennis keeps
no registry of the projects a user has, so `pack remove` cannot clean
`.context/` in N checkouts, and those converge on their own next sync.
Corpus documents are the same: this module drops the declaration, and
converging the documents with what is left is a sync's job.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from kennis.engine.errors import PackInvalid, PackNotInstalled
from kennis.engine.events import EventSink, ItemFinished, OperationFinished, Outcome
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.resolve import Declaration
from kennis.engine.pack.schema import ContentSource, LiteratureEntry, Pack, load_pack
from kennis.engine.pack.store import (
    DECLARATION_FILENAME,
    PackState,
    pack_root,
    packs_root,
    read_state,
)

OPERATION: Final = "pack-remove"

type OverlapKind = Literal["literature", "docs", "notes", "context"]

# The two sections whose content is copied. `literature` and `docs` are
# declarations that a fetch resolves, not content a sync copies.
type ContentSectionName = Literal["notes", "context"]

# The identity of one declared item, as the section it belongs to and the
# key section 5 step 3 gives that section.
type ItemKey = tuple[OverlapKind, str]


@dataclass(frozen=True, slots=True)
class InstalledPack:
    """One pack in the store, with the two facts reading it can add.

    `declaration` is the `pack.ken.yml` kennis copied, parsed back. None
    when it will not parse, which is corruption of a file kennis wrote
    itself rather than a pack that was always wrong.

    `verified` is the fourth fast-path condition, asked here for reporting
    rather than for a decision: `pack status` is where a user should find
    out the store is damaged, before a sync reads an empty store as a
    declaration that the pack now ships nothing.
    """

    state: PackState
    declaration: Pack | None
    verified: bool


@dataclass(frozen=True, slots=True)
class PackListing:
    """Every pack in the store, and every directory that is not one.

    `unreadable` holds the directory names under `packs/` with no state
    file that parses - a half-written store. Reported rather than skipped:
    a pack that `add` will rewrite and `list` says is absent is the state
    hardest to reason about from outside.
    """

    packs: tuple[InstalledPack, ...]
    unreadable: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Overlap:
    """One item two or more installed packs both declare.

    `owner` is the incumbent: the earliest `first_applied_at`, ties broken
    by pack id so two runs give the same answer.
    """

    kind: OverlapKind
    key: str
    pack_ids: tuple[str, ...]
    owner: str


@dataclass(frozen=True, slots=True)
class PackRemoval:
    """What `remove_pack` dropped.

    `recorded` is False for a partial install - a directory whose state
    file was gone - where `files` is 0 because nothing said what was
    there, not because nothing was. Reporting the two the same way would
    tell a user their store was empty when it was unreadable.
    """

    pack_id: str
    files: int
    recorded: bool


def list_installed(corpus_root: Path) -> PackListing:
    """Every pack under `packs/`, sorted by id.

    Sorted so two runs print the same order; a listing whose order came
    from the filesystem would make a diff of two runs unreadable.
    """
    root = packs_root(corpus_root)
    if not root.is_dir():
        return PackListing(packs=(), unreadable=())

    packs: list[InstalledPack] = []
    unreadable: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        state = read_state(corpus_root, child.name)
        if state is None:
            unreadable.append(child.name)
            continue
        packs.append(
            InstalledPack(
                state=state,
                declaration=_declaration(corpus_root, child.name),
                verified=_verifies(corpus_root, state),
            )
        )
    return PackListing(packs=tuple(packs), unreadable=tuple(unreadable))


def _declaration(corpus_root: Path, pack_id: str) -> Pack | None:
    path = pack_root(corpus_root, pack_id) / DECLARATION_FILENAME
    try:
        return load_pack(path.read_text(encoding="utf-8"))
    except (OSError, PackInvalid):
        return None


def _verifies(corpus_root: Path, state: PackState) -> bool:
    """Every recorded path present with its digest. Section 5, step 2 (4)."""
    root = pack_root(corpus_root, state.pack_id)
    for relative, digest in state.files.items():
        try:
            if content_digest((root / relative).read_bytes()) != digest:
                return False
        except OSError:
            return False
    return True


def overlaps_between(packs: tuple[InstalledPack, ...]) -> tuple[Overlap, ...]:
    """Every item declared by more than one of these packs.

    Keyed by section 5 step 3's diff key, because that is what makes two
    declarations the same *item* rather than two similar-looking lines.
    A pack declaring something twice is not an overlap with itself: the
    question is which pack owns an item, and there is only one pack.
    """
    claimed: dict[ItemKey, list[str]] = {}
    for one in packs:
        if one.declaration is None:
            # Nothing can be said about what a pack declares when the
            # declaration will not parse. The pack is still listed, and
            # `status` reports the corruption separately.
            continue
        for item in sorted(_declared_items(one)):
            owners = claimed.setdefault(item, [])
            if one.state.pack_id not in owners:
                owners.append(one.state.pack_id)

    found: list[Overlap] = []
    for (kind, key), owners in claimed.items():
        if len(owners) < 2:
            continue
        found.append(
            Overlap(
                kind=kind,
                key=key,
                pack_ids=tuple(sorted(owners)),
                owner=_incumbent(packs, owners),
            )
        )
    return tuple(sorted(found, key=lambda one: (one.kind, one.key)))


def _incumbent(packs: tuple[InstalledPack, ...], owners: list[str]) -> str:
    """The earliest `first_applied_at` among these packs, ties by id.

    Immutable by construction, which is the whole reason it and not
    `applied_at` decides this. Section 5, step 4.
    """
    stamps = {
        one.state.pack_id: one.state.first_applied_at
        for one in packs
        if one.state.pack_id in owners
    }
    return min(owners, key=lambda pack_id: (stamps[pack_id], pack_id))


def _declared_items(one: InstalledPack) -> set[ItemKey]:
    """Every item this pack declares, as its cross-pack identity.

    Content is keyed on **where it lands**, not on where it came from:
    two packs whose source directories are named differently still
    collide when a file ends up at the same address, and two packs
    shipping the same filename into different `group:`s do not.

    The design words this as "(section, source index, relative path)".
    The source index cannot be part of a cross-pack identity - pack A's
    first source and pack B's first source are unrelated - so it is read
    here as an intra-pack detail of the diff, and the identity is the
    destination the address resolves to. Concern #270.
    """
    declaration = one.declaration
    assert declaration is not None
    items: set[ItemKey] = set()
    for entry in declaration.corpus.literature:
        items.add(("literature", _literature_key(entry)))
    for docs in declaration.corpus.docs:
        items.add(("docs", docs.project))
    for source in declaration.corpus.notes:
        for address, _ in _destinations(one.state, source):
            items.add(("notes", address))
    for source in declaration.context:
        for address, _ in _destinations(one.state, source):
            items.add(("context", address))
    return items


def _literature_key(entry: LiteratureEntry) -> str:
    """`arxiv_id`, else `doi`, else `bibcode`, and never the citekey.

    Section 5 step 3: keying on the citekey would make correcting
    `paperCubicalFast` to `kenyonCubicalFast2018` come out as a removal
    and an addition, deleting a fetched document and pulling the identical
    paper down again. The scheme is part of the key so a DOI and an arXiv
    id that happen to share a string cannot collide.
    """
    if entry.arxiv_id is not None:
        return f"arxiv:{entry.arxiv_id}"
    if entry.doi is not None:
        return f"doi:{entry.doi}"
    return f"bibcode:{entry.bibcode}"


def _destinations(state: PackState, source: ContentSource) -> list[tuple[str, str]]:
    """Where each file under one declared source lands, and where it is now.

    Returns `(address, recorded)` pairs: the destination the file
    converges to, and its key in `state.files`, which is both its path
    under `packs/<id>/` and the handle on its digest.

    Read from `state.files`, which is the store's own record of what was
    copied, rather than by walking the pack again: the declaration and the
    store can disagree, and what the pack *installed* is what a sync will
    act on.
    """
    prefix = source.source.strip("/")
    group = source.group.strip("/") if source.group else ""
    addresses: list[tuple[str, str]] = []
    for recorded in state.files:
        if not recorded.startswith(f"{prefix}/"):
            continue
        relative = recorded[len(prefix) + 1 :]
        addresses.append((f"{group}/{relative}" if group else relative, recorded))
    return addresses


@dataclass(frozen=True, slots=True)
class DeclaredContent:
    """Every address the installed packs declare for one section.

    Section 5 step 6: a sync converges with the **union** of every
    installed pack's declarations, not with one pack against disk. So
    `pack remove A` for an item B also declares leaves B's declaration
    standing, and the next sync re-materialises the document as B's.

    `deferred` holds the `(address, pack_id)` pairs that lost: they are
    not an error, and a reader is owed them, because a provider whose
    content never appears has no other way to find out why.
    """

    declarations: dict[str, Declaration]
    deferred: tuple[tuple[str, str], ...]


def refuse_damaged_packs(packs: tuple[InstalledPack, ...]) -> None:
    """A damaged pack is not a pack that ships nothing. Section 5, step 2a.

    **Every sync calls this before reading a union**, and it is here
    rather than in either destination because the failure it prevents is
    the same one twice: a store whose content is gone, or whose stored
    declaration will not parse, declares nothing that can be read - so
    every document the pack owns looks undeclared, takes the delete row,
    and is removed, with the report saying `removed` and nothing naming
    the cause.

    "The store says N files and disk has 0" is corruption, never a
    declaration that the pack now ships nothing. Refusing is an
    acceptable outcome; proceeding to delete is not. Concern #274.
    """
    damaged = sorted(
        one.state.pack_id
        for one in packs
        if not one.verified or one.declaration is None
    )
    if not damaged:
        return
    raise PackInvalid(
        "the store is damaged for these packs, so nothing has been "
        f"synchronised: {', '.join(damaged)}",
        resolution="kennis pack status",
    )


def declared_content(
    corpus_root: Path, packs: tuple[InstalledPack, ...], section: ContentSectionName
) -> DeclaredContent:
    """The union of every installed pack's content for one section.

    One declaration per address, belonging to the incumbent - the earliest
    `first_applied_at`, the same rule `pack status` reports, and immutable
    so that re-adding a pack never changes who owns anything.
    """
    ordered = sorted(
        packs, key=lambda one: (one.state.first_applied_at, one.state.pack_id)
    )
    declarations: dict[str, Declaration] = {}
    deferred: list[tuple[str, str]] = []
    for one in ordered:
        if one.declaration is None:
            # A pack whose stored declaration will not parse declares
            # nothing that can be acted on. `pack status` reports the
            # corruption; a sync must not guess at what it wanted.
            continue
        sources = (
            one.declaration.corpus.notes
            if section == "notes"
            else one.declaration.context
        )
        for source in sources:
            for address, recorded in _destinations(one.state, source):
                if address in declarations:
                    deferred.append((address, one.state.pack_id))
                    continue
                declarations[address] = Declaration(
                    address=address,
                    pack_id=one.state.pack_id,
                    digest=one.state.files[recorded],
                    store_path=pack_root(corpus_root, one.state.pack_id) / recorded,
                )
    return DeclaredContent(declarations=declarations, deferred=tuple(sorted(deferred)))


def remove_pack(
    corpus_root: Path, pack_id: str, *, events: EventSink | None = None
) -> PackRemoval:
    """Drop one pack from the store.

    Raises `PackNotInstalled` when there is no such directory. A partial
    install - a directory whose state file is gone - is removable, because
    removing is how a user gets out of that state.

    **The corpus documents and every workspace are untouched**, and the
    command line says so. Section 9.
    """
    started = time.monotonic()
    root = pack_root(corpus_root, pack_id)
    if not root.is_dir():
        raise PackNotInstalled(f"no pack called '{pack_id}' is installed")

    state = read_state(corpus_root, pack_id)
    shutil.rmtree(root)
    _reported(events, pack_id, started)
    return PackRemoval(
        pack_id=pack_id,
        files=len(state.files) if state is not None else 0,
        recorded=state is not None,
    )


def _reported(events: EventSink | None, pack_id: str, started: float) -> None:
    if events is None:
        return
    events.emit(
        ItemFinished(operation=OPERATION, item=pack_id, outcome=Outcome.REMOVED)
    )
    events.emit(
        OperationFinished(
            operation=OPERATION,
            elapsed_seconds=time.monotonic() - started,
            counts={Outcome.REMOVED: 1},
        )
    )


__all__ = [
    "OPERATION",
    "ContentSectionName",
    "DeclaredContent",
    "InstalledPack",
    "ItemKey",
    "Overlap",
    "OverlapKind",
    "PackListing",
    "PackRemoval",
    "declared_content",
    "list_installed",
    "overlaps_between",
    "refuse_damaged_packs",
    "remove_pack",
]
