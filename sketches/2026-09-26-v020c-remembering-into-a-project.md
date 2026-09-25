# Remembering into a project

Milestone / step: v0.2.0 unit 2, concerns #169, #226
Date: 2026-09-26

## What I am about to do

`kennis remember --context`, which design section 12 specifies and milestone
5 could not build because there was nowhere for it to write (#169).

## How I expect it to work

### A second write path, not a flag on the first

`remember()` writes into a corpus `Collection`: it mints a surrogate
identifier, reserves a filename against the collection's `Uniqueness`
record, and the command commits the result to the corpus repository. A
bundle has none of those. It has no collection, its files are addressed by
path rather than by identifier, and its repository is **the user's**.

So `--context` routes to `remember_in_bundle` in `engine/context/notes.py`
rather than parameterising `remember()`. Trying to reuse it would mean
making a bundle look like a collection, which is the coupling that would
have to be undone when packs arrive.

**kennis does not commit to the user's repository.** Every corpus mutation
ends in `Repository.commit`, and doing that here would take over version
control of a repository kennis does not own. The design says the bundle is
"committed with it if the user wants" - the user commits. This is the one
place a reader might reasonably expect symmetry with the corpus and not get
it, so it is worth stating rather than leaving as an absence.

### What is shared, because it is the same question

- `title_filename` and `unique_filename` from `corpus/layout.py`. One
  filename rule for both scopes.
- `title_filename` already strips a leading dot, and its reason transfers
  exactly: in the corpus a dotted name is bookkeeping and invisible to the
  walk; in a bundle a dotted name is excluded from the index. A note titled
  `.env notes` must not become a file nothing can ever find.
- The title rule from `remember.py`: first heading or first line, trimmed to
  60 characters between words, trailing punctuation removed.

### What is not shared

Deduplication. The corpus dedupes through `Uniqueness`, built from the
collection's frontmatter identifiers. A bundle has no identifiers, so it
dedupes on the **body digest** of the markdown files already in it. That is
a full scan, which is fine: boepie's real bundle is 57 files, and the corpus
equivalent scans a collection too.

An agent repeating itself is the expected case once the MCP server exists,
so this matters for the same reason it matters in notes.

### Frontmatter

    ---
    title: ...
    description: ...
    owner: user
    source:
      via: remember
      at: '2026-09-26T...Z'
    ---

`owner: user` is what the pack resolution table keys on, and the reason the
field is written now rather than retrofitted in 0.3. `description` is in the
skeleton, so a remembered note carries the same shape as a hand-written one
even though it has nothing to put there yet.

### Indexing

There is none: `context index` is unit 3. So the report says the note is not
searchable yet, which is the shape `remember` already has for a notes
collection with no index. Honest, and it becomes a real next step in one
unit's time.

Once this lands, `context init`'s closing line can stop pointing at
`LANDING.md` and name `kennis remember --context` - a command that will then
exist, which is what rule 4.4 asks and what #233 recorded.

## What I expect to be uncertain or difficult

Whether `--context` should take `--group`. The corpus one means "a
subdirectory of the collection" and the bundle has subdirectories too, so it
transfers. The doubt is that a bundle's directories are the user's own
invention rather than a fixed three, so `--group physics` silently creating
a directory is a slightly bigger act than in a collection. I think it should
create it and say so.

Whether a bundle needs a lock. The corpus takes one for every mutation. Two
concurrent `remember --context` in one workspace could pick the same
filename between the uniqueness scan and the write. Writes are atomic
individually, so the loss is a collision rather than a corruption, and the
corpus lock is the wrong lock - it guards a different directory. Probably a
bundle lock, probably not in this unit.

Whether the empty-text error should be the corpus one. `remember` raises
`InputError` naming `kennis remember --help`; the same text with `--context`
wants the same error, and it is the same failure, so reusing it is right
unless the resolution differs.

## What actually happened that I did not expect

**Rule 4.4 did not release `context init` the way the sketch assumed.** The
plan was that `kennis remember --context` would exist and so the closing
line could name it. It does exist, but the useful form of it is
`kennis remember --context "<text>"`, and a placeholder is not a command
that runs as printed. The line therefore stays as `start at
.context/LANDING.md`, which is a *place* and can be named exactly, and the
command moved into LANDING.md's "Writing a file" section where it is
surrounded by the prose that says what to substitute. The comment above the
line had to be rewritten, because it justified itself with "does not exist
yet" and that had become false - a stale comment is worse than none, since
the next reader would have deleted the guard it argues for. #233 closes on
the second instance and stays open on nothing.

**The order was implementation, then tests.** The sketch says sketch, then
test, then implementation, and that is not what happened for the CLI half:
the flag and `_remember_in_context` were written first and the eleven tests
after. The injections are what recovered it - ten defects injected, ten
failures, two of which (`--no-index` and the dedup scan) did not apply on
the first attempt and were caught only because the harness asserts the
substitution matched. Writing the tests second means they were shaped by the
code; the injections are the only evidence they are not merely a transcript
of it, so they did more work here than usual rather than confirming what
red-first had already established.

**Running the command found two things the green suite did not, again.**
The report line read `Remembered <title>, in this project in 0ms` - the
elapsed suffix from the corpus path, where the number is dominated by
indexing and worth having, appended to a bare file write where it is always
`0ms` and answers nothing. And the detail line was bundle-relative,
`decisions/Solver choice.md`, which does not say which of the two places
`remember` writes to it landed in. Both are output, both were asserted on
only by `"Remembered" in result.output`, and neither is visible without
looking at the output. The detail line is now `.context/decisions/Solver
choice.md` and the test asserts that prefix.

**`--group` resolved as expected and needed no decision.** It creates the
directory and the detail line names it, so the "slightly bigger act" the
sketch worried about is visible in the output rather than silent. The lock
question did not come up in practice and stays open as #236; the empty-text
error reused the corpus one unchanged, because `_text_and_origin` runs
before the write path is chosen - which is itself a property worth a test,
since moving the branch above it would break `--from` and standard input
for `--context` while every other test still passed.

**`--no-index` is refused rather than accepted and ignored.** The sketch did
not consider the flag at all. It is meaningful on the corpus path and there
is nothing for it to skip on the bundle path until unit 3, so silently
accepting it would report an intention as honoured that was never
considered. It raises, and unit 3 turns the refusal into an honoured flag.

**The derived title ends on a stopword.** `Calibration is done in
four-minute chunks because the ionosphere decorrelates faster than that.`
becomes `Calibration is done in four-minute chunks because the.md`. The
trim is between words, as documented, but between-words is not the same as
at-a-clause-boundary. This is `title_for` and so is shared with the corpus
path, where it has been true since milestone 2 and was never noticed because
notes in the test corpus carry headings. Logged as #237 rather than changed
here, because changing it changes filenames in the corpus too.
