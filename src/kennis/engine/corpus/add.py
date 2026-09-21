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

import httpx

from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.converters import Converter, default_converter
from kennis.engine.corpus.document import write_document
from kennis.engine.corpus.ids import (
    derive_id,
    mint_id,
    natural_key_for_literature,
)
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
from kennis.engine.corpus.schema import (
    Bibliography,
    LiteratureFrontmatter,
    NoteFrontmatter,
    Source,
)
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
from kennis.engine.literature.citekeys import derive_citekey, unique_citekey
from kennis.engine.literature.identifiers import (
    BibEntry,
    PaperIdentifier,
    find_paper_identifiers,
    identifier_if_reference,
    looks_like_bibtex,
    parse_bibtex_file,
)
from kennis.engine.literature.metadata import (
    lookup_arxiv_metadata,
    resolve_doi_to_arxiv,
)


@dataclass(frozen=True, slots=True)
class AddOptions:
    """Everything one add invocation can vary."""

    title: str | None = None
    group: str | None = None
    keep_original: bool = False
    # An arXiv identifier, DOI or bibcode supplied by hand for a paper that
    # does not state one on its own first page. Literature only.
    identifier: str | None = None
    citekey: str | None = None
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
    # Citekeys in use, so a derived one can be disambiguated against them.
    citekeys: set[str] = field(default_factory=set)
    # A lower-cased arXiv identifier, DOI or bibcode to the document holding
    # it. The only thing that catches the same paper reached by two routes: a
    # `.bib` entry and a bare arXiv identifier derive different citekeys and
    # share no source bytes, so neither the citekey nor the checksum can.
    identities: dict[str, str] = field(default_factory=dict)

    # Documents the survey could not validate, one line each. Reported as
    # diagnostics rather than dropped: a corpus served nine tenths of in
    # silence is worse than one that says what is wrong.
    problems: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, collection: Collection) -> _Uniqueness:
        """Built from the survey rather than from validated documents.

        A document kennis cannot validate still holds an identifier and a
        checksum that are plain YAML keys, and both have to stay reserved:
        skipping it would let `mint_id` reissue its identifier, and would make
        a re-add of its source write a second copy instead of reporting a
        duplicate. Its filename is reserved even when its YAML will not parse
        at all and there is nothing else to read.
        """
        record = cls()
        for facts in collection.survey():
            record.filenames.add(facts.reserved_filename)
            if facts.citekey:
                record.citekeys.add(facts.citekey)
            if facts.identifier:
                record.identifiers.add(facts.identifier)
                if facts.checksum:
                    record.checksums[facts.checksum] = facts.identifier
                for identity in facts.identities:
                    record.identities[identity] = facts.identifier
            if facts.problem:
                record.problems.append(facts.problem)
        return record


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
    _report_problems(record, sink)
    outcomes: list[AddOutcome] = _skipped(resolved, sink)
    plan = _plan_binaries(
        _binary_candidates(item.identifier for item in resolved.items),
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


def _report_problems(record: _Uniqueness, sink: EventSink) -> None:
    """Say what the collection holds that kennis could not read.

    Reported rather than dropped, and reported without stopping: a corpus
    served nine tenths of in silence is worse than one that says what is
    wrong, but being told must not cost the operation.
    """
    for problem in record.problems:
        sink.emit(
            Diagnostic(
                severity=Severity.WARNING,
                message=f"{problem} - it was left alone",
                resolution="kennis corpus status",
            )
        )


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
    candidates: Sequence[Path],
    record: _Uniqueness,
    options: AddOptions,
    converter: Converter,
    sink: EventSink,
) -> _Plan:
    """Settle the duplicates and convert the rest, before anything is written."""
    plan = _Plan()
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


def _binary_candidates(identifiers: Iterable[str]) -> list[Path]:
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


# ---------------------------------------------------------------------------
# literature: notes plus bibliographic processing
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Paper:
    """One paper a batch will try to add, before its identity is settled."""

    identifier: str
    group: str = ""
    # A local document to convert, when there is one. A `.bib` entry may name
    # one through its `file =` field.
    path: Path | None = None
    # The entry this came from, when the argument was a `.bib`.
    entry: BibEntry | None = None
    # An identity the argument itself stated, rather than one read off a page.
    stated: PaperIdentifier | None = None


def add_literature(
    collection: Collection,
    identifiers: Sequence[str],
    options: AddOptions | None = None,
    *,
    converter: Converter | None = None,
    events: EventSink | None = None,
    arxiv: httpx.Client | None = None,
) -> AddReport:
    """Add papers to the literature collection.

    Literature is notes plus bibliographic processing: the same ingestion,
    then identifier extraction, arXiv resolution, citekey derivation and a
    `bib` block. It **refuses a document whose identity it cannot establish**,
    because an invented citekey cites nothing and duplicate detection has
    nothing to compare, so the same paper reached by another route lands
    twice.

    `arxiv` is the client the metadata lookups use, so a caller with no
    network - a test, an offline run - supplies one that says so.
    """
    options = options or AddOptions()
    sink: EventSink = events or _DiscardingSink()
    started_at = time.monotonic()

    resolved = resolve_inputs(identifiers, extra_file_types=options.extra_file_types)
    record = _Uniqueness.of(collection)
    _report_problems(record, sink)
    outcomes: list[AddOutcome] = _skipped(resolved, sink)

    papers, refused = _papers_of(resolved)
    outcomes.extend(refused)
    plan = _plan_binaries(
        [paper.path for paper in papers if paper.path is not None],
        record,
        options,
        converter or default_converter(),
        sink,
    )

    for paper in papers:
        sink.emit(ItemStarted(operation="add", item=paper.identifier))
        outcome = _add_paper(collection, paper, record, options, plan, arxiv)
        outcomes.append(outcome)
        sink.emit(
            ItemFinished(
                operation="add",
                item=paper.identifier,
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


def _papers_of(resolved: ResolvedInputs) -> tuple[list[_Paper], list[AddOutcome]]:
    """Classify each resolved input, expanding any `.bib` file into entries.

    The second expansion point in one command - `resolve_inputs` already
    turned a directory into files - and it is here rather than there because
    only literature knows what a `.bib` is.
    """
    papers: list[_Paper] = []
    refused: list[AddOutcome] = []
    for item in resolved.items:
        path = Path(item.identifier).expanduser()

        if looks_like_bibtex(item.identifier) and path.is_file():
            papers.extend(_papers_of_bibtex(path, item.group))
            continue

        stated = identifier_if_reference(item.identifier)
        if stated is not None:
            papers.append(
                _Paper(identifier=item.identifier, group=item.group, stated=stated)
            )
            continue

        if path.is_file():
            papers.append(
                _Paper(identifier=item.identifier, group=item.group, path=path)
            )
            continue

        refused.append(
            AddOutcome(
                identifier=item.identifier,
                outcome=Outcome.FAILED,
                reason=(
                    f"'{item.identifier}' is not an existing file, an arXiv "
                    f"identifier, a DOI or an ADS bibcode"
                ),
            )
        )
    return papers, refused


def _papers_of_bibtex(path: Path, group: str) -> list[_Paper]:
    """One paper per entry, following a `file =` field to a local document."""
    papers: list[_Paper] = []
    for entry in parse_bibtex_file(path):
        document = Path(entry.file_path).expanduser() if entry.file_path else None
        papers.append(
            _Paper(
                identifier=f"{path}:{entry.citekey}",
                group=group,
                path=document if document is not None and document.is_file() else None,
                entry=entry,
                stated=_stated_by(entry),
            )
        )
    return papers


def _stated_by(entry: BibEntry) -> PaperIdentifier | None:
    """The identity a `.bib` entry states, by the standing precedence."""
    if entry.arxiv_id:
        return PaperIdentifier(kind="arxiv", value=entry.arxiv_id)
    if entry.doi:
        return PaperIdentifier(kind="doi", value=entry.doi)
    return None


@dataclass(frozen=True, slots=True)
class _Identity:
    """What a paper turned out to be."""

    arxiv_id: str | None = None
    doi: str | None = None
    bibcode: str | None = None
    title: str = ""
    authors: str = ""
    year: str = ""

    @property
    def natural_key(self) -> str | None:
        return natural_key_for_literature(
            arxiv_id=self.arxiv_id, doi=self.doi, bibcode=self.bibcode
        )

    @property
    def values(self) -> tuple[str, ...]:
        found = (self.arxiv_id, self.doi, self.bibcode)
        return tuple(value.lower() for value in found if value)


def _add_paper(
    collection: Collection,
    paper: _Paper,
    record: _Uniqueness,
    options: AddOptions,
    plan: _Plan,
    arxiv: httpx.Client | None,
) -> AddOutcome:
    """One paper, from identity to written-or-refused."""
    settled = plan.settled.get(paper.path) if paper.path is not None else None
    if settled is not None:
        return replace(settled, identifier=paper.identifier)

    stated = (
        identifier_if_reference(options.identifier)
        if options.identifier
        else paper.stated
    )
    front_page = plan.front_page.get(paper.path, "") if paper.path is not None else ""
    chosen, ambiguous = _choose_identity(stated, front_page)
    if chosen is None:
        return AddOutcome(
            identifier=paper.identifier,
            outcome=Outcome.FAILED,
            reason=_no_identity_reason(paper, ambiguous),
        )

    identity = _enrich(chosen, paper.entry, arxiv)
    existing = _duplicate_identity(record, identity)
    if existing is not None:
        return AddOutcome(
            identifier=paper.identifier,
            outcome=Outcome.UNCHANGED,
            document_id=existing,
            reason="this paper is already in this collection",
        )

    converted = _converted_for(paper, identity, options, plan)
    if isinstance(converted, AddOutcome):
        return converted

    by_checksum = _duplicate_of(record, converted)
    if by_checksum is not None:
        return AddOutcome(
            identifier=paper.identifier,
            outcome=Outcome.UNCHANGED,
            document_id=by_checksum,
            reason="identical content is already in this collection",
        )

    title = (
        options.title or identity.title or converted.suggested_title or paper.identifier
    )
    citekey = _citekey_for(paper, identity, title, record, options)
    document_id, path = _write_paper(
        collection,
        record,
        converted=converted,
        title=title,
        citekey=citekey,
        identity=identity,
        group=_group_for(options, paper.group),
    )
    return AddOutcome(
        identifier=paper.identifier,
        outcome=Outcome.ADDED,
        document_id=document_id,
        title=title,
        path=path,
    )


def _choose_identity(
    stated: PaperIdentifier | None, front_page: str
) -> tuple[PaperIdentifier | None, list[PaperIdentifier]]:
    """The one identifier that names this paper, or why there is none.

    An answer from a person - typed as the argument, supplied with
    `--identifier`, or carried by a `.bib` entry - wins outright. Otherwise
    the front page decides, and only when it is unambiguous.

    **Precedence between kinds is not a guess.** One arXiv identifier and one
    DOI resolve to arXiv, because that is the precedence milestone 1 already
    wrote down and recorded in `id_from`. Two candidates *of the same kind* is
    a guess, because one of them is likely something the paper cites and no
    pattern work distinguishes them, so both are handed back for the caller to
    report.
    """
    if stated is not None:
        return stated, []
    candidates = find_paper_identifiers(front_page)
    if not candidates:
        return None, []
    best = candidates[0].kind
    of_kind = [found for found in candidates if found.kind == best]
    if len(of_kind) > 1:
        return None, of_kind
    return of_kind[0], []


def _no_identity_reason(paper: _Paper, ambiguous: list[PaperIdentifier]) -> str:
    """Why a paper cannot enter literature, and the two ways out.

    Notes is a real answer here, not a consolation prize: notes have no
    natural key *by design*, so a document with no bibliographic identity is
    exactly what that collection is for.
    """
    named = paper.path or paper.identifier
    if ambiguous:
        offered = ", ".join(found.value for found in ambiguous)
        return (
            f"its first page offers more than one {ambiguous[0].kind} identifier "
            f"({offered}) and kennis cannot tell which names the paper. Settle "
            f"it with --identifier, or add it as a note instead: "
            f"kennis corpus add -n '{named}'"
        )
    return (
        f"no arXiv id, DOI or ADS bibcode found on its first page, so it has "
        f"no bibliographic identity and cannot go to literature. Supply one "
        f"with --identifier, or add it as a note instead: "
        f"kennis corpus add -n '{named}'"
    )


def _enrich(
    chosen: PaperIdentifier, entry: BibEntry | None, arxiv: httpx.Client | None
) -> _Identity:
    """Turn one identifier into everything known about the paper.

    A DOI is resolved only as far as an arXiv preprint and a bibcode not at
    all - those need Crossref metadata or an ADS key, neither of which kennis
    asks anyone for. All three are recorded regardless, because identity is
    what duplicate detection runs on even when metadata is unavailable.
    """
    if chosen.kind == "bibcode":
        return _Identity(
            bibcode=chosen.value,
            title=entry.title if entry else "",
            authors=entry.authors if entry else "",
            year=entry.year if entry else "",
        )

    doi = chosen.value if chosen.kind == "doi" else (entry.doi if entry else None)
    arxiv_id = chosen.value if chosen.kind == "arxiv" else None
    if arxiv_id is None and doi is not None:
        arxiv_id = resolve_doi_to_arxiv(doi, client=arxiv)

    title = entry.title if entry else ""
    authors = entry.authors if entry else ""
    year = entry.year if entry else ""
    if arxiv_id is not None and not (title and authors and year):
        metadata = lookup_arxiv_metadata(arxiv_id, client=arxiv)
        if metadata is not None:
            title = title or metadata.title
            authors = authors or metadata.authors
            year = year or metadata.year

    return _Identity(
        arxiv_id=arxiv_id, doi=doi, title=title, authors=authors, year=year
    )


def _duplicate_identity(record: _Uniqueness, identity: _Identity) -> str | None:
    """The document already holding any of this paper's identifiers."""
    for value in identity.values:
        existing = record.identities.get(value)
        if existing is not None:
            return existing
    return None


def _converted_for(
    paper: _Paper, identity: _Identity, options: AddOptions, plan: _Plan
) -> Converted | AddOutcome:
    """The markdown for one paper, or the outcome that says there is none.

    A paper named only by its identifier has no local document yet - fetching
    the preprint is a later milestone - so what is written is a stub carrying
    the bibliography. That is what makes a citekey citeable before the text
    arrives.
    """
    if paper.path is None:
        return Converted(
            markdown=_stub(identity),
            via="verbatim",
            format="markdown",
            origin=_origin_of(identity, paper),
            sha256=None,
        )
    prepared = plan.converted.get(paper.path)
    try:
        return convert_local_file(
            paper.path,
            keep_original=options.keep_original,
            prepared_markdown=prepared.markdown if prepared is not None else None,
        )
    except KennisError as error:
        return AddOutcome(
            identifier=paper.identifier, outcome=Outcome.FAILED, reason=str(error)
        )


def _origin_of(identity: _Identity, paper: _Paper) -> str:
    if identity.arxiv_id:
        return f"arxiv:{identity.arxiv_id}"
    if identity.doi:
        return f"doi:{identity.doi}"
    if identity.bibcode:
        return f"bibcode:{identity.bibcode}"
    return paper.identifier


def _stub(identity: _Identity) -> str:
    """The body of a paper whose text has not been fetched yet."""
    lines = [f"# {identity.title}" if identity.title else "# Untitled", ""]
    if identity.authors:
        lines.append(f"{identity.authors}")
    if identity.year:
        lines.append(f"{identity.year}")
    lines.append("")
    lines.append("The text of this paper has not been fetched.")
    lines.append("")
    return "\n".join(lines)


def _citekey_for(
    paper: _Paper,
    identity: _Identity,
    title: str,
    record: _Uniqueness,
    options: AddOptions,
) -> str:
    """The paper's citekey: its own if it has one, derived otherwise.

    **A `.bib` entry keeps its own.** That key is what the user's own
    bibliography already cites, and deriving a new one would break every
    reference in their writing. Derivation is for a paper that arrived without
    one - a bare arXiv identifier, or a PDF with no bibliography.
    """
    base = (
        options.citekey
        or (paper.entry.citekey if paper.entry else None)
        or derive_citekey(authors=identity.authors, year=identity.year, title=title)
    )
    return unique_citekey(base, record.citekeys)


def _write_paper(
    collection: Collection,
    record: _Uniqueness,
    *,
    converted: Converted,
    title: str,
    citekey: str,
    identity: _Identity,
    group: str | None,
) -> tuple[str, Path]:
    """Write one paper, keeping `record` current.

    The surrogate identifier is **derived from the natural key**, not minted:
    two machines that fetch the same paper then write byte-identical files and
    git has nothing to resolve. `id_from` records which key it came from, so
    the derivation is auditable rather than guessable.
    """
    natural_key = identity.natural_key
    document_id = derive_id(natural_key) if natural_key else mint_id(record.identifiers)
    record.identifiers.add(document_id)
    record.citekeys.add(citekey)
    for value in identity.values:
        record.identities[value] = document_id

    filename = unique_filename(title_filename(title), record.filenames)
    record.filenames.add(filename)

    frontmatter = LiteratureFrontmatter(
        id=document_id,
        title=title,
        owner="user",
        id_from=natural_key,
        source=Source(
            origin=converted.origin,
            via=converted.via,
            format=converted.format,
            sha256=converted.sha256,
            original=converted.original_name,
        ),
        bib=Bibliography(
            citekey=citekey,
            authors=identity.authors or None,
            year=identity.year or None,
            doi=identity.doi,
            arxiv_id=identity.arxiv_id,
            bibcode=identity.bibcode,
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
