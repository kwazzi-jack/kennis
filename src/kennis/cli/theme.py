"""The role table, adapted for rich.

`kennis.render.theme` holds what a colour *means*, naming no library. This is
the half that knows about rich, and it lives under `cli/` for the reason the
separation exists: the MCP server needs the roles and must not import a
command-line package to get them.
"""

from __future__ import annotations

from typing import Final

from pygments.token import string_to_tokentype
from rich.style import Style
from rich.syntax import ANSISyntaxTheme, SyntaxTheme
from rich.theme import Theme

from kennis.render.theme import ROLES, SENTENCE_ROLES, STYLE_PREFIX

# rich's own progress style names, restated in the eight standard colours.
_RICH_PROGRESS_STYLES: Final[dict[str, str]] = {
    "bar.back": "progress_track",
    "bar.complete": "progress",
    "bar.pulse": "progress",
    "bar.finished": "progress_done",
    "progress.download": "progress_time",
    "progress.elapsed": "progress_time",
    "progress.remaining": "progress_time",
}


def rich_style_name(role: str) -> str:
    """The name a role is registered under in the rich theme.

    A severity keeps its bare name, because `display._line` builds the quiet
    variant as `<role>.line` and because those five are the roles a call site
    names directly. Everything else is namespaced.
    """
    return role if role in SENTENCE_ROLES else f"{STYLE_PREFIX}{role}"


# Which role each pygments token class wears. Deliberately short: a full
# pygments style names a hundred token types, and the eight colours cannot
# carry a hundred distinctions - so the map covers the classes that separate
# code from prose at a glance and lets everything else inherit.
_TOKEN_ROLES: Final[dict[str, str]] = {
    "Keyword": "code_keyword",
    "Name.Builtin": "code_keyword",
    "Name.Tag": "code_name",
    "Name.Function": "code_name",
    "Name.Class": "code_name",
    "Name.Attribute": "code_name",
    "Literal.String": "code_string",
    "Literal.Number": "code_number",
    "Comment": "code_comment",
    "Operator": "code_operator",
    "Punctuation": "code_operator",
}


def syntax_theme() -> SyntaxTheme:
    """The role table as a theme `rich.syntax.Syntax` can highlight with.

    An `ANSISyntaxTheme` rather than one of pygments' own. Every pygments
    style is written in true colour or 256-colour indices, which is exactly
    what `render.theme` refuses: those do not resolve against the palette the
    user's terminal is themed with, so a code block would be the one place
    kennis's output stopped being legible on a light background.

    Token classes not named here inherit, which is why the map is short -
    eight colours cannot carry the hundred distinctions a pygments style
    draws, and pretending otherwise would give six of them the same colour.
    """
    # Annotated as rich spells it. pygments' `_TokenType` subclasses `tuple`
    # and rich types its map as `dict[tuple[str, ...], Style]`; a dict is
    # invariant in its key, so the widening has to be stated rather than
    # inferred.
    styles: dict[tuple[str, ...], Style] = {
        string_to_tokentype(token): Style.parse(ROLES[role].rich_style())
        for token, role in _TOKEN_ROLES.items()
    }
    return ANSISyntaxTheme(styles)


def rich_theme() -> Theme:
    """The role table as a `rich.theme.Theme`.

    Built rather than written out, so a colour appears once. The `.line`
    variants and rich's progress styles are both derived from roles here, not
    declared beside them.
    """
    styles: dict[str, Style] = {}
    for role, definition in ROLES.items():
        styles[rich_style_name(role)] = Style.parse(definition.rich_style())
    for role in SENTENCE_ROLES:
        styles[f"{role}.line"] = Style.parse(ROLES[role].quiet().rich_style())
    for rich_name, role in _RICH_PROGRESS_STYLES.items():
        styles[rich_name] = Style.parse(ROLES[role].rich_style())
    return Theme(styles)
