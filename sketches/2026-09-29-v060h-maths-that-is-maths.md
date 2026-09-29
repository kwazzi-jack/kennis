# Maths that is maths, not dollar signs

Milestone / step: v0.6h, interface work
Date: 2026-09-29

## What I am about to do

Two defects, both of which put raw TeX or raw dollar signs in front of a
reader who should have seen typeset maths.

First, `$$...$$` written on one line - which is how the converted RIME
paper writes every equation inside a table cell - is not recognised as
display maths. `dollarmath_plugin` is configured without `double_inline`,
so its inline rule matches the *inner* pair and the outer dollars survive
into the HTML. Measured on the corpus held: 104 surviving dollar signs in
that one paper, 13 of 55 documents affected.

Second, `static/typeset.js` selects `span.math`. Display maths renders as
`<div class="math block">`, so a display equation is never typeset at all
and the reader sees `a^2 + b^2 = c^2` as text.

Third, and only because it is in the way: `katex-auto-render.min.js` is
loaded on every page and never called. `typeset.js` renders the elements
directly, and says in its own comment why. An unused vendored asset is a
request the reader pays for and a licence entry that claims something the
interface does not do.

## How I expect it to work

`_parser` in `render/html.py` passes `double_inline=True`. That alone
fixes the dollars, but `mdit_py_plugins` renders `math_inline_double` as
a `<div>`, and a `<div>` inside a `<p>` is invalid nesting that a browser
closes the paragraph to escape. So kennis supplies its own render rules
for all four maths tokens, the same way it already does for `fence` and
`image`:

| token | element | `displayMode` |
|---|---|---|
| `math_inline` | `<span class="math inline">` | no |
| `math_inline_double` | `<span class="math inline display">` | yes |
| `math_block` | `<div class="math block">` | yes |
| `math_block_label` | `<div class="math block">` + label | yes |

A `<span>` for the double-inline case is the decision: it nests legally
wherever text does, which is the whole point of the case existing. The
element carries the classes and `typeset.js` reads `display` from them,
so the two files agree through the class list rather than through two
copies of the same rule.

`typeset.js` selects `.math` rather than `span.math` and sets
`displayMode` from `classList.contains("block") ||
classList.contains("display")`.

The content is escaped by kennis rather than left to the plugin, because
these rules replace the plugin's. `_escaped` already exists and is what
`_render_fence` uses.

`katex-auto-render.min.js` is deleted, its `<script>` tag removed from
`base.html`, and `vendor/NOTICE.txt`'s KaTeX entry loses that filename.
The notice test matches on filenames, so a stale name there fails.

## What I expect to be uncertain or difficult

Whether `math_block_label` carries its label as `token.info` or as a
second token, and what the label should render as - a right-aligned
`(eq1)` beside the equation is what a paper means by it, but KaTeX does
not place it and doing so is CSS work this unit does not need.

Whether `double_inline=True` changes anything for text that is not maths
at all. A document that writes a price twice in one paragraph - `$5 and
$10` - is already at risk from the single-dollar rule; the double rule
could make a new false positive out of `$$` appearing for some other
reason. Measuring the corpus before and after is the check.

Whether `allow_space` (on by default) is already producing false
positives that the dollar count hides, since a surviving dollar is
visible and a wrongly-consumed one is not.

## What actually happened that I did not expect

**Both named uncertainties resolved cheaply, and neither was the
problem.** `math_block_label` carries its label in `token.info`, one
string, no second token. And `double_inline=True` changed exactly one
document out of 55 across the whole corpus, creating 49
`math_inline_double` tokens and no false positives anywhere - the
worry about `$5 and $10` was unfounded, because the double rule needs
two adjacent dollars and prose does not write them.

**Two defects the tests could not have found, both found by opening
the page.**

The first: the whole page scrolled sideways.
`document.documentElement.scrollWidth` was 1348 against a 1280
viewport. The cause was a table 1050px wide - the paper sets 55 of
its equations in single-cell tables - and nothing in the stylesheet
was wrong, a rule was simply absent. Concern #360.

The second, and the one I would not have predicted: **16 of that
paper's 419 expressions failed to parse**, all for one reason.
MinerU writes `\begin{array}[]{c}`, an optional argument with nothing
in it, and KaTeX fails on the `]`. I had been looking for dollar
signs and these were not dollar signs - they were red source text,
which looks like a rendering choice rather than a failure until you
count them. Stripping an empty option is now done at render time, and
it is a decision rather than a fix, so it is written up as concern
#358 with the line it does not cross.

**The unused vendored script was found by accident.** I went looking
for where `renderMathInElement` was called so I could change its
delimiters, and it was called nowhere.
`katex-auto-render.min.js` had been downloaded on every page load for
four units. Both notice tests passed the whole time, because one asks
whether what is present is declared and the other whether what is
declared is present, and neither asks whether anything uses it.
Concern #357.

**A comment turned out to be false, in the way #82 and #318 were.**
`typeset.js` said its catch block leaves the source visible. It does
not: `throwOnError: false` means KaTeX does not throw, so the ordinary
failure never reaches the catch at all - KaTeX's own error style is
what the reader sees. The comment now says that.

**Three equations are not recoverable and the reason is upstream.**
`\langle|e_{x}|^{2}\rangle` inside a table cell is split at the pipe
by the table parser before any maths rule runs. Block parsing
precedes inline parsing, so there is no ordering that avoids it, and
pre-escaping would mean editing `Document.body` and moving every
chunk offset. Concern #359, left open against the converter.

**One test of mine was wrong before the code was.** The selector test
matched maths elements with `\bmath\b`, which also matches
`math-label`, because a hyphen is a word boundary. It failed
immediately and correctly - on the equation number, not on maths.

