"""Colour, declared once as semantic roles and adapted per interface.

A role - `added`, `operation`, `warning`, `hint` - says what a piece of text
*is*. It names no library, and an architecture test enforces that - the
MCP server needs these roles too and must not import a command-line package
to reach them. `kennis.cli.theme` turns the table into a
`rich.theme.Theme` for printed output; a `prompt_toolkit` adapter for prompts
is the second consumer and arrives with prompting. Declaring the colours in
each interface instead is how two interfaces come to disagree about what a
warning looks like.

**Only the eight standard ANSI colours are named**, never a 256-colour index
or a hex value: they resolve against whatever palette the user's terminal is
themed with, so the output stays legible on a light background as well as a
dark one. `bright_black` is the one extension, used for a progress bar's
unfilled track, which has to be visible without competing with the text.

The restriction is the reason the rich adapter restates rich's own progress
styles. Its defaults are a true-colour magenta gradient and a green count -
the one place the output would stop resolving against the user's palette.

Roles carrying a colour decision for output kennis does not yet produce are in
the table with their family marked. The decision is data and costs nothing to
carry; the renderer that emits it arrives with the milestone that has
something to render.

Two roles the design names are deliberately absent: `field` and `invalid`
belong to prompting, which does not exist yet, and no colour has been chosen
for either. They arrive with the prompt_toolkit adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final, Literal

type AnsiColour = Literal[
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
    "bright_black",
]

ANSI_COLOURS: Final[tuple[AnsiColour, ...]] = (
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
    "bright_black",
)


@dataclass(frozen=True, slots=True)
class Role:
    """One semantic role: a colour from the eight, and how it is worn.

    A role with no colour and no attribute is still a role - `unchanged` is
    deliberately uncoloured, because it is the absence of news.
    """

    colour: AnsiColour | None = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False

    def rich_style(self) -> str:
        """The role as a rich style string: attributes, then the colour."""
        parts = [
            name
            for name, wanted in (
                ("bold", self.bold),
                ("dim", self.dim),
                ("italic", self.italic),
                ("underline", self.underline),
            )
            if wanted
        ]
        if self.colour is not None:
            parts.append(self.colour)
        return " ".join(parts) if parts else "none"

    def quiet(self) -> Role:
        """The same role without the bold.

        A short lead word ("Indexed", "warning:") carries the bold variant and
        the rest of the sentence stays plain. Where a whole sentence takes the
        role instead, bold would shout, so it takes this one.
        """
        return replace(self, bold=False)


# The severities. These five are the roles a whole sentence can be given, so
# each also gets a `<role>.line` style derived by `Role.quiet`.
SENTENCE_ROLES: Final[frozenset[str]] = frozenset(
    {"operation", "warning", "error", "muted", "heading"}
)

# What `MessageHighlighter.base_style` prepends to a capture group, and what
# keeps kennis's role names clear of rich's own (`bar.complete` and friends).
STYLE_PREFIX: Final = "kennis."

ROLES: Final[dict[str, Role]] = {
    # Severities. `operation` is what a past-tense verb at the margin wears;
    # it is the design's name for the role, and both `operation()` and
    # `success()` in `display` render with it.
    "operation": Role(colour="green", bold=True),
    "warning": Role(colour="yellow", bold=True),
    "error": Role(colour="red", bold=True),
    "muted": Role(dim=True),
    "heading": Role(bold=True),
    # Detail markers. The marker carries the colour and the name beside it
    # stays dim: a detail line is a list of things, and what a reader scans
    # for is which kind each one is - one character, in the same column every
    # time. `unchanged` gets no colour at all.
    "added": Role(colour="green"),
    "removed": Role(colour="red"),
    "changed": Role(colour="yellow"),
    "unchanged": Role(),
    # The fallback for a marker character with no meaning assigned.
    "marker": Role(bold=True),
    # Fragments the message highlighter picks out of an ordinary line.
    "command": Role(colour="cyan", bold=True),
    "option": Role(colour="cyan"),
    "quoted": Role(bold=True),
    "path": Role(colour="cyan"),
    "key": Role(dim=True),
    "value": Role(colour="magenta"),
    # Not `muted`: a hint is the one line a reader is meant to act on, and dim
    # made it recede into the report it follows.
    "hint": Role(colour="cyan"),
    "spinner": Role(colour="cyan"),
    # Progress. Named as roles so the colours stay in this table, and mapped
    # onto rich's own style names by `_RICH_PROGRESS_STYLES`, which lives
    # in `kennis.cli.theme` with the rest of the rich adapter.
    "progress": Role(colour="cyan"),
    "progress_done": Role(colour="green"),
    "progress_track": Role(colour="bright_black"),
    "progress_time": Role(dim=True),
    # Ranked search hits. No renderer yet; the search milestone brings one.
    "count": Role(bold=True),
    "query": Role(colour="yellow"),
    "collection": Role(colour="cyan", bold=True),
    "note": Role(colour="yellow"),
    "rank": Role(colour="cyan", bold=True),
    "title": Role(bold=True),
    "section": Role(italic=True),
    "label": Role(dim=True),
    "identifier": Role(colour="magenta", bold=True),
    "score_label": Role(dim=True),
    "score": Role(colour="cyan", dim=True),
    "chars": Role(dim=True),
    # Markdown bodies, shared by hit snippets and document spans. No renderer
    # yet. The markers are styled where they stand and never consumed, because
    # the terminal shows the same characters the corpus holds and an agent
    # would read.
    "md_heading": Role(colour="yellow", bold=True),
    "md_fence": Role(dim=True),
    "md_code": Role(colour="cyan"),
    "md_strong": Role(bold=True),
    "md_emphasis": Role(italic=True),
    "md_link": Role(colour="cyan"),
    "md_url": Role(colour="cyan", underline=True),
    "citation": Role(colour="magenta"),
    # Code inside a fence. `code_block` is the whole of a block that named no
    # language - it says "this is not prose" without claiming to know what it
    # is, which guessing did claim and got wrong 262 times out of 262 (#214).
    # The rest are pygments token classes, named as roles here so that the
    # eight-colour rule holds inside a code block as it does everywhere else:
    # every pygments style ships true colour or a 256-colour index, and either
    # stops resolving against the palette the terminal is themed with.
    "code_block": Role(colour="cyan"),
    "code_keyword": Role(colour="magenta"),
    "code_string": Role(colour="yellow"),
    "code_number": Role(colour="cyan"),
    "code_comment": Role(dim=True),
    "code_name": Role(colour="green"),
    "code_operator": Role(colour="white"),
    # `config show`'s TOML, which rich has no highlighter for. No renderer yet.
    "toml_comment": Role(dim=True),
    "toml_section": Role(colour="cyan", bold=True),
    "toml_key": Role(colour="green"),
    "toml_string": Role(colour="yellow"),
    "toml_number": Role(colour="cyan"),
    "toml_bool": Role(colour="magenta"),
}
