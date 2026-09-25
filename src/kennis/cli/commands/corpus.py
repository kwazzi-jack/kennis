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

from collections.abc import Callable
from pathlib import Path
from typing import Final

import click

from kennis.cli import display
from kennis.cli.context import Context, existing_corpus, resolve_context
from kennis.cli.group import KennisGroup
from kennis.cli.resolve import resolve_document
from kennis.cli.sink import marker_for, reporting
from kennis.engine.corpus.add import (
    AddOptions,
    AddReport,
    add_docs,
    add_literature,
    add_notes,
)
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.document import Document, move_document
from kennis.engine.corpus.layout import index_root, title_filename, unique_filename
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import KennisError
from kennis.engine.events import Outcome
from kennis.engine.history.freshness import index_freshness
from kennis.engine.history.history import (
    commit_summary,
    outcome_summary,
    read_history,
    restore_document,
)
from kennis.engine.history.outofband import detect_changes, restore_deletions
from kennis.engine.history.repository import Repository, initialise_corpus
from kennis.engine.locking import corpus_lock
from kennis.engine.rag.binding import binding_from
from kennis.engine.rag.index import build_index, read_manifest
from kennis.engine.rag.loaders import CollectionLoader
from kennis.render.words import (
    conversion_cost,
    conversion_repairs,
    count_of,
    describe_change,
    describe_freshness,
    remedies_for,
)

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
    "--citekey": "literature",
    "--identifier": "literature",
}

_ADDERS: Final[dict[str, Callable[..., AddReport]]] = {
    "notes": add_notes,
    "literature": add_literature,
    "docs": add_docs,
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
    context = existing_corpus()
    repository = Repository(context.corpus_root)

    total = 0
    indexed = False
    current = True
    for name in COLLECTION_NAMES:
        facts = Collection(root=context.corpus_root, name=name).survey()
        total += len(facts)
        display.operation(name.capitalize(), count_of(len(facts), "document"))
        for fact in facts:
            # Read through `survey`, the lenient reader, on purpose:
            # `DocumentInvalid` names this command as its resolution, so a
            # status that used the strict reader would die on exactly the
            # corpus it exists to diagnose. Concern #21.
            if fact.problem:
                display.detail("!", f"{fact.md_path.name}: {fact.problem}")
        built, in_step = _report_freshness(context, repository, name)
        indexed |= built
        current &= in_step

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

    for change in detect_changes(repository):
        display.detail("~", describe_change(change))
        # design.md: every out-of-band change is reported *alongside the
        # command that would have done it properly*. The sentence without the
        # command leaves a reader knowing something is wrong and not what to
        # type. `remedies_for` produced them and nothing printed them (#128).
        for remedy in remedies_for(change):
            display.next_step(remedy)


def _undo_hand_deletions(context: Context) -> None:
    """Put back anything deleted outside kennis, before this command writes.

    design.md, "Changes made outside kennis": **a deletion is restored rather
    than honoured**. An out-of-band delete carries no record of intent, and
    treating an accident as an instruction is the more expensive mistake -
    restoring costs an annoying extra command, honouring costs a document.
    `corpus remove` exists and says what it means.

    Here rather than in `status`, which reports and never writes. So the
    restore happens at the start of every command that already holds the lock
    and is about to commit. Without it the deletion is not merely unnoticed:
    the next `_commit` stages it, and the accident becomes history. Concern
    #128.

    Must be called **inside** the lock and **before** the operation, so that
    the command's own commit carries a tree the deletion never touched.
    """
    repository = Repository(context.corpus_root)
    restored = [
        change
        for change in restore_deletions(repository, detect_changes(repository))
        if change.restored
    ]
    if not restored:
        return
    display.operation("Restored", count_of(len(restored), "document"))
    for change in restored:
        display.detail("+", describe_change(change))


def _report_freshness(
    context: Context, repository: Repository, name: str
) -> tuple[bool, bool]:
    """How far this collection's index has fallen behind it, if it has one.

    Returns whether there was an index to report on, and whether it is
    current - both so the caller can say once, rather than three times, what
    is true of the corpus as a whole: that it has never been indexed, or
    that something in it needs rebuilding.
    """
    manifest = read_manifest(index_root(context.corpus_root), name)
    if manifest is None:
        return False, True
    freshness = index_freshness(
        repository,
        collection=name,
        built_from=manifest.built_from,
        # What the index actually holds. Without it the diff is the only
        # witness, and `built_from` is the head *before* the indexing
        # command's own commit - so every `kennis remember` reported the
        # note it had just indexed as not yet indexed. Concern #245.
        indexed=manifest.documents,
    )
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
    return True, current


@corpus_group.command(name="list")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Only this collection. All three by default.",
)
def list_command(collection: str | None) -> None:
    """Every document in the corpus."""
    context = existing_corpus()
    shown = 0
    for name in [collection] if collection else list(COLLECTION_NAMES):
        for document in (
            Collection(root=context.corpus_root, name=name).contents().documents
        ):
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
    context = existing_corpus()
    for name in [collection] if collection else list(COLLECTION_NAMES):
        found = Collection(root=context.corpus_root, name=name)
        root = found.path
        if not root.is_dir():
            continue
        display.operation(name.capitalize())
        identifiers = _identifiers_in(found)
        for path in sorted(root.rglob("*")):
            if path.name.startswith(".") or _inside_a_wrapper(path, identifiers):
                continue
            depth = len(path.relative_to(root).parts) - 1
            if path.is_dir() and path.name not in identifiers:
                display.tree_group(path.name, depth)
            else:
                display.tree_document(identifiers.get(path.name), path.name, depth)


def _identifiers_in(collection: Collection) -> dict[str, str | None]:
    """Every entry the walk will meet that is a document, by its name on disk.

    Keyed by the name the directory really holds, which for a document with
    assets is its **wrapper directory** - `Foo`, holding `Foo/content.md`.
    Not `reserved_filename`, which is `Foo.md`: that is the name the wrapper
    reserves against a future document's filename, and it is not a name the
    walk will ever see.

    A value of None is a document whose frontmatter carries no identifier to
    read, which is a document kennis cannot validate rather than one it
    cannot find.
    """
    return {
        (facts.wrapper_dir or facts.md_path).name: facts.identifier
        for facts in collection.survey()
    }


def _inside_a_wrapper(path: Path, identifiers: dict[str, str | None]) -> bool:
    """True for a file that belongs to a wrapped document rather than to the
    tree: its `content.md`, and anything under its `images/`.

    The wrapper is one document and is printed as one line. Walking into it
    would show a reader `content.md` under every title, which is an
    implementation detail of how assets are stored.
    """
    return any(part in identifiers for part in path.parts[:-1])


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
    max_pages: int,
    max_depth: int,
) -> None:
    """Add files, directories or URLs to one collection."""
    context = existing_corpus()
    destination = _destination(
        collection, notes=notes, literature=literature, docs=docs
    )
    _refuse_foreign_options(
        destination, identifier=identifier, citekey=citekey, project=project
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
        project=project,
        max_pages=max_pages,
        max_depth=max_depth,
        batch_size=context.settings.conversion.batch_size,
        request_delay_seconds=context.settings.literature.request_delay,
        extra_file_types=(),
    )

    target = Collection(root=context.corpus_root, name=destination)
    with corpus_lock(context.corpus_root), reporting() as events:
        _undo_hand_deletions(context)
        report = _ADDERS[destination](target, identifiers, options, events=events)
        _commit(
            context, "add", scope=destination, summary=outcome_summary(report.counts)
        )

    _report_add(report)


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
    counts = report.counts
    # The cost rides on the operation line rather than a line of its own: it
    # is a property of what just happened, and a separate line would give a
    # free local conversion a blank where a number used to be.
    priced = conversion_cost(report.cost_cents)
    repaired = conversion_repairs(report.repairs)
    display.operation(
        "Added",
        count_of(counts.get(Outcome.ADDED, 0), "document")
        + (f", {priced}" if priced else "")
        + (f", {repaired}" if repaired else ""),
        elapsed=report.elapsed_seconds,
    )
    for outcome in Outcome:
        named = [
            item.title or item.identifier
            for item in report.outcomes
            if item.outcome is outcome
        ]
        if named:
            display.details(marker_for(outcome), named)


# ---------------------------------------------------------------------------
# Removing and moving
# ---------------------------------------------------------------------------


@corpus_group.command(name="remove")
@click.argument("handle")
@click.option(
    "--collection",
    type=click.Choice(COLLECTION_NAMES),
    help="Look only here. All three by default.",
)
@click.option("-y", "--yes", is_flag=True, help="Do not ask first.")
def remove_command(handle: str, collection: str | None, yes: bool) -> None:
    """Delete a document, and its assets when it has any."""
    context = existing_corpus()
    found, document = resolve_document(context, handle, collection)

    if not yes:
        # Recoverable through `corpus restore`, so this is a courtesy rather
        # than the last line of defence - but a wrapped document takes its
        # assets with it, and that is worth one keystroke.
        click.confirm(
            f"Remove '{document.frontmatter.title}' from {found.name}?", abort=True
        )

    with corpus_lock(context.corpus_root):
        _undo_hand_deletions(context)
        found.remove(document)
        _commit(
            context,
            "remove",
            scope=found.name,
            summary=outcome_summary({Outcome.REMOVED: 1}),
        )

    display.operation("Removed", f"{document.id}  {document.frontmatter.title}")


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
    context = existing_corpus()
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

    found, document = resolve_document(context, handle, collection)
    _refuse_regrouping_docs(found, group)
    target = _target_path(found, document, group=group, title=title)

    with corpus_lock(context.corpus_root):
        _undo_hand_deletions(context)
        moved = move_document(
            document,
            target_md_path=target,
            updates={"title": title} if title else None,
        )
        _commit(
            context,
            "move",
            scope=found.name,
            summary=outcome_summary({Outcome.CHANGED: 1}),
        )

    display.operation("Moved", f"{moved.id}  {moved.md_path.relative_to(found.path)}")


def _refuse_regrouping_docs(found: Collection, group: str | None) -> None:
    """A docs page's directory is its project, so `--group` cannot set it.

    Notes and literature are filed into whatever group the user names, and
    their identifiers are minted independently of it. A docs page is not:
    `add_docs` writes it to `docs/<project>/` and derives its identifier from
    `(project, page)`, so moving the file alone would leave the directory,
    the `docs.project` field and the identifier disagreeing about which
    project the page belongs to.

    Changing the project properly would change the derived identifier, which
    is the one thing `move_document` refuses - every handle pointing at the
    document addresses it by that identifier. Concern #101.
    """
    if found.name == "docs" and group is not None:
        raise display.CliError(
            "a docs page's directory is its project, which is part of its "
            "identity; --group cannot change it."
        )


def _target_path(
    found: Collection, document: Document, *, group: str | None, title: str | None
) -> Path:
    """Where the moved document lands, as a bare-file path.

    Always the bare form, even for a wrapped document: `move_document` turns
    `<dir>/<name>.md` into `<dir>/<name>/content.md` itself, because the unit
    that moves is the wrapper directory and its assets travel with it.

    Each half defaults to what the document already has, so `--group` alone
    keeps the title and `--title` alone keeps the directory. Recomputing the
    filename uses the two functions `add` uses - `title_filename` and
    `unique_filename` - so a moved document lands where an added one would,
    rather than the corpus having a second naming rule reachable only by
    moving.
    """
    directory = found.path / group if group is not None else _holding(document)
    if title is None:
        return directory / f"{_stem(document)}.md"

    taken = {
        _stem(other) + ".md"
        for other in found.contents().documents
        if other.id != document.id
    }
    return directory / unique_filename(title_filename(title), taken)


def _holding(document: Document) -> Path:
    """The directory the document sits in, as a move would name it.

    A wrapped document's own `md_path.parent` is its wrapper, which is part
    of the document rather than where it is filed.
    """
    return (document.wrapper_dir or document.md_path).parent


def _stem(document: Document) -> str:
    """The document's name without the suffix, in bare-file terms.

    A wrapped document's markdown is always `content.md`, so its own filename
    says nothing about which document it is; the wrapper's name does.
    """
    if document.wrapper_dir is not None:
        return document.wrapper_dir.name
    return document.md_path.stem


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

    repository = Repository(context.corpus_root)
    root = index_root(context.corpus_root)
    documents = 0
    chunks = 0
    with corpus_lock(context.corpus_root), reporting() as events:
        _undo_hand_deletions(context)
        for name in [collection] if collection else list(COLLECTION_NAMES):
            target = Collection(root=context.corpus_root, name=name)
            # Skipped rather than attempted: `build_index` refuses an empty
            # collection by design, and two of the three are empty on most
            # corpora. Asking for all of them must not fail on that account.
            if not target.contents().documents:
                continue
            report = build_index(
                CollectionLoader(target),
                index_root=root,
                binding=binding,
                events=events,
                embed_batch_size=context.settings.embedding.batch_size,
                repository=repository,
            )
            documents += report.document_count
            chunks += report.chunk_count
            display.operation(
                "Indexed",
                f"{count_of(report.document_count, 'document')} as "
                f"{count_of(report.chunk_count, 'chunk')} in {name}",
                elapsed=report.elapsed_seconds,
            )
        # One commit for one user action, with what it actually built in the
        # subject: `index(corpus): 2 documents, 2 chunks` rather than a tally
        # of outcomes, which an index has none of.
        _commit(
            context,
            "index",
            scope=collection or "corpus",
            summary=commit_summary({"documents": documents, "chunks": chunks}),
        )

    if documents == 0:
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
    context = existing_corpus()
    entries = read_history(
        Repository(context.corpus_root), collection=collection, limit=limit
    )
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
    context = existing_corpus()
    repository = Repository(context.corpus_root)
    with corpus_lock(context.corpus_root):
        restored = restore_document(repository, document_id, commit=commit)
        _commit(
            context,
            "restore",
            scope=_collection_of(restored.path),
            summary=outcome_summary({Outcome.ADDED: 1}),
        )
    display.operation("Restored", f"{restored.document_id} from {restored.commit[:8]}")


def _collection_of(path: str) -> str:
    """Which collection a corpus-relative path belongs to.

    The scope of the commit that records the restore, so `corpus history
    --collection` finds it by the same route it finds the add that first put
    the document there.
    """
    head = path.split("/", 1)[0]
    return head if head in COLLECTION_NAMES else "corpus"


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------


def _commit(context: Context, operation: str, *, scope: str, summary: str) -> None:
    """Record what the command just did.

    `commit` returns None when the tree was already clean, which is what
    re-adding a document kennis already holds looks like. That is not a
    failure and is not reported as one: an empty commit would fill history
    with noise, and raising would fail a command that succeeded.
    """
    Repository(context.corpus_root).commit(operation, scope=scope, summary=summary)


__all__ = ["KennisError", "corpus_group"]
