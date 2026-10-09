# 11a. The shell

Milestone / step: milestone 11, unit 11a (`design/plan.md`)
Date: 2026-10-09

## What I am about to do

Replace the sidebar-and-pages window with the three-pane shell: a bar of
actions, the corpus and context as a tree on the left, the reading column in
the centre, and a strip along the bottom that every operation reports into.
Manage stops being a page; its four forms become dialogs, each also a page.

## How I expect it to work

**One route per action.** `GET /add` shows the add form and `POST /add`
starts an add; likewise `/index`, `/sync`, `/context-sync`, `/pack`. The
`/manage/*` POST paths are renamed to these, and `GET /manage` and
`GET /held` go. A GET asked for by htmx (`HX-Request: true`) answers with a
`<dialog>` fragment; any other GET answers with the same form inside the
whole shell, so a reader without a script reaches every form (#366's rule,
widened from the search box to every action).

**The bar** is `base.html`'s, on every page: the pane toggle, the wordmark,
the search form, then the actions as `<a href="/add" hx-get="/add"
hx-target="#dialog">`. htmx turns the link into a fetch into `#dialog`;
without htmx it is an ordinary link to the page. `static/dialog.js` calls
`showModal()` when a `<dialog>` arrives in `#dialog`, and closes it when a
form inside it has been sent.

**The search form moves into the bar**, so it is on every page and needs
`action="/"`: with no action, a scriptless search from `/corpus` would go to
`/corpus?q=`. Its htmx attributes (`hx-get="/hits"`, live search) are
rendered only on the search page, where `#hits` exists; elsewhere Enter is a
plain navigation to `/`. The test asserting "no action" becomes "action is
`/`, and never `/hits`".

**The pane** is drawn from `holdings(context)` - one row per collection with
its count and whether its index is current - which costs about 50 ms on
Brian's 56 documents. The documents are **not** drawn on every page:
measured, `shown_groups` for every collection is about 40 ms for 56
documents, which is 0.7 s at a thousand. Each collection is a `<details>`
whose body is fetched from `GET /tree/{collection}` when first opened
(`hx-trigger="toggle once"`); its name is also a link to
`/collection/{name}`, the scriptless way in. The context section is headed
by the bundle's parent directory's name and fetched from `GET /tree/context`
from `bundle_documents`.

The pane is reached through a Jinja global **function** taking the request,
like `sidebar_state`, because not every route builds its context through
`_frame` and the pane varies. A corpus that cannot be read leaves the pane
saying so rather than failing the page.

**The strip** holds `<div id="job">` - where every dialog's form posts its
job panel - and, when idle, the corpus's short revision and how many
collections are searchable. Every page has it, so a dialog submitted from
any page has a target. Making a job survive navigation is 11b.

**Icons** are Lucide SVG files under `static/vendor/icons/`, inlined by a
Jinja global `icon(name)` that reads them once. Inlined rather than `<img>`
so `currentColor` works. `NOTICE.txt` declares them and `LICENSE-Lucide.txt`
carries the ISC text, which the licence requires. The vendoring tests'
pattern gains `.svg`, and a "used" test asks that every vendored icon is
named by some template (#357's third question).

**The layout** is a grid on `body` sized by `100dvh`, so the strip is always
at the bottom of the window whatever its height.

## What I expect to be uncertain or difficult

- `hx-trigger="toggle once"` on a `<details>`: the `toggle` event does not
  bubble, so it must sit on the `<details>` itself. Unverified.
- Whether `showModal()` on a swapped-in `<dialog>` keeps focus correctly and
  Escape closes it in WebKitGTK as in chromium.
- How many existing tests assert the sidebar, the Manage page or the old
  POST paths - every one has to be rewritten to state the new shape, not
  deleted.
- The `samesite=strict` and token guard must cover `/tree/*` and the dialog
  routes; the middleware does that, but the guard test should list them.

## What actually happened that I did not expect

- **`remember` never builds a collection's first index**, so the test
  that expected `write_note` to make notes "current" was wrong about the
  engine, not the pane. It now walks the real sequence: never indexed,
  `corpus index --collection notes`, current, then a note written with
  `index=False`, behind. Better coverage than the test first written.
- **A centring rule on `main > *` was undone by `h1 { margin: ... }`**,
  equal specificity and later in the sheet, so the corpus page's heading
  sat beside its table. Invisible in the source, obvious in the picture -
  the layout version of #351 and #371. One element, `.column`, now owns
  the centring.
- At phone width the two selects took the search row and left the box a
  sliver; the box has a minimum width and the row wraps.
- `toggle once` on `<details>` worked first time in chromium, and the
  dialog opened as a modal and was removed on Escape. Neither is yet
  confirmed in pywebview's WebKitGTK.
- **A reader without a script reaches every form but cannot submit one
  usefully**: the forms post through htmx only, as the Manage page's did.
  The plan's sentence would have overclaimed; recorded as #412.
- Measured in the headless shell against Brian's corpus, GETs only: the
  strip's bottom edge is the window's (860 of 860 px), no horizontal
  scroll at 400 px, no console errors.
- Eight injections, each caught by the test written for it: lazy tree,
  search action, job target outside the strip, dialog/page inverted, a
  second route, empty read as never indexed, toggle inside the pane,
  height by arithmetic.
