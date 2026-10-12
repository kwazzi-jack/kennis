# A passage in a card, opened by a chevron, and everything that opens moves

Milestone / step: after milestone 11's realignment (#447)
Date: 2026-10-12

## What I am about to do

Brian, 2026-10-12, on the results: there are two ways to open a hit in
its document, the arrow by the title "which is good" and "Open it in the
document" under the passage; "can we not only use symbols like
shaftless arrows?" And: "make it easier to understand what is the chunk
and what is the title? Maybe contain the chunk in a card ... Just a
little hard to see that it is quoted/chunked text." And: components do
not fade or transition - "the sidebar is an example. Anywhere else?"

**What is usually done.** Search interfaces that quote a source -
Google Scholar's snippet, Perplexity's and Kagi's source cards,
Zotero's and Obsidian's search panes, GitHub's code search - set the
quoted text apart from the result's own title by a *surface*: a tinted
or bordered box, often with a rule down the left as a block quotation
has. The title stays outside it, in the interface's face; the excerpt
inside, in the document's.

**So:**

1. **A passage is a card**: the raised surface, a hairline border,
   rounded corners, and a rule down its left in the muted grey that
   turns the brand amber when the passage is opened - the colour the
   document uses for "here". The reading serif inside; the title above
   it stays in the interface. The fade at a closed passage's foot fades
   the text into the card's own surface.
2. **One way to the document**: the title and its arrow. The foot's
   "Open it in the document" goes, with `OPEN_IN_DOCUMENT`.
3. **The toggle is a chevron alone**, a small round button sitting on
   the card's bottom edge, pointing down when closed and up when open.
   Its words stay in Python and on the page for a screen reader, in a
   visually hidden span, swapped by `details[open]` as now.

**Motion where something opens or closes**, all CSS, a quarter second:

- the **pane** slides: `.shell`'s `grid-template-columns` transitions
  between `16rem` and `0px`, and the pane fades, hidden at the end;
- the **inspector** slides the same way, by width, instead of
  `display: none`;
- **every `<details>`** - tree folders, inspector sections, the key -
  grows open and shrinks shut through `::details-content`, which
  `interpolate-size` (already on `:root`) lets go to `auto`; a row's
  menu is excluded, because its items are positioned outside the box
  and an `overflow: hidden` would clip them;
- **fetched content** fades in where it lands: a tree branch, the add
  preview, the chooser, a note's outcome.

## How I expect it to work

`hits.html`'s foot holds only the `<details>`; the summary holds the
chevron icon and two `.visually-hidden` spans. `.passage .full` is the
card. The foot is centred and pulled up over the card's bottom border
by a negative margin, so the button sits on the edge.

## What I expect to be uncertain or difficult

- `grid-template-columns` interpolates only when both values have the
  same track count, which these do.
- `::details-content` needs Chromium 131; elsewhere details open at once
  as now. The passage's own `<details>` has no content and is unaffected.
- The inspector closed by width keeps its text laid out at zero width;
  it needs `overflow: hidden` and `visibility: hidden` at the end, or a
  screen reader still reads it and Tab still reaches it.
- The tests that read the foot's link and words change.

## What actually happened that I did not expect

- **The colour test refused the card.** "An opened passage is one
  colour" rejected the word `muted` anywhere in a passage rule, and the
  card's left rule is the muted grey. The rule is about the text, so it
  now looks at `color:` alone; an injection of muted text is still
  caught.
- Measured: the pane 256px -> 75px at 90ms -> hidden; a folder 28px ->
  108px at 80ms -> 167px; the inspector 272px -> 54px -> 0px and hidden;
  a row's menu still opens whole (232 x 190px), so excluding it from
  `::details-content` was needed and is enough.
- A closed pane still measures 17px wide: its padding overflows the
  zero column, as before this unit. It is hidden, so it takes no clicks.
- The corpus's commit changed during the walk (`8f2264c` -> `bcaed77`).
  Checked before going on: Brian's own `kennis gui` session ran Sync and
  Index at 16:34; every walk runs `--no-browser` with its log in the
  scratchpad.
- Injections: nine, all caught.
