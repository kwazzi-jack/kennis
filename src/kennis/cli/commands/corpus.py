"""`kennis corpus`: everything that reads a corpus, and everything that writes one.

A command chooses **what** to say; `kennis.render` says it. A command that
builds its own sentence is the thing concern #81 was spent removing.

Every command that changes a file does the same three things in the same
order: take the lock, call the engine, commit. The lock is `timeout=0`, so a
second writer is told the corpus is busy rather than left with a terminal
that has stopped. The readers - `status`, `list`, `tree`, `history` - do not
take it, because the command you most want when something is stuck must not
be the one that waits for whatever is stuck.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

import click

from kennis.cli import display
from kennis.cli.group import KennisGroup
from kennis.cli.paths import anchored
from kennis.cli.sink import DisplaySink, marker_for, say_waiting
from kennis.client import api
from kennis.context import existing_corpus, resolve_context
from kennis.engine.corpus.schema import COLLECTION_NAMES

if TYPE_CHECKING:
    from kennis.engine.corpus.add import AddOutcome, AddReport
    from kennis.engine.corpus.sync import CorpusSync
    from kennis.engine.errors import KennisError
    from kennis.engine.history.freshness import Freshness
    from kennis.engine.history.outofband import OutOfBandChange

# Each collection's shorthand flag, for naming it back in an error. The
# options themselves are declared literally on the command.
_SHORTHANDS: Final[dict[str, str]] = {
    "notes": "-n",
    "literature": "-l",
    "docs": "-d",
}

# Which options mean anything for which destination. `--project` is a docs
# natural key and the other two establish a paper's identity, so each is a
# usage error elsewhere rather than a flag that is quietly ignored.
_COLLECTION_ONLY: Final[dict[str, str]] = {
    "--project": "docs",
    "--version": "docs",
    "--refresh": "docs",
    "--citekey": "literature",
    "--identifier": "literature",
}


@click.group(name="corpus", cls=KennisGroup)
def corpus_group() -> None:
    """The machine-global document corpus."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@corpus_group.command(name="init")
def init_command() -> None:
    """Create the corpus and start its history."""
    from kennis.engine.history.repository import initialise_corpus

    context = resolve_context()
    # No lock. There is nothing yet to guard, `initialise_corpus` refuses a
    # root that is already a corpus, and taking one would create the
    # directory and the lock file inside it before git has been located -
    # which is exactly the partially initialised state the plan's first
    # milestone 4 test forbids.
    initialise_corpus(context.corpus_root)
    display.operation("Created", f"corpus at {context.corpus_root}")


@corpus_group.command(name="status")
def status_command() -> None:
    """What the corpus holds, and what has changed since kennis last looked."""
    from kennis.render.words import count_of, describe_change, remedies_for

    status = api.status(existing_corpus().corpus_root)

    total = 0
    indexed = False
    current = True
    for held in status.collections:
        total += len(held.facts)
        display.operation(
            held.collection.capitalize(), count_of(len(held.facts), "document")
        )
        for fact in held.facts:
            # Read through `survey`, the lenient reader, on purpose:
            # `DocumentInvalid` names this command as its resolution, so a
            # status that used the strict reader would die on exactly the
            # corpus it exists to diagnose. Concern #21.
            if fact.problem:
                display.detail("!", f"{fact.md_path.name}: {fact.problem}")
        if held.freshness is not None:
            indexed = True
            current &= _report_freshness(held.freshness, held.collection)

    if total == 0:
        display.note("the corpus has no documents yet")
    elif not indexed:
        # Once for the corpus rather than once per collection: three lines of
        # the same non-news would bury the one thing left to do. Silent on an
        # empty corpus, where the next step is to add documents, not to index
        # nothing.
        display.note("no index yet, so nothing is searchable")
        display.next_step("kennis corpus index")
    elif not current:
        # The same rule the errors follow - name the command that resolves
        # it. A stale or incomplete index was reported and left without one,
        # so a reader was told something was wrong and not what to type.
        # Once, for the same reason as above. Concern #244.
        display.next_step("kennis corpus index")

    for change in status.changes:
        display.detail("~", describe_change(change))
        # design.md: every out-of-band change is reported *alongside the
        # command that would have done it properly*. The sentence without the
        # command leaves a reader knowing something is wrong and not what to
        # type. `remedies_for` produced them and nothing printed them (#128).
        for remedy in remedies_for(change):
            display.next_step(remedy)


def report_restored(restored: Sequence[OutOfBandChange]) -> None:
    """What a restore put back, or nothing at all when it put back nothing."""
    from kennis.render.words import count_of, describe_change

    if not restored:
        return
    display.operation("Restored", count_of(len(restored), "document"))
    for change in restored:
        display.detail("+", describe_change(change))


def _report_freshness(freshness: Freshness, name: str) -> bool:
    """How far this collection's index has fallen behind it, and whether it
    is current - so the caller can say once, rather than three times, what
    is true of the corpus as a whole."""
    from kennis.render.words import describe_freshness

    described = describe_freshness(freshness, name)
    current = freshness.state == "in step" and not freshness.added
    if current:
        # `=` is the marker that carries no colour, which is right: an index
        # that is current is the absence of news.
        display.detail("=", described)
    else:
        # Stale, unverifiable and in-step-with-additions are all things to
        # act on, and a detail line in the same dim column as the good news
        # would not read as one.
        display.note(described)
    return current


@corpus_group.command(name="list")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Only this collection. All three by default.",
)
def list_command(collection: str | None) -> None:
    """Every document in the corpus."""
    from kennis.engine.corpus.schema import COLLECTION_NAMES

    corpus_root = existing_corpus().corpus_root
    shown = 0
    for name in [collection] if collection else list(COLLECTION_NAMES):
        for document in api.contents(corpus_root, name).documents:
            shown += 1
            display.row(document.id, document.md_path.name)
    if shown == 0:
        display.note("no documents")


@corpus_group.command(name="tree")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Only this collection. All three by default.",
)
def tree_command(collection: str | None) -> None:
    """The corpus as the directories it really is, with each document's handle.

    The identifiers come from `survey`, which reads them as plain YAML keys
    and so still has one for a document that fails validation. That is
    deliberate: a tree is a picture of what is on disk, and a document kennis
    cannot read is exactly the one a reader needs to be shown.
    """
    for held in api.tree(existing_corpus().corpus_root, collection):
        display.operation(held.collection.capitalize())
        for entry in held.entries:
            if entry.group:
                display.tree_group(entry.name, entry.depth)
            else:
                display.tree_document(entry.identifier, entry.name, entry.depth)


# ---------------------------------------------------------------------------
# Adding
# ---------------------------------------------------------------------------


@corpus_group.command(name="add")
@click.argument("identifiers", nargs=-1, required=True)
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Where the documents are written. One collection, never all.",
)
@click.option("-n", "--notes", "notes", is_flag=True, help="Shorthand for notes.")
@click.option(
    "-l", "--literature", "literature", is_flag=True, help="Shorthand for literature."
)
@click.option("-d", "--docs", "docs", is_flag=True, help="Shorthand for docs.")
@click.option("--title", help="Title for a single document, overriding what is found.")
@click.option("--group", help="Subdirectory within the collection.")
@click.option(
    "--keep-original/--no-keep-original",
    default=None,
    help="Retain the source bytes beside the markdown.",
)
@click.option("--identifier", help="arXiv id, DOI or bibcode. Literature only.")
@click.option("--citekey", help="Citekey to use instead of a derived one.")
@click.option("--project", help="The docs project a page belongs to. Docs only.")
@click.option(
    "--version",
    "docs_version",
    help=(
        "Which version of the documentation the pages are, such as 2.12 or "
        "latest. Read from the address when not given. Docs only."
    ),
)
@click.option(
    "--refresh",
    is_flag=True,
    help=(
        "Ask the site again for each page already held, and update one that "
        "changed. Docs only."
    ),
)
@click.option("--max-pages", type=int, default=300, show_default=True)
@click.option("--max-depth", type=int, default=5, show_default=True)
def add_command(
    identifiers: tuple[str, ...],
    collection: str | None,
    notes: bool,
    literature: bool,
    docs: bool,
    title: str | None,
    group: str | None,
    keep_original: bool | None,
    identifier: str | None,
    citekey: str | None,
    project: str | None,
    docs_version: str | None,
    refresh: bool,
    max_pages: int,
    max_depth: int,
) -> None:
    """Add files, directories or URLs to one collection."""
    from kennis.engine.corpus.add import AddOptions

    context = existing_corpus()
    destination = _destination(
        collection, notes=notes, literature=literature, docs=docs
    )
    _refuse_foreign_options(
        destination,
        identifier=identifier,
        citekey=citekey,
        project=project,
        docs_version=docs_version,
        refresh=refresh,
    )

    options = AddOptions(
        title=title,
        group=group or context.settings.corpus.default_group or None,
        keep_original=(
            context.settings.corpus.keep_original
            if keep_original is None
            else keep_original
        ),
        identifier=identifier,
        citekey=citekey,
        unpaywall_email=context.settings.literature.unpaywall_email,
        project=project,
        version=docs_version,
        refresh=refresh,
        max_pages=max_pages,
        max_depth=max_depth,
        batch_size=context.settings.conversion.batch_size,
        # arXiv's pacing, for arXiv: a docs host gets its own default. Every
        # caller passed this to every collection, and a 300-page site took
        # a quarter of an hour at three seconds a page.
        request_delay_seconds=(
            context.settings.literature.request_delay
            if destination == "literature"
            else None
        ),
        extra_file_types=(),
    )

    with DisplaySink() as shown:
        written = api.add(
            context.corpus_root,
            destination,
            anchored(identifiers),
            options,
            events=shown,
            on_waiting=say_waiting,
        )

    report_restored(written.restored)
    _report_add(written.result)


def _destination(
    collection: str | None, *, notes: bool, literature: bool, docs: bool
) -> str:
    """The one collection this add writes to.

    `--collection` here names a destination rather than a selection, so it is
    a single choice and never `all`: a document is written to exactly one
    collection. Naming one twice and differently is an error rather than a
    precedence puzzle, because someone who typed both meant one of them and
    kennis cannot tell which.
    """
    from kennis.engine.corpus.schema import COLLECTION_NAMES

    chosen = [
        name
        for name, given in (
            ("notes", notes),
            ("literature", literature),
            ("docs", docs),
        )
        if given
    ]
    if len(chosen) > 1:
        flags = ", ".join(_SHORTHANDS[name] for name in chosen)
        raise display.CliError(f"{flags} name different collections. Pass one of them.")
    shorthand = chosen[0] if chosen else None

    if collection is not None and shorthand is not None and collection != shorthand:
        raise display.CliError(
            f"--collection {collection} and {_SHORTHANDS[shorthand]} name "
            f"different collections. Pass one of them."
        )
    destination = collection or shorthand
    if destination is None:
        raise display.CliError(
            "name a collection: --collection "
            f"{'|'.join(COLLECTION_NAMES)}, or -n/-l/-d."
        )
    return destination


def _refuse_foreign_options(
    destination: str,
    *,
    identifier: str | None,
    citekey: str | None,
    project: str | None,
    docs_version: str | None,
    refresh: bool = False,
) -> None:
    """Refuse an option that means nothing for the collection being written.

    Louder than ignoring it: `--citekey` on a notes add is someone expecting
    a citekey to come out the other end, and silence would let them find that
    out from the corpus instead.
    """
    supplied = {
        "--identifier": identifier is not None,
        "--citekey": citekey is not None,
        "--project": project is not None,
        "--version": docs_version is not None,
        "--refresh": refresh,
    }
    for flag, given in supplied.items():
        owner = _COLLECTION_ONLY[flag]
        if given and owner != destination:
            raise display.CliError(
                f"{flag} applies to {owner} only, not to {destination}."
            )


def _report_add(report: AddReport) -> None:
    """What the add did: one operation line, then the items beneath it.

    Printed from the report rather than streamed from the event stream. A
    docs add of three hundred pages would otherwise put three hundred lines
    above the summary that was the answer; `display.details` caps them, and
    the log has all of them either way.
    """
    from kennis.engine.events import Outcome
    from kennis.render.words import conversion_cost, conversion_repairs, count_of

    counts = report.counts
    # The cost rides on the operation line rather than a line of its own: it
    # is a property of what just happened, and a separate line would give a
    # free local conversion a blank where a number used to be.
    priced = conversion_cost(report.cost_cents)
    repaired = conversion_repairs(report.repairs)
    updated = counts.get(Outcome.CHANGED, 0)
    display.operation(
        "Added",
        count_of(counts.get(Outcome.ADDED, 0), "document")
        + (f", {updated} updated" if updated else "")
        + (f", {priced}" if priced else "")
        + (f", {repaired}" if repaired else ""),
        elapsed=report.elapsed_seconds,
    )
    for outcome in Outcome:
        named = [_named(item) for item in report.outcomes if item.outcome is outcome]
        if named:
            display.details(marker_for(outcome), named)
    _report_remedies(report)


def _named(item: AddOutcome) -> str:
    """One detail line: what it was, and for a failure, why not.

    Only failures carry their reason. A `+` line that also explained
    itself would be noise, and an `=` line saying "identical content is
    already in this collection" repeats what the marker already means.
    A failure is the case where the name alone tells the user nothing
    they can act on - until now the reason went only to the log, which
    is the wrong place for one refused paper even if it is the right
    one for three hundred refused pages. Concern #322.
    """
    from kennis.engine.events import Outcome
    from kennis.render.refusals import describe_refusal

    name = item.title or item.identifier
    if item.outcome is not Outcome.FAILED or item.refusal is None:
        return name
    return f"{name} - {describe_refusal(item.refusal)}"


def _report_remedies(report: AddReport) -> None:
    """The commands that would resolve the failures, each one once.

    Below the items rather than beside them: two papers refused the same
    way share a remedy, and printing it twice invites the user to run it
    twice.
    """
    from kennis.engine.events import Outcome
    from kennis.render.refusals import choices_for_refusal, remedies_for_refusal

    commands: dict[str, None] = {}
    for item in report.outcomes:
        if item.outcome is Outcome.FAILED and item.refusal is not None:
            for command in (
                *choices_for_refusal(item.refusal),
                *remedies_for_refusal(item.refusal),
            ):
                commands.setdefault(command, None)
    for command in commands:
        display.hint(command)


@corpus_group.command(name="sync")
def sync_command() -> None:
    """Converge the corpus with every installed pack.

    Three sections, materialised three ways. A pack's **notes** are
    already in this machine's store, put there by `kennis pack add`, so
    they are copied. Its **papers** are fetched by identifier and its
    **documentation sites** are crawled, so this command uses the
    network - which `kennis pack add` deliberately does not.

    Nothing you own is touched. A pack's note you edited is put back as
    the pack has it, and your edit kept as a new note of yours, so none
    is lost. A paper that cannot be fetched is reported and tried again
    next time, rather than stopping the run.
    """
    from kennis.engine.pack.resolve import ACTING
    from kennis.render.packs import describe_action, describe_sync

    corpus_root = existing_corpus().corpus_root
    with DisplaySink() as shown:
        written = api.sync_corpus(corpus_root, events=shown, on_waiting=say_waiting)
    result = written.result
    report_restored(written.restored)
    display.operation("Synchronised", describe_sync(result.counts, noun="document"))
    for action in result.actions:
        display.detail(
            display.sync_marker(action.verdict),
            describe_action(action, result.places.get(action.address)),
        )
    _report_what_a_sync_left(result)
    if any(action.verdict in ACTING for action in result.actions):
        display.next_step("kennis corpus index")


def _report_what_a_sync_left(result: CorpusSync) -> None:
    """The two things a sync did not do, each said once above nothing."""
    from kennis.render.packs import (
        describe_deferred,
        describe_kept_copies,
        describe_kept_copy,
        describe_unfetched,
        describe_why_unfetched,
    )

    if result.copied:
        display.guidance(describe_kept_copies(len(result.copied)))
        # Named per document: the handle is the only way to address a
        # corpus document.
        for original, copy in result.copied:
            display.detail("+", describe_kept_copy(original, copy))
    if result.deferred:
        display.note(describe_deferred(result.deferred))
    if result.failed:
        # A failure is not a verdict: the declaration still stands and
        # the document is still absent, so the next run tries again.
        # Named rather than counted, because which paper did not arrive
        # is the whole of what a reader needs.
        display.note(describe_unfetched(result.failed))
        for address, refusal in result.why:
            display.hint(describe_why_unfetched(address, refusal))


@corpus_group.command(name="copy")
@click.argument("handle")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Look only here. All three by default.",
)
def copy_command(handle: str, collection: str | None) -> None:
    """Make your own version of a document: a new note of yours.

    For what kennis obtained - a pack's note, a documentation page - which
    is not edited in place: the copy has its own identifier, records what
    it was copied from, and is yours to change. The original is untouched.
    """
    written = api.copy_document(existing_corpus().corpus_root, handle, collection)
    report_restored(written.restored)
    document = written.result
    display.operation("Copied", f"{document.frontmatter.title} as {document.id}")
    display.next_step("kennis corpus index", note="to search it")


# ---------------------------------------------------------------------------
# Removing and moving
# ---------------------------------------------------------------------------


@corpus_group.command(name="remove")
@click.argument("handle", required=False)
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Look only here. All three by default.",
)
@click.option(
    "--project",
    help="With --version: remove that version of a docs project, every page of it.",
)
@click.option(
    "--version",
    "docs_version",
    help="With --project: the docs version to remove.",
)
@click.option("-y", "--yes", is_flag=True, help="Do not ask first.")
def remove_command(
    handle: str | None,
    collection: str | None,
    project: str | None,
    docs_version: str | None,
    yes: bool,
) -> None:
    """Delete a document, and its assets when it has any, or every page of
    one version of a docs project."""
    corpus_root = existing_corpus().corpus_root
    if project is not None or docs_version is not None:
        if handle is not None:
            raise display.CliError(
                "name a document or a docs version (--project and --version), not both."
            )
        if project is None or docs_version is None:
            raise display.CliError(
                "--project and --version name a docs version together: pass both."
            )
        _remove_docs_version(corpus_root, project, docs_version, yes=yes)
        return
    if handle is None:
        raise display.CliError(
            "name the document to remove, or a docs version with --project "
            "and --version."
        )
    found = api.found(corpus_root, handle, collection)
    document = found.document

    if not yes:
        # Recoverable through `corpus restore`, so this is a courtesy rather
        # than the last line of defence - but a wrapped document takes its
        # assets with it, and that is worth one keystroke.
        click.confirm(
            f"Remove '{document.frontmatter.title}' from {found.collection}?",
            abort=True,
        )

    # By identifier and in the collection it was found in: what was asked
    # about is what is removed, even if a name changed meanwhile.
    api.remove_document(corpus_root, document.id, found.collection)
    display.operation("Removed", f"{document.id}  {document.frontmatter.title}")


def _remove_docs_version(
    corpus_root: Path, project: str, version: str, *, yes: bool
) -> None:
    from kennis.render.words import count_of, describe_current_version

    pages = api.version_pages(corpus_root, project, version)
    if not yes:
        click.confirm(
            f"Remove {project} {version}, {count_of(pages, 'document')}, from docs?",
            abort=True,
        )
    removed = api.remove_version(corpus_root, project, version).result
    display.operation(
        "Removed", f"{project} {version}, {count_of(removed.pages, 'document')}"
    )
    if removed.current is not None:
        display.note(describe_current_version(project, removed.current))


@corpus_group.command(name="version")
@click.argument("project", required=False)
@click.argument("version", required=False)
def version_command(project: str | None, version: str | None) -> None:
    """List the versions of each docs project held, or choose the one a
    search uses by default.

    With no argument, every project; with a project, its versions; with a
    project and a version, that version becomes the one searched unless a
    search names others with --version.
    """
    from kennis.render.words import NO_DOCS_VERSIONS, describe_held_versions

    corpus_root = existing_corpus().corpus_root
    if project is not None and version is not None:
        api.make_version_current(corpus_root, project, version)
        display.operation("Current", f"{project} {version}")
        return
    held = api.docs_versions(corpus_root)
    if project is not None:
        if project not in held:
            raise display.CliError(
                f"no versions of '{project}' are held"
                + (f" - projects with versions: {', '.join(held)}" if held else "")
            )
        held = {project: held[project]}
    if not held:
        display.note(NO_DOCS_VERSIONS)
        return
    for name, versions in held.items():
        display.row(name, describe_held_versions(versions))


@corpus_group.command(name="move")
@click.argument("handle")
@click.option("--group", help="The subdirectory to move it into. Empty for the root.")
@click.option("--title", help="A new title, which renames the file with it.")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Look only here. All three by default.",
)
@click.option("--to-collection", type=click.Choice(COLLECTION_NAMES), hidden=True)
def move_command(
    handle: str,
    group: str | None,
    title: str | None,
    collection: str | None,
    to_collection: str | None,
) -> None:
    """Relocate or rename a document, keeping its identifier."""
    corpus_root = existing_corpus().corpus_root
    if to_collection is not None:
        # The design allows a document to move between collections - to notes
        # drops the extra metadata, out of notes requires it to be
        # establishable - but `move_document` keeps the collection fixed, so
        # v0.1 says so rather than half-doing it. Concern #93.
        raise display.CliError(
            "moving between collections is not supported yet; "
            "remove the document and add it to the other collection."
        )
    if group is None and title is None:
        raise display.CliError("nothing to change: pass --group, --title, or both.")

    written = api.move_document(
        corpus_root, handle, group=group, title=title, collection=collection
    )
    report_restored(written.restored)
    moved = written.result
    # Forward slashes on every system, as a document is addressed everywhere
    # else (`layout.relative_to_corpus`); Windows printed backslashes (#532).
    within = moved.md_path.relative_to(corpus_root / moved.collection).as_posix()
    display.operation("Moved", f"{moved.id}  {within}")


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


@corpus_group.command(name="index")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Only this collection. All three by default.",
)
def index_command(collection: str | None) -> None:
    """Build the search index for one collection or all of them."""
    from kennis.engine.rag.binding import binding_from
    from kennis.render.words import count_of, describe_busy_indexes

    context = existing_corpus()
    binding = binding_from(context.settings.chunking, context.settings.embedding)

    # Named before the work starts, because a dense build downloads a model on
    # a machine that has never run one and a long pause needs its explanation
    # already on screen rather than afterwards.
    display.using(
        f"{binding.model.kind} {binding.model.model}"
        if binding.model
        else "lexical search only, with no embedding backend"
    )

    with DisplaySink() as shown:
        written = api.index(
            context.corpus_root, collection, events=shown, on_waiting=say_waiting
        )
    result = written.result

    report_restored(written.restored)
    for index in result.built:
        display.operation(
            "Indexed",
            f"{count_of(index.documents, 'document')} as "
            f"{count_of(index.chunks, 'chunk')} in {index.collection}",
            elapsed=index.elapsed_seconds,
        )

    if result.busy:
        # Before the emptiness note, and instead of it: a build that
        # reached no collection reports zero documents, and "nothing to
        # index" at a corpus that is full is a false statement rather
        # than an unhelpful one. Concern #331.
        display.note(describe_busy_indexes(result.busy))
        display.next_step("kennis corpus index", note="when it has finished")
    elif result.documents == 0:
        display.note("nothing to index")
        display.next_step("kennis corpus add --help", note="to see what it takes")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@corpus_group.command(name="history")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Only commits touching this collection.",
)
@click.option("--limit", type=int, default=20, show_default=True)
def history_command(collection: str | None, limit: int) -> None:
    """What kennis did to this corpus, newest first."""
    entries = api.history(existing_corpus().corpus_root, collection, limit)
    if not entries:
        display.note("nothing recorded yet")
        return
    for entry in entries:
        # The short commit is the identifier here: it is what `corpus
        # restore` takes, so it belongs in the column a reader copies from.
        display.row(
            entry.commit[:8],
            f"{entry.when:%Y-%m-%d %H:%M}  "
            f"{entry.operation or '-'}({entry.scope or '-'}): {entry.summary}",
        )


@corpus_group.command(name="restore")
@click.argument("document_id")
@click.option(
    "--commit", "commit", default="HEAD", show_default=True, help="Restore from here."
)
def restore_command(document_id: str, commit: str) -> None:
    """Put a document back as it was at a commit."""
    restored = api.restore_document(
        existing_corpus().corpus_root, document_id, commit
    ).result
    display.operation("Restored", f"{restored.document_id} from {restored.commit[:8]}")


@corpus_group.command(name="return")
@click.argument("commit")
@click.option("-y", "--yes", is_flag=True, help="Do not ask first.")
def return_command(commit: str, yes: bool) -> None:
    """Make the corpus's documents as they were at a point in its history.

    COMMIT is a point `kennis corpus history` lists. Anything not yet
    recorded is recorded first, and the return is itself recorded, so
    returning to the point before it undoes it. The index is left as built:
    rebuild it to search what is held afterwards.
    """
    from kennis.render.words import (
        RETURN_NEEDS_AN_INDEX,
        describe_return_changes,
        describe_returned,
    )

    corpus_root = existing_corpus().corpus_root
    changes = api.return_preview(corpus_root, commit)
    lines = describe_return_changes(changes)
    if changes.nothing:
        display.note(lines[0])
        return
    for line in lines:
        display.detail("~", line)
    if not yes:
        click.confirm(
            f"Return the corpus to {changes.commit[:8]}?", abort=True, default=False
        )
    returned = api.return_corpus(corpus_root, changes.commit).result
    display.operation(
        "Returned",
        describe_returned(
            returned.commit,
            added=returned.added,
            removed=returned.removed,
            changed=returned.changed,
        ),
    )
    if returned.added or returned.removed or returned.changed:
        display.next_step("kennis corpus index", note=RETURN_NEEDS_AN_INDEX)


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


__all__ = ["KennisError", "corpus_group"]
