"""The palette, and the parts of the layout a test can hold.

A stylesheet is not a value a test can compare against an expected
one, and "it looks right" is not a standard. Four things here are
numeric or structural, and they are the ones that were actually
wrong:

- **Contrast is measured.** `warning` shipped as `#FFFF00` on white,
  a ratio of about 1.07:1, and `code_operator` shipped as `white` on
  white. Neither was a matter of taste. Every role's colour is
  checked against the ground it is shown on, in both modes.
- **The hues stay tellable apart.** Roles lean on hue difference -
  cyan is a command, magenta an identifier, yellow a warning - so
  darkening them all far enough to pass on white could quietly make
  two of them the same colour.
- **Every class the templates use has a rule.** 17 of 22 had none,
  which is how an interface comes to be browser defaults wearing
  semantic class names.
- **No colour is declared outside the adapter.** The registry decides
  which role wears which name and the adapter decides what each name
  looks like here; a literal anywhere else is a third place.
"""

from __future__ import annotations

import math
import re
from fnmatch import fnmatch
from pathlib import Path

import pytest

from kennis.gui.theme import (
    CSS_COLOURS,
    CSS_COLOURS_DARK,
    DARK_GROUND,
    LIGHT_GROUND,
    css_variables,
    stylesheet,
)
from kennis.render.theme import ANSI_COLOURS, ROLES, Role

TEMPLATES = Path(__file__).resolve().parents[1] / "src/kennis/gui/templates"

# WCAG 2.1 AA for body text. The roles are worn by text, including
# small text, so this is the applicable threshold rather than 3:1.
MINIMUM_CONTRAST = 4.5

# Two colours are "the same" to a reader well below this; CIE76 dE of
# 20 is a comfortable margin, and the point is to catch a collapse
# rather than to grade the palette.
MINIMUM_DIFFERENCE = 20.0

HUES = ("red", "green", "yellow", "blue", "magenta", "cyan")


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    digits = colour.lstrip("#")
    red, green, blue = (int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _linear(red) + 0.7152 * _linear(green) + 0.0722 * _linear(blue)


def contrast(one: str, other: str) -> float:
    """The WCAG 2.1 contrast ratio between two colours."""
    first, second = luminance(one), luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _lab(colour: str) -> tuple[float, float, float]:
    digits = colour.lstrip("#")
    red, green, blue = (_linear(int(digits[i : i + 2], 16) / 255) for i in (0, 2, 4))
    x = 0.4124 * red + 0.3576 * green + 0.1805 * blue
    y = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    z = 0.0193 * red + 0.1192 * green + 0.9505 * blue
    white_point = (0.95047, 1.0, 1.08883)

    def transfer(value: float) -> float:
        return value ** (1 / 3) if value > 0.008856 else 7.787 * value + 16 / 116

    fx, fy, fz = (
        transfer(component / reference)
        for component, reference in zip((x, y, z), white_point, strict=True)
    )
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def difference(one: str, other: str) -> float:
    """CIE76 colour difference, which is enough to catch a collapse."""
    first, second = _lab(one), _lab(other)
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second, strict=True)))


# ---------------------------------------------------------------------------
# Contrast
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "colours", "ground"),
    [("light", CSS_COLOURS, LIGHT_GROUND), ("dark", CSS_COLOURS_DARK, DARK_GROUND)],
)
def test_every_colour_is_legible_on_its_ground(
    mode: str, colours: dict[str, str], ground: str
):
    """The defect this unit exists for, as a number.

    `#FFFF00` on white is 1.07:1. A reader with ordinary eyesight
    cannot read it, and no amount of liking yellow changes that."""
    failed = {
        name: round(contrast(value, ground), 2)
        for name, value in colours.items()
        if contrast(value, ground) < MINIMUM_CONTRAST
    }
    assert not failed, f"{mode}: below {MINIMUM_CONTRAST}:1 - {failed}"


@pytest.mark.parametrize(
    ("mode", "colours", "ground"),
    [("light", CSS_COLOURS, LIGHT_GROUND), ("dark", CSS_COLOURS_DARK, DARK_GROUND)],
)
def test_no_colour_is_the_ground_it_is_shown_on(
    mode: str, colours: dict[str, str], ground: str
):
    """`code_operator` was `white` on a white page.

    Covered by the contrast test as well, and asserted separately
    because the cause is worth naming: `white` in a terminal is the
    ordinary foreground, not the colour white, and transliterating
    the name rather than the meaning is what made it disappear."""
    assert colours["white"].lower() != "#ffffff"
    for name, value in colours.items():
        assert value.lower() != ground.lower(), f"{mode}: {name} is the ground"


# ---------------------------------------------------------------------------
# The hues stay apart
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "colours"), [("light", CSS_COLOURS), ("dark", CSS_COLOURS_DARK)]
)
def test_the_hues_are_distinguishable_from_one_another(
    mode: str, colours: dict[str, str]
):
    """Contrast against the ground is only half the problem.

    A role is read by its hue - cyan is a command, magenta an
    identifier, yellow a warning, red an error - so a palette that
    passes contrast by darkening everything towards the same muddy
    middle would satisfy the test above and lose the distinction the
    roles exist to make."""
    too_close = [
        (one, other, round(difference(colours[one], colours[other]), 1))
        for index, one in enumerate(HUES)
        for other in HUES[index + 1 :]
        if difference(colours[one], colours[other]) < MINIMUM_DIFFERENCE
    ]
    assert not too_close, f"{mode}: hues too close - {too_close}"


# ---------------------------------------------------------------------------
# One colour, one place
# ---------------------------------------------------------------------------


def test_every_ansi_name_has_a_value_in_both_modes():
    """The registry may name any of the nine. A name with no dark
    value would fall back to the light one on a dark ground, which is
    the failure this whole unit is about."""
    for name in ANSI_COLOURS:
        assert name in CSS_COLOURS, f"{name} has no light value"
        assert name in CSS_COLOURS_DARK, f"{name} has no dark value"


def test_no_colour_is_written_outside_the_two_maps():
    """The layout may not name a colour.

    `render/theme.py` decides which role wears which of the nine
    names; this adapter decides what each name looks like in a
    browser. A literal in the layout block is a third place, and the
    place a drift starts."""
    from kennis.gui.theme import layout_css

    literals = re.findall(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", layout_css())
    assert not literals, f"colour literals in the layout: {literals}"


def test_the_stylesheet_declares_both_grounds():
    css = stylesheet()
    assert LIGHT_GROUND.lower() in css.lower()
    assert DARK_GROUND.lower() in css.lower()
    assert "prefers-color-scheme: dark" in css


def test_the_dark_block_redefines_every_role():
    """A role defined only in the light block keeps its light colour
    on a dark ground, where it was never measured."""
    css = stylesheet()
    dark = css.partition("prefers-color-scheme: dark")[2]
    for name in ROLES:
        assert f"--role-{name}:" in dark, f"{name} is not redefined for dark"


def _expected(role: Role, table: dict[str, str]) -> str:
    """What a role's property must be, in the three cases.

    A coloured role gets its colour, which is the guard these tests
    were written for. A **dim** role with no colour gets the muted
    grey, because dim is a terminal attribute a browser has none of -
    the same translation that made `white` the foreground. A role
    with neither gets `currentColor`, not `inherit`: a custom
    property declared at `:root` has no parent, so `inherit` resolved
    to the guaranteed-invalid value and every muted element on every
    page rendered at full ink. Concern #351.
    """
    if role.colour:
        return table[role.colour]
    return table["bright_black"] if role.dim else "currentColor"


def test_the_light_variables_still_come_from_the_registry():
    """The original guard, kept: a role's colour is the one the
    registry gave it, looked up in the map, and never chosen here."""
    emitted = dict(re.findall(r"--role-([a-z_]+):\s*([^;]+);", css_variables()))
    for name, role in ROLES.items():
        assert emitted[name] == _expected(role, CSS_COLOURS), name


# ---------------------------------------------------------------------------
# Every class the templates use has a rule
# ---------------------------------------------------------------------------


def template_classes() -> set[str]:
    """Every class name the templates put on an element.

    Jinja expressions are skipped: `class="{{ outcome.role }}"` names
    a role at render time and the roles are covered by their own
    rules."""
    found: set[str] = set()
    for path in TEMPLATES.glob("*.html"):
        for match in re.finditer(r'class="([^"{}]*)"', path.read_text()):
            found.update(match.group(1).split())
    return found


def test_every_class_the_templates_use_is_styled():
    """17 of 22 had no rule at all, which is what "the interface has
    no design" meant concretely: semantic class names over browser
    defaults."""
    css = stylesheet()
    styled = set(re.findall(r"\.([A-Za-z0-9_-]+)", css))
    unstyled = sorted(name for name in template_classes() if name not in styled)
    assert not unstyled, f"no rule for: {unstyled}"


def test_the_reading_column_has_a_measure():
    """Body prose ran to about 110 characters at 1280px. Under 70 is
    the range long-form reading wants, and a serif tolerates the
    upper end of it."""
    css = stylesheet()
    assert "--measure" in css


def test_the_vendored_face_is_declared_and_present():
    """A `@font-face` naming a file that is not there falls back
    silently to a system serif, and the page looks nearly right."""
    css = stylesheet()
    assert "@font-face" in css
    vendored = TEMPLATES.parent / "static/vendor/fonts"
    for match in re.findall(r"url\(([^)]+)\)", css):
        name = match.strip("\"'").rsplit("/", 1)[-1]
        assert (vendored / name).is_file(), f"{name} is declared and not vendored"


def test_every_vendored_asset_is_accounted_for():
    """A licence that requires its text to travel with the binary is
    a condition on distributing kennis, not a formality. The notice
    names each asset, and this checks it was updated when one was
    added rather than left describing the previous set.

    **Matched against the names the notice lists, not as a substring
    of the notice.** The first version of this test asked whether the
    family name appeared anywhere in the text, and passed for an
    undocumented `Inter-Regular.woff2` because `Inter` is inside the
    word "interface" in the opening sentence. Short family names
    collide with ordinary prose, so the comparison has to be against
    the filenames the notice actually declares. Concern #337."""
    vendor = TEMPLATES.parent / "static/vendor"
    notice = (vendor / "NOTICE.txt").read_text(encoding="utf-8")
    # What the notice declares: bare filenames, and globs for a family
    # carried in many weights.
    declared = set(re.findall(r"[\w*.-]+\.(?:woff2|js|css)", notice))

    for path in sorted(vendor.rglob("*")):
        if path.is_dir() or path.name == "NOTICE.txt" or "LICENSE" in path.name:
            continue
        assert any(fnmatch(path.name, pattern) for pattern in declared), (
            f"{path.name} is vendored and not declared in NOTICE.txt"
        )


def test_the_notice_declares_nothing_that_is_not_there():
    """The other direction, and it is the one that rots quietly: an
    asset removed leaves its entry behind, and the next reader
    believes kennis still ships something it does not."""
    vendor = TEMPLATES.parent / "static/vendor"
    notice = (vendor / "NOTICE.txt").read_text(encoding="utf-8")
    present = [path.name for path in vendor.rglob("*") if path.is_file()]

    for pattern in set(re.findall(r"[\w*.-]+\.(?:woff2|js|css)", notice)):
        assert any(fnmatch(name, pattern) for name in present), (
            f"NOTICE.txt declares {pattern}, which is not vendored"
        )
