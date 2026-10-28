"""What `corpus add` and `pack add` share, so the two read as one command.

Brian, 2026-10-26: "I would like the cli interface to be uniform where it
can". Both name one destination the same way - `--collection` or a
shorthand, never two that disagree - refuse an option that means nothing
for it in the same words, and report the same shape: one operation line,
the items under their markers, a failure's reason on its own line, and the
commands that would resolve the failures once, below.

`pack add` has a fourth destination, `context`, which `corpus add` has
not; each command passes the destinations it offers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from kennis.cli import display
from kennis.cli.sink import marker_for

if TYPE_CHECKING:
    from kennis.engine.corpus.add import AddOutcome, AddReport

# Each destination's shorthand flag, for naming it back in an error. The
# options themselves are declared literally on each command.
SHORTHANDS: Final[dict[str, str]] = {
    "notes": "-n",
    "literature": "-l",
    "docs": "-d",
    "context": "-c",
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


def destination_named(
    collection: str | None, shorthands: Mapping[str, bool], *, offered: tuple[str, ...]
) -> str:
    """The one destination this add writes to.

    `--collection` here names a destination rather than a selection, so it is
    a single choice and never `all`: a document is written to exactly one
    place. Naming one twice and differently is an error rather than a
    precedence puzzle, because someone who typed both meant one of them and
    kennis cannot tell which. `shorthands` is each offered destination's
    flag, in the order the command declares them; `offered` is what
    `--collection` takes.
    """
    chosen = [name for name, given in shorthands.items() if given]
    if len(chosen) > 1:
        flags = ", ".join(SHORTHANDS[name] for name in chosen)
        raise display.CliError(f"{flags} name different collections. Pass one of them.")
    shorthand = chosen[0] if chosen else None

    if collection is not None and shorthand is not None and collection != shorthand:
        raise display.CliError(
            f"--collection {collection} and {SHORTHANDS[shorthand]} name "
            f"different collections. Pass one of them."
        )
    destination = collection or shorthand
    if destination is None:
        flags = "/".join(SHORTHANDS[name] for name in shorthands)
        raise display.CliError(
            f"name a collection: --collection {'|'.join(offered)}, or {flags}."
        )
    return destination


def refuse_foreign_options(
    destination: str,
    *,
    identifier: str | None,
    citekey: str | None,
    project: str | None,
    docs_version: str | None,
    refresh: bool = False,
) -> None:
    """Refuse an option that means nothing for the destination being written.

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


def report_add(
    report: AddReport, *, noun: str = "document", plural: str | None = None
) -> None:
    """What the add did: one operation line, then the items beneath it.

    Printed from the report rather than streamed from the event stream. A
    docs add of three hundred pages would otherwise put three hundred lines
    above the summary that was the answer; `display.details` caps them, and
    the log has all of them either way. `noun` is what was added: a
    document to a collection, an entry to a pack.
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
        count_of(counts.get(Outcome.ADDED, 0), noun, plural)
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
        display.remedy(command)


__all__ = [
    "SHORTHANDS",
    "destination_named",
    "refuse_foreign_options",
    "report_add",
]
