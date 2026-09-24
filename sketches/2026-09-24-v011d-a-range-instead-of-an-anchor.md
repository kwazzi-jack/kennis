# A range instead of an anchor

Milestone / step: v0.1.1, concerns #203, #205
Date: 2026-09-24

## What I am about to do

Replace `--chunk N --before B --after A` with one `--chunks START:STOP`
carrying python slice semantics, and let it subsume the other three.

## How I expect it to work

Brian proposed the slice on the handle - `kennis read x[0:3]`. Measured, that
does not survive the shell: `[0:3]` is a glob bracket expression matching one
character of `0`, `:` or `3`, so in a directory holding `x0` bash rewrites
the whole thing to `x0` silently. The syntax moves into an option value,
where no metacharacter is involved.

**The engine gets the range, not the parse.** A new frozen `ChunkRange(start,
stop)` beside `DocumentSpan`, and `read_span(index, document_id, *, chunks:
ChunkRange)`. Resolving it is one line, because python already owns these
semantics:

    start, stop, _ = slice(chunks.start, chunks.stop).indices(len(chunks_of_doc))

That gives negative indices, open ends and clamping for free, and gives them
*exactly* as python does rather than as a reimplementation that is nearly the
same.

**The parse is also engine-side**, as `parse_chunk_range("0:3")`, because the
syntax is kennis's rather than the terminal's - an MCP tool taking
`chunks="0:3"` wants the same answer, and a second parser is how two front
ends come to disagree about what `-1` means. It raises `InputError` naming
the forms it accepts.

A step is refused rather than supported. `0:-1:2` would stitch non-adjacent
chunks into one passage: holes presented as continuous prose, with
`char_start` and `char_end` describing a range the text does not fill.

**The search hint has to do the arithmetic**, which is the reason the other
three options can go: a hit at chunk `n` prints
`kennis read <id> --chunks <max(0, n-1)>:<n+2>`. The `max` is the part that
will bite if I forget it - a hit at chunk 0 would otherwise print
`--chunks -1:2`, and `-1` is the *last* chunk of the document.

## What I expect to be uncertain or difficult

Whether `--chunks` should also accept a bare index (`--chunks 3`) or insist
on a range. A bare index is what a person types and what `[3]` meant in
Brian's proposal, so it has to work; the risk is that `3` and `3:` and `3:4`
are three spellings of two different things, and someone will expect `3` to
mean `3:`.

The other is what an empty selection does. `--chunks 5:5` is a legal slice
over a document with six chunks and selects nothing. Python returns an empty
list; a reader who asked to read something and got nothing back needs to be
told why rather than shown a blank.

## What actually happened that I did not expect

Both named uncertainties turned out to be real, and both had an answer the
sketch had not worked out.

**A bare negative index has no half-open stop.** `--chunks 3` is chunks
`[3, 4)`, so the obvious rule is `stop = start + 1`. From the end that rule
breaks: `-1` would become `[-1, 0)`, and python reads `0` as "before the
beginning", so it selects nothing at all. `None` is the only spelling of "to
the end", which makes the bare-index case two rules rather than one. I would
not have found this by reasoning about it - the test for `-1` was written
because the sketch said to worry about the bare form, and it failed.

**An empty selection is a legal slice.** `--chunks 5:5` over a six-chunk
document returns `[]`, and printing that would show a reader a blank screen
and let them conclude the document was empty. It raises now, naming how many
chunks the document has.

**The one I did predict bit anyway, in a place I had not looked.** The sketch
says `max(0, n - 1)` is what will be forgotten in the search hint. It was
not forgotten - but writing the test for it revealed that the hint's printed
line is `hint: run \`kennis read x --chunks 0:3\` to read one in context`, so
a test that replays "everything after `kennis read`" replays the prose too.
Rule 4.4 is about what is *inside the backticks*, which is what
`display.command` marks, and the test now extracts exactly that. The rule and
the test of the rule had different ideas about where a command ends.

**Nothing about the parse was hard, because python owns the semantics.**
`slice(start, stop).indices(count)` gives negatives, open ends and clamping
in one line, and gives them exactly as python does rather than as a
reimplementation that is nearly the same. The only part worth writing was
deciding what *not* to borrow: the step.

Unrelated, and worth recording because it cost a few minutes: the scratchpad
directory was swept between sessions, taking the injection harness with it.
The harness is a session artefact and the table it drives is worth keeping as
data rather than as code, which is how it was rebuilt - fifteen injections in
a JSON file, all fifteen CAUGHT.
