# The snippet shows maths too

Milestone / step: v0.6m, interface work
Date: 2026-09-29

## What I am about to do

Concern #376. A hit's snippet renders `$\mathsf{{B}}$` with the
dollar signs visible, in the middle of a sentence about the apparent
sky. v0.6h fixed that in `render/html.py`; `gui/snippet.py` builds
its own `MarkdownIt("commonmark")` and nothing carried the fix
across.

Two parsers, deliberately - concern #336 established that a snippet
is rendered by the window, because `snippet_of` collapses the
whitespace and a parse of the collapsed string makes a heading of the
paragraph after it. So the answer is not to merge them. It is to give
this one the same protection.

## How I expect it to work

`_tokens` uses `dollarmath_plugin(double_inline=True)`, the same as
`render/html.py`.

`_Run` gains a third kind. It currently distinguishes a tag from
text, so that truncation counts only what the reader sees and
marking touches only what the reader reads. TeX is neither: it is
escaped like text, but **must not be marked and must not be cut**.

    _Run(text, tag=None, maths=None)   # maths holds the class list

Three consequences, and each is the reason for the field:

- **Marking is skipped.** A search for "B" against
  `\mathsf{{B}}` would put `<mark>` inside the TeX, and KaTeX would
  render the tag or refuse the expression. The reader's term is not
  in the prose there in any case - it is in a symbol.
- **Truncation is all or nothing.** Half an expression is not an
  expression; `\left(\begin{array}` with no closing is a parse
  error where the whole thing would have rendered. A maths run that
  does not fit ends the snippet instead of being bisected.
- **It is escaped but not marked**, so `<` and `&` - both ordinary
  in TeX - cannot become markup.

**Everything is inline in a snippet.** A `math_block` is rendered as
an inline span rather than a display one: a snippet is one paragraph
of prose, and KaTeX's display mode is a block element that would
break the line in the middle of the sentence quoting it. Today a
block equation is *invisible* in a snippet, because `_runs` only
walks `inline` tokens - so this is a gain either way.

**The `\begin{array}[]` repair moves to where both can read it.**
Concern #358 put it in `render/html.py` as a private constant. A
snippet's TeX needs the same repair or it will fail to parse where
the same document's body succeeds, so it becomes a named function in
`render/`, which `gui/` may import - the dependency runs
`gui -> render -> engine` and this is exactly what that allows.

`typeset.js` already listens on `htmx:afterSwap` and selects
`.math`, so a swapped-in snippet typesets with no further work.

## What I expect to be uncertain or difficult

Whether counting a maths run's raw TeX length against the 280
character budget is acceptable. It is wrong in principle - `\alpha`
is six characters and renders as one - but it errs towards shorter
snippets, which is the safe direction.

Whether `math_block` reaching `_runs` at all requires a change. The
loop skips anything that is not an `inline` token with children, and
a `math_block` is a leaf block token, so it needs its own branch
rather than falling out of the existing one.

Whether the closing-tag arithmetic in `_truncated` still holds once
a run can be neither tag nor plain text. It counts opened against
closed tags, and a maths run has no tag, so I expect it to be
untouched - but that arithmetic is subtle and it is the thing most
likely to be quietly wrong.

## What actually happened that I did not expect

**The closing-tag arithmetic was untouched, as hoped.** A maths run
has no tag, so the count of opened against closed is unaffected. It
was the thing I named as most likely to be quietly wrong and it was
not wrong at all.

**Two of my own tests were wrong, and one of them in an instructive
way.**

The first used a one-character term, `B`. `_SHORTEST_TERM` is 2, so
it is not marked *anywhere* - the test passed its "no mark inside
the maths" assertion for the wrong reason and failed the "still
marked in the prose" one. A fixture that cannot exhibit the property
under test.

The second is worse and worth naming: it set a limit the expression
could not fit in, and then asserted the expression was present and
whole. Those are the two halves of one rule - *does not fit, so is
dropped* and *fits, so is whole* - asserted as if they were one
case, which is neither of them. It is now two tests, and the second
says in its docstring that it would pass for free if the first were
implemented by dropping every expression.

**Measured on the real corpus afterwards**: searching "selfcal"
gives zero literal dollar signs in the results, two maths spans,
both typeset, no KaTeX errors, and the four query marks still in
place. The snippet that showed `$\mathsf{{B}}$` now shows the
symbol.

**The repair's move to `render/` was the tidiest part.** It was a
private constant in `render/html.py` and became a named function
there, which `gui/` may import because the dependency runs
`gui -> render -> engine`. One rule, two renderers, in the layer
both can read - no new layering, and the alternative would have
been a second copy of a regular expression whose whole value is
being narrow.

