# The search box names the scope it is pointed at

Milestone / step: v0.6i, interface work
Date: 2026-09-29

## What I am about to do

Two items from Brian's list, and one of them turned out not to be a
defect.

The placeholder always reads "Search everything kennis holds", even
when the scope select says `literature`. It should name the scope:
"Search literature kennis holds". Plain text, no italics - a
`placeholder` attribute cannot carry markup, and Brian chose the
wording change over an overlay that could.

The Enter key **already submits**, and I measured it rather than
assuming: typing then pressing Enter fires a request in 12ms, ahead
of the 400ms debounce, renders 9 hits and pushes
`/?q=selfcal&scope=all` into the address. Pressing it again on an
unchanged query re-submits. So there is nothing to build, and the
right response is a test, because nothing asserts it and two small
edits would take it away - dropping `submit` from `hx-trigger`, or
removing the submit button, which is what makes a browser submit a
form on Enter at all.

While checking that I found something nobody planned: **the
interface works with JavaScript disabled.** The form carries no
`action`, so a native submission goes to the current path with `q`
and `scope` as the query string - which is exactly the address the
page reconstructs from. Measured: the query runs, 9 hits render, the
box keeps the query. That falls out of #340 and is one `action="/hits"`
away from being lost, so it gets a test too.

## How I expect it to work

`words.search_hint_for(scope)` returns the sentence, so the words
stay in Python:

    f"Search {EVERYWHERE_LABEL if scope == EVERY_SCOPE else scope} kennis holds"

`SEARCH_HINT` becomes that function's value for `EVERY_SCOPE` rather
than a separate constant, so the two cannot drift apart.

The page renders the placeholder for the scope it was drawn with.
Changing the select has to change it without a round trip, and the
words must not move into JavaScript to do that: each `<option>`
carries `data-hint`, written by the server, and `static/hint.js`
copies the selected option's `data-hint` onto the input. The script
moves a string it did not compose - the same rule `progress.js`
follows.

The input is not swapped by htmx (only `#hits` is), so nothing
undoes this.

## What I expect to be uncertain or difficult

Whether the wording reads correctly for every scope name. "Search
notes kennis holds" is fine; "Search context kennis holds" may not
be - the context scope is a bundle, not a category of document, and
its name in `SCOPE_NAMES` is whatever `CONTEXT_COLLECTION` is.

Whether a test can say anything honest about the Enter key. The
browser behaviour is the specification's, not kennis's; what kennis
owns is the markup that invokes it. A test of the markup is a proxy,
and the docstring should say that the behaviour itself was measured
in a browser rather than implying the test proves it.

Whether the no-JavaScript path is worth asserting as two tests - the
absent `action` and the server answering `GET /?q=...` - or whether
the second already exists from #340.

## What actually happened that I did not expect

**The unit was half as large as the request, because one of the two
items was not a defect.** Measuring first was the whole value here:
had I written the sketch from the request I would have "fixed" a
working Enter key and reported it as a fix. The measurement took two
minutes and the honest answer is a test, not a change.

**All three named uncertainties resolved, and the first one stands.**
"Search context kennis holds" does read oddly - `context` is a
bundle, not a category of document. I left it, because the select
itself says `context`, so the box and the thing beside it agree, and
a sentence composed differently for one scope would make a reader
wonder what was special about it. The right fix, if it is one, is a
better label for that option, which is a different change. Concern
#367.

**The no-JavaScript path turned out to be fully testable in pytest**,
which I had doubted. The browser half is "a form with no `action`
submits to the current path", which is the specification's; the
kennis half is the absent `action` and the server answering
`GET /?q=...&scope=...` with a whole page. Both are assertions, and
together they are the mechanism. The browser run confirmed the
composition.

**Something I did not intend to touch broke, and it was right that
it did.** `test_everywhere_is_a_scope_and_it_is_the_default`
asserted `value="all" selected` as a substring - two attributes that
happened to be adjacent. Writing `data-hint` between them broke it
while changing nothing about which scope is selected. It now parses
the options and asserts exactly one is selected and which, which is
the property. That is concern #352's rule arriving from the other
direction: not a test that passes for the wrong reason, but one that
fails for the wrong reason.

**The placeholder survives a search without any work.** htmx swaps
`#hits` only, so the input is never replaced. I had listed this as a
thing to check rather than a risk, and it was not one.

