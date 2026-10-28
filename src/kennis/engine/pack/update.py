"""Writing the `generated:` block. Design section 3.

**One property decides the whole design**: a rebuild that altered nothing
must leave the file byte-identical, because the pack file's sha256 is the
fast path in section 5 step 2, and a provider that calls `pack update` on
every release would otherwise change that hash every time and defeat it.

Two consequences follow, and the second is the one that shapes the code.

**When nothing changed, nothing is written.** Not rewritten with the same
bytes - not opened for writing at all. Stronger than the design asks for,
and much easier to be certain of.

**When something changed, it is changed as text.** Dumping the parsed
`Pack` back through `yaml.dump` would produce a valid file that had lost the
editor header line `pack init` exists to write, every comment an author put
there, and whatever key order they chose. So the block, the **trailing
section**, is replaced from its anchor to the end of the file, and what is
derived for a paper - its citekey, title, authors and year - is written
into the paper's own entry (`text.with_fields`), the way `uv add`
writes into `pyproject.toml` (Brian, 2026-10-26). The block keeps the
checksums, a lock file's job; every other byte above it is the person's.

That makes "the generated block is last" a rule of the format rather than a
habit of the example in section 7, where it is already last. An author who
moves their own content below it would have that content replaced, so a
block that is not the last section is refused rather than truncated.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypedDict

import httpx
import yaml

from kennis import __version__
from kennis.engine.corpus.add import ARXIV_DELAY_SECONDS
from kennis.engine.errors import PackInvalid
from kennis.engine.events import (
    EventSink,
    ItemFinished,
    OperationFinished,
    Outcome,
    Progress,
)
from kennis.engine.literature.citekeys import derive_citekey, unique_citekey
from kennis.engine.literature.metadata import (
    PaperMetadata,
    lookup_arxiv_metadata,
    lookup_doi_metadata,
)
from kennis.engine.literature.names import joined_names
from kennis.engine.pack.content import (
    SourceContent,
    address_of,
    read_file,
    read_source,
)
from kennis.engine.pack.schema import (
    ContentSource,
    GeneratedContent,
    GeneratedSource,
    LiteratureEntry,
    Pack,
    authors_from_line,
    load_pack,
    read_yaml,
)
from kennis.engine.pack.text import GENERATED_MARKER, Fields, with_fields
from kennis.engine.pack.validate import version_refusal
from kennis.engine.parallel import fetched_in_parallel
from kennis.engine.refusals import Quoted

OPERATION: Final = "pack-update"
# The lookups an update owes, which are what take its time: Crossref
# answered a DOI in 1 to 10 s here (2026-10-27).
DESCRIBING: Final = "pack-describe"

_GENERATED_KEY: Final = "generated:"


@dataclass(frozen=True, slots=True)
class PackUpdate:
    """What `pack update` did, and to how much."""

    path: Path
    outcome: Literal["written", "unchanged"]
    files: int
    # Files sitting in a declared source that no `include` pattern matched.
    # Counted rather than dropped, because the default `**/*.md` silently
    # discarding a PDF an author meant to ship is the shape of mistake
    # nothing else here would catch. Concern #266.
    unselected: int
    # Each paper this update described, by its key, and the citekey written
    # into its entry.
    described: tuple[tuple[str, str], ...] = ()
    # Papers left without a citekey, or whose lookup found nothing:
    # `corpus sync` derives one at add time, against each corpus.
    undescribed: tuple[str, ...] = ()


def update_pack(
    path: Path,
    *,
    events: EventSink | None = None,
    arxiv: httpx.Client | None = None,
    request_delay_seconds: float | None = None,
) -> PackUpdate:
    """Recompute the generated block of the pack at `path`.

    **A paper is described here** when its entry gives no citekey: the
    citekey, and whichever of title, authors and year it lacks, as `corpus
    add` would derive them, written into the entry so every machine files
    it alike (#459). An entry that has its citekey is never looked up, so a
    pack already described is updated without the network. `arxiv` is the
    client both lookups, arXiv's and doi.org's, use.

    Raises `PackInvalid` when the file does not parse, when this kennis may
    not read it, when a declared source is not a directory, when a file
    under one escapes the pack root, or when the generated block is not the
    last section.

    **`update` refuses where `validate` reports.** A missing source is a
    finding in a report and a refusal in a rewrite: writing an empty digest
    map is indistinguishable from a pack that ships nothing, and section 5
    step 2 treats that claim as authority to delete the user's files.

    **`events` is where this operation has most to say.** The report is one
    line - "2 files recorded" - and the log is the only place that records
    *which* two, and which of them are new, changed or gone since the last
    block. Section 14: the log holds what the report leaves out.
    """
    started = time.monotonic()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PackInvalid(f"{path} could not be read: {error}") from error
    pack = load_pack(text)

    refusal = version_refusal(pack)
    if refusal is not None:
        # A newer schema may nest content differently, so a block written in
        # this kennis's shape would corrupt a file it was told not to read.
        raise PackInvalid(
            f"this pack needs {refusal.kind.replace('-', ' ')} "
            f"({refusal.required}, this is {refusal.available}), "
            "so its generated block has been left alone",
            resolution="uv tool upgrade kennis",
        )

    described, undescribed = _described(
        pack,
        events=events,
        arxiv=arxiv,
        delay=(
            ARXIV_DELAY_SECONDS
            if request_delay_seconds is None
            else request_delay_seconds
        ),
    )
    filled = text
    # Any order: each insertion finds its item in the text as it now is.
    for index, fields in described:
        filled = with_fields(filled, ("corpus", "literature"), index, fields)
    if filled != text:
        # Parsed before it is written, so a defect in the insertion is a
        # refusal rather than a broken file. No test reaches this without
        # such a defect; it is what stopped one while this was written.
        pack = load_pack(filled)
    named = tuple(
        (pack.corpus.literature[index].key, str(dict(fields)["citekey"]))
        for index, fields in described
    )

    content, unselected = _walked(path.parent, pack)
    shipped = _shipped(path.parent, pack)
    previous = pack.generated.content if pack.generated is not None else None
    _reported(events, previous, content, unselected, started)
    block_unchanged = (
        pack.generated is not None
        and previous == content
        and pack.generated.files == shipped
    )
    if block_unchanged and filled == text:
        return PackUpdate(
            path=path,
            outcome="unchanged",
            files=_counted(content) + len(shipped),
            unselected=len(unselected),
            undescribed=undescribed,
        )

    path.write_text(
        filled if block_unchanged else _spliced(filled, content, shipped),
        encoding="utf-8",
        newline="\n",
    )
    return PackUpdate(
        path=path,
        outcome="written",
        files=_counted(content) + len(shipped),
        unselected=len(unselected),
        described=named,
        undescribed=undescribed,
    )


_DESCRIBED: Final = ("citekey", "title", "authors", "year")


def _described(
    pack: Pack,
    *,
    events: EventSink | None,
    arxiv: httpx.Client | None,
    delay: float,
) -> tuple[list[tuple[int, Fields]], tuple[str, ...]]:
    """The fields to write into each paper entry that gives no citekey, by
    its index in `corpus.literature`.

    **The citekey is the reason**: it is the handle the pack's prose cites
    and the one field that must agree on every machine. An entry that gives
    one is fetched at sync as before, and its lookup fills its title,
    authors and year there - so a pack written before this never reaches a
    host from `pack update`. An entry without one is given it, and whatever
    else it lacks, beside what it says.

    Once written, the citekey is the entry's, so the entry is never looked
    up again and a citekey never moves; a newly described paper deriving a
    citekey another entry holds is the one told apart. An arXiv identifier
    is looked up on arXiv and a DOI at its registry, as `corpus add` looks
    each up (Brian, 2026-10-26); a bibcode is described from what its entry
    says, because ADS needs a key kennis does not ask for.

    Each lookup advances `Progress` as it returns, over the lookups owed,
    so a person sees the run move; none is emitted when none is owed.
    """
    found = _looked_up(pack, events=events, arxiv=arxiv, delay=delay)
    taken = {entry.citekey for entry in pack.corpus.literature if entry.citekey}
    described: list[tuple[int, Fields]] = []
    undescribed: list[str] = []
    # In entry order, whatever order the answers came in: of two papers
    # deriving one citekey, the later entry is the one told apart.
    for index, entry in enumerate(pack.corpus.literature):
        if entry.citekey is not None:
            continue
        lacking = [name for name in _DESCRIBED if getattr(entry, name) is None]
        metadata: PaperMetadata | None = None
        if _owes_a_lookup(entry):
            metadata = found[index]
            if metadata is None:
                # Nothing written: a citekey made from the entry's title
                # alone is not the one `corpus add` makes once the lookup
                # answers, and a sync would rename a held paper to it.
                undescribed.append(entry.key)
                continue
        values = _values(entry, metadata, taken)
        if values["citekey"] is None:
            undescribed.append(entry.key)
            continue
        described.append(
            (
                index,
                [
                    (name, value)
                    for name in _DESCRIBED
                    if name in lacking and (value := values[name]) is not None
                ],
            )
        )
    return described, tuple(undescribed)


def _looked_up(
    pack: Pack,
    *,
    events: EventSink | None,
    arxiv: httpx.Client | None,
    delay: float,
) -> dict[int, PaperMetadata | None]:
    """What arXiv and doi.org say of each entry owing a lookup, by its index.

    The DOIs are asked together, since doi.org names no delay and a lookup
    is Crossref's 1 to 10 s (2026-10-27); `courtesy` holds a host to its own
    robots.txt either way. The arXiv identifiers are asked one at a time,
    `delay` apart, as arXiv asks. `Progress` advances as each answer
    arrives, emitted from this thread.
    """
    owed = [
        (index, entry)
        for index, entry in enumerate(pack.corpus.literature)
        if _owes_a_lookup(entry)
    ]
    if events is not None and owed:
        events.emit(Progress(operation=DESCRIBING, completed=0, total=len(owed)))
    looked = 0

    def advance(
        pair: tuple[int, LiteratureEntry], answer: PaperMetadata | None
    ) -> None:
        nonlocal looked
        looked += 1
        if events is not None:
            paper = pair[1].paper
            events.emit(
                ItemFinished(
                    operation=DESCRIBING,
                    item=f"{paper.kind}:{paper.value}",
                    outcome=Outcome.SKIPPED if answer is None else Outcome.CHANGED,
                )
            )
            events.emit(
                Progress(operation=DESCRIBING, completed=looked, total=len(owed))
            )

    dois = [pair for pair in owed if pair[1].paper.kind == "doi"]
    papers = [pair for pair in owed if pair[1].paper.kind == "arxiv"]
    answers = fetched_in_parallel(
        dois,
        lambda pair: lookup_doi_metadata(pair[1].paper.value, client=arxiv),
        on_fetched=advance,
    ) + fetched_in_parallel(
        papers,
        lambda pair: lookup_arxiv_metadata(pair[1].paper.value, client=arxiv),
        workers=1,
        spacing=delay,
        on_fetched=advance,
    )
    return {
        index: metadata
        for (index, _), metadata in zip([*dois, *papers], answers, strict=True)
    }


def _owes_a_lookup(entry: LiteratureEntry) -> bool:
    """Whether describing `entry` asks arXiv or doi.org. A citekey is
    derived from the other three, so a lookup is owed only when one of those
    is missing as well."""
    return (
        entry.citekey is None
        and entry.paper.kind in ("arxiv", "doi")
        and any(getattr(entry, name) is None for name in ("title", "authors", "year"))
    )


class _Values(TypedDict):
    citekey: str | None
    title: str | None
    authors: list[str] | None
    year: int | None


def _values(
    entry: LiteratureEntry, metadata: PaperMetadata | None, taken: set[str]
) -> _Values:
    """The four fields, the entry's own first, and a citekey derived from
    them as `corpus add` derives one."""
    title = entry.title or (metadata.title if metadata else None)
    authors = entry.authors or (
        authors_from_line(metadata.authors) if metadata else None
    )
    year = entry.year or (
        int(metadata.year) if metadata and metadata.year.isdigit() else None
    )
    citekey = entry.citekey
    if citekey is None and (title or authors):
        citekey = unique_citekey(
            derive_citekey(
                authors=joined_names(authors or []),
                year=str(year or ""),
                title=title or "",
            ),
            taken,
        )
        taken.add(citekey)
    return {"citekey": citekey, "title": title, "authors": authors, "year": year}


def _reported(
    events: EventSink | None,
    previous: GeneratedContent | None,
    current: GeneratedContent,
    unselected: list[str],
    started: float,
) -> None:
    """Every shipped file to the stream, with what happened to its digest."""
    if events is None:
        return
    for address in sorted(unselected):
        events.emit(
            ItemFinished(
                operation=OPERATION,
                item=address,
                outcome=Outcome.SKIPPED,
                refusal=Quoted("no include pattern matches it"),
            )
        )
    was = _flattened(previous) if previous is not None else {}
    now = _flattened(current)
    counts: dict[Outcome, int] = (
        {Outcome.SKIPPED: len(unselected)} if unselected else {}
    )
    for address in sorted(set(was) | set(now)):
        outcome = _outcome_for(address, was, now)
        counts[outcome] = counts.get(outcome, 0) + 1
        events.emit(ItemFinished(operation=OPERATION, item=address, outcome=outcome))
    events.emit(
        OperationFinished(
            operation=OPERATION,
            elapsed_seconds=time.monotonic() - started,
            counts=counts,
        )
    )


def _outcome_for(address: str, was: dict[str, str], now: dict[str, str]) -> Outcome:
    if address not in was:
        return Outcome.ADDED
    if address not in now:
        return Outcome.REMOVED
    return Outcome.UNCHANGED if was[address] == now[address] else Outcome.CHANGED


def _flattened(content: GeneratedContent) -> dict[str, str]:
    """Every digest keyed by `section:path`, which is what identifies it.

    **Not by path alone.** A pack may ship one tree to `notes` and to
    `context` - `validate` allows it, because section 5's diff key carries
    the section and the two destinations are distinct - so keying on the
    path would collapse two items into one and under-report the change.
    Flattened only for reporting; the block stays nested.
    """
    return {
        f"{section}:{address_of(entry.source, relative)}": digest
        for section, entries in (("notes", content.notes), ("context", content.context))
        for entry in entries
        for relative, digest in entry.files.items()
    }


def _walked(root: Path, pack: Pack) -> tuple[GeneratedContent, list[str]]:
    """Every declared source read, with the files no pattern took.

    Refuses anything that is not shippable on the way through: a missing
    directory, or a file that escapes the pack root.
    """
    unselected: list[str] = []
    notes = [_entry(root, source, unselected) for source in pack.corpus.note_sources]
    context = [_entry(root, source, unselected) for source in pack.context]
    return GeneratedContent(notes=notes, context=context), unselected


def _shipped(root: Path, pack: Pack) -> dict[str, str]:
    """The checksum of every file a `file:` or `pages:` names.

    Refused on the way through as a source is: a file that is not there
    would be recorded as nothing, and a link is never followed.
    """
    digests: dict[str, str] = {}
    for relative in pack.shipped_files:
        found = read_file(root, relative)
        if found.state == "missing":
            raise PackInvalid(
                f"{relative} is declared and is not a file in the pack",
                resolution=None,
            )
        if found.state != "present" or found.digest is None:
            raise PackInvalid(
                f"{relative} is a symbolic link, and a pack ships files, never "
                "links to them",
                resolution=None,
            )
        digests[relative] = found.digest
    return digests


def _entry(root: Path, source: ContentSource, unselected: list[str]) -> GeneratedSource:
    found = read_source(root, source)
    _refuse_unshippable(found)
    if source.named_files is None:
        # A source naming its files picks a few of a folder on purpose, so
        # the rest are not files a pattern missed.
        unselected.extend(found.unselected)
    return GeneratedSource(source=source.source, files=found.digests)


def _refuse_unshippable(found: SourceContent) -> None:
    """The two states a pack may not be published in."""
    if not found.exists:
        raise PackInvalid(
            f"{found.source} is declared and is not a directory in the pack",
            resolution=None,
        )
    if found.escaping:
        named = ", ".join(found.escaping)
        raise PackInvalid(
            f"{named} resolves outside the pack, and a digest for it would "
            "be a claim about a file the pack does not own",
            resolution=None,
        )


def _counted(content: GeneratedContent) -> int:
    return sum(len(entry.files) for entry in [*content.notes, *content.context])


def _spliced(
    text: str,
    content: GeneratedContent,
    shipped: dict[str, str],
) -> str:
    """The file with its generated block replaced, or gaining one."""
    anchor = _anchor(text)
    head = text if anchor is None else text[:anchor]
    return head.rstrip("\n") + "\n\n" + _rendered(content) + _rendered_shipped(shipped)


def _anchor(text: str) -> int | None:
    """Where the generated block starts, or None when there is not one.

    The marker if it is there, and otherwise a top-level `generated:` line -
    so a block a provider wrote by hand is rewritten rather than duplicated.
    Whichever it is, everything after it must be the block and nothing else.
    """
    found = _sole_index(text, GENERATED_MARKER)
    if found is None:
        found = _sole_index(text, f"\n{_GENERATED_KEY}")
        if found is not None:
            found += 1
    if found is None:
        return None
    _refuse_trailing_content(text[found:])
    return found


def _sole_index(text: str, needle: str) -> int | None:
    """The index of `needle`, refusing a file that holds it twice."""
    count = text.count(needle)
    if count == 0:
        return None
    if count > 1:
        raise PackInvalid(
            f"this file holds `{needle.strip()}` {count} times, and the "
            "generated block is written once at the end",
            resolution=None,
        )
    return text.index(needle)


def _refuse_trailing_content(tail: str) -> None:
    """Refuse when anything but the block sits below the anchor.

    The rewrite replaces from the anchor to the end of the file, so an
    author who moved their own declarations below it would lose them.
    Checked by parsing the tail rather than by scanning for keys, because
    YAML's ways of opening a mapping are more numerous than a scan would
    cover.
    """
    try:
        document = read_yaml(tail)
    except yaml.YAMLError as error:
        raise PackInvalid(
            f"the generated block does not parse on its own: {error}",
            resolution=None,
        ) from error
    if document is None:
        return
    if not isinstance(document, dict) or set(document) != {"generated"}:
        found = ", ".join(sorted(document)) if isinstance(document, dict) else "content"
        raise PackInvalid(
            f"the generated block is not the last section: {found} follows "
            "it, and rewriting the block would replace it",
            resolution=None,
        )


def _rendered(content: GeneratedContent) -> str:
    """The block as text, in the shape design section 7 shows.

    Written out rather than dumped so the marker, the key order and the
    quoting are the ones a reader of the design recognises.
    """
    stamped = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        GENERATED_MARKER,
        "generated:",
        f'  at: "{stamped}"',
        # major.minor.patch of the kennis that wrote the digests. Section 5
        # step 2 compares its major.minor against the running kennis to
        # decide whether materialisation has changed since.
        f'  by: "kennis {__version__}"',
    ]
    sections = [
        (name, entries)
        for name, entries in (("context", content.context), ("notes", content.notes))
        if entries
    ]
    if not sections:
        lines.append("  content: {}")
        return "\n".join(lines) + "\n"
    lines.append("  content:")
    for name, entries in sections:
        lines.append(f"    {name}:")
        for entry in entries:
            lines.append(f"      - source: {entry.source}")
            if not entry.files:
                lines.append("        files: {}")
                continue
            lines.append("        files:")
            for relative, digest in sorted(entry.files.items()):
                lines.append(f'          "{relative}": "{digest}"')
    return "\n".join(lines) + "\n"


def _rendered_shipped(shipped: dict[str, str]) -> str:
    """The shipped files' checksums, and nothing when there are none, so a
    pack shipping no single file keeps its exact bytes."""
    if not shipped:
        return ""
    lines = ["  files:"]
    for relative, digest in sorted(shipped.items()):
        lines.append(f"    {json.dumps(relative)}: {json.dumps(digest)}")
    return "\n".join(lines) + "\n"


__all__ = ["GENERATED_MARKER", "OPERATION", "PackUpdate", "update_pack"]
