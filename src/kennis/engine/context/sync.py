"""`context sync`: a project's bundle against the packs it declares (14g).

A pack's context is searched in the store and never copied into a project
(#513), so there is nothing to converge by writing. A sync does three
things, and two of them only to bundles an earlier kennis copied into:

- **A copy kennis wrote and nobody edited is removed.** The pack's own
  file is searched in its place, from the store.
- **A copy the person edited becomes theirs** (#514): `owner` becomes the
  person and `replaces:` names the pack's file, so this project searches
  the person's version and not the pack's. The body is left as it is.
- **The declaration is reported**: which declared packs this machine has,
  which it has not, and - for a project that declares none - which
  installed packs it could.

**The bundle needs no state file, because every file answers for itself.**
Who owns it is `owner:` in its frontmatter; what kennis wrote is
`source.sha256`; whether the person has typed since is the digest of its
body against that.

**Nothing is written until everything has been judged.** A document whose
`owner` kennis does not recognise is refused before the first write,
because a half-handled bundle is worse than an untouched one.

**kennis does not commit.** The bundle is in the person's repository.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from kennis.engine.atomic import replace_file
from kennis.engine.context.groups import pack_group
from kennis.engine.context.notes import bundle_files
from kennis.engine.context.packs import packs_of
from kennis.engine.context.projects import note_project
from kennis.engine.context.reset import USER_OWNER
from kennis.engine.errors import DocumentInvalid
from kennis.engine.events import EventSink, ItemFinished, OperationFinished, Outcome
from kennis.engine.frontmatter import Frontmatter, join_frontmatter, split_frontmatter
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.installed import list_installed
from kennis.engine.refusals import Quoted

OPERATION = "context-sync"

_PACK_OWNER_PREFIX = "pack:"


@dataclass(frozen=True, slots=True)
class BundleSync:
    """What one `context sync` found and did.

    Addresses are relative to the bundle. `available` is filled only for
    a project that declares no packs, because a project that chose some
    has made its choice and is not to be offered the rest on every run.
    """

    removed: tuple[str, ...]
    made_yours: tuple[str, ...]
    declared: tuple[str, ...]
    missing: tuple[str, ...]
    available: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Copy:
    """A file an earlier kennis copied from a pack into the bundle."""

    path: Path
    address: str
    pack_id: str
    header: Frontmatter
    body: str
    edited: bool


def sync_bundle(
    bundle: Path, corpus_root: Path, *, events: EventSink | None = None
) -> BundleSync:
    """Remove unedited pack copies, make edited ones the person's, and
    report the declaration.

    Raises `DocumentInvalid` when a file carries an `owner` kennis does not
    recognise, before anything is written.
    """
    note_project(bundle)
    started = time.monotonic()
    copies = _pack_copies(bundle)
    removed: list[str] = []
    made_yours: list[str] = []
    for copy in copies:
        if copy.edited:
            replace_file(copy.path, _as_yours(copy))
            made_yours.append(copy.path.relative_to(bundle).as_posix())
        else:
            copy.path.unlink()
            _prune(bundle, copy.path.parent)
            removed.append(copy.path.relative_to(bundle).as_posix())

    packs = packs_of(bundle, corpus_root)
    declared = tuple(pack.state.pack_id for pack in packs.installed)
    available = (
        ()
        if declared or packs.missing
        else tuple(
            sorted(pack.state.pack_id for pack in list_installed(corpus_root).packs)
        )
    )
    _reported(events, removed, made_yours, started)
    return BundleSync(
        removed=tuple(removed),
        made_yours=tuple(made_yours),
        declared=declared,
        missing=packs.missing,
        available=available,
    )


def _pack_copies(bundle: Path) -> list[_Copy]:
    """Every file in the bundle a pack owns, judged before anything moves.

    Wider than what a bundle indexes: a copy the person hid behind a dot
    is still a copy kennis wrote (#247).
    """
    copies: list[_Copy] = []
    unrecognised: list[str] = []
    for path in bundle_files(bundle):
        try:
            header, body = split_frontmatter(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            # A header kennis cannot read is the person's, as `context
            # reset` documents.
            continue
        owner = header.get("owner")
        if owner is None or owner == USER_OWNER:
            continue
        if not isinstance(owner, str) or not owner.startswith(_PACK_OWNER_PREFIX):
            unrecognised.append(path.relative_to(bundle).as_posix())
            continue
        source = header.get("source")
        recorded = source if isinstance(source, dict) else {}
        written = recorded.get("sha256")
        address = recorded.get("address")
        copies.append(
            _Copy(
                path=path,
                address=address
                if isinstance(address, str)
                else path.relative_to(bundle).as_posix(),
                pack_id=owner.removeprefix(_PACK_OWNER_PREFIX),
                header=header,
                body=body,
                # No digest is no evidence the person left it alone, so
                # such a file is kept as theirs rather than removed.
                edited=written != content_digest(body.encode("utf-8")),
            )
        )
    if unrecognised:
        raise DocumentInvalid(
            "these files carry an owner kennis does not recognise, so nothing "
            f"has been written: {', '.join(unrecognised)}"
        )
    return copies


def _as_yours(copy: _Copy) -> str:
    """The copy with the person as its owner, replacing the pack's file."""
    header: Frontmatter = {
        key: value for key, value in copy.header.items() if key != "source"
    }
    header["owner"] = USER_OWNER
    header["replaces"] = f"{pack_group(copy.pack_id)}/{copy.address}"
    return join_frontmatter(header, copy.body)


def _prune(bundle: Path, directory: Path) -> None:
    """Remove a group directory a removal emptied, and its empty parents.

    Only directories kennis could have created: the walk stops at the
    bundle root, and an `iterdir` that finds anything at all leaves the
    directory alone.
    """
    while directory != bundle and directory.is_dir():
        if any(directory.iterdir()):
            return
        directory.rmdir()
        directory = directory.parent


def _reported(
    events: EventSink | None,
    removed: list[str],
    made_yours: list[str],
    started: float,
) -> None:
    if events is None:
        return
    counts: Counter[Outcome] = Counter()
    for address, outcome, verdict in [
        *((address, Outcome.REMOVED, "removed") for address in removed),
        *((address, Outcome.CHANGED, "made yours") for address in made_yours),
    ]:
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


__all__ = ["OPERATION", "BundleSync", "sync_bundle"]
