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

from typing import Final, Literal

from pygments.token import STANDARD_TYPES, Token, _TokenType

from kennis.render.theme import ANSI_COLOURS, ROLES, AnsiColour, Role

# The page itself. Not white and not black: a hair off each, because
# a pure-white ground under a serif at reading size glares, and a
# pure-black one makes light text bloom.
LIGHT_GROUND: Final = "#FBFBF9"
DARK_GROUND: Final = "#16181C"

# What the nine names look like on a light ground. Measured: the
# worst is 4.82:1 and the closest pair of hues is dE 36.8.
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
    "bright_black": "#6A7078",
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
    one property and bold, dim, italic and underline are four others,
    and a single custom property cannot carry all five.
    """
    blocks: list[str] = []
    for name, role in ROLES.items():
        declarations = [f"color: var(--role-{name});"]
        if role.bold:
            declarations.append("font-weight: 600;")
        if role.dim:
            declarations.append("opacity: 0.75;")
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


# Layout only. No colour appears here: every visible colour comes
# through a `--role-`, `--ground`, `--ink` or `--rule` property above,
# and a test asserts it.
#
# The organising idea is a margin and a column. **What kennis composed
# goes in the margin; what kennis is quoting goes in the column.** The
# margin is the terminal's gutter, kept rather than disguised, and it
# is set in a monospace because that is genuinely what kennis's own
# output is. The column is set in a serif at a reading measure,
# because it holds papers.
_LAYOUT = """\
@font-face {
  font-family: 'Source Serif 4';
  font-style: normal;
  font-weight: 200 900;
  font-display: swap;
  src: url(/static/vendor/fonts/SourceSerif4-Roman.woff2) format('woff2');
}

@font-face {
  font-family: 'Source Serif 4';
  font-style: italic;
  font-weight: 200 900;
  font-display: swap;
  src: url(/static/vendor/fonts/SourceSerif4-Italic.woff2) format('woff2');
}

@font-face {
  font-family: 'Atkinson Hyperlegible';
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url(/static/vendor/fonts/AtkinsonHyperlegible-Regular.woff2) format('woff2');
}

@font-face {
  font-family: 'Atkinson Hyperlegible';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url(/static/vendor/fonts/AtkinsonHyperlegible-Bold.woff2) format('woff2');
}

@font-face {
  font-family: 'Atkinson Hyperlegible';
  font-style: italic;
  font-weight: 400;
  font-display: swap;
  src: url(/static/vendor/fonts/AtkinsonHyperlegible-Italic.woff2) format('woff2');
}

@font-face {
  font-family: 'Atkinson Hyperlegible';
  font-style: italic;
  font-weight: 700;
  font-display: swap;
  src: url(/static/vendor/fonts/AtkinsonHyperlegible-BoldItalic.woff2) format('woff2');
}

:root {
  /* The margin holds a line like `relevance: low id=nwgswtko72`,
     which is 40 monospace characters at its longest. */
  --margin: 11rem;
  --gap: 1.75rem;
  /* Under 70 characters of the column face at 1.0625rem. */
  --measure: 33rem;
  /* What the text is set at and what the column is centred in: the
     whole pane unless the width preference says otherwise (Brian,
     2026-10-12). `none` is what `max-width` takes for no limit. */
  --text: none;
  --frame: none;
  --column: 'Source Serif 4', Charter, Cambria, Georgia, serif;
  /* Two faces, divided by the rule the interface already uses.
     `--gutter` is what kennis composed - provenance, counts,
     labels, buttons, messages - and `--mono` is what must be read
     or typed verbatim.

     They were one variable, and `code, pre` was set in it. Making
     the margin proportional, which is what was asked for, would
     have put every code block in a sans and undone the syntax
     highlighting with it. Nothing would have failed. */
  --gutter: system-ui, -apple-system, 'Segoe UI', Roboto, 'Noto Sans',
            'DejaVu Sans', Arial, sans-serif;
  --mono: ui-monospace, 'DejaVu Sans Mono', 'Cascadia Mono', Menlo, monospace;

  /* The pane's width, which is the whole of what collapsing changes;
     the open width is the reader's to drag (`gui/layout.py`), drawn on
     `<html>` from a cookie, as are the inspector's and the strip's. */
  --pane-width: 16rem;
  --pane: var(--pane-width);
  --inspector-width: 17rem;
  --strip-height: 40dvh;
  /* Scrollbars in the theme: a thin thumb in the muted grey on no
     track. Inherited, so this one declaration reaches every scroller. */
  --scrollbar: color-mix(in srgb, var(--role-muted) 55%, transparent);
  scrollbar-color: var(--scrollbar) transparent;
}

/* `scrollbar-width` is not inherited, so it is set on everything. */
* { box-sizing: border-box; scrollbar-width: thin; }

body {
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: var(--column);
  font-size: 1.0625rem;
  /* A serif wants more leading than a sans at the same size. */
  line-height: 1.6;
}

/* ---------------------------------------------------------------- */
/* The shell: a bar, the pane, the column, and the strip            */
/* ---------------------------------------------------------------- */

/* A grid on `body`, sized by the dynamic viewport. The mockup sized
   it as `calc(100% - 2.3rem)` and the strip clipped at the bottom of
   the window as soon as the bar above it wrapped: arithmetic about
   one element's height is wrong the moment another's changes. Here
   each row takes what it needs and the middle row takes the rest. */
.shell {
  height: 100dvh;
  display: grid;
  grid-template-columns: var(--pane) minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr) auto;
  grid-template-areas: "bar bar" "pane main" "strip strip";
  overflow: hidden;
  transition: grid-template-columns 0.2s ease;
}

/* Collapsed, the pane takes no width at all: its toggle is in the
   bar, which never collapses, so there is nothing to leave behind. */
:root[data-pane="closed"] { --pane: 0px; }
:root[data-pane="closed"] .pane { opacity: 0; visibility: hidden; }

.bar {
  grid-area: bar;
  view-transition-name: bar;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem 0.9rem;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--rule);
  font-family: var(--gutter);
  font-size: 0.8125rem;
}

/* The one place the interface says its own name. Set in the text
   face rather than the gutter's, because it is a name and not a
   field. */
.wordmark {
  font-family: var(--column);
  font-size: 1.4rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1;
  color: var(--ink);
  text-decoration: none;
}
.wordmark:hover { text-decoration: none; }

.icon {
  width: 1rem;
  height: 1rem;
  flex: none;
  vertical-align: -0.15em;
}

/* A control that is only an icon, or an icon and a short label.
   No border until it is pointed at, so a row of them reads as a
   toolbar and not as a row of boxes. */
.ghost, .action {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 0.55rem;
  border: 1px solid transparent;
  border-radius: 5px;
  background: none;
  color: var(--ink);
  font-family: var(--gutter);
  font-size: 0.8125rem;
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
}
.ghost { color: var(--role-muted); }
.ghost:hover, .action:hover {
  background: var(--raised);
  border-color: var(--rule);
  color: var(--ink);
}

/* One control, as the mockup drew it: the icon, the field, the key
   that reaches it, and the two selects, inside one border. The ring is
   the box's while the field has the focus; a select keeps its own, so
   it is clear which part a key will change. */
.searchbox {
  flex: 1 1 24rem;
  max-width: 40rem;
  min-width: 0;
  display: flex;
  align-items: center;
  margin: 0;
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: var(--ground);
}
.searchbox:has(input:focus-visible) {
  outline: 2px solid var(--role-hint);
  outline-offset: 2px;
}
.searchbox > .icon { margin-left: 0.6rem; color: var(--role-muted); flex: none; }
.searchbox input[type="search"] {
  flex: 1 1 10rem;
  font-family: var(--column);
  border: 0;
  background: none;
}
.searchbox input[type="search"]:focus-visible { outline: none; }
/* The box keeps room to type in; the selects give way first. On a
   phone they took the row and left the box a sliver. */
.searchbox input[type="search"] { min-width: 7rem; }
.searchbox .kbd { margin-right: 0.5rem; flex: none; }
.searchbox select {
  font-size: 0.75rem;
  min-width: 0;
  flex: 0 1 auto;
  border: 0;
  border-left: 1px solid var(--rule);
  border-radius: 0;
  background-color: transparent;
  color: var(--role-muted);
}
.searchbox .searching { margin: 0 0.5rem; }

/* Quit is a form so it works without a script; `contents` lets its
   button sit in the row of actions as if the form were not there. */
.quit { display: contents; }

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.15rem;
  margin-left: auto;
}

/* ---- the pane: a tree, like an editor's file explorer ---- */

.pane {
  grid-area: pane;
  view-transition-name: pane;
  transition: opacity 0.2s ease, visibility 0.2s;
  overflow-y: auto;
  background: var(--raised);
  border-right: 1px solid var(--rule);
  padding: 0.75rem 0.5rem 1rem;
  font-family: var(--gutter);
  font-size: 0.8125rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-width: 0;
}
.pane section { margin: 0; }

.pane-head {
  margin: 0 0.4rem 0.3rem;
  font-family: var(--gutter);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--role-muted);
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
}
.pane-head a { color: inherit; text-decoration: none; }
.pane-head a:hover { color: var(--ink); }
/* A project's name, as it is spelled on disk. */
.pane-head .project {
  font-family: var(--mono);
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
  color: var(--ink);
}
.pane-note { margin: 0 0.4rem; font-size: 0.75rem; }
/* The corpus's total, beside its heading, in the case it is written in. */
.pane-head .count {
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
}
/* What the dots mean, at the foot of the pane rather than after its
   last section. */
.legend {
  margin: auto 0.4rem 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem 0.9rem;
  font-size: 0.6875rem;
}
.legend > span { display: inline-flex; align-items: center; gap: 0.3rem; }

.tree { list-style: none; margin: 0; padding: 0; }
.tree .tree {
  margin-left: 0.85rem;
  padding-left: 0.35rem;
  border-left: 1px solid var(--rule);
}
.tree summary { list-style: none; }
/* Where a collection's documents arrive when it is first opened.
   Empty until then, and an empty branch takes no room. */
.branch:empty { display: none; }
.tree summary::-webkit-details-marker { display: none; }

.node {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.22rem 0.35rem;
  border-radius: 4px;
  color: var(--ink);
  text-decoration: none;
  cursor: pointer;
  min-width: 0;
}
.node:hover { background: var(--raised); }
.node .icon { color: var(--role-muted); }
.node .name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: inherit;
  text-decoration: none;
}
.node.top .name { font-weight: 600; }
.node .file { font-family: var(--mono); font-size: 0.75rem; }
/* The chevron turns when its branch is open. It is the first icon
   in a summary; the second names the kind. */
summary.node > .icon:first-child { transition: transform 0.12s; }
details[open] > summary.node > .icon:first-child { transform: rotate(90deg); }
/* A leaf has no chevron, so it is indented by one to line up with
   its siblings' names. */
.node.leaf { padding-left: 1.6rem; }
.node[aria-current="page"] { background: var(--brand-wash); }

.pane .count {
  font-size: 0.75rem;
  color: var(--role-muted);
  font-variant-numeric: tabular-nums;
}

/* A collection's state, as a dot. The words are beside it for a
   screen reader and in its title for a pointer; the dot is for the
   glance. */
.state {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  flex: none;
  border: 1px solid var(--rule);
}
.state-current { background: var(--role-added); border-color: var(--role-added); }
.state-behind, .state-none {
  background: var(--role-warning);
  border-color: var(--role-warning);
}
.state-empty { background: none; }

/* A document's state in the tree: a letter, quiet when there is none.
   The colour is the role's, set by its class; this only sets the
   letter's face and keeps it from being squeezed by a long title. */
.doc-state {
  flex: none;
  font-family: var(--mono);
  font-size: 0.75rem;
  font-weight: 700;
}
/* The filter is CSS, so it works with no script: checked, it hides
   every row and group with nothing to report. */
.attention-filter {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin: 0.15rem 0.4rem 0.3rem;
  font-size: 0.75rem;
  color: var(--role-muted);
}
.branch:has(.attention-only:checked) .quiet { display: none; }

/* Each row's menu sits at its right-hand end, beside the thing it acts
   on rather than inside it. Shown on hover, on focus and while open, so
   it is reachable from the keyboard and quiet otherwise. */
.tree li.row, .tree li.group { position: relative; }
.tree li.row > .node, .tree li.group > details > summary.node { padding-right: 1.7rem; }
details.menu {
  position: absolute;
  top: 0.1rem;
  right: 0.15rem;
}
.menu-button {
  display: flex;
  align-items: center;
  padding: 0.12rem;
  border-radius: 4px;
  color: var(--role-muted);
  cursor: pointer;
  opacity: 0;
}
.tree li:hover > details.menu > .menu-button,
.menu-button:focus-visible,
details.menu[open] > .menu-button { opacity: 1; }
.menu-button:hover { background: var(--raised); }
.menu-items {
  position: absolute;
  right: 0;
  top: 100%;
  z-index: 5;
  display: flex;
  flex-direction: column;
  min-width: 12rem;
  padding: 0.25rem;
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: var(--ground);
  box-shadow: 0 4px 14px var(--rule);
  transition: opacity 0.12s ease, translate 0.12s ease;
}
.menu-items form.index { margin: 0; }
.menu-items .item {
  display: block;
  width: 100%;
  padding: 0.3rem 0.5rem;
  border: 0;
  border-radius: 4px;
  background: none;
  color: var(--ink);
  font: inherit;
  font-size: 0.85rem;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
}
.menu-items .item:hover, .menu-items .item:focus-visible { background: var(--raised); }
.menu-items form.move {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.2rem 0.5rem 0.3rem;
  border-block: 1px solid var(--rule);
  margin: 0.2rem 0;
}
.menu-items form.move .item { padding-inline: 0; }
.menu-items form.move input { font: inherit; font-size: 0.8rem; }

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  /* A button's own padding and border would otherwise give it a box
     larger than the pixel it is meant to occupy. */
  padding: 0;
  border: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

/* ---- the palette ---- */
/* A key as it is pressed: the face of what must be typed verbatim. */
.kbd {
  font-family: var(--mono);
  font-size: 0.6875rem;
  color: var(--role-muted);
  border: 1px solid var(--rule);
  border-bottom-width: 2px;
  border-radius: 3px;
  padding: 0 0.3rem;
  line-height: 1.4;
}
.palette-open { display: inline-flex; align-items: center; gap: 0.35rem; }
.palette { display: flex; flex-direction: column; gap: 0.4rem; }
.palette-input {
  width: 100%;
  padding: 0.5rem 0.65rem;
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: var(--ground);
  color: var(--ink);
  font: inherit;
  font-size: 0.95rem;
}
.palette-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 20rem;
  overflow-y: auto;
}
.palette-list a {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.4rem 0.6rem;
  border-radius: 5px;
  color: var(--ink);
  text-decoration: none;
}
/* The selection is the reader's place in the list, whether it was
   moved there by a key or by the pointer. */
.palette-list [aria-selected="true"] > a { background: var(--brand-wash); }
.palette-list .label { flex: 1; min-width: 0; }
/* The role gives the kind its colour only: `command` also sets the
   verbatim face, and a kind is a word kennis composes. */
.palette-list .kind {
  font-family: var(--gutter);
  font-size: 0.6875rem;
  font-weight: 400;
}
.palette-empty { margin: 0.4rem 0.6rem; }
.palette-keys {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin: 0.2rem 0 0;
  font-size: 0.6875rem;
}

/* ---- the centre ---- */

/* Lets a height move to and from `max-content`, so a passage grows
   rather than jumps. Browsers without it change at once. */
:root { interpolate-size: allow-keywords; }

main {
  grid-area: main;
  overflow-y: auto;
  padding: 1.25rem 1.5rem 4rem;
  min-width: 0;
  /* The containing block for what is positioned inside it. Without
     this a visually hidden label deep in a long document was placed
     against the whole page, which then measured 37,000px tall, and
     following a link to a passage scrolled the page itself - bar and
     all - rather than this pane. */
  position: relative;
}
/* The column keeps its measure inside whatever the pane leaves. One
   element owns the centring: on `main > *` it was undone by any later
   rule setting a child's `margin` shorthand - `h1` among them, which
   left the corpus page's heading beside its table rather than above. */
.column {
  max-width: var(--frame);
  margin: 0 auto;
  /* The spacing preference, on what is read rather than on the whole
     window: wider letters in the bar would only crowd it. */
  line-height: var(--leading);
  letter-spacing: var(--tracking);
  word-spacing: var(--word-gap);
}

/* ---- this window's preferences (12a) ----
   Each is an attribute the server writes onto <html> from a cookie.
   The default of each needs no rule: it is what the window did before
   there was a choice. */
:root { --leading: 1.6; --tracking: normal; --word-gap: normal; }
:root[data-face="sans"] { --column: var(--gutter); }
:root[data-face="hyperlegible"] {
  --column: 'Atkinson Hyperlegible', Verdana, var(--gutter);
}
/* The root's size, because the interface is in rem: a reader asking
   for larger text does not mean larger only in the column. */
:root[data-size="small"] { font-size: 90%; }
:root[data-size="large"] { font-size: 112.5%; }
:root[data-size="larger"] { font-size: 125%; }
:root[data-spacing="wide"] {
  --leading: 1.8;
  --tracking: 0.02em;
  --word-gap: 0.08em;
}
:root[data-spacing="wider"] {
  --leading: 2;
  --tracking: 0.04em;
  --word-gap: 0.16em;
}
/* The reading measure is the width the window had before there was a
   choice; wide is about a hundred characters of the column face. */
:root[data-width="wide"] { --text: 56rem; --frame: 56rem; }
:root[data-width="reading"] {
  --text: var(--measure);
  --frame: calc(var(--margin) + var(--gap) + var(--measure));
}
:root[data-strength="words"] .cells { display: none; }
:root[data-labels="icons"] .measure-name { display: none; }
:root[data-labels="words"] .measure > .icon { display: none; }

/* ---- the settings page ---- */
.settings { font-family: var(--gutter); font-size: 0.875rem; }
.settings h1 { font-family: var(--column); font-size: 1.5rem; margin: 0 0 1rem; }
.settings h2 { font-size: 1.05rem; margin: 1.2rem 0 0.2rem; }
.settings h3 {
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--role-muted);
  margin: 1.4rem 0 0.2rem;
}
/* One row per setting: its name and sentence on the left, the choices
   on the right, stacking when the window is narrow. */
.setting {
  display: grid;
  /* Both columns get a share: sized to the choices alone, five scales
     squeezed the sentence to a word a line. */
  grid-template-columns: minmax(12rem, 1fr) minmax(0, 1fr);
  gap: 0.2rem 1.2rem;
  align-items: start;
  margin: 0;
  padding: 0.75rem 0;
  border: 0;
  border-top: 1px solid var(--rule);
}
.setting-name { float: left; padding: 0; font-weight: 600; }
.setting-sentence { grid-column: 1; margin: 0; font-size: 0.8125rem; }
/* A list of radios, one to a line, for options carrying more than a
   word: the bar colours' swatches. */
.radio-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.4rem;
}
.choice {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  white-space: nowrap;
  cursor: pointer;
}
.swatches { display: inline-flex; gap: 1px; }
.swatch { display: inline-block; width: 0.55rem; height: 0.85rem; border-radius: 1px; }
.preferences { max-width: 46rem; }
.prefs-save { margin-top: 1rem; }
.settings-open { display: inline-flex; align-items: center; }
@media (max-width: 760px) {
  .setting { grid-template-columns: minmax(0, 1fr); }
}
.measure-name { color: var(--role-muted); }
/* kennis's configuration: the control in the right column beside
   everything said about it, which reads down the left. */
.kennis-settings { max-width: 46rem; }
.setting-group { margin-bottom: 0.4rem; }
.kennis .setting > p { grid-column: 1; margin: 0; font-size: 0.8125rem; }
.setting-control { grid-column: 2; grid-row: 1 / span 6; }
.setting-control select, .setting-control input { width: 100%; }
.setting-control .role-error { margin: 0.3rem 0 0; font-size: 0.8125rem; }
.kennis .cost { font-style: italic; }
.setting-key code { font-size: 0.75rem; color: var(--role-muted); }
.kennis .outcome { margin: 0.6rem 0; }
.rebuild {
  max-width: 46rem;
  margin: 0.6rem 0 1rem;
  padding: 0.6rem 0.9rem;
  border: 1px solid var(--rule);
  border-left: 3px solid var(--role-warning);
}
.rebuild h3 { margin-top: 0.2rem; }
.rebuild ul { margin: 0.3rem 0 0.6rem; padding-left: 1.2rem; }
.rebuild-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem; }
.rebuild-actions form, .rebuild-actions .undo { margin: 0; }
.rebuild-actions .later { color: var(--role-muted); }
.kennis .credential code { font-size: 0.8125rem; }
/* The Backup section: three forms, each a row like the settings above. */
.backup .backup-folder,
.backup .backup-now,
.backup .backup-test { max-width: 46rem; margin: 0; }
.backup .backup-state { grid-column: 1; margin: 0; font-size: 0.8125rem; }
.backup .password { display: block; margin-bottom: 0.4rem; }
.backup .password input { display: block; width: 100%; margin-top: 0.15rem; }
.backup .setting-control > button[type=submit] { margin-top: 0.4rem; }
.backup .entry-row { display: flex; gap: 0.4rem; }
.backup .entry-row input { flex: 1 1 auto; min-width: 0; }
@media (max-width: 760px) {
  .setting-control { grid-column: 1; grid-row: auto; }
}

.action-page h2 { font-size: 1.3rem; margin: 0 0 0.5rem; }

/* The page Quit answers with: no shell around it, because nothing in
   the shell would work any more. */
.stopped main { padding-top: 4rem; }

/* ---- an action's dialog ---- */

.dialog {
  width: min(38rem, calc(100vw - 2rem));
  max-height: calc(100dvh - 2rem);
  padding: 0;
  border: 1px solid var(--rule);
  border-radius: 8px;
  background: var(--ground);
  color: var(--ink);
  font-family: var(--gutter);
  font-size: 0.875rem;
}
.dialog::backdrop { background: var(--rule); }
.dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.9rem 1.1rem 0.3rem;
}
.dialog-head h2 { margin: 0; font-size: 1.05rem; font-family: var(--gutter); }
.dialog-body { padding: 0.3rem 1.1rem 1.1rem; }
.dialog-body p { margin: 0 0 0.6rem; }

/* ---- the strip ---- */

.strip {
  grid-area: strip;
  view-transition-name: strip;
  max-height: var(--strip-height);
  overflow-y: auto;
  position: relative;
  background: var(--raised);
  border-top: 1px solid var(--rule);
  padding: 0 1rem;
  font-family: var(--gutter);
  font-size: 0.8125rem;
}
.strip #job:not(:empty) { padding: 0.5rem 0; }

/* Past searches, offered again. Shaped like the hits list because
   it occupies the same place and answers the same question - the
   margin says where the search looked and what it found, the
   column carries the reader's own words. */
.recents { margin-top: 2.5rem; }
/* Tighter than a hit, because an entry is one line of the reader's
   own words with no snippet under it. The hit's 1.5rem left four
   queries occupying a screen. */
.recents .hits li { padding: 0.7rem 0; }
.recents .hits li > * { margin-bottom: 0; }
.recents h2 {
  font-family: var(--gutter);
  font-size: 0.8125rem;
  font-weight: 400;
  color: var(--role-muted);
  margin: 0 0 1rem;
}
.recents form { margin-top: 1.25rem; }
.recents button {
  background: none;
  border: none;
  padding: 0;
  font-family: var(--gutter);
  font-size: 0.8125rem;
  color: var(--role-muted);
  cursor: pointer;
  text-decoration: underline;
}
.recents button:hover { color: var(--ink); }

#corpus-changed { margin: 0; padding: 0.6rem 1.5rem; font-size: 0.875rem; }

/* ---------------------------------------------------------------- */
/* The margin and the column                                        */
/* ---------------------------------------------------------------- */

.hits { list-style: none; margin: 0; padding: 0; }

.hits li {
  display: grid;
  grid-template-columns: var(--margin) 1fr;
  /* Only across. One gap value put the same 1.75rem between the
     headline and its own snippet as between the margin and the
     column, which read as two unrelated things. */
  column-gap: var(--gap);
  row-gap: 0;
  padding: 1.5rem 0;
  border-top: 1px solid var(--rule);
}

.hits li > * { grid-column: 2; margin: 0 0 0.5rem; }

/* The margin: right-aligned against the column's left edge, so the
   text forms a rule without one being drawn. */
.hits .detail {
  grid-column: 1;
  grid-row: 1 / span 3;
  text-align: right;
  font-family: var(--gutter);
  font-size: 0.75rem;
  line-height: 1.5;
  /* A long identifier rather than overflow the gutter. Fields are
     separated by the block below, not by `white-space: pre-wrap`,
     which preserved the two spaces and then wrapped wherever the
     line ran out - splitting `meaning:` from `medium` as soon as a
     hit carried two bands. Concern #380. */
  word-break: break-word;
}

.hits .detail span { display: block; }

a { text-underline-offset: 0.15em; text-decoration-thickness: from-font; }
/* A link in the corpus's own text, in a document or an opened passage.
   Left to the browser it was its default blue, which on the dark ground
   is barely visible. */
article a, .full a { color: var(--role-command); }

/* A result's title is underlined on hover and not before. An inline
   link inside prose keeps its underline, because there it is the only
   thing distinguishing it from the sentence around it; a title in a
   list of results is already the one bold line in its row, and three
   underlined lines per hit was the loudest thing on the page. */
.hits a { color: var(--ink); font-weight: 600; text-decoration: none; }
.hits a:hover, .hits a:focus-visible { text-decoration: underline; }
/* Where the query matched. A wash rather than a block of colour:
   the marked words are still the corpus's prose and should read as
   prose with something behind them, not as a separate element. */
mark {
  background: var(--mark);
  color: var(--ink);
  border-radius: 0.15em;
  padding: 0 0.1em;
  /* The mockup's underline: inside a marked chunk the wash behind a
     word is the chunk's own, and the rule is what still tells it. */
  box-shadow: inset 0 -2px 0 var(--brand);
}

/* A scope the sweep could not reach, and the command that fixes it.
   One row per scope rather than the command line's one line per
   command: a list has a row to spare where a margin does not. */
.skipped {
  font-family: var(--gutter);
  font-size: 0.75rem;
  margin: 0.4rem 0 0;
  display: flex;
  gap: 0.75rem;
}

/* ---- an opened document (#447) ---- */
/* The centre on a document page: the bar, then the text and the
   inspector side by side, each scrolling on its own. `main` stops
   scrolling and padding here, and `.reading` takes both over. */
main.document {
  /* `clip`, not `hidden`: a fragment link may still scroll an element
     whose overflow is hidden, and following one to a chunk scrolled
     the bar out of sight. `clip` cannot be scrolled at all. */
  overflow: clip;
  padding: 0;
  display: flex;
  flex-direction: column;
}
main.document > #corpus-changed { margin: 0.5rem 1.5rem 0; }

/* Where the document is: back to the search, the collection, its
   group, and the handle it is cited by. */
.doc-bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.3rem 0.5rem 0.3rem 1rem;
  border-bottom: 1px solid var(--rule);
  font-family: var(--gutter);
  font-size: 0.75rem;
  color: var(--role-muted);
}
.crumbs {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}
.crumbs a { color: var(--role-muted); text-decoration: none; }
.crumbs a:hover { color: var(--ink); text-decoration: underline; }
.crumbs .sep { color: var(--rule); }
.crumbs .here { color: var(--ink); font-family: var(--mono); }

.document-body { flex: 1; min-height: 0; display: flex; }
.reading {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 2rem 1.5rem 4rem;
}

/* Beside the column rather than over it, so it never covers text. */
.inspector {
  flex: none;
  width: var(--inspector-width);
  overflow-x: hidden;
  overflow-y: auto;
  transition: width 0.2s ease, opacity 0.2s ease, visibility 0.2s;
  background: var(--raised);
  border-left: 1px solid var(--rule);
  font-family: var(--gutter);
  font-size: 0.8125rem;
  padding: 0.3rem 0 1rem;
}
/* ---- the drag handles (`resize.js`) ----
   A thin band over the edge it moves, unseen until pointed at or
   focused, when it shows the brand. Each sits where it will not scroll
   with what it sizes. */
.resize {
  z-index: 3;
  background: transparent;
  transition: background-color 0.15s ease;
  touch-action: none;
}
.resize:hover, .resize:focus-visible, :root.resizing .resize:active {
  background: var(--brand);
  outline: none;
}
.resize-pane {
  grid-area: pane;
  justify-self: end;
  width: 6px;
  margin-right: -3px;
  cursor: col-resize;
}
.resize-inspector {
  flex: none;
  width: 6px;
  margin: 0 -3px;
  position: relative;
  cursor: col-resize;
}
.resize-strip {
  position: sticky;
  top: 0;
  height: 6px;
  margin: 0 -1rem -6px;
  cursor: row-resize;
}
:root[data-pane="closed"] .resize-pane { display: none; }
:root[data-inspector="closed"] .resize-inspector { display: none; }
/* While dragging: no transition to lag the pointer, no text selected. */
:root.resizing .shell { transition: none; user-select: none; }
:root.resizing .inspector { transition: none; }

/* The strip's collapse: offered when there is a job, and collapsed it
   keeps the first line - the step while running, the headline after. */
#strip-toggle {
  float: right;
  margin: 0.3rem 0 0 0.5rem;
  padding: 0.15rem;
}
#strip-toggle .icon { transition: transform 0.2s ease; }
:root[data-strip="closed"] #strip-toggle .icon { transform: rotate(180deg); }
.strip:has(#job:empty) #strip-toggle { display: none; }
/* A height the reader dragged is the strip's height while it shows a
   job, not only its limit: a drag that changed nothing would read as a
   broken handle. Idle, the strip stays one line. The size is on
   `<html>`'s inline style, from the server or `resize.js`. */
:root[style*="--strip-height"] .strip:has(#job:not(:empty)) {
  height: var(--strip-height);
}
/* Collapsed wins over a dragged height; same specificity, so it is
   the later rule. */
:root[data-strip="closed"] .strip:has(#job:not(:empty)) { height: auto; }
:root[data-strip="closed"] .strip :is(
  .job-lines, .job-progress, .job-outcome > :not(:first-child)
) {
  display: none;
}

:root[data-inspector="closed"] .inspector {
  width: 0;
  padding: 0;
  border-left-width: 0;
  opacity: 0;
  visibility: hidden;
}
.inspector details { border-bottom: 1px solid var(--rule); }
.inspector summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.55rem 0.9rem;
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--role-muted);
}
.inspector summary::-webkit-details-marker { display: none; }
.inspector summary .icon { width: 0.8rem; height: 0.8rem; transition: transform 0.15s; }
.inspector details[open] > summary .icon { transform: rotate(90deg); }
.details dl {
  margin: 0;
  padding: 0 0.9rem 0.8rem;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 0.35rem 0.8rem;
}
.details dt { color: var(--role-muted); }
.details dd { margin: 0; overflow-wrap: anywhere; }
.details dd.verbatim { font-family: var(--mono); font-size: 0.75rem; }
.matches ol, .outline ul {
  margin: 0;
  padding: 0 0.9rem 0.8rem 2rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.outline ul { list-style: none; padding-left: 0.9rem; }
.outline li[data-level="3"] { padding-left: 0.8rem; }
.outline li[data-level="4"], .outline li[data-level="5"],
.outline li[data-level="6"] { padding-left: 1.6rem; }
.inspector a { color: var(--role-command); }
.inspector details > p { margin: 0; padding: 0 0.9rem 0.8rem; }

/* ---- search results ---- */

/* The key: one line until it is opened, then what each measure is
   measured against. Relevance is never shown without its scale, and
   this is where the scale is (#408). */
.key {
  font-family: var(--gutter);
  font-size: 0.8125rem;
  color: var(--role-muted);
  margin: 1.5rem 0 0;
}
.key summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
  cursor: pointer;
  list-style: none;
}
.key summary::-webkit-details-marker { display: none; }
.key summary:hover .label { color: var(--ink); text-decoration: underline; }
.key[open] summary .label { color: var(--ink); }
.ramp { display: inline-flex; align-items: center; gap: 0.4rem; }
.ramp .end { font-size: 0.75rem; }
.key-lines { list-style: none; margin: 0.75rem 0 0; padding: 0; }
.key-lines li {
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
  margin: 0 0 0.35rem;
}
.key p { margin: 0.5rem 0 0; max-width: var(--text); }

/* How many were found and for what, with the order beside it. */
.results-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem 1rem;
  font-family: var(--gutter);
  font-size: 0.8125rem;
  margin: 0 0 1rem;
  max-width: var(--text);
}
.results-head .summary { margin: 0; color: var(--role-muted); }

/* One measure's own order, within each collection. Links, so it works
   without a script; the current one is marked as chosen, by weight and
   by the wash, so it does not rest on colour alone. */
.order {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--role-muted);
}
.segmented {
  display: inline-flex;
  border: 1px solid var(--rule);
  border-radius: 5px;
  overflow: hidden;
}
.segmented a, .segmented label {
  position: relative;
  display: inline-flex;
  align-items: center;
  padding: 0.2rem 0.65rem;
  border-right: 1px solid var(--rule);
  font-family: var(--gutter);
  font-size: 0.75rem;
  color: var(--ink);
  text-decoration: none;
  cursor: pointer;
  transition: background-color 0.15s ease;
}
.segmented > :last-child { border-right: 0; }
.segmented a:hover, .segmented label:hover { background: var(--raised); }
.segmented a[aria-current="true"],
.segmented label:has(input:checked) {
  background: var(--brand-wash);
  font-weight: 600;
}
/* The radio stays in the form - it is what posts, what the arrow keys
   move between and what `required` is checked on - with no box of its
   own; its label is the button. */
.segmented input[type="radio"] {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  margin: 0;
  pointer-events: none;
}
.segmented label:has(input:focus-visible) {
  outline: 2px solid var(--role-hint);
  outline-offset: -2px;
}
.limit { font-family: var(--gutter); font-size: 0.75rem; margin: 0.5rem 0 0; }

/* A collection's icon, name and count over its hits, on a rule in ink:
   the strongest line on the page, because it is the one division the
   results have no common scale across (#342). */
.group-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-family: var(--gutter);
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--ink);
  margin: 2rem 0 0;
  padding-bottom: 0.4rem;
  border-bottom: 1px solid var(--ink);
  max-width: var(--text);
}
.group-head .count { font-weight: 400; color: var(--role-muted); }
.results {
  list-style: none;
  margin: 0.9rem 0 0;
  padding: 0;
  display: grid;
  gap: 1.1rem;
}
/* A hit is a card (Brian, 2026-10-12), as search interfaces set a quoted
   excerpt apart: the raised surface, a hairline, and a rule down the
   left as a block quotation has, which turns to the brand - the colour
   of "here" in a document - when the passage is open. Nothing clips,
   because the chevron hangs off the card's bottom edge. */
.hit {
  background: var(--raised);
  border: 1px solid var(--rule);
  border-left: 3px solid var(--role-muted);
  border-radius: 8px;
  max-width: var(--text);
  transition: opacity 0.2s ease, translate 0.2s ease, border-color 0.25s ease;
}
.hit:has(details[open]) { border-left-color: var(--brand); }
/* The head: what kennis says about the hit, on the page's ground so it
   reads as a band, over the passage the hit quotes. */
.hit-head {
  background: var(--ground);
  border-bottom: 1px solid var(--rule);
  border-radius: 7px 7px 0 0;
  padding: 0.6rem 1rem 0.55rem;
}
.hit-head > * { margin: 0 0 0.3rem; }
.hit-head > :last-child { margin-bottom: 0; }

/* The measures, above the title: an icon naming each, a bar of five
   cells and the level's word. The cells and the word carry the level
   without colour; the colour is a third cue (#421). */
.measures {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1.25rem;
  font-family: var(--gutter);
  font-size: 0.75rem;
  color: var(--ink);
}
.measure { display: inline-flex; align-items: center; gap: 0.4rem; }
.measure .icon { color: var(--role-muted); }
/* The level in ink, never in the strength colour: the light end of
   every scale is too pale to read as text on a light page (#421). */
.measure .level { color: var(--ink); }
.cells { display: inline-flex; gap: 2px; }
.cell {
  display: inline-block;
  width: 0.7rem;
  height: 0.5rem;
  border-radius: 1px;
  background: var(--rule);
}
.measure[data-step="1"] .cell.on,
.cell.on[data-step="1"] { background: var(--strength-1); }
.measure[data-step="2"] .cell.on,
.cell.on[data-step="2"] { background: var(--strength-2); }
.measure[data-step="3"] .cell.on,
.cell.on[data-step="3"] { background: var(--strength-3); }
.measure[data-step="4"] .cell.on,
.cell.on[data-step="4"] { background: var(--strength-4); }
.measure[data-step="5"] .cell.on,
.cell.on[data-step="5"] { background: var(--strength-5); }

.heading { display: flex; align-items: baseline; gap: 0.4rem; }
/* The document's title, in kennis's face: the passage under it is the
   document's, in the reading face, so the two are told apart before
   either is read. */
.hit .title {
  font-family: var(--gutter);
  font-size: 0.975rem;
  line-height: 1.35;
  color: var(--role-operation);
  font-weight: 600;
  text-decoration: none;
}
.hit .title:hover, .hit .title:focus-visible { text-decoration: underline; }
.open { color: var(--role-muted); }
.open:hover, .open:focus-visible { color: var(--brand); }

/* One passage, drawn once and windowed (#454). Closed, the part from
   the reader's words, cut at about six lines and faded where it is cut,
   and faded at the top too when there is text above it. Opened, the
   part above grows in, the cut grows to the whole, and the rule the
   document uses for "here" appears. The heights transition where the
   browser can interpolate to `max-content` and change at once where it
   cannot. Everything is in ink: an opened passage is one text. */
.passage { color: var(--ink); }
.passage .full { padding: 0.75rem 1rem 0.8rem; }
.passage .full > * > :first-child { margin-top: 0; }
/* Which section of the document the passage is from. */
.passage-section {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  font-family: var(--gutter);
  font-size: 0.8125rem;
  font-weight: 600;
  line-height: 1.4;
  color: var(--ink);
}
/* A chunk that was only its heading is the head alone. */
.hit:has(.body:empty) .hit-head { border-bottom: 0; border-radius: 7px; }
.passage:has(.body:empty) .full { display: none; }
.passage-section .icon {
  flex: none;
  width: 0.8rem;
  height: 0.8rem;
  align-self: center;
  opacity: 0.55;
}
.passage .full p { margin: 0 0 0.7rem; }
.passage .full :is(h1, h2, h3, h4, h5, h6) {
  font-size: 1em;
  font-weight: 600;
  margin: 0 0 0.4rem;
}
.passage .body > :last-child { margin-bottom: 0; }
.passage.clamped .lead {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.35s ease;
}
.passage.clamped .body {
  max-height: 6lh;
  overflow: hidden;
  mask-image: linear-gradient(to bottom, currentColor 45%, transparent);
  transition: max-height 0.35s ease;
}
.passage.clamped:has(.lead) .body,
.passage.clamped .body[data-shifted] {
  mask-image: linear-gradient(
    to bottom, transparent, currentColor 1.4em, currentColor 45%, transparent
  );
}
.passage.clamped:has(details[open]) .lead,
.passage.clamped:has(details[open]) .body {
  max-height: max-content;
  mask-image: none;
}
/* The chevron sits on the card's bottom edge, half of it below. */
.passage-foot {
  display: flex;
  justify-content: center;
  margin: -0.45rem 0 -0.85rem;
  position: relative;
}
.passage-foot summary {
  list-style: none;
  cursor: pointer;
  display: grid;
  place-content: center;
  width: 1.7rem;
  height: 1.7rem;
  border: 1px solid var(--rule);
  border-radius: 50%;
  background: var(--ground);
  color: var(--role-muted);
  transition: color 0.15s ease, border-color 0.15s ease, translate 0.15s ease;
}
.passage-foot summary::-webkit-details-marker { display: none; }
.passage-foot summary:hover { color: var(--brand); border-color: var(--brand); }
.passage-foot summary:hover .icon { translate: 0 1px; }
.passage-foot details[open] summary:hover .icon { translate: 0 -1px; }
.passage-foot .icon {
  width: 0.85rem; height: 0.85rem; transition: transform 0.2s ease;
}
.passage-foot details[open] .icon { transform: rotate(180deg); }
.passage-foot details:not([open]) .when-open,
.passage-foot details[open] .when-closed { display: none; }
/* Into the document only once the passage is open: closed, the title
   and the arrow beside it already lead there. */

/* A table in a passage scrolls inside it rather than widening the
   column, for the reason `article table` gives. */
.full table {
  display: block;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  font-family: var(--gutter);
  font-size: 0.8125rem;
  margin: 0 0 0.7rem;
}
.full th, .full td {
  padding: 0.2rem 0.75rem 0.2rem 0;
  border-bottom: 1px solid var(--rule);
  text-align: left;
  vertical-align: top;
}
.full th { font-weight: 600; }

/* `kennis read`'s coordinates, to copy. */
.handle {
  font-family: var(--mono);
  font-size: 0.6875rem;
  color: var(--role-muted);
}

.count { font-family: var(--gutter); font-size: 0.8125rem; margin: 0; }

/* ---------------------------------------------------------------- */
/* Reading                                                          */
/* ---------------------------------------------------------------- */

h1, h2, h3 { line-height: 1.25; font-weight: 600; }
h1 { font-size: 1.75rem; margin: 0 0 1.25rem; }
h2 { font-size: 1.3rem; margin: 2.5rem 0 0.75rem; }
h3 { font-size: 1.1rem; margin: 1.5rem 0 0.5rem; }

article { max-width: var(--text); }
article h1 { margin: 0 0 0.5rem; }
article p { margin: 0 0 1rem; }
article img { max-width: 100%; height: auto; }

/* Who wrote it and when, under the title; the rest of what the
   frontmatter says is in the inspector. */
.byline {
  font-family: var(--gutter);
  font-size: 0.8125rem;
  color: var(--role-muted);
  margin: 0 0 1.6rem;
}

/* The passage a search hit pointed at, as the mockup marks it: the
   highlighter wash with the amber rule in the margin, which is also
   an opened passage's rule, so "here" is one colour everywhere. This
   reverses an earlier choice of a cyan rule alone, made before the
   brand colour existed (#450).

   `scroll-margin-top` keeps the fragment from landing flush against
   the top of the scrolling region. */
.chunk {
  background: var(--mark);
  border-left: 3px solid var(--brand);
  padding: 0.3rem 0.7rem 0.3rem 1rem;
  margin: 0 -0.7rem 1rem -1.3rem;
  border-radius: 0 3px 3px 0;
  scroll-margin-top: 2rem;
}
.chunk > :last-child { margin-bottom: 0; }

code, pre {
  font-family: var(--mono);
  font-size: 0.9em;
}

/* A printed command had no face of its own. `.role-command` is a
   generated colour role, so it inherited its surroundings: the
   monospace inside `.skipped`, and the serif body face in
   `problem.html`, `outcome.html`, `job-outcome.html` and
   `document.html`. The same command read two ways depending on
   which page refused. rules.md 4.4 says a printed command must run
   as printed; it should look like one too. */
.role-command { font-family: var(--mono); }

pre {
  overflow-x: auto;
  padding: 0.9rem 1rem;
  border-left: 2px solid var(--rule);
}

blockquote {
  margin: 0 0 1rem;
  padding-left: 1rem;
  border-left: 2px solid var(--rule);
  color: var(--role-muted);
}

/* ---------------------------------------------------------------- */
/* Tables and listings                                              */
/* ---------------------------------------------------------------- */

/* Wider than the reading measure, and deliberately: a table is not
   prose and cramming it to 33rem would wrap every cell. */
.holdings { border-collapse: collapse; width: 100%; font-size: 0.9375rem; }
.holdings th {
  text-align: left;
  font-family: var(--gutter);
  font-size: 0.75rem;
  font-weight: 400;
  color: var(--role-muted);
  padding: 0 1.25rem 0.5rem 0;
  border-bottom: 1px solid var(--rule);
}
.holdings td { padding: 0.55rem 1.25rem 0.55rem 0; vertical-align: top; }
.holdings tr + tr td { border-top: 1px solid var(--rule); }
.holdings a { color: var(--ink); }

.documents, .packs, .items { list-style: none; margin: 0; padding: 0; }
.documents li, .packs li { padding: 0.35rem 0; font-size: 0.9375rem; }
.documents a { color: var(--ink); }
.documents .role-muted { font-family: var(--gutter); font-size: 0.75rem; }

.items li { padding: 0.3rem 0; font-size: 0.9375rem; }
.items .marker { font-family: var(--gutter); }

/* ---------------------------------------------------------------- */
/* Forms                                                            */
/* ---------------------------------------------------------------- */

.search { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0 0 1rem; }
.search input[type="search"] { flex: 1 1 12rem; }

/* kennis composed this sentence, so it wears the gutter's face -
   the same division the margin makes. `align-self: center` because
   the form is a flex row of controls and an unaligned line of text
   sits on their top edge. */
.searching {
  font-family: var(--gutter);
  font-size: 0.8125rem;
  align-self: center;
}

input, select, textarea, button {
  font: inherit;
  font-size: 0.9375rem;
  color: var(--ink);
  background: var(--ground);
  border: 1px solid var(--rule);
  border-radius: 5px;
  padding: 0.4rem 0.6rem;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}
input:hover, select:hover, textarea:hover { border-color: var(--role-muted); }

/* A select draws its own chevron: two gradients in the text colour,
   so it follows the theme and the muted search bar alike. */
select {
  appearance: none;
  padding-right: 1.8rem;
  background-image:
    linear-gradient(45deg, transparent 50%, currentColor 50%),
    linear-gradient(135deg, currentColor 50%, transparent 50%);
  background-position:
    right 0.85rem center,
    right 0.55rem center;
  background-size: 0.3rem 0.3rem;
  background-repeat: no-repeat;
  cursor: pointer;
}

/* A radio and a checkbox drawn rather than the browser's: a box in the
   muted border, the brand when chosen. The dot and the tick are a
   `::before` grown from nothing, the tick cut by a polygon, so no image
   and no colour is named. */
input[type="radio"],
input[type="checkbox"] {
  appearance: none;
  flex: none;
  display: inline-grid;
  place-content: center;
  width: 1rem;
  height: 1rem;
  margin: 0;
  padding: 0;
  border: 1.5px solid var(--role-muted);
  background: var(--ground);
  vertical-align: -0.15em;
  cursor: pointer;
}
input[type="radio"] { border-radius: 50%; }
input[type="radio"]::before {
  content: "";
  width: 0.45rem;
  height: 0.45rem;
  border-radius: 50%;
  background: var(--brand);
  transform: scale(0);
  transition: transform 0.15s ease;
}
input[type="radio"]:checked { border-color: var(--brand); }
input[type="radio"]:checked::before { transform: scale(1); }
input[type="checkbox"] { border-radius: 4px; }
input[type="checkbox"]::before {
  content: "";
  width: 0.6rem;
  height: 0.6rem;
  background: var(--ground);
  clip-path: polygon(14% 44%, 0 65%, 50% 100%, 100% 16%, 80% 0%, 43% 62%);
  transform: scale(0);
  transition: transform 0.15s ease;
}
input[type="checkbox"]:checked { background: var(--brand); border-color: var(--brand); }
input[type="checkbox"]:checked::before { transform: scale(1); }

textarea { width: 100%; font-family: var(--column); resize: vertical; }

button {
  font-family: var(--gutter);
  font-size: 0.8125rem;
  cursor: pointer;
  padding: 0.45rem 1rem;
}

button:hover { border-color: var(--role-muted); }

input:focus-visible, select:focus-visible, textarea:focus-visible,
button:focus-visible, a:focus-visible {
  outline: 2px solid var(--role-hint);
  outline-offset: 2px;
}

.fields { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.6rem 0; }
.fields label { font-family: var(--gutter); font-size: 0.8125rem; }
.fields input[type="text"] { flex: 1 1 12rem; }

/* ---- the Add dialog ---- */

/* The tabs: one per kind of thing to add. The current one is marked
   by weight and a rule under it, not by colour alone. */
.add-tab .tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0 1.1rem;
  border-bottom: 1px solid var(--rule);
  margin: 0 0 0.8rem;
}
.add-tab .tab {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0 0.45rem;
  color: var(--role-muted);
  text-decoration: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.add-tab .tab:hover { color: var(--ink); }
.add-tab .tab[aria-current="page"] {
  color: var(--ink);
  font-weight: 600;
  border-bottom-color: var(--brand);
}

/* The fields, two to a row where there is room: a required field takes
   the whole row, as does a chooser opened under a field. */
.add-fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
  gap: 0 1rem;
}
.field[data-need="required"] { grid-column: 1 / -1; }
.add-fields > .chooser { grid-column: 1 / -1; }

/* A field: its name with whether it is needed beside it, the control
   under them, and what empty becomes under that. */
.add-tab .field {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: baseline;
  /* A field shares a row with its neighbour and is stretched to the
     taller one's height; without this its own rows took the extra
     space, and two inputs side by side sat at different heights. */
  align-content: start;
  gap: 0.2rem 0.5rem;
  margin: 0 0 0.75rem;
}
.add-tab .field .name { font-weight: 600; }
.add-tab .need { color: var(--role-muted); font-size: 0.75rem; }
/* Set apart by case and weight as well as colour, as the mockup has it. */
.add-tab .field[data-need="required"] .need {
  color: var(--role-error);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.add-tab .field > .choices, .add-tab .field > .entry-row, .add-tab .field > .empty,
.add-tab .field > input, .add-tab .field > textarea {
  grid-column: 1 / -1;
}
.add-tab .entry-row { display: flex; gap: 0.4rem; align-items: start; }
.add-tab .entry-row input, .add-tab .entry-row textarea {
  flex: 1 1 auto;
  min-width: 0;
}
.add-tab .choices { justify-self: start; flex-wrap: wrap; }
.add-tab .empty { color: var(--role-muted); font-size: 0.75rem; }
.add-tab .empty b { color: var(--ink); font-weight: 600; }
.add-tab .browse { display: inline-flex; align-items: center; gap: 0.3rem; }
.add-tab .preview { min-height: 1.2rem; margin: 0 0 0.75rem; }
.add-tab .preview p { margin: 0 0 0.3rem; }
.add-tab .probe { margin: 0 0 0.75rem; }

/* Where the add goes, Cancel, and the add itself, at the foot. Inside
   a dialog it is the dialog's foot, across its whole width. */
.form-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 0.6rem;
  margin: 1rem 0 0;
}
.dialog .form-foot {
  margin: 1rem -1.1rem -1.1rem;
  padding: 0.7rem 1.1rem;
  border-top: 1px solid var(--rule);
  background: var(--raised);
}
/* Two classes, to outrank `.dialog-body p`, whose margin took away the
   `auto` that keeps this at the left. */
.form-foot .destination { margin: 0 auto 0 0; font-size: 0.8125rem; }
/* Until there is a collection there is nowhere to say: the File tab
   chooses none for the reader (#431). */
.destination:has(> [data-mirror="collection"]:empty) { visibility: hidden; }
.destination .sep { margin: 0 0.3rem; }
/* A part whose field is still empty says nothing, separator and all. */
.destination .part:has(> [data-mirror]:empty) { display: none; }
/* A link that does what a button does, drawn as one. */
a.button {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--rule);
  border-radius: 3px;
  padding: 0.45rem 1rem;
  font-family: var(--gutter);
  font-size: 0.8125rem;
  color: var(--ink);
  text-decoration: none;
}
a.button:hover { border-color: var(--role-muted); }
/* The one action a form exists for. */
button.primary {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 600;
  background: var(--ink);
  border-color: var(--ink);
  color: var(--ground);
}

/* A group of Several by group. */
.add-tab .block {
  border: 1px solid var(--rule);
  border-radius: 6px;
  padding: 0.6rem 0.8rem 0.2rem;
  margin: 0 0 0.75rem;
}
.add-tab .block legend { font-weight: 600; padding: 0 0.3rem; }
.add-tab .another { margin: 0 0 0.9rem; }
.add-tab .checks { list-style: none; margin: 0 0 0.6rem; padding: 0; }
.add-tab .check { font-size: 0.75rem; margin: 0 0 0.2rem; }
.add-tab .check code { font-family: var(--mono); }
.add-tab .held { color: var(--role-muted); }

/* The chooser: one folder of this computer, inside the dialog. */
.chooser-panel {
  border: 1px solid var(--rule);
  border-radius: 6px;
  background: var(--raised);
  padding: 0.5rem 0.7rem;
  margin: 0 0 0.75rem;
}
.chooser-panel .where { margin: 0 0 0.4rem; word-break: break-all; }
.chooser-panel .where code { font-family: var(--mono); font-size: 0.75rem; }
.chooser-panel .chooser-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 0.8rem;
  align-items: center;
  margin: 0 0 0.4rem;
}
.chooser-panel .up { color: var(--role-muted); }
.chooser-panel .entries {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 14rem;
  overflow-y: auto;
}
.chooser-panel .entry {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  padding: 0.2rem 0.3rem;
  border: none;
  border-radius: 4px;
  background: none;
  color: var(--ink);
  text-align: left;
  text-decoration: none;
  font: inherit;
  cursor: pointer;
}
.chooser-panel .entry:hover, .chooser-panel .entry:focus-visible {
  background: var(--brand-wash);
}
.chooser-panel .entry.folder .icon { color: var(--role-muted); }
.chooser-panel .entry.file .icon { color: var(--role-muted); }
.chooser:empty { display: none; }

section { margin: 0 0 3rem; }
section h2 { font-size: 1.1rem; margin: 0 0 0.35rem; }

.repair { margin: 0.5rem 0 0; }
/* A refusal's repairs and Skip, together, so Skip replaces them all. */
.repairs { margin: 0.25rem 0 0.5rem; }
.repairs .skip { margin: 0.4rem 0 0; }
/* One candidate identifier and the link to its registry's page. */
.candidate {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  margin: 0 1rem 0 0;
}
.candidate a { color: var(--role-muted); }
.candidate a:hover, .candidate a:focus-visible { color: var(--brand); }
.skip-note { margin: 0.25rem 0; }

/* ---------------------------------------------------------------- */
/* A running operation                                              */
/* ---------------------------------------------------------------- */

.job { margin: 1.5rem 0 0; }
.strip .job { margin: 0; }
.job-now, .job-progress {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
  margin: 0.3rem 0;
  font-family: var(--gutter);
  font-size: 0.8125rem;
}
.job-now:has(.job-step:empty) { display: none; }
.job-bar { flex: 1 1 12rem; max-width: 24rem; height: 0.35rem; }
.job-clock, .job-count { font-variant-numeric: tabular-nums; }

/* Idle, the strip is a status line: where the corpus stands, and the
   last operation as a link to it. */
.strip-status {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 1.2rem;
  margin: 0;
  padding: 0.3rem 0;
  font-family: var(--gutter);
  font-size: 0.8125rem;
}

/* A form whose request is out: htmx sets `htmx-request` on it and has
   already disabled the button (`hx-disabled-elt`). The cursor and the
   turning ring say the click was heard before the server answers. */
.htmx-request button[type="submit"] {
  cursor: progress;
}
.htmx-request button[type="submit"]::after {
  content: "";
  display: inline-block;
  width: 0.7em;
  height: 0.7em;
  margin-left: 0.5em;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  vertical-align: -0.1em;
  animation: turning 0.8s linear infinite;
}
@keyframes turning { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .htmx-request button[type="submit"]::after { animation: none; }
}

/* The Activity page: one row per operation kept. */
.activity { border-collapse: collapse; font-family: var(--gutter); }
.activity td { padding: 0.3rem 1rem 0.3rem 0; border-bottom: 1px solid var(--rule); }
.activity .started { font-variant-numeric: tabular-nums; }
.job-page h1 { margin-bottom: 0.5rem; }
.job-lines {
  list-style: none;
  margin: 0.5rem 0;
  padding: 0;
  font-family: var(--gutter);
  font-size: 0.8125rem;
}
.job-outcome { margin: 1rem 0 0; }

/* ---------------------------------------------------------------- */
/* Narrow screens                                                   */
/* ---------------------------------------------------------------- */

/* A table scrolls sideways rather than pushing the page wider.
   Measured: one paper sets 55 of its equations inside single-cell
   tables, and the widest is 1050px against a 1280px viewport that
   the margin has already spent 300px of - so the whole page gained
   a horizontal scrollbar and the reading column moved under the
   reader's thumb. `display: block` is what makes `overflow-x` apply
   to a table at all; the rows keep their own layout inside it. */
article table {
  display: block;
  max-width: 100%;
  overflow-x: auto;
}

/* A displayed equation gets room around it and is allowed to scroll
   sideways rather than force the whole page to. A long matrix is
   wider than a reading measure and shrinking the text to fit would
   make the equation the least legible thing on the page. */
.math.block {
  margin: 1.4rem 0;
  overflow-x: auto;
  overflow-y: hidden;
}

/* An equation number sits at the right margin of the column, which
   is where a paper puts it and where a cross-reference expects to
   find it. */
.math-label {
  float: right;
  font-family: var(--gutter);
  font-size: 0.85em;
}

@media (max-width: 46rem) {
  /* The margin goes above the column rather than beside it, and
     takes its place in document order - so the title comes first and
     the provenance follows it. That is a different order from the
     wide layout, and the right one here: a phone screen opens with
     the thing a reader recognises, not with an identifier. */
  .hits li { grid-template-columns: 1fr; row-gap: 0.4rem; }
  .hits li > * { grid-column: 1; }
  .hits .detail { grid-row: auto; text-align: left; }
  /* The pane leaves the grid: on a phone the window is the column
     and the bar, and the pane would take most of the width. Its
     places are still reachable from the bar's search and actions. */
  .shell, :root[data-pane="closed"] .shell {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: "bar" "main" "strip";
  }
  .pane { display: none; }
  #pane-toggle { display: none; }
  .resize-pane { display: none; }
  .action .label { display: none; }
  .palette-open .kbd { display: none; }
  .searchbox { order: 3; flex-basis: 100%; max-width: none; flex-wrap: wrap; }
  main { padding: 1.5rem 1rem 4rem; }
}

/* Too narrow for the text and the inspector side by side: one
   scrolling column again, with the inspector after the text. */
@media (max-width: 900px) {
  main.document { overflow-y: auto; display: block; }
  .document-body { display: block; }
  .reading { overflow: visible; }
  .inspector { width: auto; border-left: 0; border-top: 1px solid var(--rule); }
}

/* ---- motion ----
   Short and saying where a thing came from: nothing here takes more
   than a quarter of a second, and each entry is `@starting-style`, so
   the browser animates whatever is newly drawn - a dialog `dialog.js`
   opened, a menu its summary opened, hits htmx swapped in, a job the
   strip drew - with no event handled anywhere. Nothing animates
   leaving: a closed dialog is removed at once. */

/* Moving between pages cross-fades the centre; the shell is named, so
   the bar, the pane and the strip hold still. */
@view-transition { navigation: auto; }
::view-transition-old(root),
::view-transition-new(root) { animation-duration: 0.15s; }

.dialog[open] {
  opacity: 1;
  translate: 0 0;
  transition: opacity 0.18s ease, translate 0.18s ease;
}
.dialog[open]::backdrop { transition: background-color 0.18s ease; }
@starting-style {
  .dialog[open] { opacity: 0; translate: 0 0.5rem; }
  .dialog[open]::backdrop { background-color: transparent; }
}

@starting-style {
  .menu-items { opacity: 0; translate: 0 -0.25rem; }
}

@starting-style {
  .hit { opacity: 0; translate: 0 0.25rem; }
}

.strip .job { transition: opacity 0.2s ease; }
@starting-style {
  .strip .job { opacity: 0; }
}

/* Every disclosure grows open and shrinks shut. Not a row's menu: its
   items are positioned outside its box, and the clip would hide them. */
details:not(.menu)::details-content {
  block-size: 0;
  overflow: hidden;
  transition: block-size 0.2s ease, content-visibility 0.2s allow-discrete;
}
details:not(.menu)[open]::details-content { block-size: auto; }

/* What a fetch puts on the page fades in where it lands. */
.branch > *, #add-preview > *, .chooser > *, #outcome > * {
  transition: opacity 0.2s ease;
}
@starting-style {
  .branch > *, #add-preview > *, .chooser > *, #outcome > * { opacity: 0; }
}

button, a.button, .action { transition: translate 0.08s ease, border-color 0.15s ease; }
button:active,
a.button:active { translate: 0 1px; }

@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  /* `*` selects no view transition pseudo-element. */
  @view-transition { navigation: none; }
}
"""


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
