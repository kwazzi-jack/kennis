"""`kennis pack`: knowledge that arrives from outside, as data.

**Two roles, told apart by their object** (design section 9). `init`,
`update` and `validate` act on a `.ken.yml` at a path - authoring, which is
what a provider does in its own release pipeline. `add`, `remove`, `list`
and `status` act on the installed store - consuming. `validate` serves both,
and it is the only one of them that exists yet.
"""

from __future__ import annotations

from pathlib import Path

import click

from kennis.cli import display
from kennis.cli.group import KennisCommand, KennisGroup
from kennis.engine.pack.validate import PackReport, validate_pack
from kennis.render.packs import (
    describe_problem,
    describe_refusal,
    describe_update_needed,
    remedy_for,
)
from kennis.render.words import count_of

_DIGEST_KINDS = frozenset({"digest-mismatch", "digest-absent", "undigested"})


@click.group(name="pack", cls=KennisGroup)
def pack_group() -> None:
    """Author and check a pack of knowledge."""


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
    report = validate_pack(path)
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
        display.operation("Valid", f"{report.pack.pack.id} {report.pack.pack.version}")
        _say_what_was_checked(report)
        return

    display.failure(count_of(len(report.problems), "problem") + " in this pack")
    digests = [problem for problem in report.problems if problem.kind in _DIGEST_KINDS]
    if digests:
        # No `display.hint`: that prints a command, and `kennis pack update`
        # is unit 4. Rule 4.4 - a printed command runs as printed.
        display.note(describe_update_needed(len(digests)))
    for problem in report.problems:
        display.detail("-", describe_problem(problem))


def _say_what_was_checked(report: PackReport) -> None:
    """A pack with no `generated` block is valid and was checked for less.

    Said out loud because `validate` in a release pipeline is exactly where
    a forgotten `pack update` should be caught, and a bare "valid" would
    report the same word for two different amounts of checking.
    """
    if report.digests_checked:
        display.detail("+", "digests agree with the content")
        return
    display.guidance("no generated block, so no digest was checked")


__all__ = ["pack_group", "validate_command"]
