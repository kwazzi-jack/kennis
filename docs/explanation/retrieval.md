# How retrieval works

A search runs two independent legs over a collection and fuses their
rankings. This page explains why it is built that way, and why the relevance
level you see is trustworthy in one case and only comparative in another.

## Two legs

A document is split into chunks of about 1500 characters, overlapping by 200
(`chunking.size` and `chunking.overlap`). A chunk is the unit that is
searched and the unit that is returned, because a whole document is usually
too large to be an answer.

Each chunk is indexed twice:

**BM25**, a lexical ranking function. It scores a chunk by the query's terms
appearing in it, weighted so that a rare term counts for more than a common
one and a long chunk is not rewarded for length alone. It finds a chunk that
uses your words. It cannot find one that uses different words for the same
thing.

**Dense retrieval**, over embeddings. Each chunk is mapped to a vector by an
embedding model, the query is mapped by the same model, and chunks are ranked
by cosine similarity. It finds a chunk that means what you asked, including
one sharing none of your vocabulary. It can also confidently return something
merely topically adjacent.

The two fail in different directions, which is the reason for having both.

## One fusion

The legs produce two rankings, and their scores are not comparable - a BM25
score is unbounded and depends on the corpus, a cosine lies in a fixed range.
Adding them would mean inventing an exchange rate.

kennis uses **reciprocal rank fusion**, which discards the scores and keeps
only the positions:

```
score = sum over legs of  1 / (k + rank)
```

with `k = 60` (`retrieval.rrf_k`) and `rank` counted from 1. A chunk ranked
first by one leg and not at all by the other scores `1/61`. A chunk ranked
third by both scores `2/63`, and so beats it. Agreement between two methods
that fail differently is the signal.

Each leg contributes its top 50 candidates before fusion.

## Why the relevance level is not the score

This is the part worth understanding, because it determines how much to
trust what you are shown.

`kennis search` prints a level - `very high` down to `very low` - and there
are three different things it can mean.

### Banding the fusion score would be meaningless

The fused score is a function of **rank alone**. It contains no information
about how well anything matched. Banding it would restate the ordering the
numbered list already shows, and would label the first hit of a search that
matched nothing `very high` for the sole reason that it was first. kennis
never does this.

### The cosine band is absolute, and measured

A cosine similarity has a meaning independent of the query, but only for the
model that produced it. For `BAAI/bge-small-en-v1.5`, the default, the cuts
are:

| level | cosine |
|---|---|
| very high | 0.80 and above |
| high | 0.72 to 0.80 |
| medium | 0.64 to 0.72 |
| low | 0.56 to 0.64 |
| very low | below 0.56 |

These were measured rather than chosen: nine queries against a real corpus of
243 chunks, five of them genuine questions and four deliberate nonsense. The
genuine queries' best hits fell between 0.765 and 0.816; the nonsense
queries' best hits fell between 0.567 and 0.607. Nothing landed in between,
and the cuts sit in that gap.

Because the scale is absolute, `high` means the same thing for every query.
A search where everything comes back `very low` is telling you the corpus
does not contain the answer - which a relative scale could never say.

### The lexical band is relative, and says so

With no dense leg - `--mode bm25`, or an index built with
`embedding.backend = none` - there is no absolute scale. kennis falls back to
banding each hit as a fraction of that query's own best hit, at 0.8, 0.6, 0.4
and 0.2. The summary line then reads `relevance relative to the best lexical
match` rather than `relevance by cosine similarity`, because the top hit of a
lexical search is `very high` by construction.

### An unmeasured model gets no band at all

If you configure a dense model kennis has not calibrated, it prints no
relevance level. Inventing cuts for an unknown scale is precisely the failure
the other two cases are built to avoid. The hits are still ranked and still
correct; only the claim about their quality is withheld.

Use `--scores raw` to see the underlying numbers in any case:

```
kennis search "your query" --scores raw
```

## Choosing a method

```
kennis search "query" --mode hybrid   # both legs, the default
kennis search "query" --mode dense    # meaning only
kennis search "query" --mode bm25     # words only, no model needed
```

`hybrid` falls back to `bm25` against a lexical-only index rather than
failing.
