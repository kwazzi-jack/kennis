# Panes that resize, a strip that collapses, scrollbars in the theme

Milestone / step: after milestone 11's realignment (#447)
Date: 2026-10-12

## What I am about to do

Brian, 2026-10-12: "the scrollbars (not sure where else) are still
quite simple and do not match the theme ... the activity bar at the
bottom does not seem like you can collapse it or scroll it. Same for
the layout in general, we should be able to move the size of panes
should we not?"

What is there: the strip already scrolls, capped at 40% of the window,
but with the browser's default scrollbar and no other sign that it
does; it has no collapse. The pane and the inspector have fixed widths
(16rem, 17rem) and open or close only.

1. **Scrollbars** take the theme: thin, a thumb in the muted colour on
   a transparent track, by the standard `scrollbar-color` and
   `scrollbar-width`, everywhere.
2. **Three drag handles**: the pane's right edge, the inspector's left
   edge, the strip's top edge. Each is a focusable `role="separator"`
   that also moves by the arrow keys (16px a press) and returns to the
   default on a double-click or Home.
3. **The strip collapses** to its first line - the step while running,
   the headline when finished - by a chevron at its right; the chevron
   is shown only when there is a job to collapse.

Sizes and the strip's state are remembered as cookies the server draws
onto `<html>`, as the pane's state already is, so the first paint is
right.

## How I expect it to work

- **Server.** `gui/layout.py` holds `SIZES`: name (also the cookie and
  the custom property), least and most in px. `sizes_of(request)`
  returns `--pane-width: 300px; ...` for the cookies that are integers
  in range, which `base.html` writes as `style` on `<html>`;
  `strip_state(request)` is `open` or `closed`, written as
  `data-strip`. The words - each handle's label, the chevron's two
  labels - are in `gui/words.py`.
- **CSS.** `--pane: var(--pane-width)` with `--pane-width: 16rem` by
  default, so a closed pane still sets `--pane: 0px`; the inspector's
  `width: var(--inspector-width)`; the strip's `max-height:
  var(--strip-height)`. A handle is a thin, transparent strip over the
  edge that shows the brand on hover and focus. The pane's handle sits
  in the grid's pane area at its end, so it does not scroll with the
  pane; the inspector's is a flex item with negative margins; the
  strip's in the strip's area at its start. `:root.resizing` turns the
  shell's transition off and selection off while dragging, or the
  grid would lag the pointer by a fifth of a second.
- **Script.** `resize.js` - pointer events with capture on each
  `[data-resize]`, the new size from the pointer's distance to the
  edge the element is anchored to, clamped to the element's own
  `aria-valuemin`/`max`, written to `<html>`'s style and to the cookie
  on release. It composes no words. `strip.js` - the chevron, as
  `pane.js` does the pane.

## What I expect to be uncertain or difficult

- The pane's handle must not be clickable when the pane is closed.
- The inspector closes by `width: 0`; its width now comes from a
  variable, and the closed rule must still win.
- A dragged strip height must not be less than one line, or a collapse
  is indistinguishable from a broken strip.
- The `prefers-reduced-motion` and narrow-window rules that set
  `.shell`'s columns (`@media (max-width: 46rem)`) must keep working.

## What actually happened that I did not expect
- **Two arrow presses moved the pane one step.** Each press measured
  the pane, and the pane's width transitions, so the second read it
  halfway. A key now steps from `aria-valuenow`, the size last set.
- **Dragging the strip up did nothing**, because the size was only its
  `max-height` and the job's lines were shorter. A dragged height is
  now the strip's height while it shows a job (selected by the size's
  presence in `<html>`'s inline style), idle it stays one line, and a
  collapse still wins - same specificity, the later rule - measured
  282px dragged and 97px collapsed after.
- The strip already scrolled (40% of the window); what was missing was
  any sign of it and any control. Scrollbars resolve to the muted grey
  at 55% on no track in both themes on main, pane and strip; the
  headless shell draws no scrollbar in a screenshot, so that is a
  measurement, not a picture.
- Measured: the pane 256 -> 356px by a 100px drag, kept across a
  reload, 324px after two Left presses, back to 256 on Home and on a
  double-click, 160px at the least; the inspector 272 -> 392px by a
  120px drag left; neither handle visible while its pane is closed.
- Seen and not fixed: after a job the idle status and the pane's dots
  still say what was true before it (#457).
- Injections: eleven, all caught.
