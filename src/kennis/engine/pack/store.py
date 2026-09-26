"""Installing a pack into the machine-global store. Design sections 5 and 8.

`pack add` does no network I/O. It updates a **declaration**: the pack file
as handed, the content it names, and a `state.json` recording what was
applied. Converging the corpus documents with that declaration is
`corpus sync`'s job and materialising the context into a workspace is
`context sync`'s.

**The store is a cache, not corpus content.** Section 19's table marks it
"no - re-derivable / re-pushed by the provider's next run", and the git
section says version control "does not apply to the pack store, which is a
cache of an immutable wheel". So `packs/` is gitignored, and this module
makes sure of it rather than trusting a `corpus init` that may predate the
feature - the alternative is a later `corpus add` sweeping every copied
file into the user's history, which is easy to do and tedious to undo.

**The fourth fast-path condition is the reason this module is careful.**
Comparing the handed file's hash against the recorded one is cheap and
insufficient: nothing would ever check the store against its own digests,
so a partial restore, a cleared cache or an interrupted add could leave the
content gone and `state.json` intact. The next add would short-circuit, and
the next sync would see a pack declaring nothing and delete every document
it owns. So a store that does not verify is not believed.

**Repair here is simpler than section 5 step 2a reads**, because that step
is written for a caller with nothing in hand. `pack add` is handed a live
pack file with its content beside it, so a store that fails verification is
re-copied from what is in hand and the only difference is the word in the
report. Refusing is for `corpus sync` and `context sync`, which are handed
nothing and must not read an empty store as a declaration that the pack now
ships nothing. Git cannot be the second recovery for the store either,
since the store is not tracked. Concern #263.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from kennis import __version__
from kennis.engine._atomic import replace_file, replacing_directory
from kennis.engine.errors import PackInvalid
from kennis.engine.events import EventSink, ItemFinished, OperationFinished, Outcome
from kennis.engine.pack.content import content_digest, read_source
from kennis.engine.pack.schema import ContentSource, Pack
from kennis.engine.pack.validate import validate_pack

PACKS_DIRNAME: Final = "packs"
STATE_FILENAME: Final = "state.json"
DECLARATION_FILENAME: Final = "pack.ken.yml"

OPERATION: Final = "pack-add"

# What the corpus `.gitignore` must hold for the store to stay out of the
# corpus history, and the sentence saying why, so a reader of that file does
# not delete a line whose purpose is invisible.
_IGNORE_ENTRY: Final = f"{PACKS_DIRNAME}/"
_IGNORE_BLOCK: Final = f"""
# The pack store: a cache of what each provider last handed kennis. Derived,
# re-pushed by the provider's next run, and deliberately not history.
{_IGNORE_ENTRY}
"""

type InstallOutcome = Literal["installed", "unchanged", "repaired"]


@dataclass(frozen=True, slots=True)
class PackState:
    """`state.json`: what was applied, and what the next add compares against.

    `files` maps a path relative to `packs/<id>/` to the digest of the file
    kennis wrote there. It is the fourth fast-path condition's whole input.

    Section 8 also lists a digest of each **document** as kennis wrote it,
    for the user-edit check in step 4a. Nothing materialises a document
    until `corpus sync` exists, so that map has no writer and no reader yet
    and is absent rather than always empty - a field nothing fills is a
    promise nothing keeps. The store is unversioned and re-derivable, so
    adding it later costs nothing.
    """

    pack_id: str
    pack_version: str
    schema_version: int
    file_sha256: str
    files: dict[str, str]
    # Immutable. The tie-break when two packs declare the same item, and it
    # cannot be `applied_at`: a provider calls `pack add` on every run, so
    # most-recent-wins would flip ownership in a loop and rewrite documents
    # forever. Section 5, step 4.
    first_applied_at: str
    applied_at: str
    # major.minor of the kennis that wrote the store. A patch release has
    # not changed how anything is materialised; a minor one may have.
    applied_by: str
    # Recorded, and read only to repair. Never a live reference: a provider
    # that has been uninstalled leaves a pack that still works.
    source_path: str


@dataclass(frozen=True, slots=True)
class PackInstall:
    """What `install_pack` did, and what the pack holds that it did not copy.

    A pack that declares two papers and a documentation site copies nothing
    and would otherwise report `0 files`, which reads as "nothing
    happened". The declarations are counted here so the report can say what
    the pack asked for - and say it as *declared*, never as added, because
    nothing is fetched until a sync that does not exist yet.
    """

    pack_id: str
    outcome: InstallOutcome
    files: int
    literature: int
    docs: int


def packs_root(corpus_root: Path) -> Path:
    """Where every installed pack lives."""
    return corpus_root / PACKS_DIRNAME


def pack_root(corpus_root: Path, pack_id: str) -> Path:
    """Where one pack's declaration, content and state live."""
    return packs_root(corpus_root) / pack_id


def read_state(corpus_root: Path, pack_id: str) -> PackState | None:
    """The recorded state of one installed pack, or None if there is none.

    None for a pack that was never added **and** for a state file that will
    not parse: an unreadable pointer is treated as no pointer, which sends
    the caller down the slow path rather than into a guess.
    """
    path = pack_root(corpus_root, pack_id) / STATE_FILENAME
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    try:
        return PackState(
            pack_id=str(document["pack_id"]),
            pack_version=str(document["pack_version"]),
            schema_version=int(document["schema_version"]),
            file_sha256=str(document["file_sha256"]),
            files={str(key): str(value) for key, value in document["files"].items()},
            first_applied_at=str(document["first_applied_at"]),
            applied_at=str(document["applied_at"]),
            applied_by=str(document["applied_by"]),
            source_path=str(document["source_path"]),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def install_pack(
    corpus_root: Path, path: Path, *, events: EventSink | None = None
) -> PackInstall:
    """Install the pack at `path` into the store under `corpus_root`.

    Raises `PackInvalid` when the file does not parse, when this kennis may
    not read it, or when it has any content problem - including digests that
    disagree with the files beside them. `pack validate` is the provider's
    own check and nothing makes them run it, so the installing side checks
    too; section 3 puts that cost on the slow path, where walking the tree
    is free against the copy about to happen anyway.
    """
    started = time.monotonic()
    report = validate_pack(path)
    if report.refusal is not None:
        raise PackInvalid(
            f"this pack needs {report.refusal.kind.replace('-', ' ')} "
            f"({report.refusal.required}, this is {report.refusal.available})",
            resolution="uv tool upgrade kennis",
        )
    if report.problems:
        named = ", ".join(sorted({problem.kind for problem in report.problems}))
        raise PackInvalid(
            f"this pack does not describe itself correctly ({named}), so "
            "nothing has been installed",
            resolution=f"kennis pack validate {path}",
        )

    pack = report.pack
    digest = content_digest(path.read_bytes())
    previous = read_state(corpus_root, pack.pack.id)
    outcome = _outcome_for(corpus_root, pack, digest, previous)
    if previous is not None and outcome == "unchanged":
        _reported(events, pack.pack.id, outcome, len(previous.files), started)
        return _install(pack, outcome, len(previous.files))

    files = _installed(corpus_root, path, pack, digest, previous)
    _reported(events, pack.pack.id, outcome, len(files), started)
    return _install(pack, outcome, len(files))


def _install(pack: Pack, outcome: InstallOutcome, files: int) -> PackInstall:
    return PackInstall(
        pack_id=pack.pack.id,
        outcome=outcome,
        files=files,
        literature=len(pack.corpus.literature),
        docs=len(pack.corpus.docs),
    )


def _outcome_for(
    corpus_root: Path, pack: Pack, digest: str, previous: PackState | None
) -> InstallOutcome:
    """The fast path of section 5 step 2, and the four conditions it needs.

    Ordered cheapest first: three field comparisons, and only then the walk
    of the store. The fourth is the one that matters, and it is the one the
    other three cannot stand in for - they are all claims about the *file*,
    and it is the only claim about the *store*.
    """
    if previous is None:
        return "installed"
    if previous.file_sha256 != digest:
        return "installed"
    if previous.schema_version != pack.kennis.schema_version:
        return "installed"
    if previous.applied_by != _series(__version__):
        return "installed"
    if not _store_verifies(corpus_root, pack.pack.id, previous):
        # Not "installed": the declaration did not move, the store did, and
        # a reader is owed the difference between "your provider shipped
        # something new" and "what was here was damaged".
        return "repaired"
    return "unchanged"


def _store_verifies(corpus_root: Path, pack_id: str, state: PackState) -> bool:
    """Every recorded path present under `packs/<id>/` with its digest.

    A few milliseconds for the fifty-odd files a real pack ships, and the
    only thing standing between a damaged store and silent deletion.
    """
    root = pack_root(corpus_root, pack_id)
    for relative, digest in state.files.items():
        path = root / relative
        try:
            if content_digest(path.read_bytes()) != digest:
                return False
        except OSError:
            return False
    return True


def _installed(
    corpus_root: Path,
    path: Path,
    pack: Pack,
    digest: str,
    previous: PackState | None,
) -> dict[str, str]:
    """Stage, copy, swap, and only then write the state file.

    Section 5 step 5. `replacing_directory` is the same discipline the index
    build uses, for the same reason: a directory only meaningful complete,
    plus a pointer that must not be published early.
    """
    _ensure_ignored(corpus_root)
    root = pack_root(corpus_root, pack.pack.id)
    files: dict[str, str] = {}
    with replacing_directory(root) as staging:
        shutil.copy2(path, staging / DECLARATION_FILENAME)
        for source in _declared(pack):
            files.update(_copied(path.parent, staging, source))
    _write_state(root, pack, digest, files, path, previous)
    return files


def _declared(pack: Pack) -> list[str]:
    """Every source directory the pack declares, deduplicated.

    One tree may be declared by both sections; it is copied once, because
    the store holds the pack's files and the *destination* is what
    `corpus sync` and `context sync` differ on, not the copy.
    """
    seen: list[str] = []
    for source in [*pack.corpus.notes, *pack.context]:
        if source.source not in seen:
            seen.append(source.source)
    return seen


def _copied(origin: Path, staging: Path, source: str) -> dict[str, str]:
    """One declared tree into the staging directory, with its digests.

    Walked with `read_source`'s own rules rather than `shutil.copytree`, so
    the files copied are exactly the files `validate` judged - symlinks
    excluded, `include` and `exclude` honoured. `validate_pack` has already
    refused anything that escapes the pack root.
    """
    found = read_source(origin, ContentSource(source=source))
    digests: dict[str, str] = {}
    for relative in sorted(found.digests):
        target = staging / source.strip("/") / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin / source / relative, target)
        digests[f"{source.strip('/')}/{relative}"] = found.digests[relative]
    return digests


def _write_state(
    root: Path,
    pack: Pack,
    digest: str,
    files: dict[str, str],
    path: Path,
    previous: PackState | None,
) -> None:
    """`state.json`, written after the swap and never before it."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = PackState(
        pack_id=pack.pack.id,
        pack_version=pack.pack.version,
        schema_version=pack.kennis.schema_version,
        file_sha256=digest,
        files=files,
        first_applied_at=previous.first_applied_at if previous else now,
        applied_at=now,
        applied_by=_series(__version__),
        source_path=str(path.resolve()),
    )
    replace_file(
        root / STATE_FILENAME,
        json.dumps(_as_document(state), indent=2, sort_keys=True) + "\n",
    )


def _as_document(state: PackState) -> dict[str, object]:
    return {
        "pack_id": state.pack_id,
        "pack_version": state.pack_version,
        "schema_version": state.schema_version,
        "file_sha256": state.file_sha256,
        "files": state.files,
        "first_applied_at": state.first_applied_at,
        "applied_at": state.applied_at,
        "applied_by": state.applied_by,
        "source_path": state.source_path,
    }


def _series(version: str) -> str:
    """The `major.minor` of a version, which is what `applied_by` compares.

    A patch release has not changed how content is materialised; a minor one
    may have, and section 5 makes that the line.
    """
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


def _ensure_ignored(corpus_root: Path) -> None:
    """Keep `packs/` out of the corpus history, idempotently.

    Written here rather than only in the `corpus init` template, because a
    corpus created before packs existed has no such line and the first
    `corpus add` after a `pack add` would commit the whole store.
    """
    path = corpus_root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if any(line.strip() == _IGNORE_ENTRY for line in existing.splitlines()):
        return
    corpus_root.mkdir(parents=True, exist_ok=True)
    separator = "" if existing.endswith("\n") or not existing else "\n"
    path.write_text(existing + separator + _IGNORE_BLOCK, encoding="utf-8")


def _reported(
    events: EventSink | None,
    pack_id: str,
    outcome: InstallOutcome,
    files: int,
    started: float,
) -> None:
    recorded = {
        "installed": Outcome.ADDED,
        "unchanged": Outcome.UNCHANGED,
        "repaired": Outcome.CHANGED,
    }[outcome]
    if events is None:
        return
    events.emit(ItemFinished(operation=OPERATION, item=pack_id, outcome=recorded))
    events.emit(
        OperationFinished(
            operation=OPERATION,
            elapsed_seconds=time.monotonic() - started,
            counts={recorded: files},
        )
    )


__all__ = [
    "DECLARATION_FILENAME",
    "OPERATION",
    "PACKS_DIRNAME",
    "STATE_FILENAME",
    "InstallOutcome",
    "PackInstall",
    "PackState",
    "install_pack",
    "pack_root",
    "packs_root",
    "read_state",
]
