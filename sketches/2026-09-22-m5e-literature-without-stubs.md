# Literature: no stubs, no auto-resolution, and a bibliography is a unit

Milestone / step: not a plan item. A behaviour decision taken with Brian on
2026-09-22, arising from concerns #104 and #107.
Date: 2026-09-22

Previous sketch: `2026-09-22-m5d-search-and-read.md`.

## What I am about to do

Three changes to `add_literature`, all in the same direction: **a literature
document is a paper's text, or it is not written.**

1. **No stubs.** A paper whose text cannot be obtained is refused, not
   recorded as a bibliography with a note where the body should be.
2. **No auto-resolution.** A DOI is a DOI. kennis stops querying arXiv to see
   whether a preprint of it exists.
3. **A `.bib` is a unit.** If any entry of a bibliography cannot produce a
   document, nothing from that bibliography is written.

## How I expect it to work

### Why the stub has to go, beyond it being unhelpful

Brian's argument is that a corpus of literature should hold literature. There
is a second argument from the inside that is at least as strong: **a stub is
indexed.** Its bibliography is chunked and embedded like any other text, so
it competes in search results with real papers and can outrank one on a title
match. A corpus that answers a search with a stub is worse than one that
answers with nothing, because the reader believes they have the paper.

`source.via` does distinguish them - `verbatim` for a stub, `html` for a
fetch - so the information was technically present. That is exactly the kind
of distinction nobody should have to know to trust a search result.

### Where a body can come from, exhaustively

| the user names | body |
|---|---|
| a local file | converted, by MinerU or verbatim |
| an arXiv identifier | fetched, arXiv HTML then ar5iv |
| a DOI | **nothing** - refuse, name the PDF as the remedy |
| a bibcode | **nothing** - refuse, likewise |

That table is the whole change. `_enrich` stops calling
`resolve_doi_to_arxiv`, so a DOI-only paper has no `arxiv_id`, nothing to
fetch, and no body.

`--no-fetch` goes with the stub it existed to produce. Its whole meaning was
"leave the bibliography without the text", which is now not a state a
document can be in.

### Why no auto-resolution, when the code already does it

Today a DOI naming an MNRAS paper is silently answered with the arXiv
preprint: `resolve_doi_to_arxiv` queries arXiv's `doi` field, which holds the
*journal* DOI authors report, so it finds preprints of published papers. The
identifier is then derived from the preprint and the body is the preprint.
Nothing says so.

The substitution may well be what a user wants - it is one of the two user
types Brian described - but it cannot be the silent default, because the
stored document then differs from the thing that was asked for. Making it a
setting was the alternative; Brian chose to remove it entirely and let it
return as a designed feature rather than an inherited one. `future.md` now
records it.

### A bibliography is a unit, and the check is static

A `.bib` entry can produce a body from exactly two things: a `file =` field
pointing at a document that exists, or an arXiv identifier. Both are
readable from the file itself, so **the whole-batch check needs no network
and no dry run**. `_papers_of` refuses the bibliography before a single paper
is written, naming every entry that cannot work.

One line has to be drawn explicitly. A fetch that fails at *runtime* - arXiv
throttling, a paper it will not render - is a per-paper failure and does not
retract the batch. The static check refuses a bibliography that cannot work;
a transient network condition is not a property of the bibliography, and
rolling back written documents to honour it would be a transaction the corpus
has no other use for.

## What I expect to be uncertain or difficult

- **How many tests assert the stub.** Eleven mentions across four files, and
  some of them are testing something else and using a stub to do it.
- **The citekey for a DOI-only paper with a local PDF.** `derive_citekey`
  needs authors and year; with no `.bib` entry and no arXiv metadata there is
  nothing to derive from. This case survives the change - a PDF plus
  `--identifier <doi>` is the second user type - so it needs an answer.
- **Whether whole-batch refusal should apply to a list of PDFs too.** I think
  not: a `.bib` is one artifact the user wrote, a list of arguments is not,
  and per-item failure is the right granularity for the latter.
- **`_no_identity_reason` offers notes as the way out.** With stubs gone, a
  DOI-only paper now fails for a *second* reason, and the two remedies
  differ: no identity means "add it as a note", no text means "supply the
  PDF". They must not be worded the same.

## What actually happened that I did not expect

**Removing a stub removed a whole class of test fixture, and the fixtures
were the work.** Eleven tests mentioned the stub and only three were *about*
it; the rest were testing citekeys, duplicate detection and frontmatter, and
were using a stub as the cheap way to get a document. `arxiv_client` answered
the metadata query and returned 404 for the rendering, which was a deliberate
choice - it made the fixture answer only the question it was asked - and
which now refuses every add. It serves both, and `unrenderable_client` is the
new name for the old behaviour where a test really wants it.

**My own fixture used `10.1/a` as a DOI, which is not one.** A registrant
needs four or more digits, so `parse_bibtex` dropped it and every entry
looked identity-less. Three tests failed for that reason wearing the costume
of the reason I was looking for. **Fourth time in this project that a fixture
has been the thing that broke** - concern #32 - and the first where the
fixture was wrong in a way the production code was right to reject.

**A defect fell out that had nothing to do with the change.**
`add_literature` handed *every* local path to `_plan_binaries`, where the
notes path filters through `_binary_candidates` first. So a paper already in
markdown demanded MinerU, and a `.bib` naming markdown documents refused the
whole batch with an install hint. Reachable since milestone 2 by
`kennis corpus add -l paper.md`. Found only because the new bibliography
fixture points `file =` at markdown rather than at a PDF nobody has.

**The static check turned out to be the whole of the whole-batch rule.** I
expected to need a dry run to decide whether a bibliography could work. It
needs nothing: an entry has a body if it names a file that exists or carries
an eprint, and both are readable from the file. So the refusal happens in
`_papers_of` before a single paper is written, and the only thing needing a
stated boundary was the runtime case - a 406 from arXiv is not a property of
the bibliography, and rolling back to honour it would be a transaction the
corpus has no other use for.
