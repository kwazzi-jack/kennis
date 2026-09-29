# A sidebar, and one face that was doing two jobs

Milestone / step: v0.6k, interface work
Date: 2026-09-29

## What I am about to do

Three of Brian's items, and they turn out to be one piece of work:
everything around the reading column.

**The header becomes a sidebar on the left**, collapsible, and
present even when collapsed so it can always be reopened. It holds
the wordmark, the three pages, and the two actions Brian asked to
have one click away that are currently sections of Manage.

**The gutter stops being monospace.** Brian likes the serif column
and wants the small face improved; a system sans was chosen.

**And that is where the real work is.** `--gutter` is doing two
jobs. It is the face of the margin - provenance, counts, labels,
buttons - and it is also what `code, pre` is set in. Changing it to
a sans would put every code block and every inline span of code in
a proportional face, losing the alignment, the l/1/I and O/0
distinction, and the point of v0.6g's syntax highlighting. So the
variable has to split before it can change.

While looking at that: **`.role-command` has no face of its own.**
It is a generated colour role, so a printed command inherits
whatever surrounds it - monospace inside `.skipped`, and the
**serif body face** in `problem.html`, `outcome.html`,
`job-outcome.html` and `document.html`. The same command reads two
different ways depending on which page refused. rules.md 4.4 says a
printed command must run as printed; it should also look like one.

## How I expect it to work

**Two variables, divided by the rule the interface already uses.**

    --gutter   what kennis composed: provenance, counts, labels,
               buttons, messages.       -> a system sans stack
    --mono     what must be read or typed verbatim: `code`, `pre`,
               and `.role-command`.     -> the monospace stack

That is the margin/column division extended one step, and it names
why each thing wears what it wears. Eighteen of the nineteen current
uses of `--gutter` are chrome and stay `--gutter`; `code, pre` moves
to `--mono`, and `.role-command` gains `--mono` where it previously
had nothing.

**The sidebar's state is a cookie, so the server renders it.** The
alternative is `localStorage` read after paint, which shows the
sidebar open and then collapses it on every page load. A cookie is
on the request, so `<html data-sidebar="closed">` is correct in the
first byte and nothing flashes.

The value reaches every template without touching any route's
context: a Jinja global function taking the `request` Starlette
already puts in every `TemplateResponse`. `_frame` is the wrong
place - the invariant says so, because not every route builds its
context through it - and a Jinja global constant is the wrong place
too, because this varies per request.

The toggle writes the cookie and flips the attribute in the same
click, so there is no round trip. Both its labels are `data-`
attributes the server wrote, and the script picks one - the rule
`hint.js` follows.

**The list is ordered data in `words.py`**, pairs of href and
label. The three page labels are taken from `NAV_LABELS` rather than
repeated, so the existing test tying each to its page's `<h1>` keeps
covering them. The two shortcuts point at sections - `/manage#add`
and `/manage#index` - and those sections gain ids and a test tying
each label to its `<h2>`, which is the same discipline one level
down. `Add` becomes `Add documents` so the heading and the label are
the same words.

Narrow screens put it back across the top rather than off-canvas: a
static full-width bar under 46rem, which is what it is today, and a
great deal less machinery than a sliding overlay for a case Brian
does not use.

## What I expect to be uncertain or difficult

Whether `request` really is in the context for every route that
extends `base.html`. Starlette adds it for `TemplateResponse(request,
...)`, which is the form used here, but a fragment rendered another
way would raise at template time rather than fail a test - so the
test has to load every page, not one.

Whether the collapsed rail at 3rem is wide enough to be a target and
narrow enough to be worth collapsing to. I suspect 3rem is right and
that the toggle will look wrong rather than the width.

The toggle's mark. ASCII only, so no hamburger glyph and no arrows;
three bars drawn in CSS is the plan, and the accessible name comes
from Python.

Whether moving `#corpus-changed` matters. It sits between the header
and `main` today, and with `body` padded left it should simply land
in the right place - but it is the kind of thing that ends up
underneath a fixed element.

## What actually happened that I did not expect

**The sidebar was the easy half.** Everything about it worked first
time: the cookie renders the state with no flash, it survives
navigation in both directions, the collapsed rail keeps its toggle,
the shortcuts land on their sections, and the narrow layout reflows
without overflow. The uncertainties I named all resolved the way I
guessed, including `request` being present in every template.

**The two faces were the real work, and they found a third thing.**
`.role-command` having no face at all was not in the plan; I found
it while listing what `--gutter` touched. A printed command was
monospace inside `.skipped` and serif in four other templates, so
the same string read two ways depending on which page refused.
Concern #370.

**The browser found a defect the whole test suite could not, again.**
`.sidebar a` is one class plus an element; `.wordmark` is one class.
The more specific rule won, so the name of the interface rendered in
the grey meant for navigation. Measured rather than eyeballed -
which mattered, because it was subtle enough in a screenshot that I
almost moved on. Concern #371, and it is the **second** time a
colour has been lost to a rule nobody was looking at: #351 was the
first, and neither was visible in the source.

**Three of my own tests were hollow, and injection said so.**

Two matched a **comment**: the cookie test asserted `path=/` and
`samesite=strict` appeared in `sidebar.js`, and the sentence
explaining why they are there was in the comment block above. That
is concern #337 exactly - `Inter` inside "interface" - arriving in a
new place. The whole module now goes through one helper that strips
comments first, so it cannot recur here.

The third was tautological: every test compared the rendered page
against `SIDEBAR_LINKS`, so removing an entry removed it from both
and they still agreed. Nothing asserted the list contains what was
asked for. It does now, by naming the six destinations.

**And the colour-literal test had two false-positive classes.**
Adding `#add, #index { scroll-margin-top }` failed
`test_no_colour_is_written_outside_the_two_maps`, because an id
selector has the shape of a three-digit hex - and so does "concern
#351" in a comment. The test now strips comments and looks only at
declaration values, which is where a colour can be; verified it
still catches `#ff0000`, `rgb(1, 2, 3)` and a hex inside a
`border` shorthand. Narrowing a check to accommodate my own mistake
is the worst outcome available, so that verification was the point.
Concern #372.

