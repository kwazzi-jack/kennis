"""What the graphical interface says.

Beside `mcp/tools/*`, which compose their own sentences for the same
reason: `render/` holds what every front end says about an engine
value, and each front end holds what only it says. "Load images" is
not a fact about a document - it is a control on a page.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from kennis.engine.context.notes import BundleNote
from kennis.engine.corpus.add import AddReport
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.events import Outcome
from kennis.engine.remember import RememberReport
from kennis.gui.pages import ShownOutcome
from kennis.holdings import Holding
from kennis.operations import BuiltIndex, IndexBuild
from kennis.render.words import (
    conversion_cost,
    conversion_repairs,
    count_of,
    describe_freshness,
    index_state,
    joined,
    needs_an_index,
)
from kennis.retrieval import EVERY_SCOPE

RECENTS_HEADING = "Recent searches"

RECENTS_CLEAR = "Forget these"

NOTHING_FOUND = "Nothing matched. Try fewer words, or a wider scope."


def search_hint_for(scope: str) -> str:
    """What the search box says when it is empty.

    **It names the scope it is pointed at.** It read "Search
    everything kennis holds" whatever the select said, so a reader
    who had narrowed to `literature` was told the opposite of what
    was about to happen.

    `EVERYWHERE_LABEL` for a sweep rather than a second word for the
    same choice: the select's own option says "everywhere", and the
    box beside it saying "everything" would be two names for one
    scope.

    Plain text with no emphasis, because a `placeholder` attribute
    carries no markup. Italicising the scope would mean hiding the
    native placeholder behind an element positioned over the box,
    and that was weighed and declined.
    """
    where = EVERYWHERE_LABEL if scope == EVERY_SCOPE else scope
    return f"Search {where} kennis holds"


SEARCH_ACTION = "Search"

SCOPE_LABEL = "Where to look"

EVERYWHERE_LABEL = "everywhere"

BACK_TO_SEARCH = "Back to the results"

# The header's labels, keyed by the path they lead to. Here
# rather than in `base.html` because they are words, and
# because a label that disagreed with the page's own heading
# called the same page two things. A test compares them.
NAV_LABELS: Final[dict[str, str]] = {
    "held": "What is held",
    "remember": "Remember",
    "manage": "Manage",
}

NOTHING_TO_INDEX = "There is nothing to index yet."

BUNDLE_NOT_COMMITTED = (
    "kennis did not commit: the bundle is in your repository, so this "
    "change is yours to commit with the project."
)

NOTHING_MATERIALISED = (
    "Nothing has reached a collection yet. Installing records what the "
    "pack declares; a sync brings it in."
)

BUSY_WITH_ANOTHER = "Something else is running. kennis does one at a time."

CORPUS_BUSY_RETRY = (
    "The corpus is busy - something else is writing to it. Nothing was "
    "changed, so this can be tried again."
)

NOTHING_TO_ADD = "Name at least one file, directory or URL."

ADD_PREAMBLE = (
    "A file, a directory, a URL, or - for literature - an arXiv "
    "identifier, DOI or ADS bibcode. One per line."
)

ADD_ACTION = "Add"

INDEX_PREAMBLE = (
    "Building an index reads every document in a collection. With a dense "
    "backend configured it downloads a model the first time, which is why "
    "the first run is the slow one."
)

INDEX_ACTION = "Build the index"

SYNC_PREAMBLE = (
    "A corpus sync fetches what every installed pack declares, so it uses "
    "the network. A project sync copies from this machine's store and does "
    "not."
)

PACK_PREAMBLE = (
    "The path to a pack's .ken.yml. Installing records what the provider "
    "declared; nothing reaches a collection until a sync."
)

PACK_ACTION = "Install"

# No "the Index section above": Add is first on the manage page
# and Index is third, so the sentence was wrong as well as
# fragile. A message does not name a position on a page.
NOT_SEARCHABLE_YET = "Not searchable until the index is rebuilt."

NO_SUCH_JOB = "That operation has finished, or was never started here."

STILL_RUNNING = "This is still running."

NOTHING_TO_SHOW = "That operation finished without reporting anything."

MARK_WITHHELD = (
    "This document has changed since the index was built, so the passage "
    "the search matched can no longer be placed in it. Rebuild the index "
    "to see it marked again."
)

IMAGES_BLOCKED = (
    "This document refers to figures held elsewhere. They were not fetched, "
    "because requesting one tells the site which document is being read."
)

LOAD_IMAGES = "Load them"

NEVER_INDEXED = "never indexed"

CORPUS_CHANGED = "Something else has changed the corpus. Reload to see it."

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
            # Nothing was written, and the text in the box is the
            # duplicate that was refused - keeping it would invite
            # the reader to press the button again.
            clears=True,
        )
    if needs_an_index(report.index_outcome):
        state = index_state(report.index_outcome, report.chunk_count)
        return ShownOutcome(
            message=f"Remembered: {report.title} - {state}",
            role="role-operation",
            where=where,
            clears=True,
            # The note is written and is not findable, and nothing on
            # this page can change that - so it is a command, not a
            # clause appended to the good news. The Index section on
            # the manage page runs it, but a deferred rebuild is the
            # one case where waiting a moment is also an answer.
            resolution="kennis corpus index",
        )
    state = index_state(report.index_outcome, report.chunk_count)
    suffix = f" - {state}" if state else ""
    return ShownOutcome(
        message=f"Remembered: {report.title}{suffix}",
        role="role-operation",
        where=where,
        clears=True,
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
        clears=True,
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


def describe_recent(scope: str, hits: int, *, capped: bool) -> str:
    """The line beside a past search: where it looked and what it found.

    The count is what it found *then*. The corpus has moved since -
    a note written this morning may mean the same query answers
    differently now - so this is a record of the search and not a
    promise about re-running it.

    **"at least" when a scope returned all it was asked for**, which
    is most of the time: `default_top_k` is 3 per scope, so an
    everywhere search over three indexed collections stops at 9 and
    has no idea how many more there were. Every query reported "9
    hits" until this said so, which is a number that looks measured
    and is really a ceiling.
    """
    where = EVERYWHERE_LABEL if scope == EVERY_SCOPE else scope
    counted = count_of(hits, "hit")
    # "9+" rather than "at least 9": the margin is 11rem and the
    # longer form wrapped between "9" and "hits", which reads worse
    # than the notation does.
    return f"{where}, {hits}+ hits" if capped else f"{where}, {counted}"


def unknown_scope(asked: str, scopes: Sequence[str]) -> str:
    """Named rather than silently empty.

    A mistyped scope answered with no hits reads as "nothing is here",
    which is a different and wrong conclusion.
    """
    return f"There is no scope called '{asked}'. The scopes are {joined(list(scopes))}."


__all__ = [
    "ADD_ACTION",
    "ADD_PREAMBLE",
    "BACK_TO_SEARCH",
    "BUNDLE_NOT_COMMITTED",
    "BUSY_WITH_ANOTHER",
    "CORPUS_BUSY",
    "CORPUS_BUSY_RETRY",
    "CORPUS_CHANGED",
    "EVERYWHERE_LABEL",
    "GROUP_HINT",
    "IMAGES_BLOCKED",
    "INDEX_ACTION",
    "INDEX_PREAMBLE",
    "LOAD_IMAGES",
    "MARK_WITHHELD",
    "NEVER_INDEXED",
    "NOTHING_FOUND",
    "NOTHING_HELD",
    "NOTHING_MATERIALISED",
    "NOTHING_TO_ADD",
    "NOTHING_TO_INDEX",
    "NOTHING_TO_REMEMBER",
    "NOTHING_TO_SHOW",
    "NOT_SEARCHABLE_YET",
    "NO_PACKS",
    "NO_SUCH_JOB",
    "PACK_ACTION",
    "PACK_PREAMBLE",
    "RECENTS_CLEAR",
    "RECENTS_HEADING",
    "REMEMBER_ACTION",
    "REMEMBER_PLACEHOLDER",
    "REMEMBER_PREAMBLE",
    "SCOPE_LABEL",
    "SEARCH_ACTION",
    "STILL_RUNNING",
    "SYNC_PREAMBLE",
    "TITLE_HINT",
    "describe_count",
    "describe_holding",
    "describe_recent",
    "describe_written",
    "describe_written_to_bundle",
    "search_hint_for",
    "unknown_scope",
    "unreadable_note",
]


def added_headline(added: int, report: AddReport) -> str:
    """The line above an add's items.

    The cost and the repairs ride on it rather than each taking a line
    of their own: both are properties of what just happened, and a
    separate line would give a free local conversion a blank where a
    number used to be.
    """
    priced = conversion_cost(report.cost_cents)
    repaired = conversion_repairs(report.repairs)
    return (
        f"Added {count_of(added, 'document')}"
        + (f", {priced}" if priced else "")
        + (f", {repaired}" if repaired else "")
    )


def indexed_headline(built: IndexBuild) -> str:
    """What an index build amounts to, across every collection it touched."""
    if not built.built:
        return "Indexed nothing"
    return (
        f"Indexed {count_of(built.documents, 'document')} as "
        f"{count_of(built.chunks, 'chunk')}"
    )


def describe_built(index: BuiltIndex) -> str:
    """One collection's share of a build."""
    return (
        f"{count_of(index.documents, 'document')} as {count_of(index.chunks, 'chunk')}"
    )


def describe_backend(built: IndexBuild) -> str:
    """Which backend a build used, named before the wait it explains.

    A dense build downloads a model on a machine that has never run
    one, and a long pause needs its explanation already on screen
    rather than afterwards.
    """
    if built.model_kind is None or built.model_name is None:
        return "lexical search only, with no embedding backend"
    return f"{built.model_kind} {built.model_name}"


def unknown_collection(asked: str) -> str:
    """A collection that is not one of the three, named back."""
    return f"'{asked}' is not a collection. There are {joined(COLLECTION_NAMES)}."


def no_such_pack(given: str) -> str:
    """A pack path that names no file.

    The path is quoted back because a typo is the likely cause and a
    reader cannot see one they cannot see.
    """
    if not given:
        return "Name the path to a pack's .ken.yml."
    return f"'{given}' is not a file."
