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
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import IO, Any

import click
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
from rich.text import Text

from kennis.cli.theme import STYLE_PREFIX, rich_style_name, rich_theme

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
    verb: str, text: str = "", *, elapsed: float | None = None, style: str = "operation"
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
    console.print(line, soft_wrap=True)


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
