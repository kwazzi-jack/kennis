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

from typing import Final

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


def css_variables(
    colours: dict[AnsiColour, str] | None = None, ground: str | None = None
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
    return (
        f":root {{\n{css_variables()}\n}}\n\n"
        "@media (prefers-color-scheme: dark) {\n"
        f":root {{\n{css_variables(CSS_COLOURS_DARK, DARK_GROUND)}\n}}\n"
        "}\n\n"
        f"{css_weights()}\n\n{code_css()}\n\n{_LAYOUT}"
    )


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

:root {
  /* The margin holds a line like `relevance: low id=nwgswtko72`,
     which is 40 monospace characters at its longest. */
  --margin: 11rem;
  --gap: 1.75rem;
  /* Under 70 characters of the column face at 1.0625rem. */
  --measure: 33rem;
  --column: 'Source Serif 4', Charter, Cambria, Georgia, serif;
  --gutter: ui-monospace, 'DejaVu Sans Mono', 'Cascadia Mono', Menlo, monospace;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: var(--column);
  font-size: 1.0625rem;
  /* A serif wants more leading than a sans at the same size. */
  line-height: 1.6;
}

main {
  max-width: calc(var(--margin) + var(--gap) + var(--measure));
  margin: 0 auto;
  padding: 2.5rem 1.5rem 6rem;
}

/* The header is the one hairline in the design. It separates the
   interface's own furniture from everything below it, which is
   either kennis speaking or the corpus speaking. */
header {
  display: block;
  padding: 1.4rem 1.5rem 0.9rem;
  border-bottom: 1px solid var(--rule);
  font-family: var(--gutter);
  font-size: 0.8125rem;
}

header nav { display: flex; gap: 1.5rem; margin-top: 0.7rem; }
header a { color: var(--role-muted); text-decoration: none; }
header a:hover { color: var(--ink); text-decoration: underline; }

/* The one place the interface says its own name, and it says it
   once. It was the first item in the navigation, at the same size
   as "manage", so the page had no title at all - the search page
   in particular opened on a box and nothing saying what it
   searched. Set in the text face rather than the gutter's
   monospace, because it is a name and not a field. */
.wordmark {
  display: block;
  font-family: var(--column);
  font-size: 1.6rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1;
  color: var(--ink);
}
.wordmark:hover { text-decoration: none; }

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
  /* Each field on its own line, which `white-space` gives without
     the engine having to hand over the parts separately. */
  white-space: pre-wrap;
  word-break: break-word;
}

a { text-underline-offset: 0.15em; text-decoration-thickness: from-font; }

/* A result's title is underlined on hover and not before. An inline
   link inside prose keeps its underline, because there it is the only
   thing distinguishing it from the sentence around it; a title in a
   list of results is already the one bold line in its row, and three
   underlined lines per hit was the loudest thing on the page. */
.hits a { color: var(--ink); font-weight: 600; text-decoration: none; }
.hits a:hover, .hits a:focus-visible { text-decoration: underline; }
.hits .body { color: var(--role-muted); }
/* Where the query matched. A wash rather than a block of colour:
   the marked words are still the corpus's prose and should read as
   prose with something behind them, not as a separate element. */
mark {
  background: var(--mark);
  color: var(--ink);
  border-radius: 0.15em;
  padding: 0 0.1em;
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

/* Back to the results, and to the collection. A document reached
   from a search had no way to anything: its only links were the
   figures control and the citations in its own text. */
.back {
  font-family: var(--gutter);
  font-size: 0.75rem;
  display: flex;
  gap: 1rem;
  margin: 0 0 1.5rem;
}

.back a { color: var(--role-muted); }
.back a:hover { color: var(--ink); }

/* The scale a group's bands are measured on. Relevance is never
   shown without it. */
.basis {
  font-family: var(--gutter);
  font-size: 0.75rem;
  color: var(--role-muted);
  margin: 2rem 0 0;
}

.count { font-family: var(--gutter); font-size: 0.8125rem; margin: 0; }

/* ---------------------------------------------------------------- */
/* Reading                                                          */
/* ---------------------------------------------------------------- */

h1, h2, h3 { line-height: 1.25; font-weight: 600; }
h1 { font-size: 1.75rem; margin: 0 0 1.25rem; }
h2 { font-size: 1.3rem; margin: 2.5rem 0 0.75rem; }
h3 { font-size: 1.1rem; margin: 1.5rem 0 0.5rem; }

article { max-width: var(--measure); }
article h1 { margin: 0 0 0.5rem; }
article p { margin: 0 0 1rem; }
article img { max-width: 100%; height: auto; }

.provenance {
  font-family: var(--gutter);
  font-size: 0.75rem;
  color: var(--role-muted);
  margin: 0 0 2rem;
  /* The three facts on three lines. A row of them joined by
     separators is the shape every generated page reaches for, and it
     reads as decoration rather than as three different answers. */
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

/* The passage a search hit pointed at. A rule in the margin rather
   than a background wash: the mark has to be findable at a glance
   while a paper is scrolled, and a wash behind body text competes
   with the text for the eight colours available here.

   `scroll-margin-top` is what makes the fragment land correctly -
   without it the browser puts the anchor at the top of the viewport,
   where the header sits over it. */
.chunk {
  border-left: 2px solid var(--role-hint);
  padding-left: 1rem;
  margin-left: -1.25rem;
  scroll-margin-top: 2rem;
}

code, pre {
  font-family: var(--gutter);
  font-size: 0.9em;
}

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

input, select, textarea, button {
  font: inherit;
  font-size: 0.9375rem;
  color: var(--ink);
  background: var(--ground);
  border: 1px solid var(--rule);
  border-radius: 3px;
  padding: 0.4rem 0.6rem;
}

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

section { margin: 0 0 3rem; }
section h2 { font-size: 1.1rem; margin: 0 0 0.35rem; }

.repair { margin: 0.5rem 0 0; }

/* ---------------------------------------------------------------- */
/* A running operation                                              */
/* ---------------------------------------------------------------- */

.job { margin: 1.5rem 0 0; }
.job-bar { width: 100%; height: 0.35rem; }
.job-step { font-family: var(--gutter); font-size: 0.8125rem; margin: 0.4rem 0; }
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

@media (max-width: 46rem) {
  /* The margin goes above the column rather than beside it, and
     takes its place in document order - so the title comes first and
     the provenance follows it. That is a different order from the
     wide layout, and the right one here: a phone screen opens with
     the thing a reader recognises, not with an identifier. */
  .hits li { grid-template-columns: 1fr; row-gap: 0.4rem; }
  .hits li > * { grid-column: 1; }
  .hits .detail { grid-row: auto; text-align: left; }
  header { padding: 1.1rem 1rem 0.8rem; }
  header nav { flex-wrap: wrap; gap: 0.9rem; }
  main { padding: 1.5rem 1rem 4rem; }
}

@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
"""


__all__ = [
    "CSS_COLOURS",
    "CSS_COLOURS_DARK",
    "DARK_GROUND",
    "LIGHT_GROUND",
    "css_variables",
    "css_weights",
    "layout_css",
    "stylesheet",
]
