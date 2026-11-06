"""`kennis context`: the knowledge that belongs to this project.

The corpus is machine-global; a bundle is a `.context/` directory at the
root of a workspace, committed with it. Every command here starts by
deciding which directory that is, which is `find_bundle`'s job and the one
thing `design.md` left unspecified - concern #225.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand, KennisGroup
from kennis.cli.sink import DisplaySink, reporting, say_waiting
from kennis.client import api
from kennis.context import existing_corpus

if TYPE_CHECKING:
    from kennis.engine.context.bundle import (
        BundleCreated,
    )
    from kennis.engine.context.sync import BundleSync


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
    from kennis.engine.context.bundle import workspace_root

    corpus_root = existing_corpus().corpus_root
    folder = Path.cwd() if here else workspace_root(Path.cwd())
    created = api.init_bundle(corpus_root, folder)
    _report_init(created)
    if packs:
        declared = api.declare_packs(corpus_root, created.path, packs)
        display.detail("+", f"declares {', '.join(declared)}")
        display.next_step("kennis context sync", note="to copy their context in")


def _report_init(created: BundleCreated) -> None:
    """What `init` did, in the three shapes it can take.

    `guidance` rather than `note` for the two informational lines: `note`
    prints `warning:`, and a bundle that was already complete is not
    something going wrong.
    """
    from kennis.engine.context.bundle import LANDING_FILENAME

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
    from kennis.engine.context.projects import project_named
    from kennis.render.words import count_of

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
@click.option(
    "--remove-undeclared",
    is_flag=True,
    help="Also remove the unedited copies of packs this project no longer declares.",
)
def sync_command_for_context(remove_undeclared: bool) -> None:
    """Copy the context of the packs this project declares into its bundle.

    Each pack's files land at the addresses the pack gives, owned by the
    pack, and a new release replaces a copy nobody edited. **A file whose
    owner is `user` is never touched**: to keep a pack's file as your own,
    set `owner: user` in its header. A copy you edited without doing so is
    left as it is and named. A pack this project stops declaring leaves its
    copies until you sync with `--remove-undeclared`.

    **Offline**, and **kennis does not commit**: the bundle is in your
    repository, and what changed is a diff you can read before you commit.
    """
    from kennis.render.packs import (
        describe_bundle_sync,
        describe_deferred,
        describe_edited_copies,
        describe_undeclared,
        describe_yours,
    )

    corpus_root = existing_corpus().corpus_root
    bundle = require_bundle()
    with DisplaySink() as shown:
        result = api.sync_bundle(
            corpus_root,
            bundle,
            remove_undeclared=remove_undeclared,
            events=shown,
            on_waiting=say_waiting,
        ).result
    display.operation(
        "Synchronised",
        describe_bundle_sync(
            len(result.written), len(result.updated), len(result.removed)
        ),
    )
    for marker, addresses in (
        ("+", result.written),
        ("~", result.updated),
        ("-", result.removed),
    ):
        for address in addresses:
            display.detail(marker, address)
    for address, where in result.moved:
        display.detail("=", f"{address} is at {where}")
    if result.edited:
        display.note(describe_edited_copies())
        for address in result.edited:
            display.detail("!", address)
    if result.yours:
        display.info(describe_yours(len(result.yours)))
    if result.deferred:
        display.note(describe_deferred(result.deferred))
    if result.undeclared:
        display.note(describe_undeclared(len(result.undeclared)))
        for address in result.undeclared:
            display.detail("=", address)
        display.next_step("kennis context sync --remove-undeclared")
    _report_the_declaration(result)
    if result.changed_anything:
        # The index is derived from these documents and this command did
        # not rebuild it, for the same reason `remember --context` does
        # not: indexing is a separate decision with its own cost.
        display.next_step("kennis context index")


def _report_the_declaration(result: BundleSync) -> None:
    """Which packs this project reads, said on every run, because a pack
    declared and never installed is otherwise silently not searched."""
    from kennis.render.packs import (
        describe_declared,
        describe_no_declaration,
        describe_not_installed,
    )

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

    A project holds a copy of the context of the packs it declares, made by
    `kennis context sync`, so the stimela pack's advice reaches the projects
    that use stimela and no others. The
    declaration is in `.context/bundle.json`, committed with the project,
    so whoever clones it declares the same packs. The ids given are added
    to the declaration, never put in place of it, so a command printed
    for one pack cannot drop another; `--drop` removes one and `--none`
    clears it.
    """
    from kennis.engine.context.bundle import declared_packs

    if declare_none and (packs or dropped):
        raise display.CliError("pass --none alone: it clears the declaration.")
    corpus_root = existing_corpus().corpus_root
    bundle = require_bundle()
    if packs or dropped or declare_none:
        declared = api.declare_packs(
            corpus_root, bundle, packs, dropped, clear=declare_none
        )
        display.operation("Declared", ", ".join(declared) if declared else "no packs")
        # Declaring copies nothing: the files arrive, or go, at a sync the
        # person runs, so the bundle changes only when they ask (#624).
        display.next_step("kennis context sync", note="to copy their context in")
        return
    declared = declared_packs(bundle)
    if not declared:
        display.note("this project declares no packs")
        display.next_step("kennis context packs --help")
        return
    display.operation("Declares", ", ".join(declared))


@context_group.command(name="list", cls=KennisCommand)
def list_command_for_context() -> None:
    """Every project on this machine whose context kennis knows of.

    A project is listed once kennis has touched its bundle - made it,
    remembered into it, indexed, synced or searched it - or once it is
    added. One whose folder has gone stays listed as missing until it is
    forgotten, because a disk that is not mounted is not a project that
    was deleted.
    """
    from kennis.engine.context.projects import known_projects

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


@context_group.command(name="delete", cls=KennisCommand)
@click.argument("name")
@click.option("-y", "--yes", is_flag=True, help="Do not ask first.")
def delete_command_for_context(name: str, yes: bool) -> None:
    """Delete a project's `.context/` folder and take it off the list.

    kennis cannot undo this. The bundle is in the project's own repository,
    which kennis keeps no history of: what was committed there comes back
    with git, and nothing else does. `kennis context forget` unlists a
    project and leaves its folder.
    """
    from kennis.render.paths import from_home
    from kennis.render.words import count_of

    corpus_root = existing_corpus().corpus_root
    if not yes:
        # Asked of the engine's own refusals and count, so the question is
        # never put about a folder the delete would then refuse.
        preview = api.deletion_preview(corpus_root, name)
        click.confirm(
            f"Delete {from_home(str(preview.project.bundle))} and its "
            f"{count_of(preview.files, 'file')}? kennis cannot undo this",
            abort=True,
        )
    deleted = api.delete_project(corpus_root, name)
    display.operation("Deleted", f"{deleted.project.name}, {deleted.project.bundle}")
    display.detail("-", count_of(deleted.files, "file"))


@context_group.command(name="status", cls=KennisCommand)
def status_command_for_context() -> None:
    """What this project's context holds, and whether its index is in step.

    The same question `corpus status` answers, one scope down - and the
    freshness half is answered differently, because there is no commit to
    diff against. kennis does not write to your repository, so the index
    records no commit and the comparison is made against the document
    digests the index stored instead.
    """
    from kennis.engine.context.groups import CONTEXT_COLLECTION
    from kennis.render.packs import describe_without_frontmatter
    from kennis.render.words import count_of, describe_freshness

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
        display.detail("!", f"{relative}: frontmatter could not be read, not indexed")
    if status.without_frontmatter:
        display.note(describe_without_frontmatter(len(status.without_frontmatter)))
        for relative in status.without_frontmatter:
            display.detail("=", relative)

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
    from kennis.render.words import count_of

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
    from kennis.render.words import count_of

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
    from kennis.engine.context.bundle import find_bundle
    from kennis.engine.errors import ContextNotFound

    bundle = find_bundle(Path.cwd())
    if bundle is None:
        raise ContextNotFound
    return bundle


__all__ = ["context_group", "require_bundle"]
