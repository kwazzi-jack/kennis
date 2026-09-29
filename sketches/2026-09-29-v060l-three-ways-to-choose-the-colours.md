# Three ways to choose the colours

Milestone / step: v0.6l, interface work
Date: 2026-09-29

## What I am about to do

Brian asked whether there is a light/dark/system toggle. There is
not: `stylesheet()` emits the light palette at `:root` and the dark
one inside `@media (prefers-color-scheme: dark)`, and nothing else.
The reader follows the operating system and has no say.

Three states, then - `system`, `light`, `dark` - with `system`
meaning what happens today.

## How I expect it to work

**The CSS gains one guard and one rule**, and that is the whole of
the mechanism:

    :root { ...light... }

    @media (prefers-color-scheme: dark) {
      :root:not([data-theme="light"]) { ...dark... }
    }

    :root[data-theme="dark"] { ...dark... }

The guard is what makes an explicit `light` survive a dark system:
without it the media query would win on specificity grounds every
time the system is dark, and the choice would appear to do nothing
on exactly the machines where it matters. The third rule is what
makes an explicit `dark` work on a light system.

`system` needs no rule at all. It is the absence of the attribute
being anything the other two match, which means the default is the
current behaviour and a reader who never touches the control
notices nothing.

**The state is a cookie, the same as the sidebar's.** That decision
was made in v0.6k for the same reason it applies here and more so:
read from `localStorage` after paint, the page would render in the
system's colours and then repaint into the chosen ones, which is a
flash of the wrong palette on every single page load. `<html
data-theme="dark">` in the first byte has no such moment.

A `<select>` in the sidebar with the three labels from
`words.py`, and `theme.js` writes the attribute and the cookie on
change - the shape `sidebar.js` already has.

**The verification is a matrix, and it is the point of the unit.**
Three choices against two system settings is six combinations, and
four of them are only reachable by emulating the system preference.
Playwright can, so all six get walked.

## What I expect to be uncertain or difficult

Whether `:root:not([data-theme="light"])` inside the media query
actually beats plain `:root` outside it. I believe it does - it is
both later and more specific - but "the cascade did what I assumed"
is how #371 happened last unit, so this is measured rather than
reasoned about.

Whether the dark palette is legible at all. The contrast tests
cover both maps already, but nothing has ever *rendered* the dark
one: it has been emitted into a media query that this machine, in
a headless browser defaulting to light, has never triggered. I
expect to find something wrong in it, and I expect it to be
something the contrast test cannot see - a border, a shadow, a
ground that is not `--ground`.

Whether the select is legible against a dark ground. It inherits
`--ink` on `--ground` like the other controls, so it should be, but
form controls are where a browser's own defaults leak through.

## What actually happened that I did not expect

**The cascade did exactly what I assumed, and I am glad I measured
anyway.** All six combinations are right, and the one that would
have failed without the guard - a dark system with an explicit
`light` - is the one that proves the guard. Reading the CSS would
have convinced me; only the matrix established it.

**My expectation about the dark palette was wrong.** I predicted
finding something broken in it, on the reasoning that it had never
been rendered - it lived in a media query that a headless browser
defaulting to light never triggers. Nothing is broken. Nothing has
ink equal to the ground, and the manage page's forms, radios and
textarea are all legible. The contrast tests turn out to have been
enough, which is a better result than the one I expected and worth
recording as such.

**The first version of one test asserted something false.** It
iterated `CSS_COLOURS_DARK` expecting every colour in the explicit
dark rule, and failed on `blue` - which is in the palette and worn
by no role, so `css_variables` never emits it, in either copy.
`black` is the same. The real property is that the two dark blocks
are *identical*, which is what it asserts now and which is the
thing that actually matters: two places the palette is written must
not be able to differ.

**Adding a second `<select>` broke three tests at once.** All three
scanned every `<option>` on the page, so they picked up the theme
control's. None of them was wrong about scope - none of them had
*stated* a scope, having been written when there was only one
select. They now say which control they mean. Concern #375.

**And the dark screenshot showed a defect in something else
entirely.** A hit's snippet renders `$\mathsf{{B}}$` with the dollar
signs visible. v0.6h fixed that in `render/html.py`;
`gui/snippet.py` builds its own `MarkdownIt` without `dollarmath`
and nothing carried the fix across. Not this unit's, so it is
concern #376 and the next unit.

