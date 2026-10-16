"""The third adapter over `render/theme.py`'s semantic roles.

`rich` gets one, `prompt_toolkit` gets one, and this is the CSS one.
The design's reason for declaring roles separately from any library is
exactly this moment: three style systems, one palette, and no colour
defined twice.

**This adapter is a terminal palette, for a browser.** That framing
settles what it may and may not do. `render/theme.py` goes on
deciding which role wears which of the nine ANSI names - and that
file's restriction to those nine stands, because it exists so output
resolves against whatever palette the reader's terminal is themed
with. A browser has no such palette, so somebody has to supply one,
and supplying it here is the same act a terminal theme performs for
the terminal. No role's colour is chosen twice; a name's *appearance*
is chosen once, here, and its *assignment* once, there.

Two of the nine are not hues, and they are where the previous version
went wrong.

**`white` is the ordinary foreground, not `#FFFFFF`.** In a terminal
`white` is the default foreground; it looks white because the
background is black. Transliterating the name rather than the meaning
rendered `code_operator` as white text on a white page. `black` is
the same argument from the other end, which is why the light and dark
maps are not accidental inverses of one another.

**`bright_black` is the muted grey** that `muted`, `dim` and a
progress track wear, which CSS has no keyword for.

Every value here was measured rather than chosen by eye: each clears
4.5:1 against the ground it is shown on, and the six hues stay far
enough apart that a reader can still tell a command from an
identifier. `tests/test_gui_theme.py` holds both checks, and they are
the reason this file can be edited safely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal
from urllib.parse import quote

from pygments.token import STANDARD_TYPES, Token, _TokenType

from kennis.render.theme import ANSI_COLOURS, ROLES, AnsiColour, Role

# The page itself. Not white and not black: a hair off each, because
# a pure-white ground under a serif at reading size glares, and a
# pure-black one makes light text bloom.
LIGHT_GROUND: Final = "#FBFBF9"
DARK_GROUND: Final = "#16181C"

# What the nine names look like on a light ground. Measured: the
# worst is the muted grey, 5.43:1 on the page and 4.89:1 on the raised
# surface of the pane and the strip; the closest pair of hues is dE 36.8.
CSS_COLOURS: dict[AnsiColour, str] = {
    "black": "#1A1C1F",
    "white": "#1A1C1F",
    "red": "#A32B23",
    "green": "#2E6B3C",
    # Amber, not yellow. There is no yellow that is legible as text on
    # a light ground; the hue has to give way to the reading.
    "yellow": "#8A5A00",
    "blue": "#2B4CA0",
    "magenta": "#8A3382",
    "cyan": "#15626F",
    # Darkened from #6A7078, which was 4.82:1 on the page but 4.37:1 on
    # the pane and the strip, where muted text is commonest.
    "bright_black": "#626870",
}

# And on a dark one. Lighter and less saturated rather than the light
# values inverted: a hue that is legible dark-on-light is rarely the
# same hue that is legible light-on-dark.
CSS_COLOURS_DARK: dict[AnsiColour, str] = {
    "black": "#E9E9E4",
    "white": "#E9E9E4",
    "red": "#F08A82",
    "green": "#84C795",
    "yellow": "#D9A441",
    "blue": "#93B4F5",
    "magenta": "#D99BD1",
    "cyan": "#6CC0D2",
    "bright_black": "#949BA4",
}

# The registry may gain a colour. If it does, this adapter must gain a
# name for it in both maps, and finding out at import is better than
# finding out when a role renders as unstyled text on someone else's
# machine.
for _map, _mode in ((CSS_COLOURS, "light"), (CSS_COLOURS_DARK, "dark")):
    _missing = set(ANSI_COLOURS) - set(_map)
    if _missing:
        raise RuntimeError(
            f"no {_mode} CSS name for ANSI colour(s): {sorted(_missing)}"
        )


# How strongly a hit matched, as five colours from weakest to strongest.
#
# **The one place the window chooses colours by meaning rather than by
# role**, so it lives here beside the role adapter and not in
# `render/theme.py`, whose nine names are a terminal's (#416). Sequential
# scales, because an ordered strength is a sequential quantity, and not
# red against green, which is the pair the commonest colour-vision
# deficiency cannot separate.
#
# The four named maps are matplotlib's, sampled at five even steps over
# [0, 0.82] for a light ground and [0.3, 1] for a dark one, so the
# weakest step is never the end of the map that vanishes into the page.
# matplotlib's Greys flattens near white, so both grey scales are
# written by hand at even steps of CIE lightness: L* 12 to 84 light, 40
# to 96 dark. `tests/test_gui_results.py` holds every scale, in both
# themes, to monotone lightness and to adjacent steps that stay apart
# under a simulated deuteranopia - which is what makes this table safe
# to edit.
#
# Only the bar wears these. The level's word stays in ink (#421).
type StrengthScale = dict[str, tuple[str, str, str, str, str]]

STRENGTH_SCALES: Final[dict[str, StrengthScale]] = {
    "viridis": {
        "light": ("#440154", "#404588", "#297a8e", "#25ac82", "#86d549"),
        "dark": ("#355f8d", "#238a8d", "#2fb47c", "#8bd646", "#fde725"),
    },
    "cividis": {
        "light": ("#00224e", "#36466c", "#686a71", "#989277", "#cebc63"),
        "dark": ("#4f576c", "#777776", "#a19975", "#d0be62", "#fee838"),
    },
    "plasma": {
        "light": ("#0d0887", "#6c00a8", "#b32c8e", "#e4695e", "#fdae32"),
        "dark": ("#8f0da4", "#c5407e", "#ea7457", "#fdb130", "#f0f921"),
    },
    "magma": {
        "light": ("#000004", "#3d0f71", "#902a81", "#e34e65", "#fea973"),
        "dark": ("#641a80", "#ab337c", "#ed5a5f", "#feac76", "#fcfdbf"),
    },
    "greys": {
        "light": ("#1f1f1f", "#474747", "#727272", "#a0a0a0", "#d1d1d1"),
        "dark": ("#5e5e5e", "#818181", "#a6a6a6", "#cccccc", "#f3f3f3"),
    },
}

# What the bars wear until the reader chooses another (the `scale`
# preference, `gui/preferences.py`).
DEFAULT_STRENGTH_SCALE: Final = "viridis"

# Which collection something belongs to, as one accent per collection
# and theme (Brian, 2026-10-12): a hit's card, its group's heading, the
# pane's rows and a document's bar wear it. **Chosen by meaning**, like
# the strength scales, so here and not in the terminal's palette.
#
# From the Okabe-Ito set, which was drawn for colour-vision deficiency,
# then moved in lightness until docs and notes - a green and a purple,
# the pair a deuteranope merges - separated. `tests/
# test_gui_collection_colours.py` holds every one to 4.5:1 on the ground
# and on a card, every pair to dE 40 and to dE 20 as a deuteranope sees
# them, and each to dE 20 from the brand; the measurements are in
# `sketches/2026-10-12-collection-colours.md`. Each collection keeps its
# own icon as well, so the colour is never the only cue.
COLLECTION_COLOURS: Final[dict[str, dict[str, str]]] = {
    "literature": {"light": "#0B6BA8", "dark": "#5BB2E6"},
    "docs": {"light": "#0A7B4C", "dark": "#7FE0A8"},
    "notes": {"light": "#8A2F6B", "dark": "#DA6A9A"},
    "context": {"light": "#B14A12", "dark": "#EE8A57"},
}


_BRAND: Final = Path(__file__).parent / "static" / "brand"
_BRAND_MARKS: Final[dict[str, str]] = {
    scheme: quote((_BRAND / f"mark-{scheme}.svg").read_text(encoding="utf-8"), safe="")
    for scheme in ("light", "dark")
}


def css_variables(
    colours: dict[AnsiColour, str] | None = None,
    ground: str | None = None,
    scheme: Literal["light", "dark"] = "light",
) -> str:
    """One custom property per role, plus the ground and the rule.

    A role with no colour still gets a property, set to `inherit`:
    `unchanged` is deliberately uncoloured because it is the absence
    of news, and omitting it would make a stylesheet referring to it
    fall back to nothing rather than to the surrounding text.

    The ground and the hairline are emitted here rather than written
    into the layout because they are colours, and the layout may not
    name one.
    """
    table = CSS_COLOURS if colours is None else colours
    on = LIGHT_GROUND if ground is None else ground
    lines = [f"  --ground: {on};", f"  --ink: {table['white']};"]
    # What the browser draws for itself - a select's open list, a search
    # field's clear button, a number field's arrows, a file field's button,
    # a scrollbar corner - follows this, not the page's colours. Without
    # it each was drawn light in the dark theme (#476).
    lines.append(f"  color-scheme: {scheme};")
    # The hairline under the header and between table rows. The muted
    # grey at low opacity rather than a tenth colour, so the palette
    # stays nine.
    lines.append(f"  --rule: {table['bright_black']}44;")
    # The wash behind a marked query term. The `query` role's own
    # colour is a *foreground*, chosen to contrast with the ground,
    # so using it as a background would be dark on dark. The same
    # trick as the hairline: one of the nine at low alpha, composed
    # here because the layout may name no colour.
    lines.append(f"  --mark: {table['yellow']}33;")
    # The brand: the highlighter amber, which is already this palette's
    # `yellow` and already measured against the ground. Used for what
    # is chosen - the open place in the pane, a pressed control - so
    # the colour of a marked passage is also the colour of "here".
    lines.append(f"  --brand: {table['yellow']};")
    lines.append(f"  --brand-wash: {table['yellow']}1f;")
    # The surface of the pane and the strip: the muted grey at a low
    # alpha, so it works on both grounds without a tenth colour.
    lines.append(f"  --raised: {table['bright_black']}14;")
    # Every scale's steps for this theme, and the bars pointed at the
    # default. `scale_css` repoints them at the reader's choice; `var()`
    # resolves when the value is computed, after the theme block in force
    # has set these, so the scale and the theme are independent.
    for name, themes in STRENGTH_SCALES.items():
        for step, colour in enumerate(themes[scheme], start=1):
            lines.append(f"  --scale-{name}-{step}: {colour};")
    for step in range(1, 6):
        lines.append(
            f"  --strength-{step}: var(--scale-{DEFAULT_STRENGTH_SCALE}-{step});"
        )
    for name, accents in COLLECTION_COLOURS.items():
        lines.append(f"  --collection-{name}: {accents[scheme]};")
    # The open book in the bar, in this theme's drawing. Here because the
    # theme blocks are what choose light or dark; a data address because
    # the locked and stopped pages fetch nothing; percent-encoded rather
    # than base64, whose `;base64` would put a semicolon in the value.
    lines.append(f'  --brand-mark: url("data:image/svg+xml,{_BRAND_MARKS[scheme]}");')
    for name, role in ROLES.items():
        lines.append(f"  --role-{name}: {_value_for(role, table)};")
    return "\n".join(lines)


def _value_for(role: Role, table: dict[AnsiColour, str]) -> str:
    """What one role's custom property is set to here.

    Three cases, and two of them were one bug.

    **A dim role becomes the muted grey.** Dim is a terminal
    attribute and a browser has none, so the adapter has to
    translate rather than transliterate - the same argument that
    made `white` the ordinary foreground rather than `#FFFFFF`.
    Ten roles are dim without a colour, `muted` among them, and the
    interface used `var(--role-muted)` in nine places.

    **A role with no colour at all becomes `currentColor`, not
    `inherit`.** `inherit` on a custom property declared at `:root`
    has no parent to inherit from, so it resolves to the
    guaranteed-invalid value; `color: var(--role-muted)` then fell
    back to the inherited text colour and every muted element on
    every page rendered at full ink. Measured in the browser, not
    inferred. `currentColor` says what was meant and is valid.
    Concern #351.
    """
    if role.colour:
        return table[role.colour]
    if role.dim:
        return table["bright_black"]
    return "currentColor"


# Pygments' token hierarchy, mapped onto the seven code roles
# `render/theme.py` already names. **No colour is chosen here**: the
# registry decides which role wears which of the nine names and this
# file decides what a name looks like, so a second palette deciding
# the same thing for code would be the thing the split exists to
# prevent.
#
# Ordered by specificity only where two roots are on one branch -
# `String` and `Number` sit under `Literal`, and the walk finds them
# first because it climbs from the leaf.
_CODE_ROLES: Final[tuple[tuple[_TokenType, str], ...]] = (
    (Token.Comment, "code_comment"),
    (Token.Keyword, "code_keyword"),
    (Token.Literal.String, "code_string"),
    (Token.Literal.Number, "code_number"),
    (Token.Name, "code_name"),
    (Token.Operator, "code_operator"),
    (Token.Punctuation, "code_operator"),
    (Token.Generic.Deleted, "removed"),
    (Token.Generic.Inserted, "added"),
    (Token.Literal, "code_string"),
    (Token.Error, "error"),
)


def _code_role(token_type: _TokenType) -> str | None:
    """The role a pygments token wears, or None to leave it alone.

    Climbs the token's own ancestry rather than matching a name, so
    a lexer's private subtype - `Token.Literal.Scalar.Plain` in
    YAML - lands on its nearest mapped ancestor instead of falling
    through uncoloured.
    """
    walk: _TokenType | None = token_type
    while walk is not None:
        for root, role in _CODE_ROLES:
            if walk is root:
                return role
        walk = walk.parent
    return None


def code_css() -> str:
    """A rule for every class pygments can emit inside `.highlight`.

    Generated from `STANDARD_TYPES` rather than from a list someone
    wrote, because the defect this fixes was highlighting that ran
    on every fenced block and produced classes no stylesheet had a
    rule for - a hand-written list would have the same gap in a
    smaller place.

    **Two kinds of rule.** An exact class for every standard type,
    and a prefix selector for each of their roots: a token type
    pygments has no short name for is emitted as its root's name
    joined to the rest of its path, so YAML produces `l-Scalar-Plain`
    and `p-Indicator`. Without the second kind those inherit nothing.
    """
    exact: list[str] = []
    roots: dict[str, str] = {}
    for token_type, short in sorted(STANDARD_TYPES.items(), key=lambda pair: pair[1]):
        role = _code_role(token_type)
        if not short or role is None:
            continue
        exact.append(f".highlight .{short} {{ color: var(--role-{role}); }}")
        roots.setdefault(short, role)
    prefixed = [
        f'.highlight [class^="{short}-"] {{ color: var(--role-{role}); }}'
        for short, role in sorted(roots.items())
    ]
    return "\n".join(["/* Code, in the roles the terminal uses. */", *exact, *prefixed])


def css_weights() -> str:
    """The attribute half of a role, as a class per role.

    Separate from the colour because CSS keeps them apart: a colour is
    one property and bold, italic and underline are three others, and a
    single custom property cannot carry all four.

    **Dim is the colour alone, never an opacity as well.** The muted
    grey is already chosen to sit at the edge of legibility, and fading
    it by a quarter took every dim role on every page to about 3:1 -
    and a link or warning inside a dim span faded with it.
    """
    blocks: list[str] = []
    for name, role in ROLES.items():
        declarations = [f"color: var(--role-{name});"]
        if role.bold:
            declarations.append("font-weight: 600;")
        if role.italic:
            declarations.append("font-style: italic;")
        if role.underline:
            declarations.append("text-decoration: underline;")
        body = " ".join(declarations)
        blocks.append(f".role-{name} {{ {body} }}")
    return "\n".join(blocks)


def layout_css() -> str:
    """The layout, which may not name a colour.

    Exposed as a function rather than left as a private constant so a
    test can assert exactly that. Every visible colour arrives through
    a custom property `css_variables` emitted.
    """
    return _LAYOUT


def stylesheet() -> str:
    """The whole generated stylesheet.

    Generated rather than a static file because the roles are, and a
    static copy would be the second place a colour lives.
    """
    dark = css_variables(CSS_COLOURS_DARK, DARK_GROUND, "dark")
    return (
        f":root {{\n{css_variables()}\n}}\n\n"
        # The guard is the load-bearing part. This block is later in
        # the sheet and applies to the same `:root`, so without it an
        # explicit `light` would lose to a dark system - and choosing
        # light would appear to do nothing on exactly the machines
        # where a reader would want to.
        "@media (prefers-color-scheme: dark) {\n"
        f':root:not([data-theme="light"]) {{\n{dark}\n}}\n'
        "}\n\n"
        # And this is what lets a reader on a light system ask for
        # dark. `system` needs no rule: it is the absence of the
        # attribute matching either of these, so the default is the
        # behaviour that existed before there was a choice.
        f':root[data-theme="dark"] {{\n{dark}\n}}\n\n'
        f"{scale_css()}\n\n{css_weights()}\n\n{code_css()}\n\n{_LAYOUT}"
    )


def scale_css() -> str:
    """The bars and the swatches, by the reader's chosen scale.

    After the theme blocks, because a rule here has the specificity of
    the dark block's own `--strength-N` and order is what lets the
    reader's scale win in either theme. Generated, because the scales
    are a table and a hand-written copy would be the second place one
    is named.
    """
    rules: list[str] = []
    for name in STRENGTH_SCALES:
        steps = "\n".join(
            f"  --strength-{step}: var(--scale-{name}-{step});" for step in range(1, 6)
        )
        rules.append(f':root[data-scale="{name}"] {{\n{steps}\n}}')
    for name in STRENGTH_SCALES:
        for step in range(1, 6):
            rules.append(
                f'.swatch[data-scale="{name}"][data-step="{step}"] '
                f"{{ background: var(--scale-{name}-{step}); }}"
            )
    return "\n".join(rules)


# Layout only, in its own file so it is edited as CSS. No colour appears
# there: every visible colour comes through a `--role-`, `--ground`,
# `--ink` or `--rule` property above, and a test asserts it.
_LAYOUT: Final = (Path(__file__).parent / "layout.css").read_text(encoding="utf-8")


__all__ = [
    "CSS_COLOURS",
    "CSS_COLOURS_DARK",
    "DARK_GROUND",
    "DEFAULT_STRENGTH_SCALE",
    "LIGHT_GROUND",
    "STRENGTH_SCALES",
    "StrengthScale",
    "css_variables",
    "css_weights",
    "layout_css",
    "scale_css",
    "stylesheet",
]
