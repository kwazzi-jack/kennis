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
from kennis.cli.group import KennisCommand, KennisGroup
from kennis.cli.sink import DisplaySink, reporting, say_waiting
from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.context import (
    CONTEXT_COLLECTION,
    LANDING_FILENAME,
    BundleCreated,
    find_bundle,
    workspace_root,
)
from kennis.engine.context.bundle import declared_packs
from kennis.engine.context.projects import known_projects, project_named
from kennis.engine.context.sync import BundleSync
from kennis.engine.errors import ContextNotFound
from kennis.render.packs import (
    describe_bundle_sync,
    describe_declared,
    describe_made_yours,
    describe_no_declaration,
    describe_not_installed,
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
@click.option(
    "--pack",
    "packs",
    multiple=True,
    metavar="ID",
    help="A pack this project uses; repeat for several. See `context packs`.",
)
def init_command(here: bool, packs: tuple[str, ...]) -> None:
    """Create this project's `.context/` bundle.

    **Where it goes is not always where you are.** A bundle belongs at the
    root of a workspace, so this walks up to the nearest `.git` and creates
    it there; running the command three directories deep should not bury it
    there. The path is reported for that reason. `--here` overrides it.

    Re-runnable, and converging rather than merely not-failing: a scaffold
    file that was deleted is written again, and anything you added is left
    alone.
    """
    corpus_root = existing_corpus().corpus_root
    folder = Path.cwd() if here else workspace_root(Path.cwd())
    created = api.init_bundle(corpus_root, folder)
    _report_init(created)
    if packs:
        declared = api.declare_packs(corpus_root, created.path, packs)
        display.detail("+", f"declares {', '.join(declared)}")


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
@click.option(
    "--project",
    "project",
    metavar="NAME",
    help="Index another known project's context, as `kennis context list` "
    "names it, rather than this one's.",
)
def index_command_for_context(project: str | None) -> None:
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
    corpus_root = existing_corpus().corpus_root
    bundle = require_bundle() if project is None else project_named(project).bundle
    with reporting() as events:
        built = api.index_bundle(
            corpus_root, bundle, events=events, on_waiting=say_waiting
        )
    # Said after the build rather than before it: the service chose the
    # model from its settings, and only its answer can say which.
    display.using(
        f"{built.model_kind} {built.model_name}"
        if built.model_kind
        else "lexical search only, which is what a bundle is indexed with"
    )
    report = built.report
    display.operation(
        "Indexed",
        f"{count_of(report.document_count, 'document')} as "
        f"{count_of(report.chunk_count, 'chunk')} in "
        + ("this project" if project is None else project),
        elapsed=report.elapsed_seconds,
    )
    # The documents, not the index: `init` gitignores the index, so what is
    # worth committing is what the index was built from. Named because it is
    # the thing a user has to do and kennis will not - the repository is
    # theirs.
    where = f"{bundle.name}/" if project is None else f"{bundle.name}/ in {project}"
    display.guidance(f"commit {where} to share these notes with the project")


@context_group.command(name="sync", cls=KennisCommand)
def sync_command_for_context() -> None:
    """Check this project's bundle against the packs it declares.

    A pack's context is searched where `kennis pack add` stored it, so
    nothing is copied into the project. A copy an earlier kennis made is
    removed, unless you edited it: then it is yours, and this project
    searches it in place of the pack's file. Says which declared packs
    this machine has not got, and, when the project declares none, which
    installed packs it could.

    **Offline**, and **kennis does not commit**: the bundle is in your
    repository.
    """
    corpus_root = existing_corpus().corpus_root
    bundle = require_bundle()
    with DisplaySink() as shown:
        result = api.sync_bundle(
            corpus_root, bundle, events=shown, on_waiting=say_waiting
        ).result
    display.operation(
        "Synchronised",
        describe_bundle_sync(len(result.removed), len(result.made_yours)),
    )
    for address in result.removed:
        display.detail("-", address)
    for address in result.made_yours:
        display.detail("~", address)
    if result.made_yours:
        display.guidance(describe_made_yours())
    _report_the_declaration(result)
    if result.removed or result.made_yours:
        # The index is derived from these documents and this command did
        # not rebuild it, for the same reason `remember --context` does
        # not: indexing is a separate decision with its own cost.
        display.next_step("kennis context index")


def _report_the_declaration(result: BundleSync) -> None:
    """Which packs this project reads, said on every run, because a pack
    declared and never installed is otherwise silently not searched."""
    if result.declared:
        display.info(describe_declared(result.declared))
    if result.missing:
        display.note(describe_not_installed(result.missing))
        display.next_step("kennis pack list")
    if not result.declared and not result.missing:
        display.guidance(describe_no_declaration())
        for pack in result.available:
            display.next_step(f"kennis context packs {pack}")


@context_group.command(name="packs", cls=KennisCommand)
@click.argument("packs", nargs=-1, metavar="[ID]...")
@click.option(
    "--drop", "dropped", multiple=True, metavar="ID", help="Stop using this pack."
)
@click.option("--none", "declare_none", is_flag=True, help="Declare no packs.")
def packs_command_for_context(
    packs: tuple[str, ...], dropped: tuple[str, ...], declare_none: bool
) -> None:
    """The packs this project uses: shown with no arguments, added to with
    some.

    A project reads only the packs it declares, so the stimela pack's
    advice reaches the projects that use stimela and no others. The
    declaration is in `.context/bundle.json`, committed with the project,
    so whoever clones it declares the same packs. The ids given are added
    to the declaration, never put in place of it, so a command printed
    for one pack cannot drop another; `--drop` removes one and `--none`
    clears it.
    """
    if declare_none and (packs or dropped):
        raise display.CliError("pass --none alone: it clears the declaration.")
    corpus_root = existing_corpus().corpus_root
    bundle = require_bundle()
    if packs or dropped or declare_none:
        declared = api.declare_packs(
            corpus_root, bundle, packs, dropped, clear=declare_none
        )
        display.operation("Declared", ", ".join(declared) if declared else "no packs")
        return
    declared = declared_packs(bundle)
    if not declared:
        display.note("this project declares no packs")
        display.next_step("kennis context packs --help")
        return
    display.operation("Declares", ", ".join(declared))


@context_group.command(name="copy", cls=KennisCommand)
@click.argument("reference", metavar="PACK/ADDRESS")
def copy_command_for_context(reference: str) -> None:
    """Make one of a pack's context files this project's own.

    Copies `alpha/solving.md` - the `pack=` a search printed - into the
    bundle with you as its owner. This project then searches your copy
    in place of the pack's file; other projects still read the pack's.
    """
    corpus_root = existing_corpus().corpus_root
    bundle = require_bundle()
    written = api.copy_pack_file(corpus_root, bundle, reference)
    display.operation("Copied", written.relative_to(bundle.parent).as_posix())
    display.next_step("kennis context index")


@context_group.command(name="list", cls=KennisCommand)
def list_command_for_context() -> None:
    """Every project on this machine whose context kennis knows of.

    A project is listed once kennis has touched its bundle - made it,
    remembered into it, indexed, synced or searched it - or once it is
    added. One whose folder has gone stays listed as missing until it is
    forgotten, because a disk that is not mounted is not a project that
    was deleted.
    """
    projects = known_projects()
    if not projects:
        display.note("no project with a context bundle is known yet")
        display.next_step("kennis context init", note="in a project")
        return
    width = max(len(project.name) for project in projects)
    for project in projects:
        display.row(project.name.ljust(width), str(project.bundle.parent))
    for project in projects:
        if not project.present:
            display.detail(
                "!", f"{project.name}: missing, no bundle at {project.bundle}"
            )
            display.next_step(f"kennis context forget {project.name}")


@context_group.command(name="add", cls=KennisCommand)
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
def add_command_for_context(folder: Path) -> None:
    """List a project kennis has not touched yet: a folder holding a
    `.context/` bundle, or the bundle itself."""
    added = api.add_project(existing_corpus().corpus_root, folder)
    display.operation("Added", f"{added.name}, {added.bundle.parent}")


@context_group.command(name="forget", cls=KennisCommand)
@click.argument("name")
def forget_command_for_context(name: str) -> None:
    """Take a project off the list. Its files are not touched; kennis lists
    it again the next time it touches its bundle."""
    forgotten = api.forget_project(existing_corpus().corpus_root, name)
    display.operation("Forgot", f"{forgotten.name}, {forgotten.bundle.parent}")


@context_group.command(name="status", cls=KennisCommand)
def status_command_for_context() -> None:
    """What this project's context holds, and whether its index is in step.

    The same question `corpus status` answers, one scope down - and the
    freshness half is answered differently, because there is no commit to
    diff against. kennis does not write to your repository, so the index
    records no commit and the comparison is made against the document
    digests the index stored instead.
    """
    corpus_root = existing_corpus().corpus_root
    status = api.bundle_status(corpus_root, require_bundle())
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
    corpus_root = existing_corpus().corpus_root
    bundle = require_bundle()
    # Asked, not restated. The prompt has to offer exactly what the reset
    # will take, and a second copy of the rule here is a copy that can
    # stop matching - as it did when the engine widened to see a file the
    # user had hidden.
    preview = api.reset_preview(corpus_root, bundle)
    owned, has_index = list(preview.owned), preview.has_index
    if not owned and not has_index:
        display.guidance("nothing to remove - everything here is yours")
        return

    if not yes:
        # Not recoverable through kennis, unlike `corpus remove`. A bundle
        # is in a repository kennis has no history of, so the only undo is
        # the user's own `git checkout`, and only if they committed. The
        # prompt says what will go rather than asking in the abstract.
        click.confirm(f"Remove {_what_goes(owned, has_index)}?", abort=True)

    report = api.reset_bundle(corpus_root, bundle)
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
    bundle = find_bundle(Path.cwd())
    if bundle is None:
        raise ContextNotFound
    return bundle


__all__ = ["context_group", "require_bundle"]
