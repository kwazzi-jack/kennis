# Realigning the workbench, 5: the Add dialog

Milestone / step: milestone 11 realigned with the approved mockup (#447)
Date: 2026-10-12

## What I am about to do

Draw the Add dialog as the mockup does, keeping what plan 11d decided
after it (the Browse button and kennis's own chooser in place of the
mockup's drop zone, the preview, Several by group as a fourth tab):

1. **Tabs with icons**: Paper a book, Documentation site a globe, File a
   document, Several by group a folder.
2. **Fields that take less room**: "required" or "optional" beside the
   name, "If empty: **the value**" under the field, and the optional
   fields two to a row where the dialog is wide enough. A required field
   takes the whole row.
3. **A footer**: where the add will go ("Adds to literature /
   calibration"), Cancel, and a primary button named for the kind ("Add
   paper").

## How I expect it to work

**Icons** come from a `words.ADD_TAB_ICONS` map beside `ADD_TABS`, and
`ShownTab` gains `icon`. All four are vendored already.

**Fields.** `add-field.html` gains `data-need="required"|"optional"`
on its `div`, which the layout reads: the form's fields are a grid,
`repeat(auto-fill, minmax(14rem, 1fr))`, and a required field spans
`1 / -1`. The `need` span moves beside the name. `EMPTY_PREFIX` becomes
"If empty:" and the value is in `<b>`.

**Footer.** The form ends in `.form-foot`: the destination on the left,
then Cancel (`data-close`, which `dialog.js` already handles) and the
submit button. The destination is drawn by the server from what the form
holds when drawn: the fixed collection for Paper and Site, the place
the dialog was opened on (11f's "Add here" fills the group or project).
**It follows the form as the reader types**: each part is a span with
`data-mirror="<field name>"`, and `dialog.js` copies that field's value
into it on `input` and `change`. The script copies values; it composes
no words, as `hint.js` copies `data-hint`. A part whose field is empty
hides its separator by CSS (`:empty`). Several by group has no single
destination, so it draws none.

Without a script Cancel does nothing in a dialog, and there is no
dialog: the page form's Cancel is a link to the search page, which is
where Back would go. `data-close` on a link is intercepted by
`dialog.js` before the link is followed - to check.

## What I expect to be uncertain or difficult

- The file tab's collection is a radio group with nothing checked
  (#431). `form.elements["collection"]` is then a `RadioNodeList` whose
  `value` is "" until one is chosen, which is what should show.
- Whether `dialog.js`'s click handler stops a Cancel link from being
  followed. It calls `close()` but not `preventDefault()`.
- `test_gui_add.py` finds rows by `<div class="field"[^>]*>` and the
  need by `<span class="need">`; both keep working if the markup keeps
  those exact openings.

## What actually happened that I did not expect

- **The File tab's radios sat above their own label**, right-aligned,
  and had since 12a. A bare `.choices` rule written for the settings
  page placed its element in grid row 1 of whatever grid held it, and
  the Add form's collection field is a grid. The test that guards bare
  classes catches a class *declared* twice, not one declared once and
  used by two pages. Scoped to `.setting .choices`, with a test, and
  #452 for the general hazard.
- **Two inputs side by side sat 7px apart.** A field sharing a row
  with a taller neighbour is stretched to its height, and its own grid
  rows shared out the extra space. `align-content: start`. Measured,
  not seen in the source: the two fields' markup is identical.
- **`.dialog-body p` outranked `.destination`**, so its `margin-right:
  auto` was lost and the destination sat against Cancel.
- **The script test was satisfied by the function's definition.** It
  asked that `data-mirror` appear, which it does inside `mirror()`
  whether or not anything calls it. It now asks for the call; the walk
  is what shows the copy happens: typing "calibration" into Group made
  the foot read "Adds to literature / calibration", clearing it removed
  the separator too, and choosing notes on the File tab filled it in.
- `dialog.js` did not call `preventDefault`, so a Cancel *link* would
  have closed the dialog and then navigated to `/`. It does now.
- The File tab says nothing about where until a collection is chosen,
  rather than "Adds to" and a gap.
- Injections: eleven, all caught after the script test was tightened.
