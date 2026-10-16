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
    index_state,
    joined,
    needs_an_index,
)
from kennis.retrieval import EVERY_SCOPE

RECENTS_HEADING = "Recent searches"

RECENTS_CLEAR = "Clear history"

NOTHING_FOUND = "No results. Try fewer words, or search everywhere."


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
    return f"Search {where}"


SEARCH_ACTION = "Search"

# Shown while the hits on the page are not the hits for what is in
# the box. That covers the 400ms typing debounce as well as the
# request, which is the point: the request is 12ms of a 412ms wait
# and an indicator for it alone would never be seen. Concern #365.
SEARCHING = "Searching"

SCOPE_LABEL = "Search in"

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
SHOW_PASSAGE = "Show full passage"
HIDE_PASSAGE = "Show less"

# ---- an opened document: its bar and its inspector (#447) ----


def search_crumb(question: str) -> str:
    """The first breadcrumb, back to the search that led here."""
    return f"Search: {question}"


INSPECTOR_LABEL = "About this document"
CRUMBS_LABEL = "Breadcrumbs"
INSPECTOR_SHOW = "Show details panel"
INSPECTOR_HIDE = "Hide details panel"
DETAILS_HEADING = "Details"
OUTLINE_HEADING = "Outline"
NO_HEADINGS = "No headings."


def matches_heading(question: str) -> str:
    """The inspector's list of passages the reader's words occur in."""
    return f'Matches for "{question}"'


NO_MATCHES = "Your search words do not appear in this document."

MATCHES_WITHHELD = (
    "Changed since last indexed, so matches cannot be shown. Index it again "
    "to see them."
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
    "id": "ID",
    "path": "Path",
    "citekey": "Citekey",
    "arxiv": "arXiv",
    "doi": "DOI",
    "bibcode": "Bibcode",
    "project": "Project",
    "page": "Page",
    "version": "Version",
    "source": "Source",
    "converted": "Converted from",
    "added": "Added",
    "index": "Search status",
}

# Whether the index holds a document, by `holdings.DocumentState`: the
# tree's marks, in words.
INDEX_STATES: Final[dict[str, str]] = {
    "": "Searchable",
    "unindexed": "Not indexed yet",
    "changed": "Changed since last indexed",
}

# The link from a hit into its document is an icon, so this is its
# accessible name and its tooltip (#415).
OPEN_AT_PASSAGE = "Open at this passage"

# Which icon names each measure, from Lucide. The tooltip is the
# measure's own word from `render/hits.py::LEG_LABELS`; milestone 12
# lets the reader choose icons, words or both.
MEASURE_ICONS: Final[dict[str, str]] = {"lexical": "whole-word", "meaning": "brain"}

# Reordering one collection's hits by one measure's own rank (#406).
# The values are the engine's leg names, as `mode`'s are its method
# names; the labels are the measures' words. The first is empty, which
# is the order the search returned.
ORDER_LABEL = "Sort by"
# Short, because they are drawn as one segmented row after "Order".
ORDER_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    ("", "Best match"),
    ("lexical", "Keywords"),
    ("meaning", "Meaning"),
)
# The limit, said beside the control: a reorder acts on the hits already
# returned, which the fused rank chose.
ORDER_LIMIT = (
    "Sorting only reorders these results. To search by one measure, "
    f"change {MODE_LABEL}."
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
SEARCH_KEY_TITLE = "Press / to search from anywhere"


def unknown_order(asked: str) -> str:
    """Named rather than quietly replaced, as `unknown_mode` is."""
    offered = [label.lower() for value, label in ORDER_CHOICES if value]
    return f"'{asked}' is not a sort order. The orders are {joined(offered)}."


# The key at the head of the results (#408, #416). The ramp between
# these two ends is the five strength colours.
KEY_SUMMARY = "How to read the bars"
KEY_LOW = "very low"
KEY_HIGH = "very high"
KEY_ORDER = (
    "Results are ranked on both measures together, so a result with weaker "
    "bars can come first."
)


def key_models(models: Sequence[str]) -> str:
    """Which model the meaning cuts were measured for."""
    return f"Meaning levels are set for {joined(list(models))}."


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
WINDOW_SETTINGS_HEADING = "This browser"
WINDOW_SETTINGS_NOTE = "Saved in this browser only. Each change applies at once."
WINDOW_SETTINGS_TIP = "The command line and the MCP server do not use these."
APPEARANCE_HEADING = "Appearance"
RESULTS_HEADING = "Search results"
SAVE = "Save"

# Each preference's name and the sentence beside it, by its registry name.
PREFERENCE_WORDS: Final[dict[str, tuple[str, str]]] = {
    "theme": ("Theme", "Follow the system, or always light or dark."),
    "face": (
        "Reading font",
        "Font for documents and results. Atkinson Hyperlegible keeps similar "
        "letters distinct.",
    ),
    "size": ("Text size", "Scales all text in the window."),
    "spacing": (
        "Spacing",
        "Wider space between lines, letters and words. Some readers with "
        "dyslexia find this helps.",
    ),
    "width": (
        "Text width",
        "How wide documents and results run. Reading width is about 70 "
        "characters a line.",
    ),
    "strength": (
        "Match strength",
        "Show how well a result matched as bars and a word, or the word alone.",
    ),
    "labels": (
        "Measure labels",
        "Show each measure as an icon, a word, or both.",
    ),
    "scale": (
        "Bar colours",
        "Each runs dark to light and stays distinct for the most common "
        "colour blindness.",
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
        ("pane", "Full width"),
        ("wide", "Wide"),
        ("reading", "Reading width"),
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
KENNIS_SETTINGS_HEADING = "Shared settings"
KENNIS_SETTINGS_NOTE = (
    "Also used by the command line and the MCP server, from their next command."
)
KENNIS_SAVE = "Save settings"
# The configuration's headings, in page order, by the group each
# setting's section belongs to.
KENNIS_GROUPS: Final[tuple[tuple[str, str], ...]] = (
    ("searching", "Searching and indexing"),
    ("converting", "Converting documents"),
    ("adding", "Adding papers"),
)
KENNIS_SAVED = "Saved."
KENNIS_UNCHANGED = "Nothing changed."
KENNIS_NOT_SAVED = "Nothing saved. Each refused value says why."
# Each setting's name in the window, by its configuration key. The
# sentence beside it is the field's own description, as `config init`
# prints it.
SETTING_NAMES: Final[dict[str, str]] = {
    "embedding.backend": "Meaning search",
    "embedding.model": "Meaning model",
    "embedding.base_url": "Ollama address",
    "embedding.api_key": "OpenAI API key",
    "conversion.backend": "Converter",
    "conversion.mode": "Datalab quality",
    "conversion.api_key": "Datalab API key",
    "retrieval.corpus_method": "Default way to match",
    "retrieval.default_top_k": "Results per collection",
    "chunking.size": "Passage size",
    "literature.unpaywall_email": "Email for Unpaywall",
}
# What each setting is for, in an info tip beside its name. The engine's
# own description, which `config init` prints and the config file
# carries, suits the command line; these are the window's, and a key
# without one falls back to it.
SETTING_TIPS: Final[dict[str, str]] = {
    "embedding.backend": (
        "What finds results by meaning. FastEmbed downloads a 65 MB model the "
        "first time you index. None searches by keywords only."
    ),
    "embedding.model": "The model name, as the meaning search you chose knows it.",
    "embedding.base_url": (
        "The address of your Ollama server, for example http://localhost:11434."
    ),
    "conversion.backend": (
        "Turns PDF, Word, PowerPoint and Excel files into text. MinerU runs on "
        "your computer. Datalab is a paid online service and needs an API key."
    ),
    "conversion.mode": (
        "Datalab's quality and price per page: Fast 0.4c, Balanced 0.4c, "
        "Accurate 1.0c. Re-adding a document in a different mode is charged again."
    ),
    "retrieval.corpus_method": (
        f"How searches match when {MODE_LABEL} is left {MODE_CHOICES[0][1]}."
    ),
    "retrieval.default_top_k": (
        "How many results each collection returns. Searching everywhere "
        "returns this many from each."
    ),
    "chunking.size": (
        "About how many characters make one passage. Smaller passages match "
        "more precisely; larger ones give more context."
    ),
}


def credential_tip(backend: str, file_name: str, kept: str) -> str:
    """What a key's row says in its tip: where the key is kept."""
    return (
        f"Your {backend} API key. Kept in {file_name}, {kept}, never in the "
        "config file."
    )


def setting_tip(sentence: str, costs: str, key: str) -> str:
    """A setting's tip: what it is for, what changing it costs, and the
    key the command line knows it by, each on a line of its own."""
    said = f"{sentence} {costs[:1].upper()}{costs[1:]}." if costs else sentence
    return f"{said}\nConfig key: {key}"


CONVERTER_NAMES: Final[dict[str, str]] = {
    "mineru": "MinerU (local)",
    "datalab": "Datalab (hosted)",
}
SETTING_CHOICES: Final[dict[str, dict[str, str]]] = {
    "embedding.backend": {
        "fastembed": "FastEmbed (local)",
        "ollama": "Ollama (local server)",
        "openai": "OpenAI (hosted)",
        "none": "None (keywords only)",
    },
    "conversion.backend": CONVERTER_NAMES,
    "conversion.mode": {
        "fast": "Fast",
        "balanced": "Balanced",
        "accurate": "Accurate",
    },
    "retrieval.corpus_method": {value: label for value, label in MODE_CHOICES if value},
}
CONVERTER_MISSING = "MinerU is not installed. To install it, run:"
# Completed by the variable's name: "DATALAB_API_KEY is set". Neither
# is inside the other, so a test can tell them apart.
CREDENTIAL_SET = "is set"
CREDENTIAL_UNSET = "is not set"
CREDENTIAL_KEEP = "Leave empty to keep the current key."
REBUILD_HEADING = "Indexes need updating"
REBUILD_NOTE = "Until then, each index keeps its old settings:"
REBUILD_NONE = "No collection is indexed yet, so nothing needs updating."
REBUILD_NOW = "Index now"
REBUILD_LATER = "Later"
UNDO = "Undo"
LEXICAL_ONLY_INDEX = "keywords only"


def built_with(model: str | None, backend: str | None, chunk_size: int) -> str:
    """What an index was built with, as the rebuild panel names it."""
    searched = LEXICAL_ONLY_INDEX if model is None else f"{model} ({backend})"
    return f"{searched}, passages of {chunk_size} characters"


# The Backup section (13b). What the backup holds, and every sentence
# about its state, are `render/backup.py`'s, shared with `kennis backup`.
BACKUP_HEADING = "Backup"
BACKUP_FOLDER_LABEL = "Folder"
BACKUP_SAVE_FOLDER = "Save folder"
BACKUP_NOW = "Back up now"
BACKUP_NOW_NOTE = "The password is never stored. You need it to restore."
BACKUP_NOW_TIP = (
    "kennis asks for the password each time. Each new backup is checked "
    "before it replaces the last one."
)
BACKUP_PASSWORD = "Password"
BACKUP_CONFIRMATION = "Confirm password"
BACKUP_TEST = "Test backup"
BACKUP_TEST_NOTE = (
    "Checks that every file decrypts and is intact. Use the password you "
    "backed up with."
)
BACKUP_RESTORE_LABEL = "Restore"
BACKUP_RESTORE_NOTE = "Restoring replaces this corpus. Quit kennis, then run:"
PASSWORD_NEEDED = "Enter a password."
PASSWORDS_DIFFER = "The passwords do not match. Nothing was started."


def not_a_backup_folder(path: str) -> str:
    return f"'{path}' is not a folder. Nothing was saved."


# The drag handles (`gui/layout.py`), each named by what it resizes.
RESIZE_LABELS: Final[dict[str, str]] = {
    "pane-width": "Resize corpus panel",
    "inspector-width": "Resize details panel",
}
PANE_SHOW = "Show corpus panel"

PANE_HIDE = "Hide corpus panel"

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
    "/index": "Index collections",
    "/sync": "Sync packs",
    "/pack": "Install a pack",
    "/palette": "Actions and places",
}

# The palette (11g). Its actions are the bar's, opened on a tab or a
# collection where that saves a step; its places are the pane's.
PALETTE_TITLE = "Actions and places"
PALETTE_PROMPT = "Find an action or place"
PALETTE_EMPTY = "Nothing matches"
PALETTE_SHORTCUT = "Ctrl K"
PALETTE_KEYS: Final[tuple[tuple[str, str], ...]] = (
    ("Up Down", "move"),
    ("Enter", "open"),
    ("Esc", "close"),
)
# (address, label, icon), in the order the palette lists them.
PALETTE_ACTIONS_BEFORE_INDEX: Final[tuple[tuple[str, str, str], ...]] = (
    ("/add?kind=paper", "Add a paper", "file-plus"),
    ("/add?kind=site", "Add a documentation site", "globe"),
    ("/add?kind=file", "Add files", "file-plus"),
    ("/add?kind=group", "Add several at once", "folder"),
    ("/remember", "Write a note", "pencil"),
    ("/index", "Index all collections", "database"),
)
PALETTE_ACTIONS_AFTER_INDEX: Final[tuple[tuple[str, str, str], ...]] = (
    ("/sync", "Sync packs", "refresh-cw"),
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

QUIT_TITLE = "Quit kennis"

STOPPED = "kennis has stopped. You can close this tab."

QUIT_WHILE_RUNNING = (
    "A task is still running. Quit when the status bar says it has finished."
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

NOTHING_RUN = "No tasks yet. Tasks stay listed for an hour."

# The corpus's own record, under this window's jobs: everything that
# changed it, from here, a terminal or an agent.
CHANGES_HEADING = "Corpus history"

NO_CHANGES = "No changes yet."

# What each kind of job is called where a person reads it: the strip,
# the Activity page. The keys are the kinds `app.py` starts jobs under.
JOB_KINDS: Final[dict[str, str]] = {
    "add": "Add",
    "index": "Index",
    "sync": "Corpus sync",
    "context-sync": "Project context sync",
    "pack": "Pack install",
    "backup": "Backup",
}

# What the status bar says while each kind of job runs, before the job
# has reported a step of its own.
JOB_DOING: Final[dict[str, str]] = {
    "add": "Adding",
    "index": "Indexing",
    "sync": "Syncing the corpus",
    "context-sync": "Syncing the project context",
    "pack": "Installing a pack",
    "backup": "Backing up",
}

JOB_RUNNING = "running"

JOB_FINISHED = "finished"

JOB_FAILED = "failed"


def searchable_short(searchable: int, total: int) -> str:
    """How many collections a search reaches, as the bar shows it."""
    return f"{searchable}/{total}"


def to_index(count: int) -> str:
    """How many documents wait for an index, on the button that indexes."""
    return f"{count} to index"


# The bar's job segment, which opens what the job did, and the panel's way
# to the job's own page.
JOB_DETAILS = "Show what this task is doing or did"

OPEN_AS_PAGE = "Open as a page"


def searchable_summary(searchable: int, total: int) -> str:
    """How many collections a search reaches, for the status bar. What
    waits is its own item beside this, so it is not said twice."""
    return f"{searchable} of {total} collections searchable"


# The status bar's facts, each drawn as an icon and a short value.
STATUS_ICONS: Final[dict[str, str]] = {
    "commit": "git-commit-horizontal",
    "searchable": "search",
    "waiting": "triangle-alert",
    "change": "history",
}

# The status bar's labels, for a screen reader: the eye has an icon.
CORPUS_AT_LABEL = "Version"

LAST_CHANGE_LABEL = "Last change:"


def corpus_at(commit: str) -> str:
    """The commit the corpus is at, said whole: the status item's tooltip."""
    return f"{CORPUS_AT_LABEL} {commit}"


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
    return "Index all"


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
    "add": "added to",
    "move": "moved in",
    "index": "indexed",
    "sync": "synced",
    "remember": "note saved in",
    "restore": "restored",
}


def last_change(
    operation: str | None, scope: str | None, summary: str, seconds: float
) -> str:
    """The corpus's newest commit, for the status bar, after its label.

    A subject kennis did not write is quoted whole, because a commit a
    person made by hand is a change too (`read_history` keeps it).
    """
    return f"{change_line(operation, scope, summary)}, {time_ago(seconds)}"


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


CORPUS_OVERVIEW = "Overview"

NO_CONTEXT = "No project context."

NO_CONTEXT_TIP = (
    "Start kennis from a project folder that has a .context folder to see its "
    "notes here. To create one in a project, run kennis context init."
)

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
    "empty": "Empty",
    "none": "Not indexed yet",
    "behind": "Needs indexing",
    "current": "Searchable",
}

NOTHING_TO_INDEX = "Nothing to index yet."

BUNDLE_NOT_COMMITTED = (
    "Saved in your project's .context folder. Commit it with your project."
)

NOTHING_MATERIALISED = "Installed. Run Sync to bring its documents in."

BUSY_WITH_ANOTHER = "Another task is running. Try again when it finishes."

CORPUS_BUSY_RETRY = "The corpus is busy. Nothing changed; try again in a moment."

NOTHING_TO_ADD = "Nothing to add. Enter an ID, address or path, or choose a file."

# The Add dialog's four tabs, in the order offered. A kind of thing to
# add, not a collection: a PDF of a paper is a Paper, and a Markdown
# file is a File whichever collection it goes to (#413).
ADD_TABS: Final[tuple[tuple[str, str], ...]] = (
    ("paper", "Paper"),
    ("site", "Documentation site"),
    ("file", "Files"),
    ("group", "Several at once"),
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
    "paper": "Look a paper up by its identifier, or add it from a PDF.",
    "site": "The web address of a documentation site.",
    "file": "Files or a folder, into the collection you choose.",
    "group": "Many items at once: one block per group, one item per line.",
}

# Each tab's background, in an info tip beside its line.
ADD_TIPS: Final[dict[str, str]] = {
    "paper": (
        "Papers go to the literature collection. kennis looks up the title "
        "and authors, and makes a citekey for citing it."
    ),
    "site": (
        "Pages go to the docs collection. kennis reads the site's page list, "
        "or follows its links when it has none, at a polite pace, and saves "
        "each page as a document."
    ),
    "file": (
        "A folder adds every file in it that kennis can convert, such as PDF, "
        "Word, Markdown and plain text."
    ),
    "group": (
        "Each line can be an arXiv ID, DOI, bibcode, web address, file or "
        "folder. Each line is checked as you type, as its own tab would check it."
    ),
}

# Every field says which it is, and an optional one says what empty
# becomes, because "optional" alone leaves the reader to guess what
# kennis will do instead.
REQUIRED = "required"
OPTIONAL = "optional"
EMPTY_PREFIX = "Default:"
ADD_TABS_LABEL = "What to add"
# Answered to a chooser asked to write into a field no form draws.
NOT_A_FIELD = "That field does not take a path."

# What each form field is called where a person reads it. One label per
# name, whichever tab shows the field.
FIELD_LABELS: Final[dict[str, str]] = {
    "source": "Add from",
    "paper": "arXiv ID, DOI or bibcode",
    "pdf": "PDF",
    "site": "Site address",
    "file": "Files or folder",
    "identifier": "Its identifier",
    "title": "Title",
    "citekey": "Citekey",
    "group": "Group",
    "project": "Project",
    "collection": "Collection",
    "max_pages": "Page limit",
    "max_depth": "Link depth limit",
    "lines": "Items, one per line",
}

# A field's explanation, in an info tip beside its label, for the fields
# whose name alone does not say enough.
FIELD_TIPS: Final[dict[str, str]] = {
    "identifier": (
        "The arXiv ID, DOI or bibcode of the paper in the PDF. Fill it in "
        "when the PDF does not show one, or shows the wrong one."
    ),
    "citekey": "The key you cite it by in LaTeX or BibTeX.",
    "group": (
        "A folder in the collection. Write radio/calibration to file it in "
        "calibration, inside radio."
    ),
    "project": (
        "The name its pages are filed under in docs: one folder, with no "
        "groups inside it."
    ),
    "max_depth": "How many links away from the start page kennis follows.",
}

# What an empty optional field becomes.
EMPTY_MEANS: Final[dict[str, str]] = {
    "identifier": "read from the PDF",
    "title": "the paper's own title",
    "file_title": "first heading or file name",
    "citekey": "author, year, title",
    "project": "taken from the address",
    "file_project": "none (docs needs one)",
    "max_pages": "300",
    "max_depth": "5",
}


def group_empty_means(default_group: str | None) -> str:
    """What an empty group becomes, which depends on the settings."""
    if default_group:
        return f"'{default_group}', from your settings"
    return "no group"


# The Paper tab's two ways in, as Zotero has them: an identifier, looked
# up as it is typed, or a PDF, read for its identifier. Each shows only
# its own fields, and the one chosen is the one added from.
SOURCE_CHOICES: Final[tuple[tuple[str, str, str], ...]] = (
    ("identifier", "Identifier", "wand-sparkles"),
    ("pdf", "PDF", "file-text"),
)
# The Paper tab added from with nothing to add from.
NO_IDENTIFIER = "Enter an arXiv ID, DOI or ADS bibcode."
NO_PDF = "Choose a PDF, or give its web address or path."

GROUP_NEEDS_A_NAME = "Give each block that has items a group name."

# Beside a refusal's repairs. Skipping changes nothing: the item was
# already refused and the rest of the add went on, which is what the
# sentence says so that Skip is not read as undoing anything.
SKIP = "Skip"
SKIPPED = "Skipped. Nothing was added for this item; the rest are unaffected."


def open_candidate(value: str) -> str:
    """The accessible name of a candidate's link to its registry."""
    return f"Look up {value} in a new tab"


# No collection is chosen for the reader, as `corpus add` chooses none:
# a Markdown note sent to literature by a default is refused there for
# having no paper identifier, which reads as kennis failing.
CHOOSE_A_COLLECTION = "Choose a collection."
ANOTHER_GROUP = "Add another group"
BLOCK_HEADING = "Group"

BROWSE = "Browse"


# The browser's own picker, beside a field that takes paths. Its file is
# sent from the computer the reader sits at, so it works the same when
# kennis runs on another one behind `ssh -L` - where a typed path is read.
def tip_about(subject: str) -> str:
    """What an info tip's button is called, to a screen reader and on
    hover: the tip itself is the few words it opens."""
    return f"About {subject}"


UPLOAD_FILES = "Choose files"
UPLOAD_FOLDER = "Choose a folder"
UPLOAD_PDF = "Choose a PDF"
UPLOAD_HINT = "Sent from this computer, even when kennis runs on another."
UPLOAD_TYPED = "Or type a path on the kennis computer"
UPLOAD_TYPED_PDF = "Or give a web address, or a path on the kennis computer"
UPLOAD_CLEAR = "Clear"
# What was chosen, said back under the buttons. Filled in by the page's
# script, which composes no words of its own: `{name}`, `{names}` and
# `{count}` are its only part.
UPLOAD_SAID: Final[dict[str, str]] = {
    "none": "Nothing chosen.",
    "one": "{name}",
    "many": "{count} files: {names}",
    "more": "{names} and {count} more",
    "folder": "The folder {name}, {count} files",
}
CHOOSE_FOLDER = "Choose this folder"
CHOOSER_UP = "Up one folder"
CHOOSER_CANCEL = "Cancel"
CHOOSER_HEADING = "On the kennis computer:"
# A folder of thousands of files is listed only so far, and says so.
CHOOSER_SHOWN_AT_MOST = 500


def chooser_truncated(shown: int, total: int) -> str:
    return f"Showing {shown} of {total}. Type a path to reach the rest."


def not_a_folder(path: str) -> str:
    return f"'{path}' is not a folder kennis can open."


def not_a_count(label: str, given: str) -> str:
    return f"{label} needs a whole number, not '{given}'."


# The preview, for a paper.
def previewed_citekey(citekey: str) -> str:
    return f"Citekey: {citekey}"


# Shown while a preview's request is out: arXiv takes a second or more,
# and an Add pressed before it answers loses what it would have said.
LOOKING_UP: Final[dict[str, str]] = {
    "paper": "Looking up the paper...",
    "site": "Reading the address...",
}

# How many authors the found paper's card names before "and N others".
AUTHORS_SHOWN: Final = 3


def found_on_arxiv(identifier: str) -> str:
    return f"arXiv {identifier}"


def shortened_authors(names: Sequence[str]) -> str:
    """The first few authors and how many more, as a byline reads."""
    if len(names) <= AUTHORS_SHOWN:
        return ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1]
    rest = len(names) - AUTHORS_SHOWN
    return (
        ", ".join(names[:AUTHORS_SHOWN])
        + f" and {rest} other"
        + ("s" if rest > 1 else "")
    )


# Read by a screen reader on a field the preview filled in, which is
# marked by colour alone.
PREFILLED_NOTE = "Filled in from arXiv. Change it to use your own."

ARXIV_SILENT = (
    "arXiv did not respond, so the citekey comes from the title for now. "
    "kennis asks again when adding."
)
PREVIEW_FILE = "A file on the kennis computer. It is converted when added."
PREVIEW_ADDRESS = "A web address. Its file is converted when added."
PREVIEW_UNRECOGNISED = (
    "Not recognised. Enter an arXiv ID, DOI or ADS bibcode, or add from a PDF."
)


# The preview, for a site.
def previewed_project(project: str) -> str:
    return f"Pages will be filed under project '{project}'."


def docs_input_refused(identifier: str, reason: str) -> str:
    """A docs add refused before it starts, while the form is still open:
    after the dialog had closed it came back in the strip, with what was
    typed gone."""
    if reason == "missing":
        return f"'{identifier}' is not a site address or an existing file."
    return (
        f"'{identifier}' is a file, so no project name can be made from it. "
        "Enter a Project name."
    )


PROJECT_UNNAMED = "No project name can be made from this address. Enter a Project name."
CHECK_SITE = "Check site"
# Words for each way `discovery_mode` answers.
DISCOVERY_WORDS: Final[dict[str, str]] = {
    "sphinx": "Found a page list (Sphinx inventory).",
    "sitemap": "Found a page list (sitemap).",
    "crawl": "No page list found. kennis will follow links instead.",
}
SITE_UNREACHABLE = "The site did not respond. Check the address."

# A line of a group, checked.
LINE_KINDS: Final[dict[str, str]] = {
    "arxiv": "arXiv ID",
    "doi": "DOI",
    "bibcode": "bibcode",
    "address": "web address",
    "file": "file",
    "folder": "folder",
    "nothing": "not recognised",
}
LINE_HELD = "already in the corpus"

# The Add dialog's submit button, named for what the tab adds.
ADD_ACTIONS: Final[dict[str, str]] = {
    "paper": "Add paper",
    "site": "Add site",
    "file": "Add files",
    "group": "Add all",
}

# The foot of the Add dialog: where the add will go, which the window
# keeps in step with the fields as they are filled in.
ADDS_TO = "Adds to"
CANCEL = "Cancel"

# The Index form's choice for all of them, beside each collection's name.
INDEX_EVERY = "All"


def index_waiting(count: int) -> str:
    """Beside a collection in the Index dialog: how many documents a search
    cannot find until it is indexed."""
    return f"{count} to index"


# Where a note goes, by the form's value: the corpus's notes, or the
# context bundle of the project the window was started in.
REMEMBER_TARGETS: Final[tuple[tuple[str, str], ...]] = (
    ("notes", "Notes"),
    ("context", "Project context"),
)
INDEX_PREAMBLE = "Make new and changed documents searchable."

INDEX_TIP = (
    "Indexing reads every document in a collection. With meaning search on, "
    "the first run also downloads the meaning model, so it is slower."
)

INDEX_ACTION = "Index"

SYNC_PREAMBLE = "Bring in the documents your installed packs list."

SYNC_TIP = (
    "Sync corpus downloads over the network. Sync project context copies "
    "from this computer only."
)

PACK_PREAMBLE = "The path to a pack file (.ken.yml)."

PACK_TIP = "Installing records what the pack lists. Run Sync to bring its documents in."

PACK_ACTION = "Install pack"

SYNC_CORPUS_ACTION = "Sync corpus"

SYNC_CONTEXT_ACTION = "Sync project context"

# No "the Index section above": Add is first on the manage page
# and Index is third, so the sentence was wrong as well as
# fragile. A message does not name a position on a page.
NOT_SEARCHABLE_YET = "Not searchable until indexed."

INDEX_NOW = "Index now"

# More items than this and an outcome folds the ones needing nothing
# away: a 4,000-file add listed every one, and the line saying what
# happened was a screen above them.
# What happened to a group of items that share no reason, as its heading.
OUTCOME_WORDS: Final[dict[str, str]] = {
    "added": "added",
    "removed": "removed",
    "changed": "changed",
    "unchanged": "unchanged",
    "skipped": "skipped",
    "failed": "failed",
}


NO_SUCH_JOB = "That task is no longer listed, or was not started in this window."

STILL_RUNNING = "Still running."

NOTHING_TO_SHOW = "That task finished with nothing to report."


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
        f"The task stopped: {detail}. Run it again to carry on from where it "
        "stopped. Details are in the kennis log."
    )


MARK_WITHHELD = (
    "This document changed after it was indexed, so the matched passage "
    "cannot be highlighted. Index it again to restore the highlight."
)

IMAGES_BLOCKED = "Figures from other sites are not loaded, for privacy."

IMAGES_TIP = (
    "Loading a figure tells the site that hosts it which document you are reading."
)

LOAD_IMAGES = "Load figures"

NEVER_INDEXED = "Not indexed yet"
SEARCHABLE = "Searchable"
NEEDS_INDEXING = "Needs indexing"
# The corpus page's table, by column.
HOLDINGS_COLUMNS: Final[tuple[str, str, str]] = ("Collection", "Documents", "Search")

CORPUS_CHANGED = "The corpus changed elsewhere. Reload to see the latest."

NOTHING_HELD = "No documents yet. Use Add to bring some in."

NO_PACKS = "No packs installed."

REMEMBER_PREAMBLE = "Write anything worth finding again."

REMEMBER_TIP = (
    "Notes go to the notes collection and are kept in its history. Project "
    "context notes go to this project's .context folder; commit them with "
    "the project."
)

REMEMBER_PLACEHOLDER = "Something worth having again in six months"

# The Note dialog's fields by name, beside them rather than inside them:
# a placeholder is gone the moment anything is typed, a screen reader
# may not read it, and the title's was clipped mid-word.
NOTE_TEXT_LABEL = "Note"

TITLE_LABEL = "Title"

TITLE_HINT = "Optional. Default: the first line"

GROUP_LABEL = "Group"

GROUP_HINT = "Optional; a/b puts b inside a"

TARGET_LABEL = "Save to"

PACK_PATH_LABEL = "Pack file"

INDEX_WHICH_LABEL = "Collections"

REMEMBER_ACTION = "Save note"

NOTHING_TO_REMEMBER = "Write something first."

CORPUS_BUSY = "The corpus is busy. Your text is kept; try again in a moment."


def describe_written(report: RememberReport, where: str) -> ShownOutcome:
    """What one note written into the corpus came to.

    An unchanged outcome is not a failure and not a success worth
    celebrating: the thing is already known, which is why it wears the
    role that carries no colour.
    """
    if report.outcome is Outcome.UNCHANGED:
        return ShownOutcome(
            message=f"Already saved: {report.title}",
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
            message=f"Saved: {report.title} - {state}",
            role="role-operation",
            where=where,
            clears=True,
            # The note is written and is not findable: offered as the
            # window's own Index now button, not as a command to go and
            # type somewhere else.
            index_after="notes",
        )
    state = index_state(report.index_outcome, report.chunk_count)
    suffix = f" - {state}" if state else ""
    return ShownOutcome(
        message=f"Saved: {report.title}{suffix}",
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
            f"Already in project context: {note.title}"
            if already
            else f"Saved to project context: {note.title}"
        ),
        role="role-unchanged" if already else "role-operation",
        where=f"{bundle_name}/{note.relative_path}",
        clears=True,
    )


def describe_holding(holding: Holding) -> str:
    """Whether one collection can be searched, for a cell.

    The window's own short form, not the command line's sentence ("the
    notes index is stale: ..."): a cell beside the collection's name
    says the state and, where it is a count, how many wait. An index
    that was never built says so rather than being called stale, which
    sends someone to rebuild an index that does not exist.
    """
    if holding.freshness is None:
        return NEVER_INDEXED
    if holding.is_current:
        return SEARCHABLE
    waiting = holding.freshness.added + holding.freshness.changed
    return index_waiting(waiting) if waiting else NEEDS_INDEXING


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
        "are not listed. kennis corpus status names them."
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
    counted = count_of(hits, "result")
    # "9+" rather than "at least 9": the margin is 11rem and the
    # longer form wrapped between "9" and "hits", which reads worse
    # than the notation does.
    found = f"{where}, {hits}+ results" if capped else f"{where}, {counted}"
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
    return f"'{asked}' is not a way to match. The choices are {joined(offered)}."


def unknown_scope(asked: str, scopes: Sequence[str]) -> str:
    """Named rather than silently empty.

    A mistyped scope answered with no hits reads as "nothing is here",
    which is a different and wrong conclusion.
    """
    return (
        f"'{asked}' is not a place to search. The choices are {joined(list(scopes))}."
    )


# The tree's marks, after an editor's source-control view: quiet when
# the index has a document as it stands, a letter when not. The letter is
# what is seen; the sentence is its tooltip and what a screen reader says.
STATE_LETTERS: Final[dict[str, str]] = {
    "unindexed": "U",
    "changed": "M",
    "unreadable": "!",
}

STATE_WORDS: Final[dict[str, str]] = {
    "unindexed": "Not indexed yet, so search cannot find it",
    "changed": "Changed since last indexed, so search finds the old text",
    "unreadable": "kennis cannot read this document's metadata",
}

ATTENTION_ONLY = "Show only what needs attention"

MENU_OPEN = "Open"
MENU_MOVE = "Move to group"
MENU_ADD_HERE = "Add here"
MENU_INDEX = "Index this collection"

MOVE_GROUP_LABEL = "New group"
MOVE_GROUP_EMPTY = "Empty for no group; a/b puts b inside a"


def attention_count(count: int) -> str:
    """How many documents beneath a group need attention."""
    verb = "needs" if count == 1 else "need"
    return f"{count_of(count, 'document')} {verb} attention"


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
WELCOME_HEADING = "Your corpus is empty"

WELCOME = (
    "kennis keeps your papers, docs and notes on this computer and finds "
    "them by keyword and by meaning. Start by adding something."
)

WELCOME_TIP = "AI agents can search the same corpus through MCP."

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
SKIP_TO_CONTENT = "Skip to content"

# What a running job's bar is, to a screen reader.
PROGRESS_LABEL = "Progress"


# A page that could not be drawn: what went wrong, said as a heading the
# reader can find, and two ways back, so a refusal is never a dead end.
PROBLEM_HEADING = "This page cannot be shown"

NOT_FOUND_HEADING = "Not found"

PROBLEM_BACK = "Back to search"

PROBLEM_CORPUS = "Open corpus"


def no_page_at(path: str) -> str:
    """An address the window has no page for."""
    return f"There is no page at {path}."


# A request without the token: the browser was given an address with the
# key in it, and this one has neither the key nor the cookie it leaves.
LOCKED_HEADING = "Access key missing"

LOCKED = (
    "This address is missing kennis's access key. Open the full address "
    "that `kennis gui` printed, or run `kennis gui` again."
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

KEYWORDS_ONLY_INDEX = "Index with meaning"


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
    "ADD_TIPS",
    "ANOTHER_GROUP",
    "APPEARANCE_HEADING",
    "ARXIV_SILENT",
    "ATTENTION_ONLY",
    "AUTHORS_SHOWN",
    "BACKUP_CONFIRMATION",
    "BACKUP_FOLDER_LABEL",
    "BACKUP_HEADING",
    "BACKUP_NOW",
    "BACKUP_NOW_NOTE",
    "BACKUP_NOW_TIP",
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
    "CORPUS_AT_LABEL",
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
    "FIELD_TIPS",
    "GROUP_HINT",
    "GROUP_LABEL",
    "GROUP_NEEDS_A_NAME",
    "HIDE_PASSAGE",
    "HOLDINGS_COLUMNS",
    "IMAGES_BLOCKED",
    "IMAGES_TIP",
    "INDEX_ACTION",
    "INDEX_EVERY",
    "INDEX_NOW",
    "INDEX_PREAMBLE",
    "INDEX_STATES",
    "INDEX_TIP",
    "INDEX_WHICH_LABEL",
    "INSPECTOR_HIDE",
    "INSPECTOR_LABEL",
    "INSPECTOR_SHOW",
    "JOB_DETAILS",
    "JOB_DOING",
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
    "LAST_CHANGE_LABEL",
    "LEXICAL_ONLY_INDEX",
    "LINE_HELD",
    "LINE_KINDS",
    "LOAD_IMAGES",
    "LOCKED",
    "LOCKED_HEADING",
    "LOOKING_UP",
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
    "NEEDS_INDEXING",
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
    "NO_CONTEXT_TIP",
    "NO_HEADINGS",
    "NO_IDENTIFIER",
    "NO_MATCHES",
    "NO_PACKS",
    "NO_PDF",
    "NO_SUCH_JOB",
    "OPEN_AS_PAGE",
    "OPEN_AT_PASSAGE",
    "OPTIONAL",
    "ORDER_CHOICES",
    "ORDER_LABEL",
    "ORDER_LIMIT",
    "OUTCOME_WORDS",
    "OUTLINE_HEADING",
    "PACKS_HEADING",
    "PACK_ACTION",
    "PACK_PATH_LABEL",
    "PACK_PREAMBLE",
    "PACK_TIP",
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
    "PREFILLED_NOTE",
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
    "REMEMBER_TIP",
    "REQUIRED",
    "RESIZE_LABELS",
    "RESULTS_HEADING",
    "SAVE",
    "SCOPE_LABEL",
    "SEARCHABLE",
    "SEARCHING",
    "SEARCH_ACTION",
    "SEARCH_KEY_TITLE",
    "SETTINGS_HEADING",
    "SETTING_CHOICES",
    "SETTING_NAMES",
    "SETTING_TIPS",
    "SHOW_PASSAGE",
    "SITE_UNREACHABLE",
    "SKIP",
    "SKIPPED",
    "SKIP_TO_CONTENT",
    "SOURCE_CHOICES",
    "STATE_LETTERS",
    "STATE_WORDS",
    "STATUS_ICONS",
    "STILL_RUNNING",
    "STOPPED",
    "SYNC_CONTEXT_ACTION",
    "SYNC_CORPUS_ACTION",
    "SYNC_PREAMBLE",
    "SYNC_TIP",
    "TARGET_LABEL",
    "THEME_CHOICES",
    "TITLE_HINT",
    "TITLE_LABEL",
    "UNDO",
    "UPLOAD_CLEAR",
    "UPLOAD_FILES",
    "UPLOAD_FOLDER",
    "UPLOAD_HINT",
    "UPLOAD_PDF",
    "UPLOAD_SAID",
    "UPLOAD_TYPED",
    "UPLOAD_TYPED_PDF",
    "WELCOME",
    "WELCOME_ACTIONS",
    "WELCOME_HEADING",
    "WELCOME_TIP",
    "WINDOW_SETTINGS_HEADING",
    "WINDOW_SETTINGS_NOTE",
    "WINDOW_SETTINGS_TIP",
    "attention_count",
    "built_with",
    "change_line",
    "chooser_truncated",
    "corpus_at",
    "credential_tip",
    "describe_count",
    "describe_holding",
    "describe_recent",
    "describe_written",
    "describe_written_to_bundle",
    "docs_input_refused",
    "documents_held",
    "documents_waiting",
    "found_on_arxiv",
    "group_empty_means",
    "index_collection",
    "index_now",
    "index_waiting",
    "job_crashed",
    "key_models",
    "keywords_only",
    "last_change",
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
    "previewed_citekey",
    "previewed_project",
    "results_for",
    "search_crumb",
    "search_hint_for",
    "searchable_short",
    "searchable_summary",
    "setting_tip",
    "shortened_authors",
    "time_ago",
    "tip_about",
    "to_index",
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
        f"Indexed {count_of(built.documents, 'document')} in "
        f"{count_of(built.chunks, 'passage')}"
    )


def describe_built(index: BuiltIndex) -> str:
    """One collection's share of a build."""
    return (
        f"{count_of(index.documents, 'document')} in "
        f"{count_of(index.chunks, 'passage')}"
    )


def describe_backend(built: IndexBuild) -> str:
    """Which backend a build used, named before the wait it explains.

    A dense build downloads a model on a machine that has never run
    one, and a long pause needs its explanation already on screen
    rather than afterwards.
    """
    if built.model_kind is None or built.model_name is None:
        return "keywords only, with no meaning model"
    return f"{built.model_kind} {built.model_name}"


def unknown_collection(asked: str) -> str:
    """A collection that is not one of the three, named back."""
    return (
        f"'{asked}' is not a collection. The collections are "
        f"{joined(COLLECTION_NAMES)}."
    )


def no_such_pack(given: str) -> str:
    """A pack path that names no file.

    The path is quoted back because a typo is the likely cause and a
    reader cannot see one they cannot see.
    """
    if not given:
        return "Enter the path to a pack file (.ken.yml)."
    return f"No file at '{given}'. Check the path."
