"""What the graphical interface says.

Beside `mcp/tools/*`, which compose their own sentences for the same
reason: `render/` holds what every front end says about an engine
value, and each front end holds what only it says. "Load images" is
not a fact about a document - it is a control on a page.
"""

from __future__ import annotations

from collections.abc import Sequence

from kennis.engine.context.notes import BundleNote
from kennis.engine.events import Outcome
from kennis.engine.remember import RememberReport
from kennis.gui.pages import ShownOutcome
from kennis.holdings import Holding
from kennis.render.words import (
    count_of,
    describe_freshness,
    index_state,
    joined,
)

NOTHING_FOUND = "No passages matched."

IMAGES_BLOCKED = (
    "This document refers to figures held elsewhere. They were not fetched, "
    "because requesting one tells the site which document is being read."
)

LOAD_IMAGES = "Load them"

NEVER_INDEXED = "never indexed"

CORPUS_CHANGED = "The corpus has changed since this page was drawn. Reload to see it."

NOTHING_HELD = "This corpus holds no documents yet."

NO_PACKS = "No packs are installed."

REMEMBER_PREAMBLE = (
    "What is written here is kept. A note goes into the machine-global "
    "corpus and is committed to its history; a project note goes into "
    "this repository's .context/ bundle and is not committed, so it is "
    "yours to commit with the project."
)

REMEMBER_PLACEHOLDER = "Something worth having again in six months"

TITLE_HINT = "Title (optional - the first line is used otherwise)"

GROUP_HINT = "Group (optional subdirectory)"

REMEMBER_ACTION = "Remember"

NOTHING_TO_REMEMBER = "There is nothing to remember - no text was given."

CORPUS_BUSY = (
    "The corpus is busy - another kennis command is using it. Your text is "
    "still here; try again in a moment."
)


def describe_written(report: RememberReport, where: str) -> ShownOutcome:
    """What one note written into the corpus came to.

    An unchanged outcome is not a failure and not a success worth
    celebrating: the thing is already known, which is why it wears the
    role that carries no colour.
    """
    if report.outcome is Outcome.UNCHANGED:
        return ShownOutcome(
            message=f"Already remembered: {report.title}",
            role="role-unchanged",
            where=where,
        )
    if report.index_outcome == "unindexed":
        return ShownOutcome(
            message=f"Remembered: {report.title}",
            role="role-operation",
            where=where,
            # The note is written and is not findable, and nothing on
            # this page can change that - so it is a command, not a
            # clause appended to the good news.
            resolution="kennis corpus index",
        )
    state = index_state(report.index_outcome, report.chunk_count)
    suffix = f" - {state}" if state else ""
    return ShownOutcome(
        message=f"Remembered: {report.title}{suffix}",
        role="role-operation",
        where=where,
    )


def describe_written_to_bundle(note: BundleNote, bundle_name: str) -> ShownOutcome:
    """The same for a bundle note.

    Prefixed with the bundle's directory name, because
    `decisions/Solver choice.md` does not say which of the two places
    `remember` writes to it landed in.
    """
    already = note.outcome is Outcome.UNCHANGED
    return ShownOutcome(
        message=(
            f"Already in this project: {note.title}"
            if already
            else f"Remembered in this project: {note.title}"
        ),
        role="role-unchanged" if already else "role-operation",
        where=f"{bundle_name}/{note.relative_path}",
    )


def describe_holding(holding: Holding) -> str:
    """How far one collection's index has fallen behind, for a cell.

    An index that was never built says so in its own words rather than
    borrowing `describe_freshness`, which has no case for it: the
    command line simply prints nothing and moves to the next
    collection, and a table has a cell that must say something.
    """
    if holding.freshness is None:
        return NEVER_INDEXED
    return describe_freshness(holding.freshness, holding.collection)


def unreadable_note(count: int) -> str | None:
    """A listing that omitted documents says how many and why.

    None when there are none, so a page shows nothing rather than "0
    could not be read", which reads as a fault report about a corpus
    that is fine.
    """
    if not count:
        return None
    return (
        f"{count_of(count, 'document')} could not be read and "
        "are not listed. Run `kennis corpus status`."
    )


def describe_count(holding: Holding) -> str:
    """The document count, and the unreadable ones if there are any.

    The second half is never omitted when it applies. A collection
    reported as holding twelve when it holds thirteen, one of them
    broken, has been described falsely - the same rule `list_corpus`
    follows for the same reason.
    """
    counted = count_of(holding.documents, "document")
    if not holding.unreadable:
        return counted
    return f"{counted}, {holding.unreadable} unreadable"


def unknown_scope(asked: str, scopes: Sequence[str]) -> str:
    """Named rather than silently empty.

    A mistyped scope answered with no hits reads as "nothing is here",
    which is a different and wrong conclusion.
    """
    return f"There is no scope called '{asked}'. The scopes are {joined(list(scopes))}."


__all__ = [
    "CORPUS_BUSY",
    "CORPUS_CHANGED",
    "GROUP_HINT",
    "IMAGES_BLOCKED",
    "LOAD_IMAGES",
    "NEVER_INDEXED",
    "NOTHING_FOUND",
    "NOTHING_HELD",
    "NOTHING_TO_REMEMBER",
    "NO_PACKS",
    "REMEMBER_ACTION",
    "REMEMBER_PLACEHOLDER",
    "REMEMBER_PREAMBLE",
    "TITLE_HINT",
    "describe_count",
    "describe_holding",
    "describe_written",
    "describe_written_to_bundle",
    "unknown_scope",
    "unreadable_note",
]
