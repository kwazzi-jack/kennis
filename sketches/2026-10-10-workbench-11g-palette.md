# 11g. The palette

Milestone / step: milestone 11, unit 11g (`design/plan.md`)
Date: 2026-10-10

## What I am about to do

A command palette: one list of every action and place, actions first,
each with its kind on the right, filtered as it is typed, Up and Down
wrapping, the selection kept in view, Enter to run, Ctrl K to open.
Foreground colour by kind so the list is not grey. Every entry is an
alias of an existing route - nothing the palette does is reachable only
through it.

## How I expect it to work

**The server draws the list.** `GET /palette` goes through `_action`
like every bar action: htmx fetches it into `#dialog` and `dialog.js`
opens it; without a script it is a page of links, which is a usable
index of the window. Entries come from `gui/pages.py::palette_entries`,
built from words in `gui/words.py`:

- actions: Add a paper, Add a documentation site, Add a file, Add
  several by group (the four `/add?kind=` tabs), Write a note, Index
  every collection, Index each collection (`/index?collection=`),
  Synchronise, Install a pack;
- places: each collection (`/collection/<name>`), the corpus page,
  Recent searches (`/`), Activity.

An action is a link with `hx-get` into `#dialog`, as the bar's are; a
place is a plain link. So running an entry is clicking it, and the
palette's own dialog is replaced by the action's.

**Index each collection** needs the index form to take `collection` in
its address and check that radio - the same filling 11f gave the Add
dialog, for the same reason: the reader chose it.

**The script filters and moves; it composes nothing.** `palette.js`
hides entries whose `data-match` (label and kind, lower-cased by the
server) does not contain what is typed, keeps one entry selected with
`aria-selected`, wraps Up and Down over the visible ones, calls
`scrollIntoView({block: "nearest"})`, and on Enter clicks the selected
link. "Nothing matches" is the server's sentence in a hidden element
the script unhides. Ctrl K (and Cmd K) clicks the bar's palette link,
so the shortcut and the button are one route.

**Colour by kind**: the icon and the kind word wear an existing role -
`command` for an action, `operation` for a collection, `option` for a
page. The label stays ink, so the list reads as text with coloured
hints rather than as three colours of text.

**ARIA**: the input is a `combobox` controlling a `listbox`; each entry
is an `option` and the input's `aria-activedescendant` follows the
selection.

## What I expect to be uncertain or difficult

- Ctrl K in a browser focuses the address bar's search in some
  browsers; `preventDefault` on keydown is what every web app does and
  works in Chromium. In Firefox it also works from page focus.
- Whether clicking an `hx-get` link inside a `<dialog>` that is itself
  inside `#dialog` swaps cleanly: the old dialog element is removed by
  the swap, so its `close` event may not fire and `dialog.js`'s cleanup
  may not run. The new dialog must still open as a modal.
- `ACTION_TITLES` is keyed by route, and a test may require its keys to
  be the bar's actions. The palette is reached from the bar but is not
  one of its actions.

## What actually happened that I did not expect

- **Two kinds wore one colour.** `option` and `command` are both cyan,
  so pages and actions looked alike: the source said three roles and
  the page showed two colours. Found by `getComputedStyle` in the walk,
  which is #371's lesson exactly - a colour decision is only real once
  something has resolved it. Pages now wear `value` (magenta), and a
  test asserts the three roles name three ANSI colours, which the
  palette tests already hold apart by dE >= 20 (#438).
- **A role brings its face as well as its colour.** `role-command` sets
  the verbatim face, so "action" was set in bold monospace beside
  "collection" in the sans. The kind word now sets its own face; the
  role gives it colour only.
- **The worries did not arise.** Ctrl K is taken by `preventDefault` in
  Chromium; the palette's dialog is replaced by the action's and the new
  one opens as a modal, with no dialog left open after Escape; and
  `ACTION_TITLES` needed only a `/palette` key, because the bar test
  reads links classed `action` and the palette's is not one.
- **The first injection did not apply**, because the formatter had
  reflowed the code it named; the harness's own assertion stopped the
  run rather than report a catch. #66's lesson, held by the harness this
  time instead of found afterwards.
- No server-side filtering: without a script the palette is a page of
  seventeen links, which is a usable index and needs no filter.
- 17 injections, all caught.
