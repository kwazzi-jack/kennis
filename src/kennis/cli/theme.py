"""The role table, adapted for rich.

`kennis.render.theme` holds what a colour *means*, naming no library. This is
the half that knows about rich, and it lives under `cli/` for the reason the
separation exists: the MCP server needs the roles and must not import a
command-line package to get them.
"""

from __future__ import annotations

from typing import Final

from rich.style import Style
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
