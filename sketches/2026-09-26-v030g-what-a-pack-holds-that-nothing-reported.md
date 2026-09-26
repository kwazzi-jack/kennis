# What a pack holds that nothing reported

Milestone / step: milestone 7 (packs), after unit 5
Date: 2026-09-26

## What I am about to do

Brian asked whether packs had been tested substantially against the range
of inputs a real one carries. Surveying that found two silences, both of
the same shape - **the report counts copied files, and a pack is more than
its copied files** - and neither is caught by any test because every test
so far shipped markdown and nothing else.

1. A file sitting in a declared source that no `include` pattern matches is
   dropped without a word. An author who adds `table.csv` to `notes/` and
   runs `pack update` is told "Unchanged ... the file is untouched".
2. A pack that declares literature and docs but ships no content reports
   `0 files installed`, which reads as "nothing happened" for a pack that
   just declared two papers and a documentation site.

## How I expect it to work

**Dropped is not the same as excluded, and only one of them is worth
saying.** A file removed by an explicit `exclude:` was removed on purpose
and reporting it every run is noise. A file that matched no `include` was
dropped by a pattern the author may not have thought about - the default
`**/*.md` - and that is the one that can be a mistake. So `read_source`
gains `unselected`, holding only the first kind, and `exclude` stays
silent.

The wiring follows what already exists: `ItemFinished(outcome=SKIPPED)` per
unselected file, which `DisplaySink` ignores and `LogSink` writes, so the
log names each one; and a `>` detail line carrying the count, which is the
marker `Outcome.SKIPPED` already maps to and which finally has a theme role
of its own (#262).

**The install report counts declarations as well as files.** `PackInstall`
gains the number of literature entries and docs projects, so a
declarations-only pack reports what it declared rather than the zero files
it copied. Those are not installed - nothing is fetched until sync - so the
wording has to say *declared*, not *added*, or it promises documents that
are not there.

## What I expect to be uncertain or difficult

**Whether `validate` should report unselected files too.** It walks the
same sources, so the count is free. But `validate`'s output is a verdict
and a problem list, and an unselected file is neither.

**Whether the default `**/*.md` is right at all.** A pack shipping a PDF it
wants in the corpus has no way to say so, and widening the default would
put binaries in the corpus as documents. I expect the answer is that the
default stays and the reporting is the fix - literature is the declared
route for a paper - but it is worth stating rather than assuming.

## What actually happened that I did not expect

**The survey found more than the two silences it was run for, and the two
it was run for were both real.**

`pack update` now emits `ItemFinished(SKIPPED)` per unmatched file, so the
log names each one, and prints a `>` count line - including on an
`Unchanged` run, which is the run where it matters most: the author who has
just dropped a `.csv` into the source and been told "Unchanged" has no
other way to find out why. `pack add` reports declarations as *declared,
not yet fetched*.

**What the survey established about the input shapes**, none of which any
existing test covered:

| shape | what happens |
|---|---|
| nested directories, any depth | taken |
| a name with spaces, or with accented characters | taken |
| an empty file | taken, with a digest of nothing |
| CRLF line endings | preserved; the digest is of the bytes, so CRLF and LF differ |
| a 1 MB file | taken |
| `.hidden.md` | **taken** - and see below |
| `UPPER.MD` | not taken; matching is case-sensitive |
| `.pdf`, `.png`, `.txt`, `.csv` | not taken by the default `**/*.md` |

**The default include stays as it is**, and the reporting is the fix. A
pack wanting a paper in the corpus declares it under `literature:` by
identifier, which is fetched and converted; widening `**/*.md` to take PDFs
would instead copy a binary into the corpus as a document. The one thing
that was wrong was doing it in silence.

**A third thing the survey found, which is unit 7's and not this one's.**
`.hidden.md` is copied into the store, because the glob dialect matches a
leading dot the way `.gitignore` does. But a context bundle *excludes*
dot-prefixed paths from indexing - that is milestone 6's documented way to
keep a file out of the index. So a pack shipping a hidden file into a
bundle would land a file that is copied, is not indexed, and is invisible
to search. That is #247's neighbour and it is recorded as #267.

**The pronoun again.** The first wording was "5 files not included, so no
digest was recorded for it". That is the second time in this milestone I
have made a count agree in the noun and not in the rest of the sentence.
The wording now avoids the construction rather than conditioning on the
count twice.
