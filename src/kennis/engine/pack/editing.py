"""Adding entries to a pack file and removing them (Brian, 2026-10-26).

`kennis pack add` declares what `corpus add` would add - a paper, a
documentation site or its pages, a note, a folder of context - without the
author editing YAML by hand, and `kennis pack remove` takes an entry out.
A local file is copied into the pack under `files/` and named relative to
the pack file, so the pack still works on another machine; a file already
inside the pack is named where it is.

**An add is `corpus add`'s, as far as a pack allows** (Brian, 2026-10-26:
"uniform where it can"). The arguments are resolved by `resolve_inputs`,
so a pattern expands and kennis's own folders are refused as they are for
an add; the docs arguments are checked by `unusable_docs_input`; options
arrive as `AddOptions`; and each input ends as an `AddOutcome` - added,
unchanged when the pack already declares it, or failed with its refusal -
reported through the same events. What differs is what a pack is: a notes
or context folder stays one `source:`, so files added to it later ship
too, and a paper is declared by its identifier, never read for one.

**The file is edited as text, never dumped** (`text.py` says why).
Each input's change is parsed before the next is planned against it, and
nothing is copied or written when no input was added.

Both operations end with `update_pack`, so the generated block agrees
with the file the moment the command returns.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final, Literal

import httpx
from yaml.nodes import MappingNode, SequenceNode

from kennis.engine.corpus.add import (
    AddOptions,
    AddOutcome,
    AddReport,
    docs_input_refused,
    reported_skips,
    unusable_docs_input,
)
from kennis.engine.corpus.inputs import ResolvedInputs, resolve_inputs
from kennis.engine.corpus.intake import is_supported_suffix, looks_like_url
from kennis.engine.docs.sites import project_name_from_url
from kennis.engine.docs.versions import UNVERSIONED, version_in_address
from kennis.engine.errors import InputError, KennisError, PackInvalid
from kennis.engine.events import (
    DiscardingSink,
    EventSink,
    ItemFinished,
    ItemStarted,
    OperationFinished,
    Outcome,
)
from kennis.engine.literature.identifiers import identifier_if_reference
from kennis.engine.pack.content import content_digest, resolves_inside, selects
from kennis.engine.pack.schema import (
    ContentSource,
    DocsEntry,
    LiteratureEntry,
    NoteFile,
    NoteLink,
    Pack,
    load_pack,
)
from kennis.engine.pack.text import (
    Fields,
    appended,
    child,
    composed,
    dash_of,
    entry_written,
    last_line,
    node_at,
    read_pack_text,
    with_entry,
)
from kennis.engine.pack.update import PackUpdate, update_pack
from kennis.engine.pack.validate import overlapping
from kennis.engine.refusals import (
    AlreadyDeclared,
    IdentifierNeeded,
    NameTaken,
    NotAnInput,
    Quoted,
    Refusal,
    ShippedTwice,
    UnsupportedFormat,
)

type Destination = Literal["literature", "docs", "notes", "context"]

DESTINATIONS: Final[tuple[Destination, ...]] = (
    "literature",
    "docs",
    "notes",
    "context",
)

# The folder `pack add` copies into. A copy here that no entry names any
# more is deleted by `pack remove`; nothing outside it ever is.
COPIES: Final = "files"

# What a refusal of the whole command names as its way out.
ADD_HELP: Final = "kennis pack add --help"

_PACK_SUFFIX: Final = ".ken.yml"
_MARKDOWN: Final = frozenset({".md", ".markdown", ".mdown"})


@dataclass(frozen=True, slots=True)
class PackAddition:
    """What `pack add` did: each input's outcome, the copies made, and the
    update that followed - `None` when nothing was added, and so nothing
    written."""

    path: Path
    report: AddReport
    # Paths relative to the pack file.
    copied: tuple[str, ...] = ()
    update: PackUpdate | None = None


@dataclass(frozen=True, slots=True)
class PackEdit:
    """What `pack remove` changed in the pack."""

    path: Path
    # Each entry by the name an author would use for it: a paper's citekey
    # or identifier, a project, an address, a path.
    removed: tuple[str, ...] = ()
    # Paths relative to the pack file, of the copies deleted.
    deleted: tuple[str, ...] = ()
    update: PackUpdate | None = None


def find_pack_file(directory: Path) -> Path:
    """The one `*.ken.yml` in `directory`, which `pack add` edits unless
    told otherwise."""
    found = sorted(directory.glob(f"*{_PACK_SUFFIX}"))
    if len(found) == 1:
        return found[0]
    said = (
        f"there is no {_PACK_SUFFIX} file in {directory}"
        if not found
        else f"{directory} holds {len(found)} {_PACK_SUFFIX} files"
    )
    raise PackInvalid(f"{said}: name the pack with --pack", resolution=None)


# ---------------------------------------------------------------------------
# Adding
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Planned:
    """One input's change to the text, and the copies it needs, before
    anything is written."""

    # The keys from the root to the sequence the item joins.
    section: tuple[str, ...]
    item: Fields
    name: str
    copies: list[tuple[Path, str]] = field(default_factory=list)
    # For a value joining a list inside an entry the pack already declares -
    # a local docs page joining its project's `pages:`, a context file its
    # folder's `include:` - the entry's index in `section` and the list's key,
    # and the values to append.
    joins: tuple[int, str] | None = None
    joined: list[str] = field(default_factory=list)
    # The entry of `section` this item is written over: a folder declared
    # by its files one by one, given again as the folder (#557).
    replaces: int | None = None


@dataclass(slots=True)
class _Batch:
    """What every input of one add is planned against: the pack as the
    earlier inputs left it, and the copies they claimed, so two inputs of
    one add cannot copy different files to one name."""

    pack: Pack
    root: Path
    options: AddOptions
    claimed: dict[str, Path] = field(default_factory=dict)


class _Refused(Exception):
    """One input ending as something other than added. Raised inside a
    planner and caught at the input's boundary, where it becomes that
    input's `AddOutcome`."""

    def __init__(self, refusal: Refusal, outcome: Outcome = Outcome.FAILED) -> None:
        super().__init__(refusal)
        self.refusal = refusal
        self.outcome = outcome


def add_to_pack(
    path: Path,
    destination: Destination,
    inputs: Sequence[str],
    options: AddOptions,
    *,
    kept_out: Sequence[Path] = (),
    events: EventSink | None = None,
    arxiv: httpx.Client | None = None,
    request_delay_seconds: float | None = None,
) -> PackAddition:
    """Declare each input as an entry of `destination` in the pack at
    `path`, copying local files into the pack, then update it.

    Each input is added or refused on its own, as in `corpus add`. Raises
    `InputError`, with nothing written, for what is wrong with the command
    rather than with one input: no inputs, an option for one document given
    several, an `--identifier` that is none, a docs argument `corpus add -d`
    would refuse, or an argument among `kept_out`, kennis's own folders.
    `PackInvalid` when the pack does not parse.
    """
    try:
        resolved = _checked_and_resolved(destination, inputs, options, kept_out)
    except InputError as error:
        # The shared refusals name `corpus add --help`, which is not the
        # command that was typed.
        # A remedy naming this command is kept as it is.
        raise InputError(
            str(error),
            resolution=ADD_HELP
            if error.resolution == InputError.default_resolution
            else error.resolution,
        ) from error
    sink: EventSink = events or DiscardingSink()
    started_at = time.monotonic()
    text = read_pack_text(path)
    batch = _Batch(pack=load_pack(text), root=path.parent, options=options)

    outcomes = reported_skips(resolved, sink)
    planner = _PLANNERS[destination]
    planned: list[_Planned] = []
    for one in _inputs_of(resolved, destination):
        sink.emit(ItemStarted(operation="add", item=one))
        try:
            change = planner(one, batch)
            candidate = _applied(text, change)
            after = load_pack(candidate)
            _refuse_shipping_twice(batch.pack, after)
        except _Refused as refused:
            outcome = AddOutcome(
                identifier=one,
                outcome=refused.outcome,
                refusal=refused.refusal,
                # A local file or folder named as the pack names it, not by
                # the absolute path it reached here as (#557).
                title=refused.refusal.named
                if isinstance(refused.refusal, AlreadyDeclared)
                and _local(one) is not None
                else None,
            )
        except KennisError as error:
            outcome = AddOutcome(
                identifier=one, outcome=Outcome.FAILED, refusal=Quoted(str(error))
            )
        else:
            text, batch.pack = candidate, after
            batch.claimed.update(
                (relative, source) for source, relative in change.copies
            )
            planned.append(change)
            outcome = AddOutcome(
                identifier=one, outcome=Outcome.ADDED, title=change.name
            )
        outcomes.append(outcome)
        sink.emit(
            ItemFinished(
                operation="add",
                item=one,
                outcome=outcome.outcome,
                refusal=outcome.refusal,
            )
        )
    copied: list[str] = []
    update: PackUpdate | None = None
    if planned:
        for source, relative in (copy for change in planned for copy in change.copies):
            if _copy_into(source, batch.root / relative):
                copied.append(relative)
        path.write_text(text, encoding="utf-8", newline="\n")
        update = update_pack(
            path,
            events=sink,
            arxiv=arxiv,
            request_delay_seconds=request_delay_seconds,
        )
    # Timed after the update, whose lookups are most of what an add of
    # papers takes: Crossref answered a DOI in 1 to 10 s here (2026-10-27).
    report = AddReport(outcomes=outcomes, elapsed_seconds=time.monotonic() - started_at)
    sink.emit(
        OperationFinished(
            operation="add",
            elapsed_seconds=report.elapsed_seconds,
            counts=report.counts,
        )
    )
    return PackAddition(path=path, report=report, copied=tuple(copied), update=update)


def _refuse_shipping_twice(before: Pack, after: Pack) -> None:
    """Refuse a change after which a file would have two destinations, as
    `pack validate` would, unless the pack was so already."""
    held = overlapping(before)
    for problem in overlapping(after):
        if problem not in held:
            raise _Refused(ShippedTwice(path=problem.path, other=problem.other or ""))


def _checked_and_resolved(
    destination: Destination,
    inputs: Sequence[str],
    options: AddOptions,
    kept_out: Sequence[Path],
) -> ResolvedInputs:
    if not inputs:
        raise InputError("name something to add")
    _refuse_one_input_options(options, count=len(inputs))
    if options.identifier and identifier_if_reference(options.identifier) is None:
        raise InputError(
            f"'{options.identifier}' is not an arXiv identifier, a DOI or an "
            "ADS bibcode, so it cannot say which paper this is"
        )
    if destination == "docs":
        _refuse_unusable_docs(inputs, options)
    return resolve_inputs(inputs, kept_out=kept_out)


def _refuse_one_input_options(options: AddOptions, *, count: int) -> None:
    """Options that describe one document, refused for several: every paper
    would carry the one citekey, and every note the one title."""
    one_input = {
        "--title": options.title,
        "--citekey": options.citekey,
        "--identifier": options.identifier,
    }
    given = [name for name, value in one_input.items() if value is not None]
    if given and count > 1:
        listed = ", ".join(given)
        raise InputError(f"{listed} describes one document; add one at a time")


def _refuse_unusable_docs(inputs: Sequence[str], options: AddOptions) -> None:
    """The arguments `corpus add -d` refuses, refused in its words; and a
    local page with no version, which a pack cannot read one from later."""
    unusable = unusable_docs_input(inputs, project=options.project)
    if unusable is not None:
        raise docs_input_refused(*unusable, command="kennis pack add")
    if options.version is None:
        for one in inputs:
            if not looks_like_url(one):
                raise InputError(
                    f"'{one}' is a local page, so there is no address to read "
                    "a version from: name one with --version, such as "
                    f"--version latest, or --version {UNVERSIONED} when the "
                    "documentation has no versions"
                )
            if version_in_address(one) is None:
                # Refused here, before the schema refuses the entry from
                # inside pydantic (2026-10-27: a traceback).
                raise docs_input_refused(one, "unversioned", command="kennis pack add")


def _inputs_of(resolved: ResolvedInputs, destination: Destination) -> list[str]:
    """What each outcome is about: every resolved file, except that a notes
    or context folder is one input, declared as one `source:`."""
    sourced = destination in ("notes", "context")
    found: list[str] = []
    for item in resolved.items:
        one = (
            item.from_argument
            if sourced and item.origin == "directory"
            else item.identifier
        )
        if one not in found:
            found.append(one)
    return found


def _paper(raw: str, batch: _Batch) -> _Planned:
    given = batch.options
    local = _local(raw)
    copies: list[tuple[Path, str]] = []
    where: Fields = []
    identifier: str | None
    if local is not None and local.is_file():
        if given.identifier is None:
            raise _Refused(IdentifierNeeded(named=raw))
        identifier = given.identifier
        relative, copy = _placed(raw, local, batch, f"{COPIES}/literature")
        copies.extend(copy)
        where.append(("file", relative))
    elif looks_like_url(raw):
        if given.identifier is None and identifier_if_reference(raw) is None:
            raise _Refused(IdentifierNeeded(named=raw))
        identifier = given.identifier
        where.append(("url", raw))
    else:
        if identifier_if_reference(raw) is None:
            raise _Refused(NotAnInput(identifier=raw))
        if given.identifier is not None:
            raise InputError("--identifier is for a paper given as a file or address")
        identifier = raw.strip()
    item: Fields = []
    if identifier is not None:
        item.append(("identifier", identifier))
    for name in ("citekey", "title"):
        value = getattr(given, name)
        if value is not None:
            item.append((name, value))
    item.extend(where)
    if given.group is not None:
        item.append(("group", given.group))

    entry = LiteratureEntry.model_validate(dict(item))
    if entry.key in {one.key for one in batch.pack.corpus.literature}:
        raise _Refused(AlreadyDeclared(named=entry.paper.value), Outcome.UNCHANGED)
    return _Planned(
        section=("corpus", "literature"),
        item=item,
        # The entry's key, as the update names a paper it describes and as
        # `pack remove` takes it, so one line can say both.
        name=entry.citekey or entry.key,
        copies=copies,
    )


def _note(raw: str, batch: _Batch) -> _Planned:
    given, pack = batch.options, batch.pack
    local = _local(raw)
    copies: list[tuple[Path, str]] = []
    item: Fields
    if local is not None and local.is_dir():
        if given.title is not None:
            raise InputError("--title names one note, and a folder holds several")
        relative, copy = _placed(raw, local, batch, f"{COPIES}/notes")
        copies.extend(copy)
        name = f"{relative}/"
        widened = _widened(relative, local, given.group, list(pack.corpus.notes))
        if widened is not None:
            return _Planned(
                section=("corpus", "notes"),
                item=widened[1],
                name=name,
                copies=copies,
                replaces=widened[0],
            )
        item = _source_fields(relative, local, given.group)
    elif local is not None and local.is_file():
        relative, copy = _placed(raw, local, batch, f"{COPIES}/notes")
        copies.extend(copy)
        item = [("file", relative)]
        name = relative
        if relative in pack.shipped_files:
            raise _Refused(AlreadyDeclared(named=name), Outcome.UNCHANGED)
    elif looks_like_url(raw):
        item = [("url", raw)]
        name = raw
        if raw in {one.url for one in pack.corpus.note_links}:
            raise _Refused(AlreadyDeclared(named=name), Outcome.UNCHANGED)
    else:
        raise _Refused(NotAnInput(identifier=raw))
    if given.title is not None:
        item.append(("title", given.title))
    if given.group is not None and not any(key == "group" for key, _ in item):
        item.append(("group", given.group))
    return _Planned(section=("corpus", "notes"), item=item, name=name, copies=copies)


def _context(raw: str, batch: _Batch) -> _Planned:
    given, pack = batch.options, batch.pack
    local = _local(raw)
    if local is None:
        # A pack's context is shipped, never fetched.
        raise _Refused(NotAnInput(identifier=raw))
    if local.is_dir():
        relative, copies = _placed(raw, local, batch, f"{COPIES}/context")
        name = f"{relative}/"
        widened = _widened(relative, local, given.group, list(pack.context))
        return _Planned(
            section=("context",),
            item=_source_fields(relative, local, given.group)
            if widened is None
            else widened[1],
            name=name,
            copies=copies,
            replaces=None if widened is None else widened[0],
        )
    if local.suffix.lower() not in _MARKDOWN:
        raise _Refused(UnsupportedFormat(suffix=local.suffix))
    folder = f"{COPIES}/context"
    relative, copies = _placed(raw, local, batch, folder)
    covering = [
        one
        for one in pack.context
        if _under(relative, one.source)
        and selects(relative[len(one.source.strip("/")) + 1 :], one)
    ]
    if covering and not copies:
        raise _Refused(AlreadyDeclared(named=relative), Outcome.UNCHANGED)
    if not relative.startswith(f"{folder}/"):
        return _context_file(relative, given.group, pack)
    if covering:
        # The folder is declared already; the copy alone adds the file.
        return _Planned(section=(), item=[], name=relative, copies=copies)
    return _Planned(
        section=("context",),
        item=[("source", f"{folder}/")],
        name=relative,
        copies=copies,
    )


def _context_file(relative: str, group: str | None, pack: Pack) -> _Planned:
    """One file already in the pack, declared by its folder with an
    `include:` naming it (Brian, 2026-10-27: "not per file"), so the
    install, the checksums and the search treat it as any source. A further
    file of that folder joins the list of the entry already naming files
    one by one in the same group."""
    parent, _, name = relative.rpartition("/")
    source = f"{parent}/" if parent else "./"
    for index, entry in enumerate(pack.context):
        if (
            entry.source.strip("/") == parent
            and entry.group == group
            and entry.named_files is not None
        ):
            return _Planned(
                section=("context",),
                item=[],
                name=relative,
                joins=(index, "include"),
                joined=[name],
            )
    item: Fields = [("source", source)]
    if group is not None:
        item.append(("group", group))
    item.append(("include", [name]))
    return _Planned(section=("context",), item=item, name=relative)


def _docs(raw: str, batch: _Batch) -> _Planned:
    """A site for an address; a local page joins its project's `pages:`,
    declaring the project when this is its first."""
    given, pack = batch.options, batch.pack
    if looks_like_url(raw):
        project = given.project or project_name_from_url(raw)
        if project in {one.project for one in pack.corpus.docs}:
            raise _Refused(AlreadyDeclared(named=project), Outcome.UNCHANGED)
        item: Fields = [("project", project), ("base_url", raw)]
        if given.version is not None:
            item.append(("version", given.version))
        DocsEntry.model_validate(dict(item))
        return _Planned(section=("corpus", "docs"), item=item, name=project)

    # `_refuse_unusable_docs` has seen to both: a local page is a file, with
    # a project and a version named.
    assert given.project is not None and given.version is not None
    relative, copies = _placed(
        raw, Path(raw).expanduser(), batch, f"{COPIES}/docs/{given.project}"
    )
    existing = [
        index
        for index, one in enumerate(pack.corpus.docs)
        if one.project == given.project
    ]
    if not existing:
        return _Planned(
            section=("corpus", "docs"),
            item=[
                ("project", given.project),
                ("version", given.version),
                ("pages", [relative]),
            ],
            name=relative,
            copies=copies,
        )
    held = pack.corpus.docs[existing[0]]
    if held.base_url is not None or held.version != given.version:
        raise InputError(
            f"this pack already declares the project {given.project}, as a "
            "site or another version"
        )
    if relative in held.pages:
        raise _Refused(AlreadyDeclared(named=relative), Outcome.UNCHANGED)
    return _Planned(
        section=("corpus", "docs"),
        item=[],
        name=relative,
        copies=copies,
        joins=(existing[0], "pages"),
        joined=[relative],
    )


_PLANNERS: Final[dict[Destination, Callable[[str, _Batch], _Planned]]] = {
    "literature": _paper,
    "docs": _docs,
    "notes": _note,
    "context": _context,
}


def _widened(
    relative: str,
    folder: Path,
    group: str | None,
    entries: Sequence[ContentSource | NoteLink | NoteFile],
) -> tuple[int, Fields] | None:
    """The entry already declaring the folder `relative`, by its index in
    `entries`, and the fields that make it ship the whole folder; None when
    no entry declares it. Refused as unchanged when one ships it whole.

    `pack add -c context/*` then `pack add -c context/`: the second names
    the whole folder, and was told it was there already, so a file put in
    it later would not have shipped (#557). Its group is kept unless one
    is given."""
    for index, entry in enumerate(entries):
        if not isinstance(entry, ContentSource) or entry.source.strip("/") != relative:
            continue
        if entry.named_files is None:
            raise _Refused(AlreadyDeclared(named=f"{relative}/"), Outcome.UNCHANGED)
        return index, _source_fields(
            relative, folder, entry.group if group is None else group
        )
    return None


def _source_fields(relative: str, folder: Path, group: str | None) -> Fields:
    """A `source:` for a folder, including every kind of file it holds that
    kennis converts, so a PDF in it is not silently left behind (#266)."""
    suffixes = sorted(
        {
            path.suffix
            for path in folder.rglob("*")
            if path.is_file() and is_supported_suffix(path)
        }
    )
    item: Fields = [("source", f"{relative}/")]
    if group is not None:
        item.append(("group", group))
    if suffixes and suffixes != [".md"]:
        item.append(("include", [f"**/*{suffix}" for suffix in suffixes]))
    return item


def _placed(
    raw: str, local: Path, batch: _Batch, folder: str
) -> tuple[str, list[tuple[Path, str]]]:
    """Where `local` is named from the pack, and the copy that puts it there.

    A file or folder already inside the pack is named where it is. Anything
    else is copied under `folder` by its own name. A copy that would replace
    a different file - in the pack, or claimed by an earlier input of this
    add - is refused; the same bytes are reused.
    """
    if resolves_inside(local, batch.root):
        return local.resolve().relative_to(batch.root.resolve()).as_posix(), []
    relative = (PurePosixPath(folder) / local.name).as_posix()
    target = batch.root / relative
    claimed = batch.claimed.get(relative)
    if (target.exists() and not _same(local, target)) or (
        claimed is not None and claimed.resolve() != local.resolve()
    ):
        raise _Refused(NameTaken(named=raw, copy=relative))
    return relative, [(local, relative)]


def _same(local: Path, target: Path) -> bool:
    if local.is_file() and target.is_file():
        return content_digest(local.read_bytes()) == content_digest(target.read_bytes())
    return False


def _copy_into(source: Path, target: Path) -> bool:
    """Copy `source` to `target`, and whether a copy was made."""
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)
    return True


def _local(raw: str) -> Path | None:
    """`raw` as a path when something is there, an existing path winning
    over an identifier as it does for `corpus add`."""
    if looks_like_url(raw):
        return None
    path = Path(raw).expanduser()
    return path if path.exists() else None


def _under(relative: str, source: str) -> bool:
    prefix = source.strip("/")
    return relative.startswith(f"{prefix}/")


# ---------------------------------------------------------------------------
# Removing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Match:
    """One item to take out: the sequence it is in, by keys from the root,
    and its index there."""

    section: tuple[str, ...]
    index: int
    name: str
    # The files this item named, for deleting copies nothing names after.
    named: tuple[str, ...]


def remove_from_pack(
    path: Path,
    names: Sequence[str],
    *,
    events: EventSink | None = None,
    arxiv: httpx.Client | None = None,
    request_delay_seconds: float | None = None,
) -> PackEdit:
    """Take every entry a name matches out of the pack at `path`, delete the
    copies under `files/` that nothing names any more, then update it.

    A name is a citekey, an identifier in any spelling a paper's
    `identifier` takes, an address, a documentation project, a shipped
    file's path, a source folder, or a context file a folder's `include:`
    names. Raises `InputError` naming a name that
    matches nothing; nothing is written then.
    """
    text = read_pack_text(path)
    matches = _matches(load_pack(text), names)
    text = _without(text, matches)
    remaining = load_pack(text)
    path.write_text(text, encoding="utf-8", newline="\n")
    deleted = _deleted_copies(path.parent, matches, remaining)
    update = update_pack(
        path,
        events=events,
        arxiv=arxiv,
        request_delay_seconds=request_delay_seconds,
    )
    return PackEdit(
        path=path,
        removed=tuple(dict.fromkeys(one.name for one in matches)),
        deleted=deleted,
        update=update,
    )


def entries_named(path: Path, names: Sequence[str]) -> tuple[str, ...]:
    """The entries `remove_from_pack` would take out, by the name an author
    would use for each, so a front end can ask before it does. Raises as
    `remove_from_pack` does."""
    matches = _matches(load_pack(read_pack_text(path)), names)
    return tuple(dict.fromkeys(one.name for one in matches))


def _matches(pack: Pack, names: Sequence[str]) -> list[_Match]:
    if not names:
        raise InputError("name an entry to remove", resolution=None)
    matches: list[_Match] = []
    for name in names:
        found = _matching(pack, name)
        if not found:
            raise InputError(
                f"no entry in this pack is called '{name}'", resolution=None
            )
        matches.extend(one for one in found if one not in matches)
    return matches


def _matching(pack: Pack, name: str) -> list[_Match]:
    wanted = name.strip()
    folder = wanted.strip("/")
    paper = identifier_if_reference(wanted)
    found: list[_Match] = []
    for index, entry in enumerate(pack.corpus.literature):
        if (
            wanted == entry.citekey
            or wanted in (entry.url, entry.file)
            or (paper is not None and f"{paper.kind}:{paper.value}" == entry.key)
        ):
            found.append(
                _Match(
                    ("corpus", "literature"),
                    index,
                    entry.citekey or entry.paper.value,
                    (entry.file,) if entry.file else (),
                )
            )
    for index, docs in enumerate(pack.corpus.docs):
        if wanted in (docs.project, docs.base_url):
            found.append(
                _Match(("corpus", "docs"), index, docs.project, tuple(docs.pages))
            )
        elif wanted in docs.pages:
            if docs.pages == [wanted]:
                found.append(_Match(("corpus", "docs"), index, wanted, (wanted,)))
            else:
                found.append(
                    _Match(
                        ("corpus", "docs", str(index), "pages"),
                        docs.pages.index(wanted),
                        wanted,
                        (wanted,),
                    )
                )
    for index, note in enumerate(pack.corpus.notes):
        if isinstance(note, NoteLink) and wanted == note.url:
            found.append(_Match(("corpus", "notes"), index, note.url, ()))
        elif isinstance(note, NoteFile) and wanted == note.file:
            found.append(_Match(("corpus", "notes"), index, note.file, (note.file,)))
        elif isinstance(note, ContentSource) and folder == note.source.strip("/"):
            found.append(_Match(("corpus", "notes"), index, note.source, (folder,)))
    for index, source in enumerate(pack.context):
        if folder == source.source.strip("/"):
            found.append(_Match(("context",), index, source.source, (folder,)))
            continue
        found.extend(_context_file_match(index, source, wanted))
    return found


def _context_file_match(index: int, source: ContentSource, wanted: str) -> list[_Match]:
    """A file a context entry ships, as `pack remove` takes it out: from its
    `include:` list, or with the entry when it is the last there. A file a
    folder ships by pattern is refused, since no line names it alone."""
    within = source.source.strip("/").removeprefix(".")
    if within and not _under(wanted, within):
        return []
    name = wanted[len(within) + 1 :] if within else wanted
    if source.named_files is not None:
        if name not in source.include:
            return []
        if source.include == [name]:
            return [_Match(("context",), index, wanted, ())]
        return [
            _Match(
                ("context", str(index), "include"),
                source.include.index(name),
                wanted,
                (),
            )
        ]
    if within and selects(name, source):
        raise InputError(
            f"'{wanted}' is shipped as part of the folder '{source.source}', "
            "and no line names it alone: remove the folder, or declare the "
            "files you want one by one",
            resolution=None,
        )
    return []


def _deleted_copies(
    root: Path, matches: Sequence[_Match], remaining: Pack
) -> tuple[str, ...]:
    """The copies under `files/` the removed entries named and nothing that
    remains names, deleted - and only those."""
    still = set(remaining.shipped_files) | {
        one.source.strip("/")
        for one in [*remaining.corpus.note_sources, *remaining.context]
    }
    deleted: list[str] = []
    for relative in dict.fromkeys(path for one in matches for path in one.named):
        if not relative.startswith(f"{COPIES}/") or relative in still:
            continue
        if any(_under(relative, kept) or _under(kept, relative) for kept in still):
            continue
        target = root / relative
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        else:
            continue
        deleted.append(relative)
        _prune(target.parent, root / COPIES)
    return tuple(deleted)


def _prune(directory: Path, top: Path) -> None:
    """Empty folders from `directory` up to `top`, inclusive, removed."""
    while directory.is_relative_to(top) and directory.is_dir():
        if any(directory.iterdir()):
            return
        directory.rmdir()
        if directory == top:
            return
        directory = directory.parent


# ---------------------------------------------------------------------------
# The text
# ---------------------------------------------------------------------------


def _applied(text: str, change: _Planned) -> str:
    if not change.section:
        return text
    if change.replaces is not None:
        return with_entry(text, change.section, change.replaces, change.item)
    if change.joins is not None:
        index, key = change.joins
        held = entry_written(text, change.section, index)
        joined: list[tuple[str, object]] = []
        for name, value in held:
            if name == key and isinstance(value, list):
                value = [*value, *change.joined]
            joined.append((name, value))
        return with_entry(text, change.section, index, joined)
    return appended(text, change.section, change.item)


def _within_an_entry(match: _Match) -> bool:
    """Whether `match` is a value in a list inside an entry, whose section
    then names the entry by its index."""
    return any(part.isdigit() for part in match.section)


def _without(text: str, matches: Sequence[_Match]) -> str:
    """`text` with each matched item's lines deleted, one blank line beside
    it with them, and a sequence left with no items written `key: []`. A
    value leaving a list inside an entry - a docs project's `pages:`, a
    context folder's `include:` - writes that entry again without it."""
    whole = [match for match in matches if not _within_an_entry(match)]
    gone = {(match.section, match.index) for match in whole}
    leaving: dict[tuple[tuple[str, ...], int, str], set[int]] = {}
    for match in matches:
        if _within_an_entry(match):
            *holder, position, key = match.section
            leaving.setdefault((tuple(holder), int(position), key), set()).add(
                match.index
            )
    for (holder_section, entry, key), positions in leaving.items():
        if (holder_section, entry) in gone:
            continue
        kept: list[tuple[str, object]] = []
        for name, value in entry_written(text, holder_section, entry):
            if name == key and isinstance(value, list):
                value = [one for at, one in enumerate(value) if at not in positions]
            kept.append((name, value))
        text = with_entry(text, holder_section, entry, kept)

    lines = text.splitlines(keepends=True)
    root = composed(text)
    doomed: set[int] = set()
    emptied: list[int] = []
    by_section: dict[tuple[str, ...], set[int]] = {}
    for match in whole:
        by_section.setdefault(match.section, set()).add(match.index)
    for section, indices in by_section.items():
        node = node_at(root, section)
        assert isinstance(node, SequenceNode) and not node.flow_style
        for index in indices:
            item = node.value[index]
            start, _ = dash_of(text, item)
            end = last_line(item, lines)
            doomed.update(range(start, end + 1))
            if index > 0 and start > 0 and not lines[start - 1].strip():
                doomed.add(start - 1)
            elif (
                index == 0
                and end + 1 < len(lines)
                and not lines[end + 1].strip()
                and len(indices) < len(node.value)
            ):
                doomed.add(end + 1)
        if len(indices) == len(node.value):
            parent = node_at(root, section[:-1]) if section[:-1] else root
            assert isinstance(parent, MappingNode)
            found = child(parent, section[-1])
            assert found is not None
            emptied.append(found[0].start_mark.line)
            between = range(node.start_mark.line, last_line(node, lines) + 1)
            doomed.update(index for index in between if not lines[index].strip())
    for line in emptied:
        lines[line] = lines[line].rstrip("\n").rstrip() + " []\n"
    return "".join(line for index, line in enumerate(lines) if index not in doomed)


__all__ = [
    "COPIES",
    "DESTINATIONS",
    "Destination",
    "PackAddition",
    "PackEdit",
    "add_to_pack",
    "entries_named",
    "find_pack_file",
    "remove_from_pack",
]
