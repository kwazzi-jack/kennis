"""`context sync`: a project's bundle holds a copy of each declared pack's
context (Brian, 2026-11-06, #624, reversing #513).

A project declares the packs it uses in `bundle.json`; a sync copies each
one's `context:` files into the bundle, at the address the pack declares,
and the project indexes and searches them as its own files. Nothing reaches
a project except through its own sync, so a pack release changes a
repository only when the person asks, and the change is a diff they read.

**Who owns a file is in its header, and decides everything.** `pack_id_of`
on `owner:`; `pack/resolve.py` is the table, shared with `corpus sync`:

- **`owner: user` is never touched.** Taking a pack's file as one's own is
  deliberate: the person changes its owner, and no release reaches it again.
- **A pack's copy somebody typed in is never overwritten or removed**
  (`edited`). The way out is said: set the owner, or delete the file to
  take the pack's.
- **A pack the project no longer declares leaves its copies** where they
  are (`undeclared`). Removing them is a choice made at a sync,
  `remove_undeclared`, and even then an edited copy stays.
- **A copy of a pack the project declares and this machine has not
  installed is left alone**, removal asked or not: the declaration is
  committed, and whoever has the pack relies on the copy this machine
  cannot rebuild.

**The bundle needs no state file, because every file answers for itself.**
What kennis wrote is `source.sha256`, what it was built from is
`source.pack_sha256`, and where the pack declared it is `source.address`,
so a copy the person moved is followed rather than written again.

**Nothing is written until everything has been judged** (`plan_sync`,
which the window's dialog shows). A destination a bundle reserves and an
owner kennis does not recognise are refused before the first write.

**kennis does not commit.** The bundle is in the person's repository.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from kennis.engine.atomic import remove_file, replace_file
from kennis.engine.context.bundle import LANDING_FILENAME, declared_packs
from kennis.engine.context.notes import bundle_files
from kennis.engine.context.projects import note_project
from kennis.engine.corpus.schema import pack_id_of
from kennis.engine.errors import DocumentInvalid, PackInvalid
from kennis.engine.events import EventSink, ItemFinished, OperationFinished, Outcome
from kennis.engine.frontmatter import join_frontmatter, split_frontmatter
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.installed import (
    InstalledPack,
    declared_content,
    list_installed,
    refuse_damaged_packs,
)
from kennis.engine.pack.resolve import Action, Declaration, Existing, resolve
from kennis.engine.refusals import Quoted

OPERATION = "context-sync"


@dataclass(frozen=True, slots=True)
class BundleSync:
    """What one `context sync` did, or would do (`plan_sync`).

    Addresses are relative to the bundle, as the pack declares them.

    - `written`: a declared file the bundle did not have.
    - `updated`: a copy nobody edited, replaced by the pack's new release
      or by the pack that now declares its address.
    - `unchanged`: how many copies were already the pack's current text.
    - `yours`: a declared address whose file the person owns, left alone.
    - `edited`: a pack's copy somebody typed in, left alone.
    - `undeclared`: an unedited copy of a pack the project no longer
      declares, kept because no removal was asked for.
    - `removed`: such copies, removed because it was.
    - `moved`: `(address, where it is)` for a copy found elsewhere.
    - `deferred`: `(address, pack)` where two declared packs ship one
      address and the first installed keeps it.
    - `declared` / `missing`: the declared packs this machine has and has
      not; `available` the installed packs, only for a project that
      declares none.
    """

    written: tuple[str, ...]
    updated: tuple[str, ...]
    unchanged: int
    yours: tuple[str, ...]
    edited: tuple[str, ...]
    undeclared: tuple[str, ...]
    removed: tuple[str, ...]
    moved: tuple[tuple[str, str], ...]
    deferred: tuple[tuple[str, str], ...]
    declared: tuple[str, ...]
    missing: tuple[str, ...]
    available: tuple[str, ...]

    @property
    def changed_anything(self) -> bool:
        return bool(self.written or self.updated or self.removed)


@dataclass(frozen=True, slots=True)
class _Judged:
    """Every action, where each file is, and the declaration's split."""

    actions: tuple[Action, ...]
    locations: dict[str, Path]
    deferred: tuple[tuple[str, str], ...]
    declared: tuple[str, ...]
    missing: tuple[str, ...]
    available: tuple[str, ...]


def plan_sync(
    bundle: Path, corpus_root: Path, *, remove_undeclared: bool = False
) -> BundleSync:
    """What `sync_bundle` would do, with nothing written."""
    judged = _judged(bundle, corpus_root)
    return _summary(bundle, judged, remove_undeclared=remove_undeclared)


def sync_bundle(
    bundle: Path,
    corpus_root: Path,
    *,
    remove_undeclared: bool = False,
    events: EventSink | None = None,
) -> BundleSync:
    """Copy each declared pack's context into the bundle, by the rules in
    the module docstring.

    Raises `PackInvalid` for a destination a bundle reserves and
    `DocumentInvalid` for an owner kennis does not recognise, both before
    anything is written.
    """
    note_project(bundle)
    started = time.monotonic()
    judged = _judged(bundle, corpus_root)
    summary = _summary(bundle, judged, remove_undeclared=remove_undeclared)
    removing = set(summary.removed)
    for action in judged.actions:
        if action.verdict == "delete" and action.address not in removing:
            continue
        _applied(bundle, action, judged.locations)
    _reported(events, summary, started)
    return summary


def _judged(bundle: Path, corpus_root: Path) -> _Judged:
    declared = declared_packs(bundle)
    held = {one.state.pack_id: one for one in list_installed(corpus_root).packs}
    packs: tuple[InstalledPack, ...] = tuple(
        held[pack] for pack in declared if pack in held
    )
    refuse_damaged_packs(packs)
    union = declared_content(corpus_root, packs, "context")
    declarations = {
        address: declaration
        for address, declaration in union.declarations.items()
        if address.endswith(".md")
    }
    _refuse_reserved_destinations(declarations)
    present, locations = _present(bundle)
    actions = resolve(declarations, present)
    _refuse_unrecognised_owners(actions)
    return _Judged(
        actions=actions,
        locations=locations,
        deferred=union.deferred,
        declared=tuple(pack.state.pack_id for pack in packs),
        missing=tuple(pack for pack in declared if pack not in held),
        available=() if declared else tuple(sorted(held)),
    )


def _summary(bundle: Path, judged: _Judged, *, remove_undeclared: bool) -> BundleSync:
    by_verdict: dict[str, list[str]] = {}
    for action in judged.actions:
        verdict = str(action.verdict)
        if verdict == "delete" and _of_a_missing_pack(action, judged.missing):
            # Declared, not installed here: not this machine's to judge.
            verdict = "keep"
        by_verdict.setdefault(verdict, []).append(action.address)
    deletable = tuple(by_verdict.get("delete", ()))
    return BundleSync(
        written=tuple(by_verdict.get("write", ())),
        updated=tuple(
            sorted(by_verdict.get("rewrite", []) + by_verdict.get("adopt", []))
        ),
        unchanged=len(by_verdict.get("keep", ())),
        yours=tuple(by_verdict.get("yours", ())),
        edited=tuple(by_verdict.get("edited", ())),
        undeclared=() if remove_undeclared else deletable,
        removed=deletable if remove_undeclared else (),
        moved=_moved(bundle, judged),
        deferred=judged.deferred,
        declared=judged.declared,
        missing=judged.missing,
        available=judged.available,
    )


def _of_a_missing_pack(action: Action, missing: tuple[str, ...]) -> bool:
    owner = action.existing.owner if action.existing is not None else None
    return owner is not None and pack_id_of(owner) in missing


def _moved(bundle: Path, judged: _Judged) -> tuple[tuple[str, str], ...]:
    """Every declared copy not at the address its pack declares."""
    return tuple(
        (
            action.address,
            judged.locations[action.address].relative_to(bundle).as_posix(),
        )
        for action in judged.actions
        if action.declaration is not None
        and action.address in judged.locations
        and judged.locations[action.address] != bundle / action.address
    )


def _refuse_reserved_destinations(declarations: dict[str, Declaration]) -> None:
    """Two destinations a pack may not have, and why each is reserved.

    **A dot-prefixed path is never indexed or searched**, at any depth:
    that is how a person keeps a file out of the index, so a pack shipping
    one would land a file nothing ever finds (#247, #267). **`LANDING.md`**
    is the entry point an agent reads first, and it is the person's.
    """
    reserved = sorted(
        address
        for address in declarations
        if any(part.startswith(".") for part in Path(address).parts)
        or Path(address).name == LANDING_FILENAME
    )
    if reserved:
        raise PackInvalid(
            "a pack declares a destination a bundle reserves, so nothing has "
            f"been written: {', '.join(reserved)}",
            resolution=None,
        )


def _refuse_unrecognised_owners(actions: tuple[Action, ...]) -> None:
    """An unrecognised `owner` is corruption, not a case: every one is
    named at once."""
    named = [action.address for action in actions if action.verdict == "refuse"]
    if named:
        raise DocumentInvalid(
            "these files carry an owner kennis does not recognise, so nothing "
            f"has been written: {', '.join(named)}"
        )


def _present(bundle: Path) -> tuple[dict[str, Existing], dict[str, Path]]:
    """Every bundle file, keyed by the address it stands for, and where it is.

    **Wider than what the bundle indexes**: a file the person hid behind a
    dot is still a file kennis wrote (#247). **A pack's copy is keyed by the
    address it records**, so a moved copy is followed; a recorded address is
    honoured only when no file sits at it and no earlier file claimed it,
    which keeps every key distinct however many copies a person makes.

    A header kennis cannot read makes the file the person's, as `context
    reset` documents: keeping a pack's file costs a stale copy, deleting a
    person's costs their writing.
    """
    files = bundle_files(bundle)
    occupied = {path.relative_to(bundle).as_posix() for path in files}
    found: dict[str, Existing] = {}
    locations: dict[str, Path] = {}
    for path in files:
        here = path.relative_to(bundle).as_posix()
        text = path.read_text(encoding="utf-8")
        try:
            header, body = split_frontmatter(text)
        except yaml.YAMLError:
            header, body = {"owner": "user"}, text
        written, shipped, recorded = _recorded_in(header)
        claimed = (
            recorded is not None and recorded not in occupied and recorded not in found
        )
        address = recorded if claimed and recorded is not None else here
        owner = header.get("owner")
        found[address] = Existing(
            address=address,
            owner=str(owner) if owner is not None else "user",
            body_digest=content_digest(body.encode("utf-8")),
            written_digest=written,
            pack_digest=shipped,
        )
        locations[address] = path
    return found, locations


def _recorded_in(
    header: dict[str, object],
) -> tuple[str | None, str | None, str | None]:
    """A pack's copy's two digests and its address, from `source:`.

    Read only when `source.via` is `pack`: a remembered note records a
    `sha256` of the text it was given, which means something else.
    """
    source = header.get("source")
    if not isinstance(source, dict) or source.get("via") != "pack":
        return None, None, None
    values = [source.get(key) for key in ("sha256", "pack_sha256", "address")]
    written, shipped, address = (
        str(value) if value is not None else None for value in values
    )
    return written, shipped, address


def _applied(bundle: Path, action: Action, locations: dict[str, Path]) -> None:
    """Carry out one action, where the file was found rather than at the
    declared address, so a moved copy is updated in place."""
    path = locations.get(action.address, bundle / action.address)
    if action.verdict == "delete":
        remove_file(path)
        _prune(bundle, path.parent)
        return
    if action.verdict not in {"write", "rewrite", "adopt"}:
        return
    declaration = action.declaration
    assert declaration is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_file(path, _document(declaration))


def _prune(bundle: Path, directory: Path) -> None:
    """Remove a directory a removal emptied, and its empty parents, up to
    the bundle; one holding anything at all is left."""
    while directory != bundle and directory.is_dir():
        if any(directory.iterdir()):
            return
        directory.rmdir()
        directory = directory.parent


def _document(declaration: Declaration) -> str:
    """The copy as it lands: the pack's body under a header kennis writes.

    The pack's own `title` and `description` are read and its header
    replaced, never nested. Two digests: `sha256` of the body written, which
    a person's typing moves, and `pack_sha256` of the store file, which a
    release moves; with one, a pack file carrying its own header would
    digest differently from its copy and be rewritten on every run.
    """
    assert declaration.store_path is not None
    shipped, body = split_frontmatter(
        declaration.store_path.read_text(encoding="utf-8")
    )
    return join_frontmatter(
        {
            "title": shipped.get("title") or Path(declaration.address).stem,
            "description": shipped.get("description") or "",
            "owner": f"pack:{declaration.pack_id}",
            "source": {
                "via": "pack",
                "pack": declaration.pack_id,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
                "address": declaration.address,
                "sha256": content_digest(body.encode("utf-8")),
                "pack_sha256": declaration.digest,
            },
        },
        body,
    )


def _reported(events: EventSink | None, summary: BundleSync, started: float) -> None:
    if events is None:
        return
    counts: Counter[Outcome] = Counter()
    for addresses, outcome, verdict in (
        (summary.written, Outcome.ADDED, "written"),
        (summary.updated, Outcome.CHANGED, "updated"),
        (summary.removed, Outcome.REMOVED, "removed"),
        (summary.edited, Outcome.SKIPPED, "edited, left as it is"),
        (summary.yours, Outcome.SKIPPED, "yours"),
        (summary.undeclared, Outcome.SKIPPED, "no longer declared, kept"),
    ):
        for address in addresses:
            counts[outcome] += 1
            events.emit(
                ItemFinished(
                    operation=OPERATION,
                    item=address,
                    outcome=outcome,
                    refusal=Quoted(verdict),
                )
            )
    events.emit(
        OperationFinished(
            operation=OPERATION,
            elapsed_seconds=time.monotonic() - started,
            counts=dict(counts),
        )
    )


__all__ = ["OPERATION", "BundleSync", "plan_sync", "sync_bundle"]
