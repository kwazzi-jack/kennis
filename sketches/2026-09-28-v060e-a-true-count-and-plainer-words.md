# v0.6e: a true count, and words that say what happened

2026-09-28

## 1. What I am about to do

Brian: the design is right, the wording is clunky. Two pieces, and the
first is a falsehood rather than a matter of taste.

**`remember` reports a number that is not about the note.** Measured
on a scratch corpus: three one-sentence notes written in a row report
"indexed, 2 chunks", "indexed, 3 chunks", "indexed, 4 chunks". Each
note is exactly one chunk. The number is the whole collection's total
and it grows by one each time, so the reader is told their sentence
became four chunks.

The cause is a single line. `engine/remember.py::_index` returns
`report.chunk_count` from `BuildReport`, where that field correctly
means the collection's chunks - a rebuild indexes everything - and
`RememberReport.chunk_count` means the note's. Two meanings, one
name, one assignment between them.

**And a pass over the interface's fixed strings.** One of them is
also wrong rather than clumsy: `NOT_SEARCHABLE_YET` says "which the
Index section above does", and in `manage.html` Add is at line 7 and
Index at line 29. The section is below.

## 2. How I expect it to work

### The count

`build_index` already holds `chunked: list[(Document, digest,
list[Chunk])]`, so a per-document count costs no extra pass over
anything - it is a `len` per entry of a list already built.
`BuildReport` gains `chunks_by_document: Mapping[str, int]` keyed by
`Document.id`, and `_index` in `remember.py` returns the entry for
the note it just wrote.

Two things this deliberately does not do. It does not re-chunk the
note to count it, which would be a second pass over text the builder
has already chunked, and CLAUDE.md says to prefer existing metadata
over an extra processing pass. And it does not drop the count: for a
one-sentence note "1 chunk" is nearly no information, but for a long
pasted note the number says how much of it became separately
findable, and a true small number is not a reason to remove a field.

`BuildReport.chunk_count` keeps its meaning and its name. It is
correct where it is used - `kennis corpus index` reports a
collection - and the defect was the assignment, not the field.

### The words

A rule, so the pass is not just taste. **A message says what
happened, and what the reader can do about it; where nothing can be
done it says only what happened.** Two things follow that catch most
of the current set: it does not refer to where something sits on the
page, because a layout is re-laid out and the reference goes stale
without anything failing; and it does not use a word kennis invented
where an ordinary one exists.

| constant | the problem |
|---|---|
| `NOT_SEARCHABLE_YET` | names a section that is below, not above |
| `NOTHING_MATERIALISED` | "materialised" is kennis's word, not English |
| `NOTHING_FOUND` | closes the exchange; suggests nothing |
| `BUSY_WITH_ANOTHER` | says "one" three times to say one thing |
| `NO_SUCH_JOB` | a negative about the interface, not about the job |
| `NOTHING_TO_SHOW` | true and unhelpful |
| `CORPUS_CHANGED` | "drawn" for a page a reader would call loaded |

The three "busy" messages stay three. They look redundant and are
not: one is the interface's own queue refusing a second operation,
one is the corpus lock refusing an operation, and one is the corpus
lock refusing a write and promising the text is still in the box.

**The nav labels move into `gui/words.py` and match the headings.**
They are hardcoded in `base.html` today, lowercase, while every page
heading is capitalised: "what is held" over "What is held". The
labels are words, and words live in the words module.

## 3. What I expect to be uncertain or difficult

**Whether `chunks_by_document` belongs on `BuildReport` at all.** It
is a mapping the size of the collection carried for one caller that
wants one entry. The alternatives are worse - a `count_for:` argument
is a special case bolted onto a general function, and re-chunking is
a second pass - but I may find a test that asserts `BuildReport`'s
fields and decide the honest shape is different.

**Whether a shared phrase is a shared string.** `NOT_SEARCHABLE_YET`
is in `gui/words.py`, so it is the window's sentence and may refer to
the window. The command line says its own version. If the fix is
"stop naming the section", the two sentences converge, and a sentence
two front ends would both want belongs in `render/words.py` - which
is a move, not an edit, and touches #297's byte-identical property in
the direction of more sharing rather than less.

**Testing wording at all.** A string is not behaviour. What is
testable: that no message names a page position, that the nav labels
and the page headings agree, and - for the count - that a note of
known length reports its own number and not the collection's. The
rest is read aloud and judged.

## 4. What actually happened that I did not expect

**The count was not a bug; it was a decision, written down, that no
caller ever acted on.** I expected to find an oversight and found
`test_the_report_counts_what_the_rebuilt_index_holds`, whose
docstring argued for exactly the behaviour I was about to remove:
"the whole collection, not the one note. What a caller wants to say
afterwards is how big the index now is, and a per-note count would be
the number 1 every time."

That deserved checking rather than overriding, and both halves failed
the check. `index_state` is the field's only reader and it prints the
number after the note's own title, so no caller ever said how big the
index is. And a per-note count is not always 1 - the long-note test
reports four. Section 3 had worried about the wrong risk again: I
expected the argument against my change to be the cost of
`chunks_by_document`, and the real argument was a recorded intention
that had never been realised. Concern #344.

**My replacement test was hollow on its first run, and said so.** It
asserted the note's count was 1 and, as a guard, that the
collection's total differed. The fixture's collection held exactly
one chunk, so the guard fired: without it the test would have passed
for either meaning of the field, which is the defect it exists to
catch. The guard cost one line and was the only thing between me and
a green test that proved nothing.

**Screenshots found the wording defect the catalogue missed.** My
list of seven clunky strings was assembled by reading
`gui/words.py`. Rendering the holdings page showed a sentence that
was not in that module and not merely clunky: `the literature index
is in step, with 1 document not yet indexed`. In step means
synchronised, so the sentence denies itself. The distinction it was
protecting - missing is not stale - is real, and the fix was to state
the gap as a gap. Concern #345.

That is now three units running where driving the real thing found
something reading the source did not.

**One clunky thing I did not fix, deliberately.** The same table
reads `literature | 3 documents | the literature index is in step`,
naming the collection twice and the column once. The sentence is
right for `kennis corpus status`, where a line stands alone. Making
both front ends compose their own subject means splitting
`describe_freshness`, and its unverifiable branches put the subject
mid-sentence, so the split is not clean. Inventing that abstraction
inside a wording pass is how a wording pass becomes a refactor.
Concern #346, left on watch.

**A template global, not a context entry.** Putting `nav_labels` in
`_frame` broke twenty tests at once, because the header is on every
page and not every route builds its context through `_frame`. It is
a constant, so it belongs on the Jinja environment. Worth
remembering: `_frame` is what a page carries that *varies*, and
anything invariant that every page needs should not be routed
through it.

**Four existing tests asserted the old strings as literals.** They
now assert against the constant, which keeps what they were actually
for - the message is present in the response - and stops a reword
breaking a test about something else.
