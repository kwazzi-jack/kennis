# Each leg says its own score

Milestone / step: v0.7a, retrieval reporting
Date: 2026-09-29

## What I am about to do

Brian searched for `selfcal`, saw the word highlighted in the
passage, and was told `relevance: low`. He was right that this makes
no sense, and the cause is exact.

`basis_for(model, dense_ran)` returns `"cosine"` whenever a dense
leg ran against a calibrated model. `relevance` then bands **only**
the cosine and returns `None` if there is no dense score. So under
hybrid search - the default - every hit is banded on the dense leg
alone and **BM25 is never allowed to speak**. A one-word query
embeds to a modest cosine against a full chunk, so an exact lexical
match reports `low`.

The design was right about the hard part and wrong about the
conclusion. `render/hits.py`'s docstring reasons carefully that the
two scales mean different things and must not be conflated, and then
resolves it by picking one. The resolution should have been to show
both, labelled.

## How I expect it to work

`relevance` becomes `relevances`, returning one band per leg that
actually scored:

    lexical   bm25_score as a fraction of this query's best, in this
              collection - relative, and the label says so
    meaning   dense_score against the cuts measured for this index's
              own model - absolute, and only for a model kennis has
              measured

A leg that did not run contributes nothing, which falls out of its
score being `None` rather than needing to be asked. That is what
removes `Hit.basis` and `basis_for` entirely: `basis` existed to
choose between the two, and there is no longer a choice.
`Hit.model` stays, because each collection's index has its own
embedding model and the cuts belong to the model.

`hit_detail` goes from

    relevance: low  id=zp7iju8j60 chunk=51

to

    lexical: very high  meaning: low  id=zp7iju8j60 chunk=51

`basis_phrase` describes the legs the group actually has rather
than refusing when they differ. Its old refusal - "one sentence
cannot describe both" - was a consequence of there being one band;
with two labels the sentence describes both, and mixing is now the
ordinary case rather than the broken one.

**Nothing about ordering changes.** Hits are still fused by
reciprocal rank, so a hit reading `lexical: very high, meaning:
low` can sit below one reading `lexical: high, meaning: medium`.
That will look odd and it is honest: it is what fusion did, and it
is the thing the single band was hiding.

`rendered_hit` is shared, so both front ends get this at once and
the byte-identical test keeps holding.

## What I expect to be uncertain or difficult

The two labels. "lexical" is the engine's own word and a reader of
this interface is a researcher, so it is not jargon here.
"meaning" is a claim - a cosine is a claim about meaning only to
the extent the model is any good - but "dense" and "embedding" name
the mechanism rather than what it is for. I expect to keep
"meaning" and to be slightly uneasy about it.

Whether the detail line becomes too long. It is in the margin,
which is 11rem, and `relevance: very high` already wrapped there.
Two labelled bands will certainly wrap, and the margin may need to
stack them rather than run them together.

Whether any test asserts the old single-band phrasing in a way that
hides a real regression when I change it. There are byte-identical
tests between the front ends, and those should keep passing for the
right reason rather than because both sides changed together.

## What actually happened that I did not expect



The margin worry was right and its remedy was wrong. The sketch
said "the margin may need to stack them"; the CSS already carried
`white-space: pre-wrap` with a comment claiming that gave "each
field on its own line ... without the engine having to hand over
the parts separately". That claim was false and had been false
since it was written - `pre-wrap` preserves the two spaces and then
wraps wherever the line runs out. It looked true only because
`relevance: medium  id=... chunk=...` happened to break at the
right place. The second band made it break inside one:

    lexical: very high  meaning:
    medium  id=zp7iju8j60
    chunk=6

So `rendered_hit` now hands over `detail_parts` as well as
`detail`, and a test asserts `"  ".join(parts) == detail` so the
two cannot drift. That is a fourth false claim in a comment found
the same way as #82, #318 and the `typeset.js` one - and again the
comment was confident, specific, and had never been checked against
a browser.

The wording had a second-order effect I did not see coming. I
changed the scale labels from noun phrases to full clauses
("lexical is relative to the best match here") because they read
better in isolation. Both front ends print the phrase directly
after the collection's name, so the page then read **"Notes meaning
is an absolute cosine"**, which parses as a possessive. The command
line did not show it, because `display.operation` colours the verb
and the colour does the separating. A phrase that is correct in
isolation and wrong in both its call sites is not a wording
question, and it went back to noun phrases.

One injection was inert rather than caught, which #318 says to
diagnose before touching the test. `relevance_phrase` iterated
`LEGS` *and* its only caller sorted by `LEGS.index` first - one
rule in two places, so removing either could not be observed. The
fix was to delete the caller's sort and change the parameter from
`Sequence[Leg]` to `Collection[Leg]`, which says the order is the
function's. The injection then failed as it should. Worth stating
plainly: **a rule enforced twice is a rule that cannot be tested.**

`score_style_for` changed behaviour and I only noticed because it
was the last thing referring to the removed `Hit.basis`. It used to
ask "does a scale exist", which was true whenever a dense leg ran;
it now asks "can anything here be banded at all". The case that
moves is a hybrid search on a model kennis has not measured: it
used to drop the whole group to raw numbers, and now shows the
lexical band and omits the meaning one. That is better, but it was
a behaviour change arrived at by following a compile error, not by
deciding, so it is written down in #379.

A new test tripped over the #337 comment trap for the third time in
this milestone: the CSS rule *explains* that it no longer sets
`white-space: pre-wrap`, and a regex over the rule body read the
explanation as the declaration. Stripping comments before scanning
is now what all three of these tests do, and it is starting to look
like a helper rather than a habit.
