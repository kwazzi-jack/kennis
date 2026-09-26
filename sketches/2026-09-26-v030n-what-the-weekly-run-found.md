# v0.3 unit n: the first extended CI run, and its three failures

Date: 2026-09-26

## 1. What I am about to do

`.github/workflows/extended.yml` ran for the first time. The slow job
passed; the network job failed three of eleven tests. None of the three
is caused by this milestone's work - they are what a job nobody had run
was hiding, which is #253's lesson and the reason the workflow exists.

- `test_a_real_arxiv_paper_has_metadata` - reproduces locally.
- `test_the_default_backend_really_embeds` - CI only.
- `test_the_whole_dense_path_runs_end_to_end` - CI only, downstream of
  the second.

## 2. How I expect it to work

**The two embedding failures are one cause.** `filterwarnings =
["error"]` turns every warning into an exception, including one raised
inside `huggingface_hub` while it downloads a model: `hf_xet
.download_files() is deprecated`. The download dies part-way, the cache
is left without `model_optimized.onnx`, and the next test fails loading
it. This cannot happen on a machine where the model is already cached,
which is why it has never been seen here. The filter list gains one
narrow entry matching that message, so every other warning stays an
error.

**The arXiv failure is arXiv.** `lookup_arxiv_metadata("1101.1764")`
returns None because `export.arxiv.org/api/query` answers 406. I
measured it rather than guessing: eleven identifiers, some served, some
refused, and the difference is not the paper or the subject. A 406 has
`cache-control: private, no-store` and `x-cache: MISS, MISS` with no
origin hop; a 200 has `x-cache-hits: 15` and a `via: 1.1 google`. The
edge is serving what is warm in its cache and refusing everything else.
So any identifier may fail depending on cache state, and a test that
asserts a particular one is served is asserting something arXiv does not
promise.

The library is already right about this, which I checked by running the
real command rather than reading it: `kennis corpus add -l 1101.1764`
warns "arXiv did not answer for 1101.1764, so its metadata is missing
and its citekey is derived from the title alone" and writes the document
with the title taken from the fetched text. Nothing to fix in `src/`.

So the test learns the distinction the library deliberately does not
make: it probes the endpoint, skips with the status when arXiv is
refusing, and asserts the parse when arXiv answers. A network test that
cannot tell "the service refused us" from "our parsing is wrong" reports
the wrong thing on the only run anyone reads.

## 3. What I expect to be uncertain or difficult

- Whether the 406 is an arXiv incident today or a new standing policy. I
  cannot tell from outside, and the test has to be right either way,
  which is the argument for skipping rather than for choosing a
  different identifier.
- Whether one narrow `filterwarnings` entry is enough, or whether a cold
  cache raises more than one deprecation on the way through. I will only
  find out by running it on a cold cache, which locally means moving the
  model directory aside.

## 4. What actually happened that I did not expect

**The partial cache outlived the failure.** With the filter added, the
two embedding tests still failed - the aborted download had left the
model directory in a state that no amount of correct code could load.
Deleting it and running again was what showed the fix worked. I had
assumed a failed download leaves nothing behind. On CI this matters
more than here: a cache action would carry the damage into later runs
and the fix would look ineffective.

**Both of my first two explanations of the 406 were wrong**, and cheap
measurement is the only reason I did not write either of them down as
fact. I first blamed the `User-Agent`, and tried five header
combinations - all 406. Then the subject, because the three refused
identifiers were all astro-ph and the two served ones were cs - and the
next round refused a cs paper and served another. The cache headers
settled it, and the answer is about CDN warmth, which is not a property
of kennis or of the paper at all.

**The library was already right.** I expected to find something to fix
in `src/`. Running `kennis corpus add -l 1101.1764` showed the warning
is accurate, the citekey falls back to the title, and the document is
written - and the offline test for that path exists, with a control. My
grep for the warning's text found it only in `add.py` and I briefly
concluded it was untested; the test asserts on substrings, not the whole
sentence.

**Choosing a warm identifier mattered more than the skip.** The skip
alone would have left a test that skips on nearly every run, which is a
test in name only. Pointing it at `1706.03762` - chosen for how often
the world asks for it - makes it assert on most runs and skip only when
even that is cold. The skip is the honest fallback, not the mechanism.

**Two things noticed on the way, both logged rather than acted on.**
`Diagnostic.message` is a sentence composed in the engine, which the
phrasing invariant does not list as an exception (#285). And the network
suite runs eleven tests here and ten on CI, because a `DATALAB_API_KEY`
is present on this machine, so running the set locally uploads a
generated PDF to a third party (#286). I ran it that way myself before
noticing.
