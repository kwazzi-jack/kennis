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

# Shown while the hits on the page are not the hits for what is in
# the box. That covers the 400ms typing debounce as well as the
# request, which is the point: the request is 12ms of a 412ms wait
# and an indicator for it alone would never be seen. Concern #365.
SEARCHING = "Searching"

SCOPE_LABEL = "Where to look"

# How to match, and **the labels are the band's labels**. A hit
# reads `keywords: very high  meaning: low`, so a control
# offering "bm25" and "dense" beside it would give the reader two
# vocabularies for one distinction. Those are the engine's names for
# the mechanism; these name what it measures.
#
# The first value is empty, and it is not "hybrid". Passing no mode
# lets each scope use its own setting, and a bundle's is lexical by
# design - design section 13, because a dense bundle index costs what
# `retrieval.context_method` exists to avoid. Sending "hybrid" for a
# reader who touched nothing would ask the bundle for a leg it
# deliberately has not got, and then report the absence as news.
MODE_LABEL = "How to match"
MODE_DEFAULT = ""
MODE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (MODE_DEFAULT, "As configured"),
    ("hybrid", "Keywords and meaning"),
    ("bm25", "Keywords only"),
    ("dense", "Meaning only"),
)

EVERYWHERE_LABEL = "everywhere"

BACK_TO_SEARCH = "Back to the results"

# A hit's passage opens in place, and the button says which way it
# goes. Both are handed to `static/passage.js` in `data-` attributes,
# because a sentence in a script is one a wording pass cannot find.
SHOW_PASSAGE = "Show the whole passage"
HIDE_PASSAGE = "Show less"

# The link from a hit into its document is an icon, so this is its
# accessible name and its tooltip (#415).
OPEN_AT_PASSAGE = "Open the document at this passage"

# Which icon names each measure, from Lucide. The tooltip is the
# measure's own word from `render/hits.py::LEG_LABELS`; milestone 12
# lets the reader choose icons, words or both.
MEASURE_ICONS: Final[dict[str, str]] = {"lexical": "whole-word", "meaning": "brain"}

# Reordering one collection's hits by one measure's own rank (#406).
# The values are the engine's leg names, as `mode`'s are its method
# names; the labels are the measures' words. The first is empty, which
# is the order the search returned.
ORDER_LABEL = "Order"
ORDER_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("", "As ranked"),
    ("lexical", "By keywords"),
    ("meaning", "By meaning"),
)
# The limit, said beside the control: a reorder acts on the hits already
# returned, which the fused rank chose.
ORDER_LIMIT = (
    "Reordering sorts the hits this search returned. To search by one "
    f"measure, choose it under {MODE_LABEL}."
)


def unknown_order(asked: str) -> str:
    """Named rather than quietly replaced, as `unknown_mode` is."""
    offered = [label.lower() for value, label in ORDER_CHOICES if value]
    return f"There is no order called '{asked}'. The orders are {joined(offered)}."


# The key at the head of the results (#408, #416). The ramp between
# these two ends is the five strength colours.
KEY_SUMMARY = "What the measures mean"
KEY_LOW = "very low"
KEY_HIGH = "very high"
KEY_ORDER = (
    "Hits are listed in the order the search ranked them, which combines "
    "both measures by rank, so a hit with weaker bars can be listed first."
)


def key_models(models: Sequence[str]) -> str:
    """Which model the meaning cuts were measured for."""
    return f"Meaning cuts measured for {joined(list(models))}."


THEME_LABEL = "Colours"

# The three choices, in the order they are offered. `system` first
# because it is the default and the behaviour that existed before
# there was a choice.
THEME_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("system", "Match the system"),
    ("light", "Light"),
    ("dark", "Dark"),
)

PANE_SHOW = "Show the corpus"

PANE_HIDE = "Hide the corpus"

# The bar's actions as (path, label, icon), in the order they are
# shown. **The path is the action's one route**: `GET` shows its form,
# as a dialog when htmx asks and as a page otherwise, and `POST` does
# the work. The bar, the palette and any later entrance are aliases of
# these paths, never second implementations.
#
# A verb or a short noun for something done. Places are the pane's and
# are nouns; a label here names what happens when it is pressed.
ACTIONS: Final[tuple[tuple[str, str, str], ...]] = (
    ("/add", "Add", "file-plus"),
    ("/remember", "Note", "pencil"),
    ("/index", "Index", "database"),
    ("/sync", "Sync", "refresh-cw"),
    ("/pack", "Pack", "package"),
)

# Each action's dialog heading. It contains the action's label, so the
# button and what it opens are recognisably one thing; a test asserts
# it.
ACTION_TITLES: Final[dict[str, str]] = {
    "/add": "Add to the corpus",
    "/remember": "Write a note",
    "/index": "Rebuild an index",
    "/sync": "Synchronise",
    "/pack": "Install a pack",
}

CLOSE = "Close"

# Quit is in the bar because closing a browser tab does not end the
# process serving it (#420).
QUIT = "Quit"

QUIT_TITLE = "Stop kennis"

STOPPED = "kennis has stopped. You can close this tab."

QUIT_WHILE_RUNNING = (
    "An operation is still running, and stopping now would cut it off "
    "part of the way through. Quit once the strip says it has finished."
)

CORPUS_HEADING = "Corpus"

CONTEXT_HEADING = "Context"

KENNIS_HEADING = "kennis"

ACTIVITY_HEADING = "Activity"

NOTHING_RUN = "Nothing has run since kennis started. Operations are kept for an hour."

# What each kind of job is called where a person reads it: the strip,
# the Activity page. The keys are the kinds `app.py` starts jobs under.
JOB_KINDS: Final[dict[str, str]] = {
    "add": "Add",
    "index": "Index",
    "sync": "Corpus sync",
    "context-sync": "Context sync",
    "pack": "Pack install",
}

JOB_RUNNING = "running"

JOB_FINISHED = "finished"

JOB_FAILED = "failed"


def searchable_summary(searchable: int, total: int, behind: int) -> str:
    """Where the corpus stands, for the strip when nothing is running."""
    summary = f"{searchable} of {total} collections searchable"
    if behind:
        summary += f", {behind} behind"
    return summary


def last_job(kind: str, state: str) -> str:
    """The most recent operation, as the strip's link text."""
    return f"Last: {JOB_KINDS.get(kind, kind)}, {state}"


CORPUS_OVERVIEW = "Overview"

NO_CONTEXT = "No project here. Run kennis context init in one."

CORPUS_UNREADABLE = "The corpus could not be read."

# A collection's icon names its kind. There are exactly three kinds
# (`schema.COLLECTION_NAMES`), so this is a complete mapping rather
# than a default with exceptions, and a test asserts it covers them.
COLLECTION_ICONS: Final[dict[str, str]] = {
    "literature": "book-open",
    "docs": "globe",
    "notes": "sticky-note",
}

# What each collection's dot says, keyed by the pane's state. Four
# states, because "empty" and "never indexed" are different answers
# to "is there anything to do" (#245).
PANE_STATES: Final[dict[str, str]] = {
    "empty": "Nothing held yet",
    "none": "Never indexed",
    "behind": "Needs indexing",
    "current": "Searchable",
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

# The Add dialog's four tabs, in the order offered. A kind of thing to
# add, not a collection: a PDF of a paper is a Paper, and a Markdown
# file is a File whichever collection it goes to (#413).
ADD_TABS: Final[tuple[tuple[str, str], ...]] = (
    ("paper", "Paper"),
    ("site", "Documentation site"),
    ("file", "File"),
    ("group", "Several by group"),
)

ADD_PREAMBLES: Final[dict[str, str]] = {
    "paper": (
        "A paper for the literature collection: an arXiv identifier, a DOI, "
        "an ADS bibcode, or a PDF on this computer."
    ),
    "site": (
        "A documentation site for the docs collection. kennis walks its pages "
        "from the address given, politely, and stores each as a document."
    ),
    "file": (
        "A file or a folder on this computer, into the collection you choose. "
        "A folder adds every file in it that kennis can convert."
    ),
    "group": (
        "Several things at once, one group per block. Each line is checked "
        "as its own tab would check it."
    ),
}

# Every field says which it is, and an optional one says what empty
# becomes, because "optional" alone leaves the reader to guess what
# kennis will do instead.
REQUIRED = "required"
OPTIONAL = "optional"
EMPTY_PREFIX = "Left empty:"
ADD_TABS_LABEL = "What to add"
# Answered to a chooser asked to write into a field no form draws.
NOT_A_FIELD = "There is no such field to choose a path for."

# What each form field is called where a person reads it. One label per
# name, whichever tab shows the field.
FIELD_LABELS: Final[dict[str, str]] = {
    "paper": "Paper",
    "site": "Address",
    "file": "File or folder",
    "identifier": "Its identifier",
    "title": "Title",
    "citekey": "Citekey",
    "group": "Group",
    "project": "Project",
    "collection": "Collection",
    "max_pages": "Pages at most",
    "max_depth": "Links deep at most",
    "lines": "One per line",
}

# What an empty optional field becomes.
EMPTY_MEANS: Final[dict[str, str]] = {
    "identifier": "read from the PDF's first page",
    "title": "the paper's own title, from arXiv or its first heading",
    "file_title": "the document's first heading, or its file name",
    "citekey": "made from the first author, the year and the title",
    "project": "named from the address",
    "file_project": "needed only for docs, where it names the project",
    "max_pages": "300",
    "max_depth": "5",
}


def group_empty_means(default_group: str | None) -> str:
    """What an empty group becomes, which depends on the settings."""
    if default_group:
        return f"'{default_group}', the default group in your settings"
    return "the collection itself, in no group"


GROUP_NEEDS_A_NAME = "Each block with lines in it needs a group name."

# Beside a refusal's repairs. Skipping changes nothing: the item was
# already refused and the rest of the add went on, which is what the
# sentence says so that Skip is not read as undoing anything.
SKIP = "Skip"
SKIPPED = "Skipped. Nothing was added for this one; the rest of the add went on."


def open_candidate(value: str) -> str:
    """The accessible name of a candidate's link to its registry."""
    return f"Look up {value} in a new tab"


# No collection is chosen for the reader, as `corpus add` chooses none:
# a Markdown note sent to literature by a default is refused there for
# having no paper identifier, which reads as kennis failing.
CHOOSE_A_COLLECTION = "Choose the collection to add to."
ANOTHER_GROUP = "Another group"
BLOCK_HEADING = "Group"

BROWSE = "Browse"
CHOOSE_FOLDER = "Choose this folder"
CHOOSER_UP = "Up one folder"
CHOOSER_CANCEL = "Cancel"
CHOOSER_HEADING = "Choose from this computer"
# A folder of thousands of files is listed only so far, and says so.
CHOOSER_SHOWN_AT_MOST = 500


def chooser_truncated(shown: int, total: int) -> str:
    return f"Showing {shown} of {total}. Type the path to reach one not shown."


def not_a_folder(path: str) -> str:
    return f"'{path}' is not a folder kennis can list."


def not_a_count(label: str, given: str) -> str:
    return f"{label} must be a whole number; '{given}' is not one."


# The preview, for a paper.
def previewed_arxiv(identifier: str, title: str, authors: str, year: str) -> str:
    who = ", ".join(part for part in (authors, year) if part)
    return f"arXiv {identifier}: {title}" + (f" - {who}" if who else "")


def previewed_citekey(citekey: str) -> str:
    return f"Citekey: {citekey}"


ARXIV_SILENT = (
    "arXiv did not answer, so the citekey will be made from the paper's title. "
    "The add asks again."
)
PREVIEW_FILE = (
    "A file on this computer. It is converted when added, and its identifier "
    "read from its first page unless one is given as its identifier."
)
PREVIEW_ADDRESS = "An address. What it serves is converted when added."
PREVIEW_UNRECOGNISED = "Not an identifier kennis recognises yet."


# The preview, for a site.
def previewed_project(project: str) -> str:
    return f"Filed under the project '{project}'."


PROJECT_UNNAMED = (
    "No project name can be made from this address; give one as the project."
)
CHECK_SITE = "Check how its pages are found"
# Words for each way `discovery_mode` answers.
DISCOVERY_WORDS: Final[dict[str, str]] = {
    "sphinx": "Its pages are listed by its Sphinx inventory.",
    "sitemap": "Its pages are listed by its sitemap.",
    "crawl": "It has no list of pages, so kennis will follow its links.",
}
SITE_UNREACHABLE = "The site did not answer."

# A line of a group, checked.
LINE_KINDS: Final[dict[str, str]] = {
    "arxiv": "arXiv identifier",
    "doi": "DOI",
    "bibcode": "bibcode",
    "address": "address",
    "file": "file",
    "folder": "folder",
    "nothing": "not recognised",
}
LINE_HELD = "already held"

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

SYNC_CORPUS_ACTION = "Synchronise the corpus"

SYNC_CONTEXT_ACTION = "Synchronise this project"

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


def describe_recent(scope: str, hits: int, *, capped: bool, mode: str) -> str:
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
    found = f"{where}, {hits}+ hits" if capped else f"{where}, {counted}"
    # The mode only when it is not the default, because two facts
    # were asked for and a third is worth a line only when it is
    # news. A search that ran as everything else does is not.
    if mode == MODE_DEFAULT:
        return found
    return f"{found}, {dict(MODE_CHOICES)[mode].lower()}"


def unknown_mode(asked: str) -> str:
    """Named rather than quietly replaced by the default.

    Parallel to `unknown_scope`, and for the same reason: falling
    back answers a question other than the one in the address and
    says nothing about having done so. The remedy is not a command -
    `retrieval.as_mode` offers `kennis config get
    retrieval.corpus_method`, which is the wrong thing to hand
    someone who edited a URL - so this names the choices instead.
    """
    offered = [label for value, label in MODE_CHOICES if value]
    return (
        f"There is no way to match called '{asked}'. The choices are {joined(offered)}."
    )


def unknown_scope(asked: str, scopes: Sequence[str]) -> str:
    """Named rather than silently empty.

    A mistyped scope answered with no hits reads as "nothing is here",
    which is a different and wrong conclusion.
    """
    return f"There is no scope called '{asked}'. The scopes are {joined(list(scopes))}."


__all__ = [
    "ACTIONS",
    "ACTION_TITLES",
    "ACTIVITY_HEADING",
    "ADD_ACTION",
    "ADD_PREAMBLES",
    "ADD_TABS",
    "ADD_TABS_LABEL",
    "ANOTHER_GROUP",
    "ARXIV_SILENT",
    "BACK_TO_SEARCH",
    "BLOCK_HEADING",
    "BROWSE",
    "BUNDLE_NOT_COMMITTED",
    "BUSY_WITH_ANOTHER",
    "CHECK_SITE",
    "CHOOSER_CANCEL",
    "CHOOSER_HEADING",
    "CHOOSER_SHOWN_AT_MOST",
    "CHOOSER_UP",
    "CHOOSE_A_COLLECTION",
    "CHOOSE_FOLDER",
    "CLOSE",
    "COLLECTION_ICONS",
    "CONTEXT_HEADING",
    "CORPUS_BUSY",
    "CORPUS_BUSY_RETRY",
    "CORPUS_CHANGED",
    "CORPUS_HEADING",
    "CORPUS_OVERVIEW",
    "CORPUS_UNREADABLE",
    "DISCOVERY_WORDS",
    "EMPTY_MEANS",
    "EMPTY_PREFIX",
    "EVERYWHERE_LABEL",
    "FIELD_LABELS",
    "GROUP_HINT",
    "GROUP_NEEDS_A_NAME",
    "HIDE_PASSAGE",
    "IMAGES_BLOCKED",
    "INDEX_ACTION",
    "INDEX_PREAMBLE",
    "JOB_FAILED",
    "JOB_FINISHED",
    "JOB_KINDS",
    "JOB_RUNNING",
    "KENNIS_HEADING",
    "KEY_HIGH",
    "KEY_LOW",
    "KEY_ORDER",
    "KEY_SUMMARY",
    "LINE_HELD",
    "LINE_KINDS",
    "LOAD_IMAGES",
    "MARK_WITHHELD",
    "MEASURE_ICONS",
    "MODE_CHOICES",
    "MODE_DEFAULT",
    "MODE_LABEL",
    "NEVER_INDEXED",
    "NOTHING_FOUND",
    "NOTHING_HELD",
    "NOTHING_MATERIALISED",
    "NOTHING_RUN",
    "NOTHING_TO_ADD",
    "NOTHING_TO_INDEX",
    "NOTHING_TO_REMEMBER",
    "NOTHING_TO_SHOW",
    "NOT_A_FIELD",
    "NOT_SEARCHABLE_YET",
    "NO_CONTEXT",
    "NO_PACKS",
    "NO_SUCH_JOB",
    "OPEN_AT_PASSAGE",
    "OPTIONAL",
    "ORDER_CHOICES",
    "ORDER_LABEL",
    "ORDER_LIMIT",
    "PACK_ACTION",
    "PACK_PREAMBLE",
    "PANE_HIDE",
    "PANE_SHOW",
    "PANE_STATES",
    "PREVIEW_ADDRESS",
    "PREVIEW_FILE",
    "PREVIEW_UNRECOGNISED",
    "PROJECT_UNNAMED",
    "QUIT",
    "QUIT_TITLE",
    "QUIT_WHILE_RUNNING",
    "RECENTS_CLEAR",
    "RECENTS_HEADING",
    "REMEMBER_ACTION",
    "REMEMBER_PLACEHOLDER",
    "REMEMBER_PREAMBLE",
    "REQUIRED",
    "SCOPE_LABEL",
    "SEARCHING",
    "SEARCH_ACTION",
    "SHOW_PASSAGE",
    "SITE_UNREACHABLE",
    "SKIP",
    "SKIPPED",
    "STILL_RUNNING",
    "STOPPED",
    "SYNC_CONTEXT_ACTION",
    "SYNC_CORPUS_ACTION",
    "SYNC_PREAMBLE",
    "THEME_CHOICES",
    "THEME_LABEL",
    "TITLE_HINT",
    "chooser_truncated",
    "describe_count",
    "describe_holding",
    "describe_recent",
    "describe_written",
    "describe_written_to_bundle",
    "group_empty_means",
    "key_models",
    "last_job",
    "not_a_count",
    "not_a_folder",
    "open_candidate",
    "previewed_arxiv",
    "previewed_citekey",
    "previewed_project",
    "search_hint_for",
    "searchable_summary",
    "unknown_mode",
    "unknown_order",
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
