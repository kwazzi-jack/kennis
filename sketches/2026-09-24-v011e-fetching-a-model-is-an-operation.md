# Fetching a model is an operation

Milestone / step: v0.1.1, concerns #196, #209
Date: 2026-09-24

## What I am about to do

Make the embedding model's download something kennis reports rather than
something a dependency prints over the top of it, and make the ollama backend
fetch its model the way the fastembed one already does.

## How I expect it to work

**The announcement needs to know whether a download is coming.** fastembed
publishes it: `TextEmbedding.list_supported_models()` gives each model a
`sources.hf` repository, and huggingface caches under
`<cache_dir>/models--<org>--<repo>`. So the check is whether that directory
exists, read from the *installed* fastembed rather than hardcoded - which
matters, because the spelling is version-dependent (see below).

**One function, both backends, one call site.** `ensure_model_available(
binding, events)` in `engine/rag/embedding.py`, called by `embed_texts` only
when it built the embedder itself. A caller that supplied its own embedder -
every test - never reaches it, so no test acquires a network dependency by
accident.

    fastembed: not in the cache -> ItemStarted("fetch-model", <model>), download
    ollama:    not in `client.list()` -> ItemStarted, `client.pull(model)`
    openai:    nothing to fetch

`ItemStarted` rather than a new event type: it is exactly "work began on one
item, named so a front end can show what is in flight before there is an
outcome". The words live in `render/`, the layout in `cli/sink.py`.

**The quieting.** huggingface_hub draws `Fetching 5 files: 100%|...` with
tqdm on stderr, in the middle of kennis's own report.
`huggingface_hub.utils.disable_progress_bars()` turns it off at the source,
called once before the model is constructed. The information is not lost: the
event goes to the log like every other event, which is what the event stream
exists for.

**Ollama pulls rather than refusing.** kennis's convention is that an error
names the command that resolves it, so `ollama pull <model>` would be
defensible - but fastembed downloads without asking, and a person who set
`embedding.backend = ollama` and named a model has asked for that model.
Refusing for one backend and not the other is an inconsistency a user has to
learn. The risk is that a typo'd model name pulls something large; ollama
answers a name it does not have with a 404, so a typo is an error rather than
a download.

## What I expect to be uncertain or difficult

Whether `disable_progress_bars()` is enough. fastembed may print on its own
account, and huggingface_hub reads `HF_HUB_DISABLE_PROGRESS_BARS` at import
in some versions, so a function called later may be too late. I expect to
have to check by running it rather than by reading it.

The second is the ollama membership test. `client.list()` returns names as
`nomic-embed-text:latest` while the configured model is usually
`nomic-embed-text`, so an exact match will report every model as missing and
re-pull it on every index.

## What actually happened that I did not expect

Both named uncertainties were real, and one of them bit in a way the sketch
described and I still walked into.

**The quieting works, and the ordering hazard is one I created.** The sketch
says huggingface_hub reads the variable at import, so a call made later is
too late - and then I wrote `_hf_repository`, which imports fastembed to read
the model list, and called it *before* the quieting. First live run: the line
printed, the bar printed under it. Naming a hazard in advance is not the same
as noticing the code that walks into it. `_quieten_downloads()` is now the
first statement of the fastembed branch, with a comment saying why the order
is load-bearing.

**fastembed re-enables what we turn off.** It calls `enable_progress_bars()`
in a `finally` after each download, and huggingface_hub answers that with a
`UserWarning` when the environment variable has already disabled them. The
variable wins - the bar stays away - so the warning reports a conflict kennis
created on purpose and tells a reader nothing actionable. Suppressed at the
construction site, and it had to be: `filterwarnings = ["error"]` would make
it fatal in any test that ever loads a real model.

**The hook was in the wrong place and the tests could not see it.** I put the
fetch in `embed_texts`, guarded by "only when no embedder was supplied". That
covers the *search* path, where `embed_texts` builds one for a single query,
and misses the *indexing* path entirely - `index` builds an embedder once and
hands it to every batch, so `embed_texts` always saw one. The command that
actually downloads was the one left unannounced, and nine passing unit tests
said nothing, because they all called `ensure_model_available` directly.

The fix is one line moved: building an embedder is what needs the model, so
`embedder_for` ensures it. The lesson is the test that was missing rather
than the line that was wrong - `test_building_an_embedder_is_what_fetches_
the_model` exists now and an injection confirms it fails without the call.

**The ollama check found a defect nobody was looking for.** Indexing through
ollama works; searching the index it builds has never worked on any version,
because the host is deliberately absent from the stored binding and
`validate_binding` refuses a daemon backend that has none. Two correct
decisions meeting to produce a backend that can write an index and not read
one. Concern #210.

The predicted tag problem was real and cost nothing, because the sketch had
already named it: `list()` returns `nomic-embed-text:latest` where the
configured name is `nomic-embed-text`, and the test was written before the
code.
