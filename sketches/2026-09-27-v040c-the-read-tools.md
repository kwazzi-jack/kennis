# v0.4 unit 8c: three read tools, batched, over the shared span rendering

Date: 2026-09-27

## 1. What I am about to do

`read_notes`, `read_literature`, `read_docs`. The follow-up to a search
hit: pass its `document_id` and `chunk_index` and get the surrounding
prose back.

**There is no `read_context`**, and that is a decision rather than an
omission. A bundle file is a file in the user's own repository, so a
context hit's handle is a path and the agent opens it with native file
tools. `kennis read` refuses `--collection context` for the same reason
and says so in as many words.

Section 20's exception covers this half too - "search hits **and
document spans**" - so the span provenance line is shared with the
command line exactly as the hit lines now are.

## 2. How I expect it to work

`describe_span(collection, span, title)` already lives in
`render/words.py` and the command line already calls it, so the shared
half largely exists. What is missing is the pairing of that line with
the text, which the command line does by sending one to stderr and the
other to stdout - an output contract a tool cannot borrow.

So `render/words.py` gains:

```
rendered_span(collection, span, title) -> RenderedSpan
    provenance: str   what describe_span returns
    text: str         the stitched prose
```

Two fields for the same reason `RenderedHit` has three: the command
line sends them to different streams, the server joins them, and the
text is identical either way.

**Batched, and that is the point of the shape.** One call carries a
list of requests, so an agent expands three hits without three round
trips:

```
class ReadRequest:
    document_id: str
    chunk_index: int | None   # omitted: the whole document
    before: int = 1
    after: int = 1
```

`before`/`after` rather than a slice string, because an agent has a
chunk index from a hit and wants the neighbourhood of it; `--chunks
0:3` is a person's syntax at a shell. They convert to the engine's
`ChunkRange` on the way in, with `max(0, index - before)` - the same
arithmetic `around()` does for the printed hint, and for the same
reason: a hit at chunk 0 with `before=1` would otherwise ask for `-1`,
which is the document's *last* chunk.

**No index is needed for a whole-document read.** `chunk_index=None`
reads the body from the corpus, as `kennis read` without `--chunks`
does, so a document that has never been indexed is still readable. A
range is stitched out of the index and needs one.

**The id is resolved within the tool's own collection**, with
`Collection.resolve`, so `read_notes` cannot return a paper. An
identifier an agent constructed rather than copied fails here, which is
what the instructions block already warns about.

## 3. What I expect to be uncertain or difficult

- Whether a whole-document read should be capped. A 60-page paper is
  most of a context window, and boepie allowed it. I am inclined to
  allow it and say in the docstring to prefer a range, because a tool
  that silently truncates a document is worse than one that returns a
  big answer to a question that asked for it - but I want to see the
  size before deciding.
- What one failing request does to a batch of four. Raising loses the
  three that worked; reporting per request costs a shape. I think the
  batch reports per request and never raises for a bad id, because the
  whole point of batching is that one bad handle should not cost the
  others.
- Whether `RenderedSpan` belongs in `words.py` beside `describe_span`
  or in a module of its own with the hit rendering. `words.py` for now:
  the span renderer is already there and moving both is churn this unit
  does not need.

## 4. What actually happened that I did not expect

**`RenderedSpan` was not needed and was not written.** Section 2 planned
a dataclass pairing the provenance line with the text, by analogy with
`RenderedHit`. The analogy is false. `RenderedHit` exists because
*composing* a hit line is real work - the band, the basis phrase, the
best-lexical marker, the snippet - and that work had been duplicated.
A span has no composition: `describe_span` already returns the whole
provenance line and `span.text` is already the prose, both already
shared with the command line. A `rendered_span` would have been
`RenderedSpan(describe_span(...), span.text)` - a wrapper with no
content, dressed as a shared renderer. The joining of the two strings
is one f-string in the adapter, which is where the difference between
the two front ends actually lives.

Worth naming as a shape: "the last unit needed a value object, so this
one does too" is a plausible-sounding reason to add indirection. The
test for it is whether the object would contain any logic. This one
would not.

**The whole-document read is capped after all**, at 20,000 characters,
against the inclination recorded in section 3. Seeing the size decided
it, as section 3 said it would: the astropy docs pages are small, but
`literature` holds a converted 70B-model paper, and a tool answer is
not a file a reader scrolls - it is tokens spent before the agent can
think. The objection in section 3 was to *silent* truncation, and that
objection is met: the cut is announced in the answer and names
`chunk_index` as the way to read the rest. A batch cap of 8 came with
it, for the same reason and refusing rather than truncating, because a
caller who asked for 40 documents and got 8 should be told which
question was not answered.

**A test was measuring an error message against a passage.** The
window test built a note of forty short paragraphs, which at a 1500
character chunk target is *one* chunk, so `chunk_index=1` was out of
range and the narrow read returned a failure block. `len(wide) >
len(narrow)` was true, and would have stayed true with the window
arithmetic deleted. Concern #298. Both reads now assert the chunk range
named in their own provenance line, and the fixture asserts the note
really chunked. This is the second time in two units that the test
which mattered most was the hollow one (#297 was the first), and both
times the shape was the same: an assertion weak enough to be satisfied
by the wrong thing.

**Running it live found what the tests could not.** All seven injected
defects were caught and the suite was green, and the first real call to
`read_docs` still showed something wrong: the provenance line carried
`/home/brian/.local/share/kennis/docs/...` where a span read of the
same corpus carried `notes/kennis.md`. Two addressing conventions in
one tool group, and an absolute path is the user's account name sent
to a model provider. Concern #299, left open because the fix is in
`describe_document`, which the command line shares.

**fastmcp puts the dataclass docstring in the tool schema.** The
`$defs.ReadRequest.description` in the generated JSON schema is
`ReadRequest`'s docstring verbatim, so the explanation of
`chunk_index`, `before` and `after` reaches the agent without being
restated in three tool docstrings. Not planned; worth knowing, because
it means a parameter object's docstring is interface text and should
be written as such.
