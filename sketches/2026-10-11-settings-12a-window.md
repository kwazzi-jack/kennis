# 12a. Settings: this window's preferences

Milestone / step: milestone 12, first half (`design/plan.md`), #416
Date: 2026-10-11

## What I am about to do

A settings page, reached from a gear at the end of the bar, whose first
part is the window's own preferences: colours (moved off the bar),
reading face, text size, spacing, how a match's strength is shown,
how each measure is labelled, and the colour scale of the bars. None
of these is kennis's configuration - the command line and the MCP
server never see them - and the page says so. kennis's configuration
is 12b.

## How I expect it to work

**One registry, `gui/preferences.py`.** Each preference has a name
(which is also its cookie and its `<html data-NAME>` attribute), its
choices as values, and a default; the words are in `gui/words.py`.
`preference_of(request, name)` returns the cookie's value only when it
is one of the choices, else the default - the rule `_theme_choice`
already follows, generalised. A Jinja global `preferences(request)`
returns all of them, and `base.html` writes every one onto `<html>`,
so the first byte is right and nothing repaints after load.

| name | choices | default | applied by |
|---|---|---|---|
| theme | system, light, dark | system | the existing guards |
| face | serif, sans, hyperlegible | serif | `--column` |
| size | small, normal, large, larger | normal | the root font size |
| spacing | normal, wide, wider | normal | leading, letter and word spacing |
| strength | bars, words | bars | hide `.cells` |
| labels | icons, words, both | icons | hide the icon or the name |
| scale | viridis, cividis, plasma, magma, greys | viridis | `--strength-N` |

**Size scales everything**, by the root font size, because the
interface is in `rem`; a reader asking for larger text does not mean
larger only in the column.

**The scale without a fifth and sixth copy of the dark block.** The
variable blocks emit every scale's steps for their theme as
`--scale-<name>-<n>`, and `--strength-<n>` becomes
`var(--scale-viridis-<n>)`. After the theme blocks, one rule per scale,
`:root[data-scale="X"] { --strength-n: var(--scale-X-n) }`, picks the
scale; `var()` resolves at computed-value time on `:root`, after the
theme block has set that scale's colours for the theme in force. So
the scale and the theme are independent axes and neither knows the
other.

**Measure labels need the word in the markup.** A measure is an icon
whose title is its name; `labels=words|both` needs the name as text, so
the template carries both and CSS hides one.

**Saving.** With a script, `prefs.js` (replacing `theme.js`) applies a
change at once - writes the attribute and the cookie - for every
control marked `data-pref`; it composes nothing. Without one, the form
posts to `/settings`, which sets the cookies from the same registry
(unknown values dropped) and answers 303 to `/settings`. The Save
button is for that path, and the script hides it, because with a
script nothing waits for it.

**Faces.** Source Serif 4 is vendored; the system sans is the gutter's
stack; Atkinson Hyperlegible is vendored now, regular and bold in roman
and italic, latin subset, from Google Fonts, with its OFL text, as
Source Serif was. The gear is Lucide's `settings`.

**Swatches.** Each scale's choice shows its five steps as small blocks
coloured by `var(--scale-X-n)` - the layout names no colour, and the
swatches follow the theme like the bars do.

## What I expect to be uncertain or difficult

- Whether `var()` in a custom property on `:root` really picks up the
  theme block's value for the referenced property, under both the
  media query and the explicit attribute. Measure with
  `getComputedStyle` across theme x scale.
- Which tests assume the theme select is in the bar; they move to the
  settings page.
- A cookie per preference is seven cookies on every request. Small,
  and the alternative - one packed cookie - is a format to parse.

## What actually happened that I did not expect
- **The `var()` worry was unfounded, and measured rather than argued.**
  All 30 combinations of system scheme, theme and scale gave the
  scale's step for the theme in force: a custom property on `:root`
  that names another resolves after the cascade, so the scale rules
  need know nothing about themes.
- **A cookie test was hollow by substring.** "path=/" is inside
  "path=/settings", so a cookie scoped to the settings page alone -
  absent from every other page, which is the defect - passed. The
  injection first tried was inert (Starlette's `set_cookie` already
  defaults to `path="/"`), and only the second, a real change, showed
  the hole. The header is now parsed and each attribute compared (#439).
- **Spacing belongs to the column, not the body.** Letter and word
  spacing on `body` would widen the bar and the pane, which crowds them
  and helps no reader; the preference is about what is read.
- **The row's layout was sized by its widest control.** With the choices
  column at `auto`, five scales squeezed the sentence beside them to a
  word a line. Both columns now take a share.
- The scratchpad was emptied between days, harnesses with it; the
  injection loop was rewritten from the CLAUDE.md rules rather than
  copied. A harness that matters could live in the repository.
- 24 injections, all caught once the hollow test was fixed.
