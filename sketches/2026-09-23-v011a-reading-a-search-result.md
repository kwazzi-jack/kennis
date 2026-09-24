# Reading a search result

Milestone / step: v0.1.1, from `design/brian/v0-1-0-concerns.md` (concerns #186, #194)
Date: 2026-09-23

## What I am about to do

Give `kennis search` a hit rendering a person can act on: a rank, the title
and section, the identifier and chunk index that `kennis read` takes, and a
relevance reading that is either five human levels or the raw per-leg scores.
Style it with the roles that have been in `render/theme.py` since milestone 0
with no renderer.

## How I expect it to work

Three layers, as everywhere else.

`render/hits.py` (new) is the words. `describe_hit` is replaced by a function
returning the *lines* of one hit as plain strings:

    [1] [literature] Dying for freedom: political martyrdom in South Africa
        read: document_id=rxdzjplj8m chunk_index=4
        relevance: high
        <snippet>

The relevance line is where the thought is. `SearchResult.score` is the RRF
value and is a function of rank alone, so banding it says nothing the
ordering has not already said (#186). Two bases instead:

- **cosine**, when `dense_score` is not None. It is in `[-1, 1]` and means
  the same thing for every query and every corpus, so fixed cuts are
  defensible: `>= 0.80` very high, `0.65` high, `0.50` medium, `0.35` low,
  below that very low.
- **lexical, relative to this query's best hit**, when only `bm25_score` is
  set. BM25 is unbounded and corpus-relative, so the only honest reading is
  `score / best`, banded at `0.8 / 0.6 / 0.4 / 0.2`. The top hit is "very
  high" by construction, which is why the basis has to be printed.

So the basis is named once, on the header line, not repeated per hit:

    Found 5 passages, relevance by cosine similarity
    Found 5 passages, relevance relative to the best lexical match

`--scores raw` prints `bm25=12.31 cos=0.874 rrf=0.0312` instead of the level,
which is boepie's `--score-detail` and the thing a person tuning retrieval
needs. `--scores none` drops the line.

`cli/display.py` gets `hit_lines(...)` - no; the CLI already has `plain` and
`detail`. What it needs is a highlighter: `HitHighlighter` over the patterns
`_RANK`, `_HIT_LABEL`, `_HIT_HANDLE`, `_SCORE`, matching boepie's, plus a
`BodyHighlighter` over the `md_*` roles for the snippet and for the spans
`read` prints, and a `TomlHighlighter` for `config show`. Each is a
`RegexHighlighter` with `base_style = "kennis."`, so every group name is
already a role in the table.

The snippet is indented under its hit, because at column zero it is
indistinguishable from the next hit's first line.

## What I expect to be uncertain or difficult

The cosine cuts are a guess dressed as a decision. `bge-small-en-v1.5` is
trained with cosine similarity and its scores sit high - unrelated sentences
land around 0.6 rather than around 0 - so a 0.5 "medium" cut may put
everything in "high" and the band may carry as little information as the RRF
one would have. I expect to have to measure this against a real index before
choosing the numbers, and to record the measurement rather than the numbers.

The second thing is the highlighter's ordering. rich applies patterns in
order and later spans paint over earlier ones, so a `document_id=rxdzjplj8m`
inside a `read:` line has to be matched after the label and not before, and
the snippet's markdown patterns must not run over the handle lines.

## What actually happened that I did not expect

The uncertainty was named correctly and its answer was the opposite of what
the sketch assumed, twice over.

**The cosine cuts could not be guessed, and my first measurement made a
comparison nobody makes.** Measured on 243 chunks of Brian's own corpus, the
model's scores occupy roughly `[0.37, 0.82]`, so the sketch's 0.80 / 0.65 /
0.50 / 0.35 would have put every hit of every query into two bands. Worse,
the first run seemed to show that *nothing* absolute could work: pure noise
("zzzz qqqq xxxx") scored 0.607 at the top, above the *median* of two real
queries. That reading is wrong, and it sent me to a second idea.

**Standardising a hit against its own candidate pool - the idea that looked
principled - inverts the answer.** `(score - median) / MAD` over the 50
candidates gives the four nonsense queries 3.5 to 6.5 and gives two of the
five real queries 2.05 and 2.44. A query with nothing to match produces a
*tight* pool, so any deviation from it looks enormous. It would have
confidently labelled nonsense as the best kind of hit.

**The comparison that matters is top against top, and there the absolute
cosine separates cleanly.** Real queries' best hits: 0.765 to 0.816. Nonsense
queries' best hits: 0.567 to 0.607. Nothing in between. The lesson is about
the measurement rather than about the model: I compared a distribution's tail
to another distribution's centre, concluded the statistic was useless, and
went looking for a cleverer one. Nobody reads a median.

Two smaller things. `rich.padding.Padding` renders a *block* and pads every
line out to the console width, so the first live run wrote a screen of
trailing spaces that were invisible on screen and would have landed in any
redirected file - the snippet is wrapped with `textwrap` instead. And the
engine needed one change I had not planned: `dense_score` was only set for
hits inside the dense candidate window, so a hybrid hit fused in by the
lexical leg had no cosine and could not be banded at all. Cosine is defined
for every chunk; the window is a retrieval budget, not a limit on what is
known.

One thing to watch rather than fix. With `--mode hybrid` the *ordering* is
RRF and the *band* is cosine, so a hit ranked second can carry a higher band
than the one above it. That is honest - the two measure different things -
but it will be asked about.

One more, found at the very end and not about this work at all: the injection
harness left injection A's bytecode in place after restoring the source, so
the suite ran the reverted defect for twenty minutes. CPython validates a
`.pyc` on the source's (mtime, size) and the injection changed neither.
Concern #202, and all nine injections re-run afterwards.
