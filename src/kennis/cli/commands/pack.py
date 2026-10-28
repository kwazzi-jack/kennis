"""`kennis pack`: knowledge that arrives from outside, as data.

**Two roles, told apart by their object** (design section 9). `init`,
`add`, `remove`, `update` and `validate` act on a `.ken.yml` at a path -
authoring, which is what a provider does in its own release pipeline.
`install`, `uninstall`, `list` and `status` act on the installed store -
consuming. `validate` serves both.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import click

from kennis.cli import display
from kennis.cli.adding import destination_named, refuse_foreign_options, report_add
from kennis.cli.group import KennisCommand, KennisGroup
from kennis.cli.paths import anchored
from kennis.cli.sink import DisplaySink, reporting, say_waiting
from kennis.client import api
from kennis.context import existing_corpus, resolve_context
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.pack.versions import DEFAULT_VERSION

if TYPE_CHECKING:
    from kennis.engine.corpus.add import AddReport
    from kennis.engine.pack.editing import Destination
    from kennis.engine.pack.installed import (
        InstalledPack,
        PackListing,
    )
    from kennis.engine.pack.update import PackUpdate
    from kennis.engine.pack.validate import PackReport

# What a pack declares, as `--collection` takes it: the corpus's three and a
# project's context. Built here rather than imported from `editing`, which
# loads the add path and so every command with it (#536).
DESTINATIONS: Final = (*COLLECTION_NAMES, "context")

_DIGEST_KINDS = frozenset({"digest-mismatch", "digest-absent", "undigested"})

# The operation verb and the detail marker for each install outcome. Layout
# rather than wording, so it lives here and not in `render/`.
_INSTALL_VERBS = {
    "installed": "Installed",
    "unchanged": "Unchanged",
    "repaired": "Repaired",
}
_INSTALL_MARKERS = {"installed": "+", "unchanged": "=", "repaired": "~"}


@click.group(name="pack", cls=KennisGroup)
def pack_group() -> None:
    """Author and check a pack of knowledge."""


@pack_group.command(name="install", cls=KennisCommand)
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def install_command(path: Path) -> None:
    """Install a pack into this machine's store.

    **Meant to be called by the provider**, from its own sync command, on
    every run: `boepie sync` ends by handing kennis the path to its own
    `.ken.yml`. Calling it repeatedly is cheap - a pack whose file and
    store both check out is recognised and nothing is rewritten.

    No network, and nothing is materialised into the corpus yet: this
    records what the provider declared. `corpus sync` and `context sync`
    converge the documents with it, and neither is built.
    """
    from kennis.render.packs import (
        describe_after_install,
        describe_declarations,
        describe_install,
    )

    corpus_root = existing_corpus().corpus_root
    with DisplaySink() as shown:
        install = api.install_pack(
            corpus_root, path, events=shown, on_waiting=say_waiting
        ).result
    display.operation(_INSTALL_VERBS[install.outcome], install.pack_id)
    display.detail(_INSTALL_MARKERS[install.outcome], describe_install(install))
    declared = describe_declarations(install)
    if declared is not None:
        display.detail(">", declared)
    if install.outcome != "unchanged":
        # Said at all because "Installed" otherwise implies everything is
        # searchable, and it is not: the corpus's share arrives with a
        # sync, and a project reads the pack's context once it declares
        # the pack (14g). Only when something changed - a provider calling
        # this on every run does not need the same sentence each time.
        display.guidance(describe_after_install())
        display.next_step("kennis corpus sync")
        display.next_step(
            f"kennis context packs {install.pack_id}",
            note="in each project that uses it",
        )


@pack_group.command(name="init", cls=KennisCommand)
@click.option(
    "--id", "identifier", required=True, help="The pack's slug, stable forever."
)
@click.option("--name", required=True, help="What the pack is called, for a reader.")
@click.option(
    "--pack-version",
    "version",
    default=DEFAULT_VERSION,
    show_default=True,
    help="The pack's own version, which `pack status` reports.",
)
@click.option(
    "--description",
    default=None,
    help="A sentence or two. It reaches a model, not only a reader.",
)
@click.argument("path", required=False, type=click.Path(dir_okay=False, path_type=Path))
def init_command(
    identifier: str,
    name: str,
    version: str,
    description: str | None,
    path: Path | None,
) -> None:
    """Scaffold a new `.ken.yml`.

    **The line at the top is the point of the command.** It points an editor
    at kennis's published JSON Schema, so an author gets completion and
    inline errors while writing the pack - with kennis not installed at all.

    Writes `<id>.ken.yml` in the working directory unless a path is given,
    and refuses an existing file: a pack holds declarations kennis did not
    write and cannot restore.
    """
    from kennis.engine.pack.scaffold import scaffold_pack

    destination = path if path is not None else Path(f"{identifier}.ken.yml")
    with reporting() as events:
        written = scaffold_pack(
            destination,
            identifier=identifier,
            name=name,
            version=version,
            description=description,
            events=events,
        )
    display.operation("Created", f"{written}")
    display.detail("+", f"{identifier} {version}")


@pack_group.command(name="add", cls=KennisCommand)
@click.argument("inputs", nargs=-1, required=True)
@click.option(
    "--collection",
    type=click.Choice(DESTINATIONS),
    help="What the entries are. One kind, never several.",
)
@click.option("-n", "--notes", "notes", is_flag=True, help="Shorthand for notes.")
@click.option(
    "-l", "--literature", "literature", is_flag=True, help="Shorthand for literature."
)
@click.option("-d", "--docs", "docs", is_flag=True, help="Shorthand for docs.")
@click.option("-c", "--context", "context", is_flag=True, help="Shorthand for context.")
@click.option("--title", help="Title for a single document, overriding what is found.")
@click.option(
    "--group", help="Subdirectory within the pack's folder of the collection."
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
    "--pack",
    "pack_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="The pack file. The one *.ken.yml here when not given.",
)
def add_command(
    inputs: tuple[str, ...],
    collection: str | None,
    notes: bool,
    literature: bool,
    docs: bool,
    context: bool,
    title: str | None,
    group: str | None,
    identifier: str | None,
    citekey: str | None,
    project: str | None,
    docs_version: str | None,
    pack_path: Path | None,
) -> None:
    """Declare papers, documentation, notes or context in a pack file.

    Anything `kennis corpus add` takes, and each input is added or refused
    on its own as there. A local file or folder is copied into the pack
    under `files/` and named relative to the pack file, so the pack still
    works on another machine; a context file already in the pack is
    declared by its folder with an `include:` naming it. The file is edited
    in place - comments and layout stay - and its generated block is brought
    up to date.
    """
    from kennis.engine.corpus.add import AddOptions
    from kennis.engine.pack.editing import add_to_pack, find_pack_file
    from kennis.engine.settings import own_directories
    from kennis.render.packs import describe_copied

    destination = destination_named(
        collection,
        {"notes": notes, "literature": literature, "docs": docs, "context": context},
        offered=DESTINATIONS,
    )
    refuse_foreign_options(
        destination,
        identifier=identifier,
        citekey=citekey,
        project=project,
        docs_version=docs_version,
    )
    path = pack_path or find_pack_file(Path.cwd())
    with reporting() as events:
        addition = add_to_pack(
            path,
            # `destination_named` returns one of `offered`.
            cast("Destination", destination),
            anchored(inputs),
            AddOptions(
                title=title,
                group=group,
                identifier=identifier,
                citekey=citekey,
                project=project,
                version=docs_version,
            ),
            # Never a source, though no corpus need exist: the pack would
            # publish what is in them.
            kept_out=own_directories(resolve_context().corpus_root),
            events=events,
        )
    report_add(
        _with_citekeys(addition.report, addition.update),
        noun="entry",
        plural="entries",
    )
    for relative in addition.copied:
        display.detail(">", describe_copied(relative))
    if addition.update is None:
        return
    _say_what_the_update_did(addition.update, described=False)
    display.next_step(f"kennis pack install {path}", note="to install this version")


@pack_group.command(name="remove", cls=KennisCommand)
@click.argument("names", nargs=-1, required=True)
@click.option(
    "--pack",
    "pack_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="The pack file. The one *.ken.yml here when not given.",
)
@click.option("-y", "--yes", is_flag=True, help="Do not ask first.")
def remove_command(names: tuple[str, ...], pack_path: Path | None, yes: bool) -> None:
    """Take entries out of a pack file.

    Each name is a citekey, an identifier, an address, a documentation
    project, a shipped file's path, a source folder, or a context file its
    folder's `include:` names. A copy `pack add`
    made under `files/` that no entry names any more is deleted; nothing
    else in the pack is.
    """
    from kennis.engine.pack.editing import (
        entries_named,
        find_pack_file,
        remove_from_pack,
    )
    from kennis.render.packs import describe_deleted

    path = pack_path or find_pack_file(Path.cwd())
    if not yes:
        # The pack's history is the author's, so this is a courtesy - but a
        # removal deletes the copies only this entry named, and that is
        # worth one keystroke, as it is for `corpus remove`.
        listed = ", ".join(entries_named(path, names))
        click.confirm(f"Remove {listed} from {path.name}?", abort=True)
    with reporting() as events:
        edit = remove_from_pack(path, names, events=events)
    from kennis.render.words import count_of

    display.operation("Removed", count_of(len(edit.removed), "entry", "entries"))
    for name in edit.removed:
        display.detail("-", name)
    for relative in edit.deleted:
        display.detail("-", describe_deleted(relative))
    _say_what_the_update_did(edit.update)
    display.next_step(f"kennis pack install {path}", note="to install this version")


def _with_citekeys(report: AddReport, update: PackUpdate | None) -> AddReport:
    """`report` with each paper the update described named with the citekey
    it was given, so the paper is one line rather than two (Brian,
    2026-10-27). A paper is named by its entry's key, which is what the
    update names it by."""
    from dataclasses import replace

    from kennis.render.packs import describe_described

    citekeys = dict(update.described) if update is not None else {}
    return replace(
        report,
        outcomes=[
            replace(outcome, title=describe_described(outcome.title, citekey))
            if outcome.title is not None
            and (citekey := citekeys.get(outcome.title)) is not None
            else outcome
            for outcome in report.outcomes
        ],
    )


def _say_what_the_update_did(
    result: PackUpdate | None, *, described: bool = True
) -> None:
    """What the update after an edit did. The block's file count only when
    the pack ships files, since an edit's answer is the entries; `described`
    is False where the papers were already named with their citekeys."""
    from kennis.render.packs import describe_recorded

    if result is None:
        return
    if result.files:
        display.detail("=", describe_recorded(result))
    _say_the_rest(result, described=described)


@pack_group.command(name="update", cls=KennisCommand)
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def update_command(path: Path) -> None:
    """Recompute a pack's generated block from the content it names.

    A paper declared without a `citekey` is described here, as `corpus add`
    would describe it - looked up on arXiv or at its DOI's registry - and
    the citekey, title, authors and year it lacks are written into its
    entry, so every machine files it alike. An entry with a citekey is not
    looked up.

    **Run this after changing any file the pack ships**, and before
    `pack validate`. A pack whose digests disagree with its files is
    believed on kennis's fast path, so the block is what makes the pack
    honest about itself.

    A run that finds nothing changed leaves the file byte-identical, so
    calling it on every release build is free.
    """
    from kennis.engine.pack.update import update_pack
    from kennis.render.packs import describe_recorded

    with reporting() as events:
        result = update_pack(path, events=events)
    if result.outcome == "unchanged":
        display.operation("Unchanged", f"{path}")
        display.detail("=", describe_recorded(result))
        _say_the_rest(result)
        return
    display.operation("Updated", f"{path}")
    display.detail("+", describe_recorded(result))
    _say_the_rest(result)


@pack_group.command(name="format", cls=KennisCommand)
@click.option(
    "--pack",
    "pack_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="The pack file. The one *.ken.yml here when not given.",
)
def format_command(pack_path: Path | None) -> None:
    """Write every entry of a pack file the way kennis writes one.

    Each entry becomes a mapping in braces with one key per line, a paper's
    identifier first and its authors last, as a list, and entries are set
    apart by a blank line. Comments between entries are kept; a comment
    inside an entry is not. A pack whose authors are one string, as kennis
    wrote them before, is made readable again by this.
    """
    from kennis.engine.pack.editing import find_pack_file
    from kennis.engine.pack.formatting import format_pack

    path = pack_path or find_pack_file(Path.cwd())
    if format_pack(path):
        display.operation("Formatted", path.name)
        return
    display.operation("Unchanged", path.name)
    display.detail("=", "already formatted")


def _say_the_rest(result: PackUpdate, *, described: bool = True) -> None:
    """Each paper described and the citekey it was given; then files in a
    declared source that no pattern took, and papers left undescribed.

    The leftovers are reported on an unchanged run as well, because that is
    the run where it matters most: an author who has just added a `.csv` to
    the source and been told "Unchanged" has no other way to find out why.
    """
    from kennis.render.packs import (
        describe_described,
        describe_undescribed,
        describe_unselected,
    )

    for key, citekey in result.described if described else ():
        display.detail("+", describe_described(key, citekey))
    if result.unselected:
        display.detail(">", describe_unselected(result.unselected))
    if result.undescribed:
        display.detail(">", describe_undescribed(result.undescribed))


@pack_group.command(name="validate", cls=KennisCommand)
@click.argument(
    "path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def validate_command(path: Path) -> None:
    """Check a `.ken.yml` file against kennis and against its own content.

    **Meant for a release pipeline.** A pack that ships without this having
    passed can declare digests that disagree with the files beside them, and
    kennis believes a pack's own digests on the fast path - so the check that
    keeps that honest is this one, run where the pack is built.

    Exits non-zero when anything is wrong, so a pipeline stops.
    """
    from kennis.engine.pack.validate import validate_pack

    with reporting() as events:
        report = validate_pack(path, events=events)
    _report(report)
    if not report.ok:
        raise SystemExit(1)


def _report(report: PackReport) -> None:
    """Everything found, refusals first."""
    from kennis.render.packs import (
        describe_problem,
        describe_refusal,
        describe_update_needed,
        remedy_for,
    )
    from kennis.render.words import count_of

    if report.refusal is not None:
        display.failure(describe_refusal(report.refusal))
        display.remedy(remedy_for(report.refusal))
        return

    if not report.problems:
        # "Checked", not "Valid": `display.operation` takes the past-tense
        # verb for what the command did, and the verdict is the line under
        # it. Every other operation in kennis reads the same way.
        display.operation(
            "Checked", f"{report.pack.pack.id} {report.pack.pack.version}"
        )
        _say_what_was_checked(report)
        return

    display.failure(count_of(len(report.problems), "problem") + " in this pack")
    digests = [problem for problem in report.problems if problem.kind in _DIGEST_KINDS]
    if digests:
        display.note(describe_update_needed(len(digests)))
        display.remedy(f"kennis pack update {report.path}")
    for problem in report.problems:
        display.detail("-", describe_problem(problem))


def _say_what_was_checked(report: PackReport) -> None:
    """A pack with no `generated` block is valid and was checked for less.

    Said out loud because `validate` in a release pipeline is exactly where
    a forgotten `pack update` should be caught, and a bare "valid" would
    report the same word for two different amounts of checking.
    """
    from kennis.render.packs import describe_verdict

    # Both verdicts are details of the same operation, so both sit in the
    # detail column. `>` is the marker `sink.marker_for` already gives a
    # skipped item, and the digest check is exactly what was skipped - not a
    # warning, because a pack that ships no content is not going wrong.
    marker = "+" if report.digests_checked else ">"
    display.detail(marker, describe_verdict(report))


@pack_group.command(name="list", cls=KennisCommand)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print one JSON document for a program to read, instead of rows.",
)
def list_command(*, as_json: bool) -> None:
    """Every pack installed on this machine.

    The listing is the whole answer, so it is a listing and not a report:
    the pack id leads, because it is the column you copy out of and hand
    to `pack uninstall`.

    `--json` is for a provider asking whether its pack is held, so the
    rows stay free to change for a person (#401 reversed). No corpus is
    still a failure rather than an empty document, because "kennis cannot
    answer" and "kennis holds nothing" lead a provider to different things.
    """
    from kennis.render.machine_readable import pack_list_document
    from kennis.render.packs import describe_holdings, describe_installed

    if as_json:
        display.declare_stdout_a_payload()
    listing = api.pack_listing(existing_corpus().corpus_root)
    if as_json:
        display.plain(pack_list_document(listing).model_dump_json(indent=2))
        return
    # Padded so the versions line up. Layout, not wording, so it is decided
    # here: `corpus list` needs none of this because a surrogate id is fixed
    # width, and a pack id is whatever the provider called itself.
    width = max((len(one.state.pack_id) for one in listing.packs), default=0)
    # Sorted the way `describe_holdings` sorts, so the two sequences line
    # up. Section 11 makes these the same bytes the MCP server's
    # instructions block carries, and a listing whose order differs from
    # the block's would pair a pack with another's description.
    ordered = sorted(listing.packs, key=lambda one: one.state.pack_id)
    for installed, holding in zip(ordered, describe_holdings(ordered), strict=True):
        display.row(installed.state.pack_id.ljust(width), describe_installed(installed))
        # Aligned under the version column, not at the row's own indent.
        # At the same indent it reads as another pack id - a one-word
        # pack name is indistinguishable from an id, which is exactly
        # what running it showed. `row` with no identifier is the
        # quiet-guarded way to print a dimmed continuation.
        display.row("", " " * (width + 2) + holding)
    if listing.unreadable:
        _report_unreadable(listing)
    if not listing.packs and not listing.unreadable:
        display.note("no packs installed")


def _report_unreadable(listing: PackListing) -> None:
    """Directories under `packs/` that are not installed packs.

    Named with the command that ends the state, not only reported.
    Concern #244: a reader told something is wrong and not told what to
    type has been sent round a loop. Removing is the only way out - there
    is no state file to repair from, and `add` would rewrite the
    directory without ever mentioning what was there.
    """
    from kennis.render.packs import describe_unreadable

    display.note(describe_unreadable(listing.unreadable))
    for name in listing.unreadable:
        display.next_step(f"kennis pack uninstall {name}")


@pack_group.command(name="status", cls=KennisCommand)
def status_command() -> None:
    """What each installed pack recorded, and where two of them collide.

    **The overlaps are the reason this command exists.** Two packs
    declaring the same paper or the same documentation project is resolved
    silently, by whichever was installed first, and a resolution nobody is
    told about is one nobody can correct. Reported here every run rather
    than once, inside an automated provider run nobody reads.
    """
    from kennis.render.packs import describe_installed, describe_when

    listing = api.pack_listing(existing_corpus().corpus_root)
    for installed in listing.packs:
        display.operation(installed.state.pack_id, describe_installed(installed))
        display.detail("=", describe_when(installed))
        _report_damage(installed)
    _report_overlaps(listing)
    if listing.unreadable:
        _report_unreadable(listing)
    if not listing.packs and not listing.unreadable:
        display.note("no packs installed")


def _report_damage(installed: InstalledPack) -> None:
    """A damaged pack, and the command that puts it back.

    The store records where the pack came from, so when that path still
    resolves the repair is one command. When it does not - a provider
    uninstalled, a checkout deleted - there is nothing on this machine to
    repair from and the only answer is the provider's own run, which
    kennis cannot name because it is not a kennis command.
    """
    from kennis.render.packs import describe_damage, describe_lost_source

    damage = describe_damage(installed)
    if damage is None:
        return
    display.detail("!", damage)
    source = Path(installed.state.source_path)
    if source.is_file():
        display.next_step(f"kennis pack install {source}")
    else:
        display.hint(describe_lost_source(installed))


def _report_overlaps(listing: PackListing) -> None:
    """Every item more than one installed pack declares.

    Under its own heading rather than beneath one of the packs: an overlap
    belongs to the pair, and filing it under either one would say it twice
    or say it in the wrong place.
    """
    from kennis.engine.pack.installed import overlaps_between
    from kennis.render.packs import describe_overlap
    from kennis.render.words import count_of

    found = overlaps_between(listing.packs)
    if not found:
        return
    display.operation("Shared", count_of(len(found), "item"))
    for overlap in found:
        display.detail("~", describe_overlap(overlap))


@pack_group.command(name="uninstall", cls=KennisCommand)
@click.argument("pack_id")
def uninstall_command(pack_id: str) -> None:
    """Drop a pack from this machine's store.

    **It reaches the store and nothing else.** Documents already in the
    corpus stay, and so does this pack's content in any project you have
    checked out - kennis keeps no registry of your projects, so it cannot
    reach them. They converge when each one is next synchronised.
    """
    from kennis.render.packs import (
        describe_removal,
        describe_what_uninstall_cannot_reach,
    )

    corpus_root = existing_corpus().corpus_root
    with DisplaySink() as shown:
        removal = api.uninstall_pack(
            corpus_root, pack_id, events=shown, on_waiting=say_waiting
        ).result
    display.operation("Uninstalled", removal.pack_id)
    display.detail("-", describe_removal(removal))
    display.guidance(describe_what_uninstall_cannot_reach())
    # Named because the limit above is otherwise only a statement of
    # helplessness: kennis cannot reach the user's projects, and the user
    # can. The corpus it *can* reach, so that one is named too.
    display.next_step("kennis corpus sync")
    display.next_step(
        "kennis context sync", note="in each project that has its content"
    )


__all__ = ["pack_group", "validate_command"]
