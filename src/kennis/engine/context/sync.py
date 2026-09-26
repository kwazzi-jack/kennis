"""`context sync`: converging a bundle with every installed pack.

Design section 5, steps 4, 4a and 6. The bundle is the destination with no
network in it - a pack's context content is already in the store, so this
converges by copying and never by fetching.

**The bundle needs no state file, because every file answers for itself.**
Who owns it is `owner:` in its frontmatter; what it was built from is
`source.sha256`; whether the user has typed since is the digest of its body
against that. A state file would have to live in a repository kennis does
not own, and would go stale the moment somebody edited a file outside
kennis - which the frontmatter cannot, because it travels with the content.

**Nothing is written until everything has been judged.** Two refusals -
a pack declaring a destination it may not have, and a document whose
`owner` kennis does not recognise - are collected first and raised before
the first write, because a half-converged bundle is worse than an
unconverged one.

**kennis does not commit.** The bundle is in the user's repository.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from kennis.engine._atomic import replace_file
from kennis.engine.context.bundle import LANDING_FILENAME
from kennis.engine.context.notes import bundle_documents
from kennis.engine.errors import DocumentInvalid, PackInvalid
from kennis.engine.events import EventSink, ItemFinished, OperationFinished, Outcome
from kennis.engine.frontmatter import split_frontmatter
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.installed import (
    declared_content,
    list_installed,
    refuse_damaged_packs,
)
from kennis.engine.pack.resolve import Action, Declaration, Existing, Verdict, resolve

OPERATION = "context-sync"

# How each verdict is reported as an outcome. `edited` and `yours` are both
# skips and are told apart by the report, not by the stream: one is a file
# kennis would have written and did not, the other is a file that was never
# kennis's to write.
_OUTCOMES: dict[Verdict, Outcome] = {
    "write": Outcome.ADDED,
    "rewrite": Outcome.CHANGED,
    "adopt": Outcome.CHANGED,
    "delete": Outcome.REMOVED,
    "keep": Outcome.UNCHANGED,
    "edited": Outcome.SKIPPED,
    "yours": Outcome.SKIPPED,
}


@dataclass(frozen=True, slots=True)
class BundleSync:
    """What one `context sync` did, by verdict.

    `counts` is keyed by verdict rather than by `Outcome` because the
    report distinguishes what the stream does not: `edited` and `yours`
    are both skips and mean entirely different things to a reader.
    """

    actions: tuple[Action, ...]
    counts: dict[Verdict, int]
    deferred: tuple[tuple[str, str], ...]


def sync_bundle(
    bundle: Path, corpus_root: Path, *, events: EventSink | None = None
) -> BundleSync:
    """Converge `bundle` with every installed pack's `context:` content.

    Raises `PackInvalid` when a pack declares a destination a bundle
    reserves, and `DocumentInvalid` when a file carries an `owner` kennis
    does not recognise. Both are raised before anything is written.
    """
    started = time.monotonic()
    packs = list_installed(corpus_root).packs
    refuse_damaged_packs(packs)
    union = declared_content(corpus_root, packs, "context")
    _refuse_reserved_destinations(union.declarations)

    actions = resolve(union.declarations, _present(bundle))
    _refuse_unrecognised_owners(actions)

    for action in actions:
        _applied(bundle, action)
    counts = Counter(action.verdict for action in actions)
    _reported(events, actions, started)
    return BundleSync(actions=actions, counts=dict(counts), deferred=union.deferred)


def _refuse_reserved_destinations(declarations: dict[str, Declaration]) -> None:
    """Two destinations a pack may not have, and why each is reserved.

    **A dot-prefixed path is never indexed or searched**, at any depth.
    That is the documented way a user keeps a file out of the index, so a
    pack shipping one would land a file that is copied, never indexed and
    invisible to search, with nothing saying so. Refusing at the join is
    the only answer that leaves both halves intact, and it is a
    provider-side mistake caught where the provider can see it. Concerns
    #247 and #267.

    `LANDING.md` is the entry point an agent is told to read first, and it
    is deliberately not indexed for the same reason a map is not an
    answer. It is the user's to edit.
    """
    reserved = sorted(
        address
        for address in declarations
        if any(part.startswith(".") for part in Path(address).parts)
        or Path(address).name == LANDING_FILENAME
    )
    if not reserved:
        return
    raise PackInvalid(
        "a pack declares a destination a bundle reserves, so nothing has "
        f"been written: {', '.join(reserved)}",
        resolution=None,
    )


def _refuse_unrecognised_owners(actions: tuple[Action, ...]) -> None:
    """Section 6: an unrecognised `owner` is corruption, not a case.

    Every one of them at once, because an author with three corrupt files
    is better served by three names than by three runs.
    """
    named = [action.address for action in actions if action.verdict == "refuse"]
    if not named:
        return
    raise DocumentInvalid(
        "these files carry an owner kennis does not recognise, so nothing "
        f"has been written: {', '.join(named)}"
    )


def _present(bundle: Path) -> dict[str, Existing]:
    """Every bundle document, as the resolution table needs to see it.

    Uses `bundle_documents`, so the two rules that decide what a bundle
    holds - no dot-prefixed path at any depth, and not `LANDING.md` - are
    stated once and apply here too.
    """
    found: dict[str, Existing] = {}
    for path in bundle_documents(bundle):
        address = path.relative_to(bundle).as_posix()
        frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
        written, shipped = _recorded_in(frontmatter)
        found[address] = Existing(
            address=address,
            owner=_owner_in(frontmatter),
            body_digest=content_digest(body.encode("utf-8")),
            written_digest=written,
            pack_digest=shipped,
        )
    return found


def _owner_in(frontmatter: dict[str, object]) -> str:
    """The file's `owner`, defaulting to the user.

    A file with no frontmatter at all, or one whose header kennis cannot
    read, is the user's - which is what `context reset` already documents
    and what makes a hand-written file safe by default. Only a value that
    is *present and unrecognised* is corruption, and `resolve` decides
    that; this returns the string it was given.
    """
    owner = frontmatter.get("owner")
    return str(owner) if owner is not None else "user"


def _recorded_in(frontmatter: dict[str, object]) -> tuple[str | None, str | None]:
    """The two digests a pack's file records: what kennis wrote, and from what.

    `sha256` is the body kennis wrote and is what a user edit moves.
    `pack_sha256` is the store file it was built from and is what a
    provider release moves. They differ for any pack file that carried
    its own frontmatter, because that header is read and replaced rather
    than copied - which is why there are two.

    A remembered note records a `sha256` too, of the text that was given,
    and it means something else. Read only when `source.via` says `pack`,
    so the two cannot be confused - though `owner` decides the row before
    either is ever consulted for a user's file.
    """
    source = frontmatter.get("source")
    if not isinstance(source, dict) or source.get("via") != "pack":
        return None, None
    written = source.get("sha256")
    shipped = source.get("pack_sha256")
    return (
        str(written) if written is not None else None,
        str(shipped) if shipped is not None else None,
    )


def _applied(bundle: Path, action: Action) -> None:
    """Carry out one action. `keep`, `yours` and `edited` write nothing."""
    path = bundle / action.address
    if action.verdict == "delete":
        path.unlink(missing_ok=True)
        _prune(bundle, path.parent)
        return
    if action.verdict not in {"write", "rewrite", "adopt"}:
        return
    declaration = action.declaration
    assert declaration is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_file(path, _document(declaration))


def _prune(bundle: Path, directory: Path) -> None:
    """Remove a group directory a deletion emptied, and its empty parents.

    Only directories kennis could have created: the walk stops at the
    bundle root, and an `iterdir` that finds anything at all - including a
    file kennis does not index - leaves the directory alone.
    """
    while directory != bundle and directory.is_dir():
        if any(directory.iterdir()):
            return
        directory.rmdir()
        directory = directory.parent


def _document(declaration: Declaration) -> str:
    """The file as it lands in the bundle.

    The shape `.skeleton.md` shows, so a pack's file and a remembered one
    are the same kind of file - a reader should not be able to tell which
    command wrote it, only who owns it.

    **The body is the pack's content**, with the pack's own frontmatter
    read for `title` and `description` and then replaced - never nested,
    never two blocks in one file.

    Two digests are recorded, and the second is the one that is easy to
    leave out. `sha256` is the body written here, so a user edit moves it;
    `pack_sha256` is the store file it came from, so a provider release
    moves that one instead. With only the first, a pack file that carried
    its own header digests differently from the store copy and is
    rewritten on every run forever.
    """
    # A content declaration always has one; only a paper or a
    # documentation project, which a fetch resolves, does not.
    assert declaration.store_path is not None
    content = declaration.store_path.read_text(encoding="utf-8")
    shipped, body = split_frontmatter(content)
    title = shipped.get("title") or Path(declaration.address).stem
    description = shipped.get("description") or ""
    written_at = datetime.now(UTC).isoformat(timespec="seconds")
    return (
        "---\n"
        f"title: {title}\n"
        f"description: '{description}'\n"
        f"owner: pack:{declaration.pack_id}\n"
        "source:\n"
        "  via: pack\n"
        f"  pack: {declaration.pack_id}\n"
        f"  at: '{written_at}'\n"
        f"  sha256: {content_digest(body.encode('utf-8'))}\n"
        f"  pack_sha256: {declaration.digest}\n"
        "---\n"
        "\n"
        f"{body}"
    )


def _reported(
    events: EventSink | None, actions: tuple[Action, ...], started: float
) -> None:
    if events is None:
        return
    counts: Counter[Outcome] = Counter()
    for action in actions:
        outcome = _OUTCOMES[action.verdict]
        counts[outcome] += 1
        events.emit(
            ItemFinished(
                operation=OPERATION,
                item=action.address,
                outcome=outcome,
                reason=action.verdict,
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
