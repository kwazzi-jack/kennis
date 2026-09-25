"""The semantic roles, and the rich adapter that is the first consumer of them.

The eight-colour restriction is the substance of these tests: a role resolves
against whatever palette the user's terminal is themed with, which a
256-colour index or a hex value would not.
"""

from __future__ import annotations

import pytest
from rich.style import Style

from kennis.cli.theme import rich_style_name, rich_theme
from kennis.render.theme import ANSI_COLOURS, ROLES, SENTENCE_ROLES, Role


def test_the_eight_standard_colours_are_the_palette():
    assert ANSI_COLOURS == (
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


@pytest.mark.parametrize("name", sorted(ROLES), ids=str)
def test_every_role_uses_a_colour_the_terminal_owns(name: str):
    colour = ROLES[name].colour

    assert colour is None or colour in ANSI_COLOURS


@pytest.mark.parametrize("name", sorted(ROLES), ids=str)
def test_every_role_resolves_to_a_style_rich_accepts(name: str):
    """A typo in the table would otherwise surface as a runtime error the
    first time the role is printed."""
    Style.parse(ROLES[name].rich_style())


def test_a_colourless_role_is_still_a_style():
    assert Role().rich_style() == "none"


def test_attributes_precede_the_colour():
    assert Role(colour="green", bold=True).rich_style() == "bold green"
    assert Role(dim=True).rich_style() == "dim"
    assert Role(colour="cyan", underline=True).rich_style() == "underline cyan"


def test_the_quiet_variant_keeps_the_colour_and_drops_the_bold():
    """A lead word in bold colour is a signal; a whole sentence in it shouts."""
    assert Role(colour="green", bold=True).quiet() == Role(colour="green")


@pytest.mark.parametrize("name", sorted(SENTENCE_ROLES), ids=str)
def test_a_sentence_role_is_named_without_the_prefix(name: str):
    """`_line` builds `<role>.line` from the role name, so the severities are
    the one family whose rich style name is the bare role."""
    assert rich_style_name(name) == name


def test_every_other_role_is_namespaced():
    """The prefix is what `MessageHighlighter.base_style` prepends to a
    capture group, and it keeps kennis's names clear of rich's own."""
    assert rich_style_name("added") == "kennis.added"


def test_the_rich_theme_covers_every_role():
    theme = rich_theme()

    missing = [name for name in ROLES if rich_style_name(name) not in theme.styles]

    assert not missing


def test_the_rich_theme_carries_a_quiet_variant_for_each_sentence_role():
    theme = rich_theme()

    for name in SENTENCE_ROLES:
        assert f"{name}.line" in theme.styles


@pytest.mark.parametrize("name", sorted(SENTENCE_ROLES), ids=str)
def test_a_quiet_variant_drops_the_bold_unless_that_is_all_there_is(name: str):
    theme = rich_theme()
    quietened = theme.styles[f"{name}.line"]

    if ROLES[name].rich_style() == "bold":
        assert quietened.bold is True
    else:
        assert quietened.bold is not True


@pytest.mark.parametrize("name", sorted(SENTENCE_ROLES), ids=str)
def test_a_quietened_sentence_role_is_still_visible(name: str):
    """`quiet()` removes the bold, so a role defined *only* as bold is
    quietened into nothing and reaches the terminal unstyled.

    This is how `heading` printed with no style at all for five milestones.
    Checking that the bold was dropped passed either way; checking that
    something survives is the property that was meant. Concern #216.
    """
    assert ROLES[name].quiet().rich_style() != "none"


def test_the_rich_theme_restates_the_progress_styles():
    """rich's defaults are a true-colour gradient, which is the one place the
    output would stop resolving against the user's palette."""
    theme = rich_theme()

    for name in ("bar.back", "bar.complete", "bar.finished", "bar.pulse"):
        assert name in theme.styles
    assert theme.styles["bar.complete"] == Style.parse("cyan")
    assert theme.styles["bar.finished"] == Style.parse("green")


def test_the_severities_keep_their_colours():
    assert ROLES["operation"] == Role(colour="green", bold=True)
    assert ROLES["warning"] == Role(colour="yellow", bold=True)
    assert ROLES["error"] == Role(colour="red", bold=True)
    assert ROLES["muted"] == Role(dim=True)
    assert ROLES["heading"] == Role(bold=True)


def test_the_detail_markers_keep_their_colours():
    assert ROLES["added"] == Role(colour="green")
    assert ROLES["removed"] == Role(colour="red")
    assert ROLES["changed"] == Role(colour="yellow")
    assert ROLES["unchanged"] == Role()


def test_a_hint_is_not_muted():
    """A hint is the one line a reader is meant to act on, and dim made it
    recede into the report it follows."""
    assert ROLES["hint"] != ROLES["muted"]
    assert ROLES["hint"].dim is False
