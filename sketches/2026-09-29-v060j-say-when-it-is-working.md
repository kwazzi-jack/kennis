# Say when it is working

Milestone / step: v0.6j, interface work
Date: 2026-09-29

## What I am about to do

Concern #365 established that the Enter key was never broken, and
guessed at why it looked broken: `hx-trigger` debounces typing by
400ms, so the reader waits about 412ms with no sign anything is
happening, and Enter short-circuits that to 12ms. Both end in
results appearing, so neither reads as an action.

An indicator that covers only the request would be useless here -
the request is 12ms of the 412ms and would flash or be missed
entirely. It has to cover the wait the reader actually experiences,
which starts at the keystroke.

## How I expect it to work

**Derived from state, not latched by events.** The temptation is to
show on `input` and hide on `htmx:afterSwap`, and that gets stuck:
htmx's trigger is `input changed`, so typing a character and
deleting it fires no request at all and the indicator never comes
down. An event-latched flag has a failure mode that is silent and
permanent.

Instead the indicator answers one question, recomputed each time
anything could change the answer: **are the hits on the page the
hits for what is in the box?**

`hits.html` opens with a marker the server writes:

    <span class="answered" data-query="{{ question }}"
          data-scope="{{ scope }}" hidden></span>

It sits inside `#hits`, which is what htmx replaces, so every swap
brings a fresh statement of what the visible hits are for. Exact
string comparison, no trimming: htmx sends the input's value
verbatim and the server echoes it, so they are equal precisely when
the results match the box.

`static/searching.js` recomputes on `input`, on `change` of the
scope, and on `htmx:afterSwap`. Nothing is remembered between
those, so there is no state to get stuck.

One exception, which is the only remembered thing: a failed request
hides it. htmx does not swap on an error, so the marker still says
the old query and the indicator would otherwise say "Searching"
forever about a search that has stopped. `htmx:afterRequest` with
`detail.successful` false hides it; the next keystroke shows it
again, which is true.

The word is `words.SEARCHING`, and the element carries
`aria-live="polite"` so it is announced rather than only seen. It
goes in the gutter font and the muted role: kennis composed it, and
the invariant says what kennis composed goes in the margin.

## What I expect to be uncertain or difficult

Whether it flickers. On this machine a search is 12ms, so on a page
that is already up to date the indicator should never appear at all;
but during the 400ms debounce it should be visible the whole time. I
expect that to be right and I expect to be wrong about something in
it.

Whether `hidden` on an `aria-live` region actually announces. It is
the simplest mechanism and it is not guaranteed across screen
readers; a `visibility` or class toggle may be needed instead. I
cannot test this properly here and should say so rather than claim
it.

Whether the marker belongs in `hits.html` at all. It is an empty
element that exists to carry two attributes, which is the kind of
thing that reads as a hack. The alternative is an `hx-swap-oob`
fragment updating the form, which is more machinery for the same
fact.

## What actually happened that I did not expect

**The derived design was right and I could prove it, which I had not
expected to be able to do.** The stuck case is not hypothetical and
it is not subtle: type a character, delete it, and htmx's `input
changed` fires nothing. Measured in the browser, the indicator
stays hidden - an event-latched version would be showing
"Searching" about a search that will never happen, forever, until
the next keystroke. That case went into the walk deliberately
because the sketch named it, and naming it first is what made it
testable.

**A test I did not know about caught a real mistake.**
`test_every_class_the_templates_use_is_styled` failed on my marker's
`class="answered"`, which carries no styling because it is an
invisible data carrier. The right answer was an id, not a style
rule - the test was correct and my markup was lazy. Three units in
a row now where an existing test has caught something in passing.

**One measurement misled me and re-measuring fixed it.** Changing
the scope appeared not to show the indicator: `false` at 80ms after
the change. The explanation is that a scope change fires htmx
immediately, with no debounce, and the search is 12ms - so it was
already finished. Re-running with the response delayed by 900ms
shows it true at 60ms, 300ms and 700ms. I nearly recorded a defect
that was my instrument.

**The uncertainty I could not resolve, stated rather than
glossed.** Whether toggling `hidden` on an `aria-live` region is
announced by a real screen reader is not something this setup can
establish. It is the simplest correct-looking mechanism and it may
not be sufficient. Not claimed as working - concern #368 records it
as untested rather than as done.

**The marker still reads slightly like a hack** and I left it. An
empty `<span>` carrying two attributes is what it is; the
alternative, an `hx-swap-oob` fragment updating the form, is more
machinery for the same fact and puts the statement further from the
thing it describes.

