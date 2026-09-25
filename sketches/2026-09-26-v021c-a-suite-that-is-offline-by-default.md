# A suite that is offline by default

Milestone / step: after v0.2.0, first green CI run
Date: 2026-09-26

## What I am about to do

Fix the three defects the first real CI run exposed, all of which had passed
locally since the day they were written:

1. Three `test_cli_corpus.py` tests download `BAAI/bge-small-en-v1.5` from
   Hugging Face, because their `isolated` fixture does not set
   `KENNIS_EMBEDDING_BACKEND=none` and `retrieval.corpus_method` defaults to
   `hybrid`. Invisible here because the model is already in
   `~/.cache/kennis/models`.
2. Three `test_converters.py` tests import `reportlab`, which this checkout
   has only because the `mineru` extra pulls it in. CI installs no extras.
3. `test_texts_are_sent_in_batches` asserts `[4, 4, 2]` on a list that
   concurrent workers append to, so it asserts an order `embed_texts`
   explicitly does not promise.

## How I expect it to work

**Offline by default, opt in to the network.** The guard moves from seven
individual test modules into `tests/conftest.py` as an autouse fixture that
sets `KENNIS_EMBEDDING_BACKEND=none`. Every module then inherits it, and a
module that wants a real backend sets its own with `monkeypatch.setenv`,
which runs later and wins. `test_live.py` is the only such module and it is
already marked `network`.

The mechanism the guard relies on: `embed_texts` builds an embedder only
when the caller supplied none, and `ensure_model_available` is reached only
from there. A CLI test supplies nothing, so the backend setting is the only
thing standing between `kennis corpus index` and a download.

**`reportlab` becomes a declared dev dependency** (`uv add --dev reportlab`)
rather than an accident of the `mineru` extra, and the `pytest.importorskip`
in `a_real_pdf` goes with it. A guard that always skips in CI is worse than
a missing dependency: it reports green for a path nothing ran.

**The batching test asserts the partition, not the order**: the multiset of
batch sizes is `{4, 4, 2}` and their concatenation is the input. Input order
of the returned matrix is a separate promise with its own test.

## What I expect to be uncertain or difficult

Whether an autouse `KENNIS_EMBEDDING_BACKEND=none` breaks a test that asserts
the *default* backend. `test_settings.py` and `test_setup.py` both touch the
variable, and a test reading "the default is fastembed" would now read
"none". Those need `monkeypatch.delenv`, and finding them means running the
suite rather than reasoning about it.

Second: whether making the suite genuinely cache-independent is worth doing
now. Pointing `XDG_CACHE_HOME` at `tmp_path` would turn any future download
into a local failure rather than a CI-only one, but it breaks
`test_the_model_cache_is_not_in_a_temporary_directory` by construction.

## What actually happened that I did not expect

Both uncertainties named above turned out to be real, and one other thing did
not go as expected.

**The eleven tests were exactly where I guessed, and that was luck.** The
autouse default broke `test_cli_config.py`, `test_settings.py` and
`test_setup.py` - the three modules whose subject is what the settings layer
reads out of the environment. What I had not thought through is the ordering
question it raises: a conftest fixture and a module fixture are both autouse
and both function-scoped, and the module's `delenv` only works because
conftest fixtures are instantiated first. That is a property of pytest, not
of this code, and the comment in each module says so rather than leaving the
next reader to test it.

**My first attempt to reproduce the failure proved nothing.** I ran the suite
with `HF_HOME` pointed at an empty directory and `HF_HUB_OFFLINE=1`, watched
1867 tests pass, and nearly concluded the CI failure was environmental.
`model_cache_dir()` is `Path(user_cache_dir("kennis")) / "models"` - it never
reads `HF_HOME`, so the real cache at `~/.cache/kennis/models` was still
there and `_ensure_fastembed` returned early. The variable that works is
`XDG_CACHE_HOME`. A negative result from a check that could not have been
positive is the same mistake as an injection that matches nothing (#66), and
I made it in the course of investigating three tests that had passed for the
same kind of reason.

**Making the suite cache-independent turned out to be free, and I still did
not do it.** With `XDG_CACHE_HOME` empty the suite passes except for
`test_the_model_cache_is_not_in_a_temporary_directory`, which fails only
because a scratchpad lives under `/tmp`. So the offline run is a two-line
shell command any session can execute, and a permanent fixture that pins
`XDG_CACHE_HOME` would buy little beyond it while breaking a test whose
subject is that very path. Recorded in #253 instead, where the next session
will find the command.

**One thing I did not expect at all**: the two docstrings in `embedding.py`
that state the safety property were not merely incomplete, they asserted the
opposite of the truth, and they were written by whoever built the seam that
makes the property achievable. Being the author of the mechanism is not
evidence about the environment it runs in.
