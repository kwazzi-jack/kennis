"""Terminal presentation: one console, one theme, one place that knows how
kennis's output is shaped.

**The report grammar.** Every line a command prints about work it did is an
*operation*: a past-tense verb at the margin, then the thing it acted on, then
how long it took. What belongs to an operation - the documents it touched, the
command to run next - is indented one step under it (`_CONTENT_INDENT`). Read
down the left edge and you have the order things happened in::

    Initialized corpus at ~/knowledge in 7ms
    Created 3 corpus directories in 0ms
      + /home/brian/.local/share/kennis/literature
    Rebuilt literature index - 2 of 19 documents added in 1m11s
    Registered kennis with claude, copilot
      hint: run `kennis register --force`

**Indentation, not alignment.** Right-aligning verbs into a fixed column is
uv's and cargo's convention, and it gives the payload one column at the cost
of two left edges: a detail marker cannot join the verb column without being
inset ten characters, so the eye has to track both. With everything at the
margin there is one edge for operations and one for their contents. The
payload no longer starts in a fixed column, and the in-flight/finished pair
(`Indexing` -> `Indexed`) shares a *start* rather than an end - which still
replaces cleanly, since the progress block is erased whole.

Diagnostics are the exception. `warning:` and `error:` stay at column zero: a
problem has to break the left edge to be seen, and must not scan as one more
step that went fine. `hint:` is indented with the other content, because
advice is subordinate to the line it follows.

**Two shapes, and only two.** A command either reports a *sequence of
operations* or describes *state*, and the two want different layouts. Anything
that does things in order uses the operation lines above; anything answering
"what is here" keeps an aligned `label:` column - several facts about several
things, where the label carries the severity and one column can be scanned for
anything wrong. Forcing the second group into operation lines would mean
writing `Checked` against every row of a status listing, claiming an action
where there was only a look. The distinction is the design, not an
unconverted remnant: what the two share is diction, not layout.

**This module owns layout, not wording.** It decides where a verb sits and
what colour it wears; which verb, and the sentence after it, belong to the
caller. The colours themselves belong to `theme`, which declares them once as
semantic roles for every interface to adapt.

Colour disappears on its own when stdout is not a terminal (rich checks
`isatty`), so piping or redirecting any command gives the plain text back with
no flag to remember.

Messages are built as `rich.text.Text` rather than markup strings, so an
interpolated title, snippet or config value containing a literal `[` is data
rather than an unknown style tag rich would silently swallow.
"""

from __future__ import annotations

import contextlib
import textwrap
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from functools import lru_cache
from typing import IO, Any

import click
from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound
from rich.console import Console, RenderableType
from rich.highlighter import RegexHighlighter
from rich.padding import Padding
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.syntax import SyntaxTheme
from rich.text import Text

from kennis.cli.theme import rich_style_name, rich_theme, syntax_theme
from kennis.render.markdown import Block, detected_language, split_blocks
from kennis.render.theme import STYLE_PREFIX

_THEME = rich_theme()

# highlight=False: rich's default ReprHighlighter guesses at numbers, paths and
# repr syntax in any string printed, which is unpredictable over payloads that
# are already structured. Every renderer below states its own highlighter.
console = Console(theme=_THEME, highlight=False)

# Errors follow click's convention of going to stderr, so a piped command's
# stdout stays clean.
error_console = Console(theme=_THEME, highlight=False, stderr=True)

# Progress bars go to stderr so a redirected stdout keeps only the report.
_progress_console = Console(theme=_THEME, highlight=False, stderr=True)

# Advances a bar: no arguments steps it by one, `(done, total)` sets both.
type ProgressUpdate = Callable[..., None]


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
#
# A RegexHighlighter styles each named group as `<base_style><group name>`, so
# every group name below is a role name in `theme`. Patterns apply in order
# with later spans drawn over earlier ones, so the list is ordered
# broad-to-specific.

# A command to run. The backtick is the marker, and `command()` below is the
# only thing that writes one, so the highlighter never has to work out which
# words in a sentence are an invocation. Deriving that from a list of kennis's
# own subcommands is what the marker replaces: such a list falls silently
# behind the interface, rendering one suggestion cyan and the next plain for
# no reason a reader can see, and it can never match the commands that are not
# kennis's own.
_COMMAND = r"(?P<command>`[^`\n]+`)"
_OPTION = r"(?P<option>(?<![\w-])--[a-z][\w-]*)"
# A value rather than a command: a config key, an id, a citekey, something the
# user typed or kennis read back. Quotes only - backticks mean a command, and
# the two must not share a pattern or they will share a style.
_QUOTED = r"(?P<quoted>'[^'\n]*'|\"[^\"\n]*\")"
# The lookbehind stops a relative path's tail ("literature/bm25") being styled
# from its slash onwards; only a genuine path root starts a match.
_PATH = r"(?P<path>(?<!\w)(?:~|\.{1,2})?/[\w.@+-]+(?:/[\w.@+-]+)*/?)"
# The bracketed alternative keeps a list value (`available=[a, b, c]`) whole;
# without it only the opening item would be styled and the line would read as
# though the highlighting had broken off mid-value.
_KEY_VALUE = r"(?P<key>\b[a-z][\w.]*=)(?P<value>\[[^\]\n]*\]|[^\s,)\]]+)"

# _COMMAND last: a command is one thing and must render as one span, so it
# draws over the option and path fragments inside it. `--collection` styled on
# top of the invocation it belongs to loses the command's bold and makes a
# single suggestion look like two.
_MESSAGE_PATTERNS = [_PATH, _KEY_VALUE, _QUOTED, _OPTION, _COMMAND]


class MessageHighlighter(RegexHighlighter):
    """Picks the actionable parts out of an ordinary line.

    Runs over every message printed, so a suggested command, a path or a
    `key=value` is findable at a glance without each call site marking it up
    by hand.
    """

    base_style = STYLE_PREFIX
    highlights = _MESSAGE_PATTERNS


_MESSAGE_HIGHLIGHTER = MessageHighlighter()


# A ranked hit, styled through the roles `render/theme.py` has carried since
# milestone 0 under "no renderer yet". The text is `render.hits`'s; nothing
# here rewrites it, so the same words reach a front end that cannot colour.
#
# Anchored to line starts and to the shapes `render.hits` emits, in the order
# broad-to-specific that the module docstring describes.
_RANK = r"(?m)^\s*(?P<rank>\[\d+\])\s"
# The second bracketed group on a hit line, which is the collection. The
# lookbehind is what keeps it from matching the rank.
_HIT_COLLECTION = r"(?<=\]\s)(?P<collection>\[\w+\])"
# Everything after the collection, up to the " - " that introduces a section.
_HIT_TITLE = r"(?<=\]\s)(?P<title>[^\n\[\]]+?)(?=\s-\s|$)"
_HIT_SECTION = r"(?m)(?P<section>\s-\s[^\n]+)$"
_RELEVANCE = r"(?P<label>\brelevance:)\s(?P<score>very high|very low|high|medium|low)"
_LEG_SCORE = r"(?P<score_label>\b(?:bm25|cos|rrf)=)(?P<score>[\d.]+)"


# Broad to specific, as above: the title claims the whole of what follows the
# collection, and the rank, the collection and the scores are drawn over it.
_HIT_PATTERNS = [
    _HIT_TITLE,
    _HIT_SECTION,
    _RANK,
    _HIT_COLLECTION,
    _KEY_VALUE,
    _RELEVANCE,
    _LEG_SCORE,
]


class HitHighlighter(RegexHighlighter):
    """Styles one ranked hit without touching a character of it."""

    base_style = STYLE_PREFIX
    highlights = _HIT_PATTERNS


# Markdown, styled where it stands and never consumed: the terminal shows the
# same characters the corpus holds and an agent would read, so a heading keeps
# its hashes and a fence keeps its backticks.
_MD_FENCE = r"(?m)^(?P<md_fence>```[\w-]*)$"
_MD_HEADING = r"(?m)^(?P<md_heading>#{1,6} [^\n]*)$"
_MD_CODE = r"(?P<md_code>`[^`\n]+`)"
_MD_STRONG = r"(?P<md_strong>\*\*[^*\n]+\*\*)"
_MD_EMPHASIS = r"(?P<md_emphasis>(?<![*\w])\*[^*\n]+\*(?![*\w]))"
_MD_LINK = r"(?P<md_link>!?\[[^\]\n]*\])(?P<md_url>\([^)\n]*\))"


_MD_PATTERNS = [
    _MD_FENCE,
    _MD_HEADING,
    _MD_LINK,
    _MD_STRONG,
    _MD_EMPHASIS,
    _MD_CODE,
]


class BodyHighlighter(RegexHighlighter):
    """Styles a markdown body: a hit's snippet, or a document `read` prints."""

    base_style = STYLE_PREFIX
    highlights = _MD_PATTERNS


# TOML, which rich has no highlighter for. `config show` emits a whole file
# of it, and a sixty-line block of one colour is read by nobody.
_TOML_COMMENT = r"(?m)(?P<toml_comment>(?:^|\s\s)#[^\n]*)$"
_TOML_SECTION = r"(?m)^(?P<toml_section>\[[\w.-]+\])$"
_TOML_KEY = r"(?m)^(?P<toml_key>[\w.-]+)(?=\s=\s)"
_TOML_STRING = r"(?P<toml_string>\"(?:[^\"\\\n]|\\.)*\")"
_TOML_NUMBER = r"(?<== )(?P<toml_number>-?\d+(?:\.\d+)?)\b"
_TOML_BOOL = r"(?<== )(?P<toml_bool>true|false)\b"


_TOML_PATTERNS = [
    _TOML_SECTION,
    _TOML_KEY,
    _TOML_STRING,
    _TOML_NUMBER,
    _TOML_BOOL,
    _TOML_COMMENT,
]


class TomlHighlighter(RegexHighlighter):
    """Styles the TOML `config show` prints."""

    base_style = STYLE_PREFIX
    highlights = _TOML_PATTERNS


_HIT_HIGHLIGHTER = HitHighlighter()
_BODY_HIGHLIGHTER = BodyHighlighter()
_TOML_HIGHLIGHTER = TomlHighlighter()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _line(style: str | None, text: str, lead: str | None, indent: str) -> Text:
    """One message line, styled by the `lead`-carries-the-colour convention.

    With a `lead` ("Indexed", "Warning:") only that word takes `style` and the
    rest of the sentence stays plain; without one the whole line takes the
    quieter `.line` variant, since a full sentence in bold colour shouts.
    Either way the text is highlighted, never parsed as markup.
    """
    prefix = indent if lead is None else f"{indent}{lead}{' ' if text else ''}"
    line = Text(f"{prefix}{text}")
    _MESSAGE_HIGHLIGHTER.highlight(line)
    if lead is None:
        if style is not None:
            line.style = f"{style}.line"
    elif style is not None:
        line.stylize(style, len(indent), len(indent) + len(lead))
    return line


def info(text: str = "", *, lead: str | None = None, indent: str = "") -> None:
    """A neutral line: no severity, only the fragments the highlighter finds."""
    console.print(_line(None, text, lead, indent))


def success(text: str = "", *, lead: str | None = None, indent: str = "") -> None:
    """Something happened. `lead` is the past-tense verb that says what."""
    console.print(_line("operation", text, lead, indent))


def warning(text: str = "", *, lead: str | None = None, indent: str = "") -> None:
    """Something is off but the command carries on."""
    console.print(_line("warning", text, lead, indent))


def error(text: str = "", *, lead: str | None = None, indent: str = "") -> None:
    """Something failed. Printed to stdout like the rest of a command's
    report; a failure that aborts the command raises `CliError` instead."""
    console.print(_line("error", text, lead, indent))


def heading(text: str = "", *, lead: str | None = None, indent: str = "") -> None:
    """A line that names the thing the lines under it are about."""
    console.print(_line("heading", text, lead, indent))


def muted(text: str = "", *, lead: str | None = None, indent: str = "") -> None:
    """An aside worth printing but not worth reading first."""
    console.print(_line("muted", text, lead, indent))


# ---------------------------------------------------------------------------
# The operation column
# ---------------------------------------------------------------------------

# What an operation's contents are indented by: its detail lines, and the hint
# that follows it. Two levels and no alignment - an operation at the margin,
# everything belonging to it one step in. Nothing is aligned to a width that a
# longer verb could overflow.
_CONTENT_INDENT = 2

# Detail lines: one marker character, then the item. `uv` prints ` + rich==15.0.0`.
_DETAIL_INDENT = " " * _CONTENT_INDENT

# How many details an operation prints before summarising the rest. A large
# batch touches a hundred items, and a hundred lines of titles is a wall
# nobody reads; the count above it already said how many there were.
# `--verbose` lifts this.
DETAIL_LIMIT = 10


def _format_elapsed(seconds: float) -> str:
    """`31ms`, `4.7s`, `2m25s` - the precision a reader can act on.

    Milliseconds below a second, as uv prints them: `in 0.0s` on work that
    took 40ms reads as a rounding artefact and tells the reader nothing, where
    `40ms` says plainly that the step is free. Past a minute the seconds still
    matter (a 2m25s fetch and a 2m55s one feel different) but tenths do not.
    """
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}m{remainder:02d}s"


def using(text: str) -> None:
    """The environment banner a command opens with.

    It names the ground the run stands on rather than something kennis did,
    and since operations start at the margin too, that is carried by the dim
    `Using` lead alone rather than by position - every other line's first word
    is a past-tense verb in a severity colour.
    """
    if _quiet:
        return
    line = Text(f"Using {text}")
    _MESSAGE_HIGHLIGHTER.highlight(line)
    line.stylize("muted", 0, 5)
    console.print(line, soft_wrap=True)


def operation(
    verb: str,
    text: str = "",
    *,
    elapsed: float | None = None,
    style: str = "operation",
    stderr: bool = False,
) -> None:
    """One line of the report: what kennis did, to what, and how long it took.

    The verb starts at the margin and carries the colour; the rest stays
    plain, so a scan down the left edge reads as a list of operations in the
    order they happened. `elapsed`, when given, is appended as `in 1.4s` - the
    answer to "has this stopped, or is it just slow", which a reader can only
    learn by being told what a step normally costs.
    """
    if _quiet:
        return
    trailer = f" in {_format_elapsed(elapsed)}" if elapsed is not None else ""
    line = Text(f"{verb} {text}{trailer}".rstrip())
    _MESSAGE_HIGHLIGHTER.highlight(line)
    line.stylize(style, 0, len(verb))
    # `stderr` for a command whose stdout is a payload rather than a report:
    # `kennis read x > x.md` must write the document and not a report line
    # above it. The same split `note` makes, for the same reason.
    (error_console if stderr else console).print(line, soft_wrap=True)


# What each detail marker means, and so how it is coloured. `=` is unchanged
# and gets no colour at all - it is the absence of news.
_MARKER_ROLES = {"+": "added", "-": "removed", "~": "changed", "=": "unchanged"}


def detail(marker: str, text: str) -> None:
    """One item an operation touched: `+` added, `-` removed, `~` changed,
    `=` unchanged.

    **The marker carries the colour and the name stays dim.** A detail line is
    a list of things, and what a reader scans for is which kind each one is -
    that is one character, in the same column every time. Printing the names
    at full weight makes ten lines shout as loudly as the operation they
    belong to.

    soft_wrap because these are overwhelmingly paths and identifiers - one
    token each, which rich's word wrap would break in the middle.
    """
    if _quiet:
        return
    # Assembled rather than styled over a base: a `muted` base is `dim`, and
    # rich composes styles, so a green marker on top of it comes out dim green
    # - which is precisely the colour that was meant to stand out.
    role = _MARKER_ROLES.get(marker, "marker")
    line = Text.assemble(
        _DETAIL_INDENT,
        (marker, rich_style_name(role)),
        (f" {text}", "muted"),
    )
    console.print(line, soft_wrap=True)


# A corpus tree's own indent step. Two spaces per level on top of the content
# indent, so a group's contents sit under its name rather than under the
# collection heading.
_TREE_STEP = "  "

# What stands in an identifier column for a document whose frontmatter kennis
# could not read. The same width as a real identifier, so the names stay in
# one column and the gap is visibly a gap rather than a short name.
_NO_IDENTIFIER = "-" * 10


def tree_group(name: str, depth: int) -> None:
    """A directory in the corpus tree: a collection's group, or a docs project.

    Nothing addresses a group, so it carries no identifier - and that absence
    is what tells it apart from the documents under it, along with the
    trailing slash and the heading weight. `detail` is not used because its
    marker column means added, removed or changed, and every line of a tree
    is unchanged.
    """
    line = Text.assemble(
        _DETAIL_INDENT + _TREE_STEP * depth,
        (f"{name}/", rich_style_name("heading")),
    )
    console.print(line, soft_wrap=True)


def tree_document(identifier: str | None, name: str, depth: int) -> None:
    """A document in the corpus tree, with the handle every command takes.

    The identifier leads so that the identifiers line up in one column and
    can be read down and copied; the name follows, dim, because a reader
    scanning for something already knows what they are looking for.
    """
    line = Text.assemble(
        _DETAIL_INDENT + _TREE_STEP * depth,
        (identifier or _NO_IDENTIFIER, rich_style_name("identifier")),
        (f"  {name}", "muted"),
    )
    console.print(line, soft_wrap=True)


def details(
    marker: str, items: Sequence[str], *, limit: int | None = DETAIL_LIMIT
) -> None:
    """Every item an operation touched, capped so a large batch stays readable.

    `limit=None` prints all of them, which is what `--verbose` passes. The
    count is already on the operation line above, so the elision loses nothing
    but names.
    """
    shown = list(items) if limit is None else list(items)[:limit]
    for item in shown:
        detail(marker, item)
    remaining = len(items) - len(shown)
    if remaining:
        muted(f"{_DETAIL_INDENT}  ... and {remaining} more")


# ---------------------------------------------------------------------------
# Diagnostics: deliberately outside the column
# ---------------------------------------------------------------------------


def _diagnostic(
    label: str, style: str, text: str, *, stderr: bool = False, indent: str = ""
) -> None:
    line = Text(f"{indent}{label}: {text}")
    _MESSAGE_HIGHLIGHTER.highlight(line)
    line.stylize(style, len(indent), len(indent) + len(label) + 1)
    (error_console if stderr else console).print(line, soft_wrap=True)


def note(text: str, *, stderr: bool = False) -> None:
    """`warning: ...` - something is off and the command carries on.

    Column zero, beside the operations: a problem has to break the left edge
    to be seen, and must not scan as one more step that went fine. Lowercase,
    as uv and cargo print it.

    `stderr` is for a command whose stdout is a *payload* rather than a
    report - `config show` emits valid TOML, so a warning printed among it
    would end up in whatever file the user redirected it to. Everywhere else
    stdout is the report and a diagnostic belongs in it.
    """
    if _quiet:
        return
    _diagnostic("warning", "warning", text, stderr=stderr)


def guidance(text: str) -> None:
    """How to answer what comes next - not a diagnostic.

    Separate from `note` because `note` prints `warning:`, and telling
    someone how a prompt behaves is not something going wrong. Separate from
    `muted`, which is a style primitive with no `--quiet` guard.
    """
    if _quiet:
        return
    muted(text)


def failure(text: str) -> None:
    """`error: ...` - printed even under --quiet, which suppresses reports
    rather than problems."""
    _diagnostic("error", "error", text)


# Advice is indented under the operation it follows. `warning:` and `error:`
# keep the margin, because a problem has to break the left edge to be seen; a
# hint is subordinate to the line above it - the next thing to do about what
# just happened - and indenting says so.
_HINT_INDENT = " " * _CONTENT_INDENT


def hint(text: str, *, stderr: bool = False) -> None:
    """`hint: ...` - the command to run next.

    `stderr` as for `note`: it follows the warning it belongs to.
    """
    if _quiet:
        return
    _diagnostic(
        "hint", rich_style_name("hint"), text, stderr=stderr, indent=_HINT_INDENT
    )


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

# An ASCII spinner, because the rest of kennis's output is ASCII and a
# runtime-only glyph would be the one place that is not. rich ships several
# unicode ones; this is the classic four-frame line.
_SPINNER_FRAMES = ("-", "\\", "|", "/")
_SPINNER_SECONDS_PER_FRAME = 0.12

# The bar hangs under its label, not beside it. A description and a bar on one
# row is as wide as both, so on an ordinary terminal the counts and times get
# squeezed off the end - and the label is the part that says what is being
# waited for. Two lines cost nothing: the whole block is transient and is
# replaced by the operation line that summarises it.
_PROGRESS_INDENT = " " * _CONTENT_INDENT


class _StackedProgress(Progress):
    """rich's Progress with the task description on a line of its own.

    The description column is deliberately absent from the columns passed in;
    it is rendered here instead, behind a spinner, with the bar row beneath.
    """

    def get_renderables(self) -> Iterable[RenderableType]:
        frame = _SPINNER_FRAMES[
            int(time.monotonic() / _SPINNER_SECONDS_PER_FRAME) % len(_SPINNER_FRAMES)
        ]
        for task in self.tasks:
            label = Text(f"{frame} ", style=rich_style_name("spinner"))
            label.append(task.description, style="heading.line")
            yield label
        # Padding rather than table.padding, which is per-cell and so would
        # indent every column instead of the row.
        yield Padding(
            self.make_tasks_table(self.tasks), (0, 0, 0, len(_PROGRESS_INDENT))
        )


@contextlib.contextmanager
def progress_bar(description: str, total: int | None) -> Iterator[ProgressUpdate]:
    """A live bar for one long step, yielding the callable that advances it.

    Called with no arguments it advances by one; called with `(done, total)`
    it sets both, which is what a step whose total is not known up front needs
    - chunking cannot say how many chunks there are until it has finished, and
    renders as an indeterminate spinner until it can.

    **On stderr, and transient.** The bar is progress, not output: it is
    erased when the step ends, leaving the `operation` line that summarises
    it, and it never lands in a redirected file. `kennis sync > log.txt`
    therefore gives clean report lines with no bar residue - which is not true
    of a bar written to stdout, where every redraw is another set of escape
    codes in the file.

    Yields a no-op when `progress_wanted()` is False, so a caller never has to
    branch on it.
    """
    if not progress_wanted():

        def undrawn(completed: int | None = None, total: int | None = None) -> None:
            return None

        yield undrawn
        return

    with _StackedProgress(
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=_progress_console,
        transient=True,
    ) as progress:
        task_id = progress.add_task(description, total=total)

        def update(completed: int | None = None, total: int | None = None) -> None:
            if completed is None and total is None:
                progress.advance(task_id)
                return
            progress.update(task_id, completed=completed, total=total)

        yield update


# ---------------------------------------------------------------------------
# Verbosity
# ---------------------------------------------------------------------------

# --quiet suppresses the report but never a failure; --no-progress suppresses
# live bars but never the summary line that follows one. Module-level because
# they are set once from the command line's own options and read by every
# primitive.
_quiet = False
_progress_wanted = True


def set_verbosity(*, quiet: bool = False, progress: bool = True) -> None:
    """Apply `--quiet` / `--no-progress` for the rest of the process."""
    global _quiet, _progress_wanted
    _quiet = quiet
    _progress_wanted = progress


def progress_wanted() -> bool:
    """Whether a live bar should be drawn. False under --no-progress, under
    --quiet, and whenever stdout is not a terminal - a bar redrawing itself
    into a redirected file is noise nobody asked for."""
    return _progress_wanted and not _quiet and console.is_terminal


# Set only by `following_steps(False)`. A composite command runs the steps its
# parts would otherwise be advising, and a sub-command has no way to know it
# is not the outermost caller.
_next_steps_wanted = True


@contextlib.contextmanager
def following_steps(wanted: bool) -> Iterator[None]:
    """Suppress the next-step advice inside the block when `wanted` is False.

    `corpus sync` closes by telling you to run `corpus index`. Inside
    `kennis setup` that is advice to do what the next phase does anyway, and
    twice over for two collections. Suppressing it here keeps the decision
    with the command that knows it is a composite, rather than teaching four
    sub-commands to ask whether anyone is above them.
    """
    global _next_steps_wanted
    previous = _next_steps_wanted
    _next_steps_wanted = wanted
    try:
        yield
    finally:
        _next_steps_wanted = previous


def next_step(
    command: str, *, before: str = "", note: str = "", stderr: bool = False
) -> None:
    """The "what to run now" line a command closes with, as a `hint:`.

    One helper so the phrasing and the command's styling stay identical
    everywhere. It reads as a diagnostic rather than an operation because that
    is what it is - advice about a command that has not run yet, which must
    not scan as a step that already did.
    """
    if not _next_steps_wanted or _quiet:
        return
    preamble = f"{before} " if before else ""
    trailer = f" {note}" if note else ""
    hint(f"{preamble}run `{command}`{trailer}".strip(), stderr=stderr)


# ---------------------------------------------------------------------------
# Fragments inside a message
# ---------------------------------------------------------------------------

# These return text rather than printing it: a command or a value is almost
# always part of a sentence a caller is composing, and the sentence belongs to
# the caller. What belongs here is the *delimiter*, because the delimiter is
# what the highlighter reads to decide the style - so a call site that picks
# its own is choosing a colour without knowing it.


def command(invocation: str) -> str:
    """An invocation the reader is being told to run.

    Backticks, which is what uv, cargo and click all use and what survives
    being copied out of a terminal. Use it for any command - kennis's own or
    not - and never for a value.
    """
    return f"`{invocation}`"


def value(text: object) -> str:
    """Something the user typed or kennis read back: a config key, an id, a
    citekey, a filename. Quoted, so it never reads as a command."""
    return f"'{text}'"


def path(location: object) -> None:
    """A bare filesystem path on its own line.

    soft_wrap because a path is one token: rich's word wrap would otherwise
    break a long one mid-token into something that cannot be copied out.
    """
    console.print(Text(str(location), style=rich_style_name("path")), soft_wrap=True)


def plain(text: str) -> None:
    """Text that must reach stdout exactly as given, with no styling at all -
    a config value being read by a script, for instance."""
    console.print(Text(text), soft_wrap=True)


# A hit's own contents - its handle, its relevance and its snippet - sit one
# step in from the hit line, which is itself one step in from the `Found`
# operation. Three levels rather than two because a hit is a thing with parts,
# and at two the snippet's first line is indistinguishable from the next hit.
_HIT_INDENT = " " * _CONTENT_INDENT
_HIT_CONTENT_INDENT = " " * (_CONTENT_INDENT * 3)


def hit(headline: str) -> None:
    """One ranked hit's own line: `[1] [literature] Title - Section`."""
    line = Text(f"{_HIT_INDENT}{headline}")
    _HIT_HIGHLIGHTER.highlight(line)
    console.print(line, soft_wrap=True)


def hit_detail(text: str) -> None:
    """A line belonging to the hit above it: its handle, or its relevance."""
    line = Text(f"{_HIT_CONTENT_INDENT}{text}")
    _HIT_HIGHLIGHTER.highlight(line)
    console.print(line, soft_wrap=True)


def body(text: str, *, indent: str = "") -> None:
    """Markdown as the corpus holds it, styled but never rewritten.

    With an `indent` the text is a snippet - one paragraph - and is wrapped
    to the terminal with every line carried in, so a continuation lines up
    with the line it continues instead of running back to the margin.

    Without one it is a whole document, and it is printed exactly as stored:
    re-wrapping would put line breaks inside fenced code and inside tables,
    and this is the output a person pipes into a file.

    Wrapped here rather than with `rich.padding.Padding`, which renders a
    block and pads every line out to the console width - trailing spaces
    that are invisible on screen and land in the file on a redirect.
    """
    if indent:
        width = max(40, console.width - len(indent))
        text = textwrap.fill(
            text,
            width=width,
            initial_indent=indent,
            subsequent_indent=indent,
            # Neither break is right over a corpus: `sub-recipe` split across
            # two lines reads as two words, and a long identifier or URL cut
            # in the middle looks corrupted rather than wrapped. A line that
            # overruns is the lesser fault.
            break_on_hyphens=False,
            break_long_words=False,
        )
        # A snippet is one collapsed paragraph, so there are no blocks in it
        # to find and nothing for the block renderer to do. `textwrap.fill`
        # returns no trailing newline, so the line ending is supplied here.
        _prose(text + "\n")
        return
    for block in split_blocks(text):
        _block(block)


def _block(block: Block) -> None:
    """One run of a markdown body, styled for what it is.

    Every branch prints with `end=""` and passes the block's text unaltered,
    because the text already carries the newlines the document had. `read` is
    a payload: what comes out must be what is stored, byte for byte, and a
    renderer that adds a newline turns a document into a different document.
    A test asserts the whole round trip.
    """
    if block.kind == "prose":
        _prose(block.text)
    elif block.kind == "fence":
        console.print(
            Text(block.text, style=rich_style_name("md_fence")),
            end="",
            soft_wrap=True,
        )
    else:
        language = block.language or detected_language(block.text)
        # Named no language and parsed as nothing, so no lexer. Coloured as
        # one thing, which says "this is not prose" without claiming to know
        # what it is - the claim guessing made and got wrong every time.
        # Concern #214.
        rendered = _lexed(block.text, language) if language else None
        if rendered is None:
            rendered = Text(block.text, style=rich_style_name("code_block"))
        console.print(rendered, end="", soft_wrap=True)


@lru_cache(maxsize=1)
def _syntax_theme() -> SyntaxTheme:
    return syntax_theme()


@lru_cache(maxsize=16)
def _lexer_for(language: str) -> Lexer | None:
    """The pygments lexer for `language`, or None if there is no such thing.

    A fence's info string is whatever its author typed, so an unknown name is
    ordinary input rather than an error.

    `ensurenl=False` and `stripnl=False` are what make the token stream
    concatenate back into the text it came from. With the defaults pygments
    appends a newline to a block that had none and strips leading ones, and
    `read` would then emit a document the corpus does not hold.
    """
    try:
        return get_lexer_by_name(language, stripnl=False, ensurenl=False)
    except ClassNotFound:
        return None


def _lexed(text: str, language: str) -> Text | None:
    """`text` styled token by token, or None when `language` is not a lexer.

    Built from the token stream rather than with `rich.syntax.Syntax`, which
    pads every line out to the console width - trailing spaces that are
    invisible on screen and land in the file when `read` is redirected, the
    same fault that ruled out `rich.padding.Padding` for snippets.
    """
    lexer = _lexer_for(language)
    if lexer is None:
        return None
    theme = _syntax_theme()
    rendered = Text()
    for token_type, value in lexer.get_tokens(text):
        rendered.append(value, theme.get_style_for_token(token_type))
    return rendered


def _prose(text: str) -> None:
    """Prose printed verbatim, with `end=""` for the same reason as code."""
    rendered = Text(text)
    _BODY_HIGHLIGHTER.highlight(rendered)
    console.print(rendered, end="", soft_wrap=True)


def toml(text: str) -> None:
    """A whole TOML document, on stdout, styled so it can be read.

    Styling survives only to a terminal: rich drops colour when stdout is
    redirected, so `kennis config show > config.toml` still writes a file
    with no escape codes in it.
    """
    rendered = Text(text)
    _TOML_HIGHLIGHTER.highlight(rendered)
    console.print(rendered, soft_wrap=True)


# ---------------------------------------------------------------------------
# Errors that abort the command
# ---------------------------------------------------------------------------


class PlainMessage(click.ClickException):
    """Base for every abort whose message kennis wrote itself.

    It exists so the help formatter has one type to check. These messages
    routinely end by naming the command that fixes the problem, and a bordered
    panel word-wraps that across a border into something the reader cannot
    copy - so they render through their own `show` instead. A new abort type
    that forgot to be listed there would silently get the panel back;
    subclassing this cannot.
    """


class Cancelled(PlainMessage):
    """The user stopped the command. Not a failure, and not a success.

    Its own type, because a composite has to be able to tell cancellation
    apart from the failures it deliberately carries on past: a command that
    warns and continues when one phase fails would otherwise treat a Ctrl-C as
    exactly such a failure, run every later phase anyway, and exit 0.

    Exit code 130 is the shell's convention for a process killed by SIGINT
    (128 + 2), which is what a caller checking `$?` in a loop expects.
    """

    exit_code = 130

    def show(self, file: IO[Any] | None = None) -> None:
        # Not `Error:` - nothing went wrong, and calling it an error sends the
        # reader looking for a cause.
        line = Text()
        line.append("Cancelled: ", style="warning")
        message = Text(self.format_message())
        _MESSAGE_HIGHLIGHTER.highlight(message)
        line.append_text(message)
        error_console.print(line, soft_wrap=True)


class CliError(PlainMessage):
    """A ClickException that reports through the themed stderr console.

    click's own `show` writes an unstyled `Error: ...`; this keeps that
    wording and stream and only colours it, so scripts parsing stderr see what
    they always did.

    soft_wrap for the same reason: click emits the message as one unwrapped
    line, and these messages routinely name the command that fixes the problem
    - rich's word wrap would split that across a line break and make it
    uncopyable.
    """

    def show(self, file: IO[Any] | None = None) -> None:
        # Text(style=...) would make `error` the base style of everything
        # appended after it, not just the prefix.
        line = Text()
        line.append("Error: ", style="error")
        message = Text(self.format_message())
        _MESSAGE_HIGHLIGHTER.highlight(message)
        line.append_text(message)
        error_console.print(line, soft_wrap=True)
