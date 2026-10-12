# Realigning the workbench, 4: the document, with its inspector

Milestone / step: milestone 11 realigned with the approved mockup (#447)
Date: 2026-10-12

## What I am about to do

Draw an opened document as the mockup does. The plan's settled shape
says "the reading column in the centre with an inspector over its right
margin"; the window has never had the inspector.

1. **A bar above the document**: breadcrumbs - "Search: q" when the
   reader came from a search, the collection, the group when there is
   one, and the document's handle in the monospace face - and a button
   that shows or hides the inspector.
2. **A byline** under the title: the authors and year for a paper, the
   project and version for a documentation page.
3. **The inspector**, three disclosures:
   - *Details*: what the frontmatter says, as label and value - the
     collection, the group, the citekey and the paper's identifiers,
     the documentation project and page, where it came from, how it was
     converted, when it was added, and whether the index holds it.
   - *Matches for "q"*: each chunk of this document the reader's words
     occur in, named by the heading it falls under, each a link that
     marks that chunk.
   - *Outline*: the document's headings, each a link to itself.
4. **The marked chunk** in the highlighter wash with the amber rule,
   where it is now a cyan rule in the margin.

## How I expect it to work

**Layout.** `base.html` wraps the column in `{% block centre %}` so the
document page can replace it. `main` on that page is a flex column with
no padding and no overflow of its own: the notice of a changed corpus,
the bar, then a row holding a scrolling `.reading` region (the column)
and the `aside.inspector`, which scrolls separately. So the bar and the
inspector stay put while the text scrolls, which is what the mockup
draws. The inspector sits *beside* the column rather than over it: at
1280px with the pane open the centre is about 1024px, enough for both,
and covering text is what the mockup's own screenshot shows going wrong.
Below 900px the row becomes a column and the inspector follows the text.
A fragment link (`#chunk-6`) scrolls the nearest scrolling ancestor, so
it lands inside `.reading` as it landed in `main`. To be measured.

**Open or closed** is a cookie, `inspector`, drawn onto `<html
data-inspector>` by the server, as the pane's is (the invariant: a
preference the server must render is a cookie). `inspector.js` handles
the button; with no script the inspector is simply open.

**Details** are built in `gui/pages.py` from the frontmatter as
`(label, value, verbatim)` triples, the labels in `gui/words.py`. The
group is `_group_of`, which the tree already uses. The index row reads
`holdings.document_marks(...).state_of(...)`, the tree's own rule, and
is left out when the index cannot be checked, as the tree says nothing
then.

**Outline and anchors** come from `render/html.py`: a heading gets
`id="heading-<line>"`, its source line, so the anchor is the same in
every parse whether or not the leading title heading was dropped.
`headings_of(body, without_title=...)` returns `(level, text, anchor,
start)` with `start` the heading's character offset in the body.

**Matches** need the chunks: `retrieval.document_chunks(context,
collection, document_id)` beside `chunk_range`, which then uses it.
Only when the index is in step - the same rule that withholds the mark,
because a chunk of a changed document addresses text that has moved. A
chunk matches when `query_pattern(terms_of(q))` finds a word in its
text, the same rule that marks the words. Its label is the last heading
starting at or before it, or "Passage N" before any heading.

## What I expect to be uncertain or difficult

- Whether the fragment still lands with `scroll-margin-top` once the
  scrolling element is not `main`.
- The bundle route renders the same template with less to say: no
  frontmatter model, no `document_marks`. Its Details are the scope and
  the path; Matches use the bundle's freshness.
- Tests that read `.back` or `.provenance`. The breadcrumbs replace the
  first and the inspector the second.
- Whether "heading-<line>" ids collide with anything a document's own
  HTML defines. Markdown-it is built with `html=False`, so a document
  defines none.

## What actually happened that I did not expect

- **`overflow: hidden` does not stop a fragment link scrolling.**
  Following a hit's link scrolled `main` by 40px even though it could
  not be scrolled by hand, and the bar of breadcrumbs went under the
  top bar. `overflow: clip` cannot be scrolled at all. Measured: the bar
  now stays at the top and the chunk lands inside `.reading`. The
  sketch's guess that the fragment would land inside `.reading` was
  right; it did not foresee that it would also move `main`.
- **The chunker already names each chunk's section.** `Chunk.section`
  is the heading a chunk falls under, so a match is labelled by that
  and the heading offsets the sketch planned (`Heading.start`) were not
  needed. A test for them was written and removed.
- **A long section matches several times.** On Brian's RIME paper four
  matches all read "Introduction to the series". They are numbered
  within their section now: "(2 of 4)".
- **The document did not mark the reader's words**, though the mockup
  does and an opened passage does. It does now, by the same rule. That
  broke a test of the bundle's mark, which stripped tags by putting a
  space in their place and so read `deconvolution .` - a test
  assumption, not a product defect, since nothing had been marked on a
  document page before.
- **A mark inside the marked chunk was the same amber on the same
  amber.** The mockup's `mark` has a 2px amber underline; it does now.
  Checked in the walk, not by a test.
- **`state_in` was untested at first.** The test of an uncheckable
  index called `document_details(state=None)` directly, so removing the
  guard that produces `None` passed, and an uncheckable index would
  have shown "Searchable". A test of `state_in` itself now fails.
- The heading ids are behind `heading_anchors=True`, set only for a
  document page: an opened passage on the results page renders through
  `to_html` too, and several passages would repeat an id.
- The paper on Brian's corpus has no byline: its frontmatter carries
  no authors or year. The docs page shows "stimela 2.2.0rc1".
- Injections: twenty, all caught after the `state_in` test.
