"""Getting documents into the corpus.

Notes are the base case of ingestion: anything text-bearing goes in, a
surrogate identifier and a content digest are the whole of its identity, and
there is no natural key to establish. Literature and docs are the same path
with processing layered on top, which is why this module holds the order of
work and they will hold only what they add to it.

**The order of work is the design.**

1. Arguments are expanded into concrete inputs. What a directory walk declined
   is reported, not dropped.
2. The collection is walked **once** into a uniqueness record. Per document it
   would be quadratic, because walking a collection parses every document in
   it.
3. Every local binary file is **hashed and compared against the collection
   before anything is converted**. Re-adding a folder of fifty PDFs then costs
   fifty file reads instead of fifty conversions whose results are thrown
   away. Detecting the duplicate afterwards is correct and expensive; the
   ordering is the whole point.
4. What survives is converted in **runs**, because a converter loads its model
   stack once per process and writes nothing until a run finishes. A run is
   therefore both the unit of progress and the unit lost to an interruption.
5. The write loop walks the inputs in order, taking prepared markdown where
   the batch produced it.

**A batch never aborts on one failure.** One unreachable URL among twenty must
not cost the other nineteen, so every identifier produces an outcome and the
caller reports them together. The exceptions are raised before the batch
starts - an argument naming nothing, a converter that is absent - because
those mean the command as typed cannot be carried out at all.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.converters import Converter, default_converter
from kennis.engine.corpus.document import write_document
from kennis.engine.corpus.ids import mint_id
from kennis.engine.corpus.inputs import ResolvedInputs, resolve_inputs
from kennis.engine.corpus.intake import (
    BINARY_FORMATS,
    Converted,
    convert_local_file,
    convert_url,
    detect_format,
    looks_like_url,
    sha256_of,
)
from kennis.engine.corpus.layout import (
    title_filename,
    title_needs_dot_stripped,
    unique_filename,
)
from kennis.engine.corpus.schema import NoteFrontmatter, Source
from kennis.engine.errors import KennisError
from kennis.engine.events import (
    Diagnostic,
    Event,
    EventSink,
    ItemFinished,
    ItemStarted,
    OperationFinished,
    Outcome,
    Progress,
    Severity,
)


@dataclass(frozen=True, slots=True)
class AddOptions:
    """Everything one add invocation can vary."""

    title: str | None = None
    group: str | None = None
    keep_original: bool = False
    # Extra suffixes a directory walk accepts, beyond the ones kennis knows.
    extra_file_types: tuple[str, ...] = ()
    # How many documents one converter run takes. Zero means one run for the
    # whole batch, which converts fastest and reports nothing until the end.
    batch_size: int = 8


@dataclass(frozen=True, slots=True)
class AddOutcome:
    """What became of one identifier.

    `outcome` is the event stream's own vocabulary rather than a second enum:
    a duplicate is `UNCHANGED`, because the corpus already holds the document
    and nothing was written - the `=` marker that carries no colour, since it
    is the absence of news.
    """

    identifier: str
    outcome: Outcome
    document_id: str | None = None
    title: str | None = None
    path: Path | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AddReport:
    """What one add invocation did, per item and in total."""

    outcomes: list[AddOutcome]
    elapsed_seconds: float

    @property
    def counts(self) -> dict[Outcome, int]:
        tally: dict[Outcome, int] = {}
        for outcome in self.outcomes:
            tally[outcome.outcome] = tally.get(outcome.outcome, 0) + 1
        return tally


class _DiscardingSink:
    """The sink a caller gets when it wants only the report."""

    def emit(self, event: Event) -> None:
        return None


@dataclass
class _Uniqueness:
    """The bookkeeping a batch keeps consistent as it goes.

    Loaded once per batch. Every write updates it in place, so the second
    document in a batch sees the first - which is what makes two files of
    identical content in one command produce one document rather than two.
    """

    identifiers: set[str] = field(default_factory=set)
    filenames: set[str] = field(default_factory=set)
    checksums: dict[str, str] = field(default_factory=dict)

    @classmethod
    def of(cls, collection: Collection) -> _Uniqueness:
        record = cls()
        for document in collection.documents():
            record.identifiers.add(document.id)
            record.filenames.add(_reserved_filename(document.md_path, document))
            checksum = document.frontmatter.source.sha256
            if checksum:
                record.checksums[checksum] = document.id
        return record


def _reserved_filename(md_path: Path, document: object) -> str:
    """The name a document occupies in its parent directory.

    A wrapped document's own file is always `content.md`, so what a new
    document's candidate filename would collide with is the wrapper
    directory's name, not the file inside it.
    """
    wrapper = getattr(document, "wrapper_dir", None)
    if isinstance(wrapper, Path):
        return f"{wrapper.name}.md"
    return md_path.name


@dataclass
class _Plan:
    """Everything settled about a batch's binary documents before writing."""

    # Ready to write, keyed by the path as the caller spelled it.
    converted: dict[Path, Converted] = field(default_factory=dict)
    # Already answered: a duplicate found by checksum, or a document the
    # converter could not convert.
    settled: dict[Path, AddOutcome] = field(default_factory=dict)
    # Page-one text per document, page furniture included. Unused by notes;
    # literature is what reads it.
    front_page: dict[Path, str] = field(default_factory=dict)


def add_notes(
    collection: Collection,
    identifiers: Sequence[str],
    options: AddOptions | None = None,
    *,
    converter: Converter | None = None,
    events: EventSink | None = None,
) -> AddReport:
    """Add local files or URLs to the notes collection.

    Notes extend the base schema with nothing: no natural key, no namespaced
    block. They are addressed by their surrogate identifier and reconciled
    against nothing.
    """
    options = options or AddOptions()
    sink: EventSink = events or _DiscardingSink()
    started_at = time.monotonic()

    resolved = resolve_inputs(identifiers, extra_file_types=options.extra_file_types)
    record = _Uniqueness.of(collection)
    outcomes: list[AddOutcome] = _skipped(resolved, sink)
    plan = _plan_binaries(
        (item.identifier for item in resolved.items),
        record,
        options,
        converter or default_converter(),
        sink,
    )

    for item in resolved.items:
        sink.emit(ItemStarted(operation="add", item=item.identifier))
        outcome = _add_one(
            collection, item.identifier, item.group, record, options, plan, sink
        )
        outcomes.append(outcome)
        sink.emit(
            ItemFinished(
                operation="add",
                item=item.identifier,
                outcome=outcome.outcome,
                reason=outcome.reason,
            )
        )

    report = AddReport(outcomes=outcomes, elapsed_seconds=time.monotonic() - started_at)
    sink.emit(
        OperationFinished(
            operation="add",
            elapsed_seconds=report.elapsed_seconds,
            counts=report.counts,
        )
    )
    return report


def _add_one(
    collection: Collection,
    identifier: str,
    walked_group: str,
    record: _Uniqueness,
    options: AddOptions,
    plan: _Plan,
    sink: EventSink,
) -> AddOutcome:
    """One identifier, from settled-or-converted to written-or-refused."""
    settled = plan.settled.get(Path(identifier).expanduser())
    if settled is not None:
        return replace(settled, identifier=identifier)

    try:
        converted = _convert(identifier, options, plan)
    except KennisError as error:
        return AddOutcome(
            identifier=identifier, outcome=Outcome.FAILED, reason=str(error)
        )

    existing = _duplicate_of(record, converted)
    if existing is not None:
        return AddOutcome(
            identifier=identifier,
            outcome=Outcome.UNCHANGED,
            document_id=existing,
            reason="identical content is already in this collection",
        )

    title = options.title or converted.suggested_title or identifier
    if title_needs_dot_stripped(title):
        sink.emit(
            Diagnostic(
                severity=Severity.WARNING,
                message=(
                    f"title '{title}' looked like a dotfile name; the leading "
                    f"dot was stripped from the filename so it stays visible "
                    f"to search"
                ),
            )
        )

    document_id, path = _write(
        collection,
        record,
        converted=converted,
        title=title,
        group=_group_for(options, walked_group),
    )
    return AddOutcome(
        identifier=identifier,
        outcome=Outcome.ADDED,
        document_id=document_id,
        title=title,
        path=path,
    )


def _write(
    collection: Collection,
    record: _Uniqueness,
    *,
    converted: Converted,
    title: str,
    group: str | None,
) -> tuple[str, Path]:
    """Write one converted source as a note, keeping `record` current."""
    document_id = mint_id(record.identifiers)
    record.identifiers.add(document_id)

    filename = unique_filename(title_filename(title), record.filenames)
    record.filenames.add(filename)

    frontmatter = NoteFrontmatter(
        id=document_id,
        title=title,
        owner="user",
        source=Source(
            origin=converted.origin,
            via=converted.via,
            format=converted.format,
            sha256=converted.sha256,
            original=converted.original_name,
        ),
    )

    assets: dict[str, bytes] | None = None
    if converted.original_bytes is not None and converted.original_name is not None:
        assets = {converted.original_name: converted.original_bytes}

    target_dir = collection.path / group if group else collection.path
    document = write_document(
        target_dir / filename,
        frontmatter=frontmatter,
        body=converted.markdown,
        assets=assets,
    )
    if converted.sha256:
        record.checksums[converted.sha256] = document_id
    return document_id, document.md_path


def _group_for(options: AddOptions, walked: str) -> str | None:
    """Where one walked file lands, given the option and its own subdirectory.

    `group` is a *prefix* rather than an override once a directory is being
    walked: collapsing every file into one flat group would undo the thing the
    mirrored structure is for, which is keeping same-named files - a
    `README.md` per subdirectory - apart.
    """
    if not walked:
        return options.group
    return f"{options.group}/{walked}" if options.group else walked


def _skipped(resolved: ResolvedInputs, sink: EventSink) -> list[AddOutcome]:
    """Files the walk declined, reported rather than dropped in silence."""
    outcomes: list[AddOutcome] = []
    for skip in resolved.skipped:
        outcomes.append(
            AddOutcome(
                identifier=skip.identifier,
                outcome=Outcome.SKIPPED,
                reason=skip.reason,
            )
        )
        sink.emit(
            ItemFinished(
                operation="add",
                item=skip.identifier,
                outcome=Outcome.SKIPPED,
                reason=skip.reason,
            )
        )
    return outcomes


def _convert(identifier: str, options: AddOptions, plan: _Plan) -> Converted:
    """A local path or an http(s) URL becomes markdown."""
    if looks_like_url(identifier):
        return convert_url(identifier, keep_original=options.keep_original)

    path = Path(identifier).expanduser()
    if path.is_file():
        ready = plan.converted.get(path)
        if ready is not None:
            return ready
        return convert_local_file(path, keep_original=options.keep_original)

    raise _Unresolved(
        f"'{identifier}' is not an existing file or an http(s) URL, and no "
        f"resolver recognised it"
    )


class _Unresolved(KennisError):
    """An identifier notes cannot make sense of.

    Collected as a failed outcome rather than raised out of the batch: another
    collection's resolver might have recognised it, and the rest of this batch
    is still worth adding.
    """

    default_resolution = "kennis corpus add --help"


def _duplicate_of(record: _Uniqueness, converted: Converted) -> str | None:
    if converted.sha256 is None:
        return None
    return record.checksums.get(converted.sha256)


def _plan_binaries(
    identifiers: Iterable[str],
    record: _Uniqueness,
    options: AddOptions,
    converter: Converter,
    sink: EventSink,
) -> _Plan:
    """Settle the duplicates and convert the rest, before anything is written."""
    plan = _Plan()
    candidates = _binary_candidates(identifiers, converter)
    pending: list[Path] = []
    for path in candidates:
        existing = record.checksums.get(sha256_of(path.read_bytes()))
        if existing is None:
            pending.append(path)
            continue
        plan.settled[path] = AddOutcome(
            identifier=str(path),
            outcome=Outcome.UNCHANGED,
            document_id=existing,
            reason="identical content is already in this collection",
        )
    if not pending:
        return plan

    runs = list(_conversion_runs(pending, options.batch_size))
    for number, run in enumerate(runs, start=1):
        sink.emit(Progress(operation="add", completed=number, total=len(runs)))
        batch = converter.convert(run)
        for path in run:
            markdown = batch.markdown.get(path)
            if markdown is None:
                plan.settled[path] = AddOutcome(
                    identifier=str(path),
                    outcome=Outcome.FAILED,
                    reason=_nothing_produced(path, batch.failure_reason),
                )
                continue
            plan.converted[path] = convert_local_file(
                path,
                converter=converter,
                keep_original=options.keep_original,
                prepared_markdown=markdown,
            )
            plan.front_page[path] = batch.front_page.get(path, "")
    return plan


def _binary_candidates(identifiers: Iterable[str], converter: Converter) -> list[Path]:
    """The local files in a batch the converter will have to see.

    Deduplicated: the same PDF named twice in one command would otherwise be
    converted twice, to have the second copy rejected as a duplicate of the
    first.
    """
    candidates: dict[Path, None] = {}
    for identifier in identifiers:
        path = Path(identifier).expanduser()
        if path.is_file() and detect_format(path) in BINARY_FORMATS:
            candidates.setdefault(path, None)
    return list(candidates)


def _conversion_runs(paths: Sequence[Path], size: int) -> Iterator[Sequence[Path]]:
    """Split a conversion into runs of `size`, or one run when `size` is zero.

    A converter writes nothing until a run finishes, so one run over a whole
    folder reports no progress and keeps nothing if it is interrupted.
    Chunking costs one extra model load per run and buys both of those back.
    """
    if size <= 0:
        yield paths
        return
    for start in range(0, len(paths), size):
        yield paths[start : start + size]


def _nothing_produced(path: Path, reason: str | None) -> str:
    if reason:
        return f"could not convert '{path.name}': {reason}"
    return (
        f"no markdown was produced for '{path.name}'. "
        f"The file may be empty, encrypted, or an unsupported variant."
    )
