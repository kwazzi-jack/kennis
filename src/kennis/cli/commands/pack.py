"""`kennis pack`: knowledge that arrives from outside, as data.

**Two roles, told apart by their object** (design section 9). `init`,
`update` and `validate` act on a `.ken.yml` at a path - authoring, which is
what a provider does in its own release pipeline. `add`, `remove`, `list`
and `status` act on the installed store - consuming. `validate` serves both.
"""

from __future__ import annotations

from pathlib import Path

import click

from kennis.cli import display
from kennis.cli.context import existing_corpus
from kennis.cli.group import KennisCommand, KennisGroup
from kennis.cli.sink import reporting
from kennis.engine.locking import corpus_lock
from kennis.engine.pack.installed import (
    InstalledPack,
    PackListing,
    list_installed,
    overlaps_between,
    remove_pack,
)
from kennis.engine.pack.scaffold import DEFAULT_VERSION, scaffold_pack
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import PackUpdate, update_pack
from kennis.engine.pack.validate import PackReport, validate_pack
from kennis.render.packs import (
    describe_damage,
    describe_declarations,
    describe_install,
    describe_installed,
    describe_lost_source,
    describe_overlap,
    describe_problem,
    describe_recorded,
    describe_refusal,
    describe_removal,
    describe_unreadable,
    describe_unselected,
    describe_update_needed,
    describe_verdict,
    describe_what_remove_cannot_reach,
    describe_when,
    remedy_for,
)
from kennis.render.words import count_of

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


@pack_group.command(name="add", cls=KennisCommand)
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def add_command(path: Path) -> None:
    """Install a pack into this machine's store.

    **Meant to be called by the provider**, from its own sync command, on
    every run: `boepie sync` ends by handing kennis the path to its own
    `.ken.yml`. Calling it repeatedly is cheap - a pack whose file and
    store both check out is recognised and nothing is rewritten.

    No network, and nothing is materialised into the corpus yet: this
    records what the provider declared. `corpus sync` and `context sync`
    converge the documents with it, and neither is built.
    """
    context = existing_corpus()
    with corpus_lock(context.corpus_root), reporting() as events:
        install = install_pack(context.corpus_root, path, events=events)
    display.operation(_INSTALL_VERBS[install.outcome], install.pack_id)
    display.detail(_INSTALL_MARKERS[install.outcome], describe_install(install))
    declared = describe_declarations(install)
    if declared is not None:
        display.detail(">", declared)
    if install.outcome != "unchanged":
        # Said at all because "Installed" otherwise implies the content is
        # searchable, and it is not: this records what the provider
        # declared and a sync materialises it. Only when something
        # changed - a provider calling this on every run does not need the
        # same sentence each time.
        display.guidance(
            "nothing is materialised yet: a sync converges each scope with "
            "what every installed pack declares"
        )
        display.next_step("kennis corpus sync")
        display.next_step("kennis context sync", note="in each project that wants it")


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


@pack_group.command(name="update", cls=KennisCommand)
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def update_command(path: Path) -> None:
    """Recompute a pack's generated block from the content it names.

    **Run this after changing any file the pack ships**, and before
    `pack validate`. A pack whose digests disagree with its files is
    believed on kennis's fast path, so the block is what makes the pack
    honest about itself.

    A run that finds nothing changed leaves the file byte-identical, so
    calling it on every release build is free.
    """
    with reporting() as events:
        result = update_pack(path, events=events)
    if result.outcome == "unchanged":
        display.operation("Unchanged", f"{path}")
        display.detail("=", describe_recorded(result))
        _say_what_was_left(result)
        return
    display.operation("Updated", f"{path}")
    display.detail("+", describe_recorded(result))
    _say_what_was_left(result)


def _say_what_was_left(result: PackUpdate) -> None:
    """Files in a declared source that no pattern took.

    Reported on an unchanged run as well, because that is the run where it
    matters most: an author who has just added a `.csv` to the source and
    been told "Unchanged" has no other way to find out why.
    """
    if result.unselected:
        display.detail(">", describe_unselected(result.unselected))


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
    with reporting() as events:
        report = validate_pack(path, events=events)
    _report(report)
    if not report.ok:
        raise SystemExit(1)


def _report(report: PackReport) -> None:
    """Everything found, refusals first."""
    if report.refusal is not None:
        display.failure(describe_refusal(report.refusal))
        display.hint(remedy_for(report.refusal))
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
        display.hint(f"kennis pack update {report.path}")
    for problem in report.problems:
        display.detail("-", describe_problem(problem))


def _say_what_was_checked(report: PackReport) -> None:
    """A pack with no `generated` block is valid and was checked for less.

    Said out loud because `validate` in a release pipeline is exactly where
    a forgotten `pack update` should be caught, and a bare "valid" would
    report the same word for two different amounts of checking.
    """
    # Both verdicts are details of the same operation, so both sit in the
    # detail column. `>` is the marker `sink.marker_for` already gives a
    # skipped item, and the digest check is exactly what was skipped - not a
    # warning, because a pack that ships no content is not going wrong.
    marker = "+" if report.digests_checked else ">"
    display.detail(marker, describe_verdict(report))


@pack_group.command(name="list", cls=KennisCommand)
def list_command() -> None:
    """Every pack installed on this machine.

    The listing is the whole answer, so it is a listing and not a report:
    the pack id leads, because it is the column you copy out of and hand
    to `pack remove`.
    """
    context = existing_corpus()
    listing = list_installed(context.corpus_root)
    # Padded so the versions line up. Layout, not wording, so it is decided
    # here: `corpus list` needs none of this because a surrogate id is fixed
    # width, and a pack id is whatever the provider called itself.
    width = max((len(one.state.pack_id) for one in listing.packs), default=0)
    for installed in listing.packs:
        display.row(installed.state.pack_id.ljust(width), describe_installed(installed))
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
    display.note(describe_unreadable(listing.unreadable))
    for name in listing.unreadable:
        display.next_step(f"kennis pack remove {name}")


@pack_group.command(name="status", cls=KennisCommand)
def status_command() -> None:
    """What each installed pack recorded, and where two of them collide.

    **The overlaps are the reason this command exists.** Two packs
    declaring the same paper or the same documentation project is resolved
    silently, by whichever was installed first, and a resolution nobody is
    told about is one nobody can correct. Reported here every run rather
    than once, inside an automated provider run nobody reads.
    """
    context = existing_corpus()
    listing = list_installed(context.corpus_root)
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
    damage = describe_damage(installed)
    if damage is None:
        return
    display.detail("!", damage)
    source = Path(installed.state.source_path)
    if source.is_file():
        display.next_step(f"kennis pack add {source}")
    else:
        display.hint(describe_lost_source(installed))


def _report_overlaps(listing: PackListing) -> None:
    """Every item more than one installed pack declares.

    Under its own heading rather than beneath one of the packs: an overlap
    belongs to the pair, and filing it under either one would say it twice
    or say it in the wrong place.
    """
    found = overlaps_between(listing.packs)
    if not found:
        return
    display.operation("Shared", count_of(len(found), "item"))
    for overlap in found:
        display.detail("~", describe_overlap(overlap))


@pack_group.command(name="remove", cls=KennisCommand)
@click.argument("pack_id")
def remove_command(pack_id: str) -> None:
    """Drop a pack from this machine's store.

    **It reaches the store and nothing else.** Documents already in the
    corpus stay, and so does this pack's content in any project you have
    checked out - kennis keeps no registry of your projects, so it cannot
    reach them. They converge when each one is next synchronised.
    """
    context = existing_corpus()
    with corpus_lock(context.corpus_root), reporting() as events:
        removal = remove_pack(context.corpus_root, pack_id, events=events)
    display.operation("Removed", removal.pack_id)
    display.detail("-", describe_removal(removal))
    display.guidance(describe_what_remove_cannot_reach())
    # Named because the limit above is otherwise only a statement of
    # helplessness: kennis cannot reach the user's projects, and the user
    # can. The corpus it *can* reach, so that one is named too.
    display.next_step("kennis corpus sync")
    display.next_step(
        "kennis context sync", note="in each project that has its content"
    )


__all__ = ["pack_group", "validate_command"]
