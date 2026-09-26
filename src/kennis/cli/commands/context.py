"""`kennis context`: the knowledge that belongs to this project.

The corpus is machine-global; a bundle is a `.context/` directory at the
root of a workspace, committed with it. Every command here starts by
deciding which directory that is, which is `find_bundle`'s job and the one
thing `design.md` left unspecified - concern #225.
"""

from __future__ import annotations

from pathlib import Path

import click

from kennis.cli import display
from kennis.cli.context import existing_corpus
from kennis.cli.group import KennisCommand, KennisGroup
from kennis.cli.sink import reporting
from kennis.engine.context import (
    CONTEXT_COLLECTION,
    LANDING_FILENAME,
    BundleCreated,
    bundle_status,
    find_bundle,
    index_bundle,
    index_root_for,
    init_bundle,
    removable_documents,
    reset_bundle,
    workspace_root,
)
from kennis.engine.context.sync import BundleSync, sync_bundle
from kennis.engine.errors import ContextNotFound
from kennis.engine.pack.resolve import ACTING
from kennis.engine.rag.binding import binding_from, chunk_parameters
from kennis.engine.rag.embedding import ModelBinding
from kennis.engine.settings import Settings, load_settings
from kennis.render.packs import (
    describe_action,
    describe_claim_needed,
    describe_deferred,
    describe_moved,
    describe_sync,
)
from kennis.render.words import count_of, describe_freshness


@click.group(name="context", cls=KennisGroup)
def context_group() -> None:
    """The knowledge bundle for the project you are standing in."""


@context_group.command(name="init", cls=KennisCommand)
@click.option(
    "--here",
    is_flag=True,
    help="Create it in the working directory instead of the workspace root.",
)
def init_command(here: bool) -> None:
    """Create this project's `.context/` bundle.

    **Where it goes is not always where you are.** A bundle belongs at the
    root of a workspace, so this walks up to the nearest `.git` and creates
    it there; running the command three directories deep should not bury it
    there. The path is reported for that reason. `--here` overrides it.

    Re-runnable, and converging rather than merely not-failing: a scaffold
    file that was deleted is written again, and anything you added is left
    alone.
    """
    created = init_bundle(Path.cwd() if here else workspace_root())
    _report_init(created)


def _report_init(created: BundleCreated) -> None:
    """What `init` did, in the three shapes it can take.

    `guidance` rather than `note` for the two informational lines: `note`
    prints `warning:`, and a bundle that was already complete is not
    something going wrong.
    """
    if created.created:
        display.operation("Created", f"context bundle at {created.path}")
        # Not `next_step`, which prints a command: rule 4.4 says a printed
        # command runs as printed, and the one a new bundle wants next is
        # `kennis remember --context <text>`, whose placeholder does not.
        # The landing file is a place rather than a command, so it can be
        # named exactly. Relative to the bundle, which the line above just
        # gave in full: an absolute path is long enough to be wrapped by the
        # prose style that prints it, and a wrapped path cannot be copied.
        display.guidance(f"start at {created.path.name}/{LANDING_FILENAME}")
        return
    display.operation("Found", f"context bundle at {created.path}")
    if created.restored:
        # The markers say what happened; a count beneath them would repeat
        # what the reader just read.
        display.details("+", list(created.restored))
        return
    display.guidance("already complete, nothing to put back")


@context_group.command(name="index", cls=KennisCommand)
def index_command_for_context() -> None:
    """Build this project's context index.

    **BM25 only, and offline.** Design section 13: a bundle index that
    embedded would turn setting a project up from a 40ms scaffold into a
    model download, and the bundle is small enough that lexical search over
    it is the right answer rather than a concession.

    **The index is not committed.** `context init` writes a `.gitignore`
    that keeps it out of the repository, because it is derived from the
    documents beside it and specific to whoever built it - their chunk
    settings, and their embedding model if they configured one. A clone
    gets the documents and runs this command once.
    """
    bundle = require_bundle()
    settings = load_settings()
    model = context_model(settings)
    display.using(
        f"{model.kind} {model.model}"
        if model
        else "lexical search only, which is what a bundle is indexed with"
    )
    with reporting() as events:
        report = index_bundle(
            bundle,
            chunking=chunk_parameters(settings.chunking),
            model=model,
            events=events,
            embed_batch_size=settings.embedding.batch_size,
        )
    display.operation(
        "Indexed",
        f"{count_of(report.document_count, 'document')} as "
        f"{count_of(report.chunk_count, 'chunk')} in this project",
        elapsed=report.elapsed_seconds,
    )
    # The documents, not the index: `init` gitignores the index, so what is
    # worth committing is what the index was built from. Named because it is
    # the thing a user has to do and kennis will not - the repository is
    # theirs.
    display.guidance(f"commit {bundle.name}/ to share these notes with the project")


@context_group.command(name="sync", cls=KennisCommand)
def sync_command_for_context() -> None:
    """Converge this project's context with every installed pack.

    **Offline.** A pack's context content is already in this machine's
    store, put there by `kennis pack add`, so this copies and never
    fetches.

    Nothing you own is touched. A file whose `owner` is you is reported
    and left alone on every run, and so is a pack's file you have edited
    in place - kennis will not overwrite your writing to apply a
    provider's release.

    **kennis does not commit.** The bundle is in your repository.
    """
    bundle = require_bundle()
    context = existing_corpus()
    with reporting() as events:
        result = sync_bundle(bundle, context.corpus_root, events=events)
    display.operation("Synchronised", describe_sync(result.counts))
    for action in result.actions:
        display.detail(display.sync_marker(action.verdict), describe_action(action))
    _report_what_was_left(result)
    if any(action.verdict in ACTING for action in result.actions):
        # The index is derived from these documents and this command did
        # not rebuild it, for the same reason `remember --context` does
        # not: indexing is a separate decision with its own cost.
        display.next_step("kennis context index")


def _report_what_was_left(result: BundleSync) -> None:
    """The two things a sync did not do, each said once above nothing.

    All three are reported every run rather than only on the run they
    began, because a provider whose file never appears, a user whose edit
    is never applied, and a file that is not where the pack says it is
    all need telling more than once.
    """
    edited = result.counts.get("edited", 0)
    if edited:
        # Guidance rather than a note: nothing is going wrong. kennis
        # protected the user's writing and is saying so, and `warning:`
        # would read as a fault in a bundle that is behaving correctly.
        display.guidance(describe_claim_needed(edited))
    if result.moved:
        # Guidance, not a diagnostic: the user moved the file and kennis
        # honoured it. `note` prints `warning:`, which would read as a
        # fault in a bundle that is doing exactly what was asked.
        display.guidance(describe_moved(result.moved))
    if result.deferred:
        display.note(describe_deferred(result.deferred))


@context_group.command(name="status", cls=KennisCommand)
def status_command_for_context() -> None:
    """What this project's context holds, and whether its index is in step.

    The same question `corpus status` answers, one scope down - and the
    freshness half is answered differently, because there is no commit to
    diff against. kennis does not write to your repository, so the index
    records no commit and the comparison is made against the document
    digests the index stored instead.
    """
    status = bundle_status(require_bundle())
    display.operation("Context", str(status.path))
    # "Holds" rather than "Documents", which would print `Documents 3
    # documents`. `corpus status` gets away with the shape because its verb
    # is the collection's name.
    display.operation("Holds", count_of(status.document_count, "document"))
    if len(status.groups) > 1:
        # Only when there is a breakdown to give. A bundle whose files all
        # sit at the top level would otherwise get one row repeating the
        # line above it, and a fresh bundle has no directories at all -
        # they are the user's own invention, not a fixed three.
        for group, held in sorted(status.groups.items()):
            # The root's own count is labelled rather than left blank: a
            # blank first column in a list of directory names reads as a
            # missing value rather than as "here".
            display.row(group or "(top level)", count_of(held, "document"))
    for relative in status.unreadable:
        display.detail("!", f"{relative}: frontmatter could not be read")

    if status.freshness is None:
        if status.document_count:
            display.note("no index yet, so nothing here is searchable")
            display.next_step("kennis context index")
        else:
            # No "nothing here yet": the count line above has just said so,
            # and the only thing left to add is what changes it.
            display.next_step("kennis remember --help")
        return
    described = describe_freshness(status.freshness, CONTEXT_COLLECTION)
    if status.freshness.state == "in step" and not status.freshness.added:
        # `=` is the marker that carries no colour, which is right: an index
        # that is current is the absence of news.
        display.detail("=", described)
        return
    display.note(described)
    display.next_step("kennis context index")


@context_group.command(name="reset", cls=KennisCommand)
@click.option("-y", "--yes", is_flag=True, help="Do not ask first.")
def reset_command(yes: bool) -> None:
    """Remove the index and anything kennis owns, keeping your own files.

    A file kennis owns is one a pack applied - `owner: pack:<id>` in its
    frontmatter. Everything `remember --context` writes is marked `owner:
    user`, and so is anything you wrote by hand, including a file with no
    frontmatter at all, so a reset leaves all of it.

    Renaming a file to a dot-prefixed name keeps it out of the index; it
    does not make it yours, and a reset removes it if a pack owns it.
    `LANDING.md` and `.skeleton.md` are kept whatever they say, because
    they are yours to maintain and `context init` restores either one.

    A file with a header kennis cannot read counts as yours. The two
    mistakes do not cost the same.
    """
    bundle = require_bundle()
    # Asked, not restated. The prompt has to offer exactly what the reset
    # will take, and a second copy of the rule here is a copy that can
    # stop matching - as it did when the engine widened to see a file the
    # user had hidden.
    owned = [
        path.relative_to(bundle).as_posix() for path in removable_documents(bundle)
    ]
    has_index = index_root_for(bundle).is_dir()
    if not owned and not has_index:
        display.guidance("nothing to remove - everything here is yours")
        return

    if not yes:
        # Not recoverable through kennis, unlike `corpus remove`. A bundle
        # is in a repository kennis has no history of, so the only undo is
        # the user's own `git checkout`, and only if they committed. The
        # prompt says what will go rather than asking in the abstract.
        click.confirm(f"Remove {_what_goes(owned, has_index)}?", abort=True)

    report = reset_bundle(bundle)
    # Documents first, each under its own heading, and the index last with
    # the command that rebuilds it beside it. The other order put a hint
    # about the index above the list of documents it had nothing to do with.
    if report.removed:
        display.operation("Removed", count_of(len(report.removed), "document"))
        for relative in report.removed:
            display.detail("-", relative)
    else:
        display.guidance("your own files were left untouched, which was all of them")
    if report.index_removed:
        display.operation("Removed", "the context index")
        display.next_step("kennis context index", note="to build it again")


def context_model(settings: Settings) -> ModelBinding | None:
    """The embedding model a bundle index is built with, if any.

    One line of policy, named so it can be asked directly: without a name it
    is only observable through a command that builds an index, and on a
    machine with no embedding backend both answers look identical from
    there.

    `binding_from` answers `model=None` when the backend is `none`, so
    asking for hybrid without a backend yields a lexical index rather than a
    failure - the corpus behaves the same way.
    """
    if settings.retrieval.context_method == "bm25":
        return None
    return binding_from(settings.chunking, settings.embedding).model


def _what_goes(owned: list[str], has_index: bool) -> str:
    """What the prompt says is about to be deleted.

    Named rather than counted where there is one of them: "Remove
    conventions/naming.md and the context index?" is checkable at a glance
    and a bare count is not.
    """
    parts: list[str] = []
    if owned:
        parts.append(owned[0] if len(owned) == 1 else count_of(len(owned), "document"))
    if has_index:
        parts.append("the context index")
    return " and ".join(parts)


def require_bundle() -> Path:
    """The bundle governing the working directory, or the error naming the
    command that makes one.

    Every context command but `init` starts here.
    """
    bundle = find_bundle()
    if bundle is None:
        raise ContextNotFound
    return bundle


__all__ = ["context_group", "context_model", "require_bundle"]
