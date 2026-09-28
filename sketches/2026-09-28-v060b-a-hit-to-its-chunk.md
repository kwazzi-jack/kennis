# v0.6b: a hit takes you to its chunk, and the chunk is marked

2026-09-28

## 1. What I am about to do

A search hit in the interface links to `/document/{collection}/{id}`,
which opens the document at the top. For a 19-page paper that is the
wrong place: the reader has been told the match is in chunk 3 and then
has to find it by eye.

Make the link carry the chunk, scroll to it, and mark it. Three
changes, and a fourth that is the interesting one:

1. `ShownHit` gains `chunk_index`, a third coordinate beside
   `collection` and `document_id`. Its docstring already says the
   extra fields are "coordinates, not words: a page needs them to
   build a link", so this is that field's third instance rather than
   a new kind of thing.
2. The hit link becomes `/document/{collection}/{id}?chunk=3`, and
   the reader renders with that chunk marked and given an `id`, so a
   `#chunk-3` fragment scrolls to it.
3. `render/html.py::to_html` gains an optional chunk range and wraps
   the blocks it covers.
4. **The mark is suppressed when the index is behind the document**,
   because the offsets are the index's and would then point at text
   that has moved.

## 2. How I expect it to work

### The offsets exist and are exact

`engine/rag/models.py::Chunk` already carries `char_start` and
`char_end`, offsets into the document's markdown. Nothing needs to be
computed or stored; the chunk is already addressable. What is missing
is only a way to ask for one chunk of one document without running a
search, so the reader route needs a lookup: open the collection's
index, find `{document_id}::{chunk}`, take its two offsets.

`engine/rag/search.py` already reads chunks out of an index by
document for `read --chunks`, so the lookup is an existing shape and
not a new one.

**The two sides address the same string, and I checked rather than
assumed.** The reader renders `document.body`; the chunker chunks
`rag.Document.text`, which `rag/loaders.py` fills with `held.body` -
the same accessor on the same document. Had the loader indexed the
file including its frontmatter, every offset would have been long by
the length of the frontmatter block, and the mark would have been
consistently wrong by a plausible-looking amount, which is the worst
kind of wrong. A test asserts the agreement rather than trusting the
line in the loader to stay that way.

### Character offsets become element boundaries

The reader shows HTML, not markdown, so a character range in the
source has to become a range of elements in the output.
`render/html.py` builds on `markdown_it`, and every block token
carries `map`, a `[start_line, end_line)` pair. So:

- convert `char_start` and `char_end` to line numbers, by the same
  `_line_offsets` walk `chunking.py::_blocks` already does;
- parse rather than render, walk the level-0 tokens, and find those
  whose `map` intersects the line range;
- put `id="chunk-3"` and a class on the first, and close the wrap
  after the last.

The wrapper is a real element rather than an attribute on each block,
because the mark should read as one passage and not as five separately
highlighted paragraphs.

**This is block-granular, and that is a decision, not a limitation I
failed to notice.** I measured the real corpus: of 524 chunks across
52 documents, **510 (97.3%) begin and end exactly on a top-level block
boundary**. The other 14 do not, because `chunking.py::_pack` is
allowed to bisect one thing - a prose paragraph longer than
`size=1500` - and slides a window through it. For those, the marked
region is the containing paragraph, which is a superset of the chunk
and never a subset. The longest such paragraph in the corpus is 1508
characters, so the overshoot is bounded by roughly one screen.

The alternative, marking the exact characters, means descending into
`markdown_it`'s inline tokens, which do not carry reliable source
offsets, to gain exactness on 2.7% of chunks. Not worth it, and the
honest superset is a better failure than an exact highlight that is
sometimes off by an inline token.

### Chunks overlap, so an anchor is not a partition

`ChunkParameters.overlap` is 200, so consecutive chunks of a bisected
paragraph share text. Two anchors can therefore cover the same block,
and one block can belong to two chunks. This is only a problem if
something assumes the anchors partition the document; nothing will,
because the reader is given one chunk to mark and not a list.

### The staleness guard

The offsets belong to the index. If the document changed after it was
indexed, they point at text that has moved, and the mark would sit
confidently on the wrong paragraph. Silently marking the wrong
paragraph is worse than marking none.

`holdings.py` already computes `Freshness` per collection, so the
reader asks for it and, when the state is `stale`, drops the mark and
says why. `unverifiable` also drops it: "kennis cannot check" is not
"kennis checked and it is fine".

Not a redirect and not an error - the document is perfectly readable,
and only the mark is withheld. One sentence in `gui/words.py`.

### What the reader does with it

The route takes `?chunk=` rather than reading the fragment, because a
fragment never reaches the server and the marking happens in Python.
The response then carries `#chunk-N` in its own anchor so the browser
scrolls natively; `scroll-margin-top` keeps it clear of the header.

## 3. What I expect to be uncertain or difficult

**Whether `to_html` should take a chunk range at all.** It currently
takes markdown and a flag. Adding a range makes a second reason for
the renderer to know about the index. The alternative is to mark the
markdown before rendering, with a sentinel, which is worse: a
sentinel can land inside a code fence and be shown to the reader.

**Injecting tokens into a `markdown_it` stream.** I have not done it
in this codebase. `html_block` tokens with raw `content` should work,
but the renderer may escape or re-wrap them, and a `<div>` inside a
`<p>` is invalid HTML that browsers silently restructure - which would
move the mark. If wrapping proves unreliable, the fallback is an `id`
and a class on each covered block and a CSS rule that joins adjacent
marked blocks visually.

**Verifying the staleness guard by injection.** The guard is an `if`
whose condition is rarely true, and the test has to make a document
change after indexing without rebuilding. That is arrangeable - write
the note, index, then edit the file - but it is the kind of test that
passes for the wrong reason, because a marking that is absent for any
other reason looks identical. The test must assert the mark is present
when the index is current and absent when it is not, and both halves
have to fail under injection.

**Whether `/read` should gain the same thing.** The command line's
`read --chunks` prints the passage alone rather than the document, so
it has no equivalent problem. Leaving it out.

## 4. What actually happened that I did not expect

**The assumption in section 2 was false, and measuring it was worth
more than checking it.** I had read `_Block` as "one top-level
markdown block" and expected chunk boundaries to align with block
boundaries always. They do not: `_pack` is allowed to bisect one
thing, a prose paragraph longer than `size`, and slides a window
through it. Counting rather than reasoning turned a yes/no question
into a number - 510 of 524, 97.3% - which is what made the decision
easy. Had I only checked whether it was *always* true I would have
concluded no and built the hard version.

**Injecting tokens into the stream was the easy part.** Section 3
expected it to be the difficult one. `html_block` tokens with raw
content render exactly as written, and `_closes_at` walking the
nesting counter handled a paragraph and a table the same way. What
took the time was elsewhere entirely.

**Running the interface found a defect the suite could not have.**
Sixth unit running. A hit in the `context` scope linked to
`/document/context/<name>.md`, which answers "unknown collection
'context'" and a 404 - one scope in four answering a search with an
error page, since unit 9b. The suite could not see it because no
test had ever followed a context hit's link. Concern #332. Fixing it
was most of this unit: a `/bundle/` route, a bundle reader, and the
same staleness guard over `bundle_freshness`.

**Two injections were not caught, and they failed in the two
different ways #318 names.** Both were worth the time it took to
tell them apart.

The path-traversal injection was **inert**. Starlette normalises `..`
out of a request path before a route sees it, so every traversal
answers 404 whether the membership check is there or not - measured,
with three encodings, against a real bundle. The check is defence in
depth that no HTTP request can currently exercise. Weakening the test
would have been wrong and deleting the check would have been worse;
the answer was a test that calls the function directly, which is
also how a second front end would call it. Concern #333.

The frontmatter injection was a **weak test**, and it took two
attempts to sharpen. My first version asserted a search term appeared
inside the mark. Rendering the whole file shifts every offset by the
header's length, and the term survived. My second version asserted
the chunk's opening line appeared inside the mark - and that survived
too, because chunk 0 starts at offset 0, so the shift does not move
where the mark *starts*; it makes the mark a superset that begins
with the frontmatter and still contains the chunk further down.
Only `startswith` separates the two.

That is the lesson worth keeping, and it is a shape rather than a
detail: **when a defect makes an answer a superset of the right one,
every containment check passes.** #297 says a containment check
passes for a front end that drops a field; this is the same rule
from the other side. It cost two attempts because both times the
assertion looked like it was about position and was actually about
membership.

**`write_note` and the corpus route needed no sharing.** I expected
to factor `_marked` and `_marked_in_bundle` into one function. They
are the same three decisions in the same order over a different
index, a different freshness function and a different identifier -
about three lines alike and every value in them different. Written
out twice, deliberately.
