# Realigning the workbench, 3: the search box and the head of the results

Milestone / step: milestone 11 realigned with the approved mockup (#447)
Date: 2026-10-12

## What I am about to do

Draw the search box and the results' head as the mockup does, where the
plan does not decide otherwise:

1. **One search box.** A search icon, the input, a `/` key hint, then
   the scope and mode selects inside the same border. No visible
   Search button.
2. **A results head.** "9+ results for "selfcal"" on the left and the
   Order control on the right, drawn as a segmented control. The limit
   sentence is shown only when the results have been reordered, since
   that is the only time it describes what is on the page.
3. **Group heads** carry the collection's icon, its name as the pane
   spells it, and how many hits it holds, over a rule in ink.
4. **Titles** in the operation colour.
5. **The handle** (`id=... chunk=...`) moves into the measures row, in
   the monospace face, instead of a line under the passage.

Kept against the mockup, because the plan decided after it: the key line
under the head (#408), the measures as icons with tooltips (#417), and
the arrow that opens the document at the passage (11c: "following the
passage into the document is an icon").

## How I expect it to work

**The box.** `base.html`'s form gains the `search` icon (Lucide, to be
vendored) before the input and a `<kbd class="kbd">/</kbd>` after it.
The submit button stays in the markup with `visually-hidden`: a test
keeps it there because the Enter key and the scriptless path depend on
it. `hint.js` gains the `/` handler: on `keydown` of `/` with no
modifier, when the focus is not in a field, it focuses the box and
prevents the character. The words stay in Python; the key's title is a
`data-` attribute or `title` written by the server.

**The head.** `_hits_context` already computes the total and whether a
scope filled its quota, for the history. Computing both once and putting
them in the context as `found`/`capped` lets the head say
`words.results_for(count, capped, question)`. `ORDER_CHOICES` labels
become "As ranked", "Keywords", "Meaning", because "Order: By keywords"
in a segmented row repeats itself. `orders` stays a list of links (no
script needed), drawn inside `.results-head`. `order_limit` appears only
when `order` is not empty.

**Groups.** `ShownGroup` gains `icon` and a `count` property; `heading`
becomes the collection's own name. The context scope's icon is `folder`,
as the pane draws `.context`.

## What I expect to be uncertain or difficult

- Tests that match `<h2 class="place">`, `<nav class="order"` and
  "Literature" by text. They describe the old layout and are rewritten
  where the layout is what changed, not where a behaviour did.
- Whether "/" collides with anything: the palette uses Ctrl K, menus use
  Escape. Typing "/" into the search box itself, or a note's textarea,
  must still type it.
- The narrow layout: the mockup hides the key hint and the mode select
  below 600px. The mode select carries a choice, so hiding it is a loss;
  check how it wraps before deciding.

## What actually happened that I did not expect

- **The hidden submit button was 34px wide.** `.visually-hidden` set a
  1px width but not the button's own padding and border, so its box was
  larger than intended. It was clipped and absolutely positioned, so
  nothing showed; the rule now zeroes padding and border as the usual
  form of it does.
- **The count was already computed, for the history.** The total and
  whether a scope filled its quota were inline arguments to
  `history.record`. They are computed once now and given to both the
  head and the history, so the two cannot disagree about "9+".
- **Three old tests named the old markup**: `<p class="handle">` twice
  and the capitalised "Notes". They were rewritten to the new elements;
  none of them was about a behaviour that changed.
- **`.title` was a bare class used only by hits.** It is `.hit .title`
  now, so the operation colour cannot reach a later `.title` elsewhere
  (#425's lesson).
- The order labels became "As ranked", "Keywords", "Meaning": after the
  word "Order" in a segmented row, "By keywords" repeated itself.
- The mode select stays visible at 600px. The mockup hides it there,
  but it carries a choice the reader made, and it wraps acceptably.
- Walked on Brian's corpus, light and dark at 1280px and light at
  600px. Titles compute to the operation colour in both themes, the
  group rule to ink, the limit appears only on the reordered page, and
  `/` from the corpus page focuses the box without typing a slash.
- Injections: twelve, all caught.
