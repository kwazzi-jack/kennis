"""What the graphical interface says.

Beside `mcp/tools/*`, which compose their own sentences for the same
reason: `render/` holds what every front end says about an engine
value, and each front end holds what only it says. "Load images" is
not a fact about a document - it is a control on a page.
"""

from __future__ import annotations

import re
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


# A hit's passage opens in place, and the summary says which way it
# goes. Both are drawn by the server and CSS shows the one that applies.
SHOW_PASSAGE = "Show the whole passage"
HIDE_PASSAGE = "Show less"

# ---- an opened document: its bar and its inspector (#447) ----


def search_crumb(question: str) -> str:
    """The first breadcrumb, back to the search that led here."""
    return f"Search: {question}"


INSPECTOR_LABEL = "About this document"
CRUMBS_LABEL = "Where this document is"
INSPECTOR_SHOW = "Show details, matches and outline"
INSPECTOR_HIDE = "Hide details, matches and outline"
DETAILS_HEADING = "Details"
OUTLINE_HEADING = "Outline"
NO_HEADINGS = "This document has no headings."


def matches_heading(question: str) -> str:
    """The inspector's list of passages the reader's words occur in."""
    return f'Matches for "{question}"'


NO_MATCHES = "None of these words occurs in a passage of this document."

MATCHES_WITHHELD = (
    "The document has changed since it was indexed, so its passages cannot be placed."
)


def passage_label(chunk_index: int) -> str:
    """A match before the document's first heading, by its position."""
    return f"Passage {chunk_index + 1}"


def match_in_section(section: str, ordinal: int, count: int) -> str:
    """One of several matches under one heading, told apart by place."""
    return f"{section} ({ordinal} of {count})"


# The inspector's rows, keyed by what each is. Only the rows a document
# has are drawn.
DETAIL_LABELS: Final[dict[str, str]] = {
    "collection": "Collection",
    "group": "Group",
    "id": "Identifier",
    "path": "Path",
    "citekey": "Citekey",
    "arxiv": "arXiv",
    "doi": "DOI",
    "bibcode": "Bibcode",
    "project": "Project",
    "page": "Page",
    "version": "Version",
    "source": "Source",
    "converted": "Converted",
    "added": "Added",
    "index": "Index",
}

# Whether the index holds a document, by `holdings.DocumentState`: the
# tree's marks, in words.
INDEX_STATES: Final[dict[str, str]] = {
    "": "Searchable",
    "unindexed": "Not indexed yet",
    "changed": "Changed since it was indexed",
}

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
# Short, because they are drawn as one segmented row after "Order".
ORDER_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("", "As ranked"),
    ("lexical", "Keywords"),
    ("meaning", "Meaning"),
)
# The limit, said beside the control: a reorder acts on the hits already
# returned, which the fused rank chose.
ORDER_LIMIT = (
    "Reordering sorts the hits this search returned. To search by one "
    f"measure, choose it under {MODE_LABEL}."
)


def results_for(count: int, *, capped: bool, question: str) -> str:
    """How many hits a search found and what was asked, at the head.

    A floor when any scope returned all it was asked for, as the recent
    searches say it (#348).
    """
    found = f"{count}+ results" if capped else count_of(count, "result")
    return f'{found} for "{question}"'


def more_from(collection: str) -> str:
    """Under a collection's results, when it had more to give."""
    return f"More from {collection}"


# The key hint inside the search box: the key itself is drawn, and this
# is its tooltip.
SEARCH_KEY_TITLE = "Press / to search from anywhere on the page"


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


# The three choices, in the order they are offered. `system` first
# because it is the default and the behaviour that existed before
# there was a choice.
THEME_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("system", "Match the system"),
    ("light", "Light"),
    ("dark", "Dark"),
)

# Settings (milestone 12). The window's own preferences are kept apart
# from kennis's configuration on the page, and say so.
SETTINGS_HEADING = "Settings"
WINDOW_SETTINGS_HEADING = "This window"
WINDOW_SETTINGS_NOTE = (
    "Kept by this window only, in this browser. The command line and the "
    "MCP server never see these, and each takes effect as you choose it."
)
APPEARANCE_HEADING = "Appearance"
RESULTS_HEADING = "Search results"
SAVE = "Save"

# Each preference's name and the sentence beside it, by its registry name.
PREFERENCE_WORDS: Final[dict[str, tuple[str, str]]] = {
    "theme": ("Colours", "Follow the system, or always light or dark."),
    "face": (
        "Reading face",
        "The face documents and search results are set in. Atkinson "
        "Hyperlegible was designed to keep similar letters apart.",
    ),
    "size": ("Text size", "Everything in the window grows or shrinks with it."),
    "spacing": (
        "Spacing",
        "Wider line, letter and word spacing in what you read. Extra "
        "spacing has helped some readers with dyslexia more than any "
        "special typeface.",
    ),
    "width": (
        "Text width",
        "How wide documents and search results are set: across the whole "
        "pane, wide, or at a reading measure of about 70 characters a line.",
    ),
    "strength": (
        "Match strength",
        "How each measure shows how well a result matched: bars beside "
        "the level, or the level alone.",
    ),
    "labels": (
        "Measure labels",
        "Name each measure by its icon, by its word, or by both.",
    ),
    "scale": (
        "Bar colours",
        "Each runs from dark to light, and stays distinguishable to the "
        "commonest colour-vision deficiency.",
    ),
}

PREFERENCE_CHOICES: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "face": (
        ("serif", "Source Serif"),
        ("sans", "System sans"),
        ("hyperlegible", "Atkinson Hyperlegible"),
    ),
    "size": (
        ("small", "Small"),
        ("normal", "Normal"),
        ("large", "Large"),
        ("larger", "Larger"),
    ),
    "spacing": (("normal", "Normal"), ("wide", "Wide"), ("wider", "Wider")),
    "width": (
        ("pane", "Fit the pane"),
        ("wide", "Wide"),
        ("reading", "Reading measure"),
    ),
    "strength": (("bars", "Bars and words"), ("words", "Words only")),
    "labels": (("icons", "Icons"), ("words", "Words"), ("both", "Both")),
    "scale": (
        ("viridis", "Viridis"),
        ("cividis", "Cividis"),
        ("plasma", "Plasma"),
        ("magma", "Magma"),
        ("greys", "Greys"),
    ),
}

# kennis's own configuration (12b): the same file `kennis config set`
# writes, so the note says who else reads it. `corpus.root` is not
# offered and not named: it moves the corpus from under an open window.
KENNIS_SETTINGS_HEADING = "kennis"
KENNIS_SETTINGS_NOTE = (
    "kennis's own configuration. The command line and the MCP server read "
    "it too, from their next command."
)
KENNIS_SAVE = "Save configuration"
# The configuration's headings, in page order, by the group each
# setting's section belongs to.
KENNIS_GROUPS: Final[tuple[tuple[str, str], ...]] = (
    ("searching", "Searching and indexing"),
    ("converting", "Converting documents"),
)
KENNIS_SAVED = "Saved."
KENNIS_UNCHANGED = "Saved. No value was changed."
KENNIS_NOT_SAVED = "Nothing was saved. Each value that was refused says why."
# Each setting's name in the window, by its configuration key. The
# sentence beside it is the field's own description, as `config init`
# prints it.
SETTING_NAMES: Final[dict[str, str]] = {
    "embedding.backend": "Embedding",
    "embedding.model": "Embedding model",
    "embedding.base_url": "Ollama address",
    "embedding.api_key": "OpenAI key",
    "conversion.backend": "Converter",
    "conversion.mode": "Datalab mode",
    "conversion.api_key": "Datalab key",
    "retrieval.corpus_method": "Default matching",
    "retrieval.default_top_k": "Results per collection",
    "chunking.size": "Chunk size",
}
CONVERTER_NAMES: Final[dict[str, str]] = {
    "mineru": "MinerU (local)",
    "datalab": "Datalab (hosted)",
}
SETTING_CHOICES: Final[dict[str, dict[str, str]]] = {
    "embedding.backend": {
        "fastembed": "FastEmbed (local)",
        "ollama": "Ollama (a local server)",
        "openai": "OpenAI (hosted)",
        "none": "None: keywords only",
    },
    "conversion.backend": CONVERTER_NAMES,
    "conversion.mode": {
        "fast": "Fast",
        "balanced": "Balanced",
        "accurate": "Accurate",
    },
    "retrieval.corpus_method": {value: label for value, label in MODE_CHOICES if value},
}
CONVERTER_MISSING = "MinerU is not installed on this machine. To install it:"
# Completed by the variable's name: "DATALAB_API_KEY is set". Neither
# is inside the other, so a test can tell them apart.
CREDENTIAL_SET = "is set"
CREDENTIAL_UNSET = "is not set"
CREDENTIAL_KEEP = "Leave it empty to keep the key there is."
REBUILD_HEADING = "The indexes need rebuilding"
REBUILD_NOTE = (
    "Until it is rebuilt, each index keeps searching with what it was built with:"
)
REBUILD_NONE = "No collection has an index yet, so nothing needs rebuilding."
REBUILD_NOW = "Rebuild now"
REBUILD_LATER = "Later"
UNDO = "Undo"
LEXICAL_ONLY_INDEX = "keywords only"


def built_with(model: str | None, backend: str | None, chunk_size: int) -> str:
    """What an index was built with, as the rebuild panel names it."""
    searched = LEXICAL_ONLY_INDEX if model is None else f"{model} ({backend})"
    return f"{searched}, in chunks of {chunk_size} characters"


# The Backup section (13b). What the backup holds, and every sentence
# about its state, are `render/backup.py`'s, shared with `kennis backup`.
BACKUP_HEADING = "Backup"
BACKUP_FOLDER_LABEL = "Folder"
BACKUP_SAVE_FOLDER = "Save folder"
BACKUP_NOW = "Back up now"
BACKUP_NOW_NOTE = (
    "Asks for a password each time and never stores it. The backup is "
    "tested with it before it replaces the last one."
)
BACKUP_PASSWORD = "Password"
BACKUP_CONFIRMATION = "Password again"
BACKUP_TEST = "Test the backup"
BACKUP_TEST_NOTE = "Decrypts every file in it and compares each with its checksum."
BACKUP_RESTORE_LABEL = "Restore"
BACKUP_RESTORE_NOTE = (
    "Restoring replaces the corpus this window shows, so it is a command, "
    "run with no window open:"
)
PASSWORD_NEEDED = "A backup needs a password."
PASSWORDS_DIFFER = "The two passwords differ, so nothing was started."


def not_a_backup_folder(path: str) -> str:
    return f"'{path}' is not a folder, so it was not saved."


# The drag handles (`gui/layout.py`), each named by what it resizes.
RESIZE_LABELS: Final[dict[str, str]] = {
    "pane-width": "Resize the corpus pane",
    "inspector-width": "Resize the details",
    "strip-height": "Resize the activity strip",
}
# The activity strip's collapse, by its state.
STRIP_SHOW = "Show all of the activity"
STRIP_HIDE = "Show only the first line of the activity"
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
    "/palette": "Every action and place",
}

# The palette (11g). Its actions are the bar's, opened on a tab or a
# collection where that saves a step; its places are the pane's.
PALETTE_TITLE = "Every action and place"
PALETTE_PROMPT = "Type an action or a place"
PALETTE_EMPTY = "Nothing matches"
PALETTE_SHORTCUT = "Ctrl K"
PALETTE_KEYS: Final[tuple[tuple[str, str], ...]] = (
    ("Up Down", "move"),
    ("Enter", "run"),
    ("Esc", "close"),
)
# (address, label, icon), in the order the palette lists them.
PALETTE_ACTIONS_BEFORE_INDEX: Final[tuple[tuple[str, str, str], ...]] = (
    ("/add?kind=paper", "Add a paper", "file-plus"),
    ("/add?kind=site", "Add a documentation site", "globe"),
    ("/add?kind=file", "Add a file", "file-plus"),
    ("/add?kind=group", "Add several by group", "folder"),
    ("/remember", "Write a note", "pencil"),
    ("/index", "Index every collection", "database"),
)
PALETTE_ACTIONS_AFTER_INDEX: Final[tuple[tuple[str, str, str], ...]] = (
    ("/sync", "Synchronise", "refresh-cw"),
    ("/pack", "Install a pack", "package"),
)
PALETTE_KINDS: Final[dict[str, str]] = {
    "action": "action",
    "collection": "collection",
    "page": "page",
    "search": "search",
}


def index_collection(collection: str) -> str:
    """The palette's entry that opens the index form on one collection."""
    return f"Index {collection}"


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

PACKS_HEADING = "Packs"

# The palette's places beyond the collections, by the pane's own names.
PALETTE_PAGES: Final[tuple[tuple[str, str, str], ...]] = (
    ("/corpus", CORPUS_HEADING, "database"),
    ("/", RECENTS_HEADING, "history"),
    ("/activity", ACTIVITY_HEADING, "activity"),
    ("/corpus#packs", PACKS_HEADING, "package"),
    ("/settings", SETTINGS_HEADING, "settings"),
)

NOTHING_RUN = "Nothing has run since kennis started. Operations are kept for an hour."

# The corpus's own record, under this window's jobs: everything that
# changed it, from here, a terminal or an agent.
CHANGES_HEADING = "Changes to the corpus"

NO_CHANGES = "The corpus has no history yet."

# What each kind of job is called where a person reads it: the strip,
# the Activity page. The keys are the kinds `app.py` starts jobs under.
JOB_KINDS: Final[dict[str, str]] = {
    "add": "Add",
    "index": "Index",
    "sync": "Corpus sync",
    "context-sync": "Context sync",
    "pack": "Pack install",
    "backup": "Backup",
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


def corpus_at(commit: str) -> str:
    """The commit the corpus is at, for the strip."""
    return f"Corpus at {commit}"


def documents_held(count: int) -> str:
    """How many documents the corpus holds, beside its heading."""
    return count_of(count, "document")


def documents_waiting(count: int) -> str:
    """How many documents a search cannot find until an index is rebuilt."""
    verb = "needs" if count == 1 else "need"
    return f"{count_of(count, 'document')} {verb} indexing"


def index_now(collections: Sequence[str]) -> str:
    """The strip's button beside what needs indexing: the sentence was
    plain text, and the reader had to find the Index dialog themselves."""
    if len(collections) == 1:
        return f"Index {collections[0]}"
    return "Index them"


def time_ago(seconds: float) -> str:
    """How long ago something happened, to the unit a person would say.

    A negative interval is a clock on another machine ahead of this
    one, and reads as now rather than as the future.
    """
    whole = int(seconds)
    if whole < 60:
        return "just now"
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if whole >= size:
            return f"{count_of(whole // size, unit)} ago"
    return "just now"


# What each operation kennis records was, by the verb in its commit
# subject, and the word joining it to the scope it acted on.
CHANGE_KINDS: Final[dict[str, str]] = {
    "init": "created",
    "add": "add to",
    "move": "move in",
    "index": "index of",
    "sync": "sync of",
    "remember": "note in",
    "restore": "restore in",
}


def last_change(
    operation: str | None, scope: str | None, summary: str, seconds: float
) -> str:
    """The corpus's newest commit, for the strip.

    A subject kennis did not write is quoted whole, because a commit a
    person made by hand is a change too (`read_history` keeps it).
    """
    ago = time_ago(seconds)
    return f"Last change: {change_line(operation, scope, summary)}, {ago}"


def change_line(operation: str | None, scope: str | None, summary: str) -> str:
    """One commit of the corpus, as the Activity page and the strip say it.

    A subject kennis did not write is quoted whole, because a commit a
    person made by hand is a change too.
    """
    if operation is None or scope is None:
        return summary
    kind = CHANGE_KINDS.get(operation, operation)
    return f"{kind} {scope} ({_one_is_one(summary)})"


def _one_is_one(summary: str) -> str:
    """A kennis summary read for a person: "1 documents" as "1 document".

    The summary is a storage format the history parses back (`commit_
    summary` writes every count with its plural), so it is read in the
    singular here rather than written differently there.
    """
    return re.sub(r"\b1 (\w+?)s\b", r"1 \1", summary)


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
# Each tab's picture: the collection a paper or a site goes to, a
# document for a file, a folder for a group.
ADD_TAB_ICONS: Final[dict[str, str]] = {
    "paper": "book-open",
    "site": "globe",
    "file": "file-text",
    "group": "folder",
}

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
EMPTY_PREFIX = "If empty:"
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

# The Add dialog's submit button, named for what the tab adds.
ADD_ACTIONS: Final[dict[str, str]] = {
    "paper": "Add paper",
    "site": "Add site",
    "file": "Add",
    "group": "Add every group",
}

# The foot of the Add dialog: where the add will go, which the window
# keeps in step with the fields as they are filled in.
ADDS_TO = "Adds to"
CANCEL = "Cancel"

# The Index form's choice for all of them, beside each collection's name.
INDEX_EVERY = "every collection"
# Where a note goes, by the form's value: the corpus's notes, or the
# context bundle of the project the window was started in.
REMEMBER_TARGETS: Final[tuple[tuple[str, str], ...]] = (
    ("notes", "notes"),
    ("context", "this project"),
)
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

INDEX_NOW = "Index now"

# More items than this and an outcome folds the ones needing nothing
# away: a 4,000-file add listed every one, and the line saying what
# happened was a screen above them.
FOLDED_AFTER = 8


def every_item(count: int) -> str:
    """The fold's label over a long outcome's ordinary items."""
    return f"Show all {count_of(count, 'item')}"


NO_SUCH_JOB = "That operation has finished, or was never started here."

STILL_RUNNING = "This is still running."

NOTHING_TO_SHOW = "That operation finished without reporting anything."


def job_crashed(crash: Exception) -> str:
    """A job that died of something kennis has no sentence for.

    The exception's own words are quoted, because they are the only
    account there is of what happened; where the rest is kept is said, so
    the reader knows there is more than this line.

    **And what to do next, which is the same thing again.** Each document
    is written whole and what was written is committed as interrupted
    (`operations.committed_if_interrupted`), and every operation a job runs
    skips what is already there - an add finds the same content, a sync
    converges, an index and a backup start over - so running it again
    carries on rather than repeating.
    """
    detail = str(crash) or type(crash).__name__
    return (
        f"That operation stopped part-way: {detail}. Anything it wrote before "
        "it stopped is kept, so running it again carries on from there. The "
        "details are in kennis's log."
    )


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

# The Note dialog's fields by name, beside them rather than inside them:
# a placeholder is gone the moment anything is typed, a screen reader
# may not read it, and the title's was clipped mid-word.
NOTE_TEXT_LABEL = "Note"

TITLE_LABEL = "Title"

TITLE_HINT = "Optional - the first line otherwise"

GROUP_LABEL = "Group"

GROUP_HINT = "Optional subfolder"

TARGET_LABEL = "Save to"

PACK_PATH_LABEL = "Pack file"

INDEX_WHICH_LABEL = "Collections"

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


# The tree's marks, after an editor's source-control view: quiet when
# the index has a document as it stands, a letter when not. The letter is
# what is seen; the sentence is its tooltip and what a screen reader says.
STATE_LETTERS: Final[dict[str, str]] = {
    "unindexed": "U",
    "changed": "M",
    "unreadable": "!",
}

STATE_WORDS: Final[dict[str, str]] = {
    "unindexed": "Not in the index yet, so search will not find it",
    "changed": "Changed since it was indexed, so search finds the earlier text",
    "unreadable": "kennis cannot read this document's frontmatter",
}

ATTENTION_ONLY = "Only what needs attention"

MENU_OPEN = "Open"
MENU_MOVE = "Move to group"
MENU_ADD_HERE = "Add here"
MENU_INDEX = "Index this collection"

MOVE_GROUP_LABEL = "Group to move it to"
MOVE_GROUP_EMPTY = "empty for the top level"


def attention_count(count: int) -> str:
    """How many documents beneath a group need attention."""
    verb = "needs" if count == 1 else "need"
    return f"{count_of(count, 'document')} here {verb} attention"


def menu_for(name: str) -> str:
    """The accessible name of a row's menu button, which is only an icon."""
    return f"Actions for {name}"


def overridden_by(variable: str) -> str:
    """A setting the environment decides, beside the control it disables."""
    return (
        f"Set by the environment variable {variable}, which overrides the "
        "file. Unset it to choose here."
    )


# The home page of an empty corpus: what kennis is, and the first things
# to do with it, as the dialogs that do them. It was a blank centre.
WELCOME_HEADING = "Nothing here yet"

WELCOME = (
    "kennis keeps your papers, documentation and notes on this computer "
    "and finds them again by keyword and by meaning. Agents read the same "
    "corpus through MCP."
)

WELCOME_ACTIONS: Final[tuple[tuple[str, str, str], ...]] = (
    ("/add?kind=paper", "Add a paper", "file-plus"),
    ("/add?kind=site", "Add a documentation site", "globe"),
    ("/add?kind=file", "Add files from this computer", "folder"),
    ("/remember", "Write a note", "pencil"),
)


# The inspector's button beside a citekey, and what it says once pressed.
COPY_LABEL = "Copy"

COPIED_LABEL = "Copied"


# The first tab stop on every page.
SKIP_TO_CONTENT = "Skip to the content"

# What a running job's bar is, to a screen reader.
PROGRESS_LABEL = "Progress"


# A page that could not be drawn: what went wrong, said as a heading the
# reader can find, and two ways back, so a refusal is never a dead end.
PROBLEM_HEADING = "That could not be shown"

NOT_FOUND_HEADING = "Not found"

PROBLEM_BACK = "Back to search"

PROBLEM_CORPUS = "See the corpus"


def no_page_at(path: str) -> str:
    """An address the window has no page for."""
    return f"There is no page at {path}."


# A request without the token: the browser was given an address with the
# key in it, and this one has neither the key nor the cookie it leaves.
LOCKED_HEADING = "This window needs its key"

LOCKED = (
    "This address is missing the key kennis was started with, so it will "
    "not answer. Open the address `kennis gui` printed, or run `kennis gui` "
    "again for a new one."
)


def keywords_only(collections: Sequence[str]) -> str:
    """Searches that ran by keywords although meaning was asked for.

    One sentence for every collection rather than one each: three
    near-identical warnings took the top of every results page before
    a single result (#381 said it; the reviews found it said too loudly).
    """
    names = joined(list(collections))
    noun = "index was" if len(collections) == 1 else "indexes were"
    return f"Matched by keywords only: the {names} {noun} built without meaning."


KEYWORDS_ONLY_CHOOSE = "Choose a meaning model in Settings"

KEYWORDS_ONLY_INDEX = "Index them with meaning"


__all__ = [
    "ACTIONS",
    "ACTION_TITLES",
    "ACTIVITY_HEADING",
    "ADDS_TO",
    "ADD_ACTIONS",
    "ADD_PREAMBLES",
    "ADD_TABS",
    "ADD_TABS_LABEL",
    "ADD_TAB_ICONS",
    "ANOTHER_GROUP",
    "APPEARANCE_HEADING",
    "ARXIV_SILENT",
    "ATTENTION_ONLY",
    "BACKUP_CONFIRMATION",
    "BACKUP_FOLDER_LABEL",
    "BACKUP_HEADING",
    "BACKUP_NOW",
    "BACKUP_NOW_NOTE",
    "BACKUP_PASSWORD",
    "BACKUP_RESTORE_LABEL",
    "BACKUP_RESTORE_NOTE",
    "BACKUP_SAVE_FOLDER",
    "BACKUP_TEST",
    "BACKUP_TEST_NOTE",
    "BLOCK_HEADING",
    "BROWSE",
    "BUNDLE_NOT_COMMITTED",
    "BUSY_WITH_ANOTHER",
    "CANCEL",
    "CHANGES_HEADING",
    "CHANGE_KINDS",
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
    "CONVERTER_MISSING",
    "CONVERTER_NAMES",
    "COPIED_LABEL",
    "COPY_LABEL",
    "CORPUS_BUSY",
    "CORPUS_BUSY_RETRY",
    "CORPUS_CHANGED",
    "CORPUS_HEADING",
    "CORPUS_OVERVIEW",
    "CORPUS_UNREADABLE",
    "CREDENTIAL_KEEP",
    "CREDENTIAL_SET",
    "CREDENTIAL_UNSET",
    "CRUMBS_LABEL",
    "DETAILS_HEADING",
    "DETAIL_LABELS",
    "DISCOVERY_WORDS",
    "EMPTY_MEANS",
    "EMPTY_PREFIX",
    "EVERYWHERE_LABEL",
    "FIELD_LABELS",
    "FOLDED_AFTER",
    "GROUP_HINT",
    "GROUP_LABEL",
    "GROUP_NEEDS_A_NAME",
    "HIDE_PASSAGE",
    "IMAGES_BLOCKED",
    "INDEX_ACTION",
    "INDEX_EVERY",
    "INDEX_NOW",
    "INDEX_PREAMBLE",
    "INDEX_STATES",
    "INDEX_WHICH_LABEL",
    "INSPECTOR_HIDE",
    "INSPECTOR_LABEL",
    "INSPECTOR_SHOW",
    "JOB_FAILED",
    "JOB_FINISHED",
    "JOB_KINDS",
    "JOB_RUNNING",
    "KENNIS_GROUPS",
    "KENNIS_HEADING",
    "KENNIS_NOT_SAVED",
    "KENNIS_SAVE",
    "KENNIS_SAVED",
    "KENNIS_SETTINGS_HEADING",
    "KENNIS_SETTINGS_NOTE",
    "KENNIS_UNCHANGED",
    "KEYWORDS_ONLY_CHOOSE",
    "KEYWORDS_ONLY_INDEX",
    "KEY_HIGH",
    "KEY_LOW",
    "KEY_ORDER",
    "KEY_SUMMARY",
    "LEXICAL_ONLY_INDEX",
    "LINE_HELD",
    "LINE_KINDS",
    "LOAD_IMAGES",
    "LOCKED",
    "LOCKED_HEADING",
    "MARK_WITHHELD",
    "MATCHES_WITHHELD",
    "MEASURE_ICONS",
    "MENU_ADD_HERE",
    "MENU_INDEX",
    "MENU_MOVE",
    "MENU_OPEN",
    "MODE_CHOICES",
    "MODE_DEFAULT",
    "MODE_LABEL",
    "MOVE_GROUP_EMPTY",
    "MOVE_GROUP_LABEL",
    "NEVER_INDEXED",
    "NOTE_TEXT_LABEL",
    "NOTHING_FOUND",
    "NOTHING_HELD",
    "NOTHING_MATERIALISED",
    "NOTHING_RUN",
    "NOTHING_TO_ADD",
    "NOTHING_TO_INDEX",
    "NOTHING_TO_REMEMBER",
    "NOTHING_TO_SHOW",
    "NOT_A_FIELD",
    "NOT_FOUND_HEADING",
    "NOT_SEARCHABLE_YET",
    "NO_CHANGES",
    "NO_CONTEXT",
    "NO_HEADINGS",
    "NO_MATCHES",
    "NO_PACKS",
    "NO_SUCH_JOB",
    "OPEN_AT_PASSAGE",
    "OPTIONAL",
    "ORDER_CHOICES",
    "ORDER_LABEL",
    "ORDER_LIMIT",
    "OUTLINE_HEADING",
    "PACKS_HEADING",
    "PACK_ACTION",
    "PACK_PATH_LABEL",
    "PACK_PREAMBLE",
    "PALETTE_ACTIONS_AFTER_INDEX",
    "PALETTE_ACTIONS_BEFORE_INDEX",
    "PALETTE_EMPTY",
    "PALETTE_KEYS",
    "PALETTE_KINDS",
    "PALETTE_PAGES",
    "PALETTE_PROMPT",
    "PALETTE_SHORTCUT",
    "PALETTE_TITLE",
    "PANE_HIDE",
    "PANE_SHOW",
    "PANE_STATES",
    "PASSWORDS_DIFFER",
    "PASSWORD_NEEDED",
    "PREFERENCE_CHOICES",
    "PREFERENCE_WORDS",
    "PREVIEW_ADDRESS",
    "PREVIEW_FILE",
    "PREVIEW_UNRECOGNISED",
    "PROBLEM_BACK",
    "PROBLEM_CORPUS",
    "PROBLEM_HEADING",
    "PROGRESS_LABEL",
    "PROJECT_UNNAMED",
    "QUIT",
    "QUIT_TITLE",
    "QUIT_WHILE_RUNNING",
    "REBUILD_HEADING",
    "REBUILD_LATER",
    "REBUILD_NONE",
    "REBUILD_NOTE",
    "REBUILD_NOW",
    "RECENTS_CLEAR",
    "RECENTS_HEADING",
    "REMEMBER_ACTION",
    "REMEMBER_PLACEHOLDER",
    "REMEMBER_PREAMBLE",
    "REMEMBER_TARGETS",
    "REQUIRED",
    "RESIZE_LABELS",
    "RESULTS_HEADING",
    "SAVE",
    "SCOPE_LABEL",
    "SEARCHING",
    "SEARCH_ACTION",
    "SEARCH_KEY_TITLE",
    "SETTINGS_HEADING",
    "SETTING_CHOICES",
    "SETTING_NAMES",
    "SHOW_PASSAGE",
    "SITE_UNREACHABLE",
    "SKIP",
    "SKIPPED",
    "SKIP_TO_CONTENT",
    "STATE_LETTERS",
    "STATE_WORDS",
    "STILL_RUNNING",
    "STOPPED",
    "STRIP_HIDE",
    "STRIP_SHOW",
    "SYNC_CONTEXT_ACTION",
    "SYNC_CORPUS_ACTION",
    "SYNC_PREAMBLE",
    "TARGET_LABEL",
    "THEME_CHOICES",
    "TITLE_HINT",
    "TITLE_LABEL",
    "UNDO",
    "WELCOME",
    "WELCOME_ACTIONS",
    "WELCOME_HEADING",
    "WINDOW_SETTINGS_HEADING",
    "WINDOW_SETTINGS_NOTE",
    "attention_count",
    "built_with",
    "change_line",
    "chooser_truncated",
    "corpus_at",
    "describe_count",
    "describe_holding",
    "describe_recent",
    "describe_written",
    "describe_written_to_bundle",
    "documents_held",
    "documents_waiting",
    "every_item",
    "group_empty_means",
    "index_collection",
    "index_now",
    "job_crashed",
    "key_models",
    "keywords_only",
    "last_change",
    "last_job",
    "match_in_section",
    "matches_heading",
    "menu_for",
    "more_from",
    "no_page_at",
    "not_a_backup_folder",
    "not_a_count",
    "not_a_folder",
    "open_candidate",
    "overridden_by",
    "passage_label",
    "previewed_arxiv",
    "previewed_citekey",
    "previewed_project",
    "results_for",
    "search_crumb",
    "search_hint_for",
    "searchable_summary",
    "time_ago",
    "unknown_collection",
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
