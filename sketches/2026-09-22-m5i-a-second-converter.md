# Milestone 5, out of band: Datalab as a second conversion backend

Milestone / step: Brian's scope decision - PDF conversion and the Datalab
alternative are both part of the minimum working version.
Date: 2026-09-22

Previous sketch: `2026-09-22-m5h-git-paths-are-bytes.md`.

## What I am about to do

Two things, in order.

1. **Prove MinerU converts.** `test_converters.py` says in its own first
   line that a fake `mineru` on PATH pins the command line and nothing more.
   Concern #109 item 1. Done: a real two-page PDF through `corpus add -l`
   produced correct markdown in 18.6s on the GPU.
2. **Add `DatalabConverter`**, the hosted alternative, behind the `Converter`
   protocol that was declared for exactly this.

## How I expect it to work

### MinerU stays on 3.x, and this is a finding rather than a preference

Brian asked whether moving to v4 helps. It does not. v4 is a different
program wearing the same name:

| | v3.4.5 | v4.0.4 |
|---|---|---|
| shape | one-shot CLI, `-p in -o out -b pipeline` | subcommands, client to a daemon |
| a run | `mineru ... ` converts and exits | `mineru server start` first, or every command refuses |
| full local parse | the pipeline backend, local models | a *second* "parse-server", or `--remote` |
| `--remote` | none | uploads the document to mineru.net |
| local without a daemon | everything | `--tier flash`, text-only: no OCR, no tables |

`mineru parse` itself refuses without the server, so the daemon is not
optional. kennis's decisions record says **no background service**, and the
converter's own docstring explains why it drives a subprocess: MinerU imports
torch at import time, and a crash must not take kennis down. A daemon
inverts both. The pin becomes `mineru[pipeline]>=3.4,<4` - the `pipeline`
extra because the bare package has no torch and the default backend needs it.

### The Datalab shape, and where it differs from MinerU

`POST https://www.datalab.to/api/v1/convert`, `X-API-Key`, multipart `file`
plus `output_format=markdown` and `mode`. The response carries
`request_check_url`; poll it - with the same header - until `status` is
`complete`, then read `markdown`. `success: false` or `status: failed` means
read `error`.

Two consequences for the interface:

- **There is no batch endpoint**, so a batch is N requests. The converter's
  docstring guessed that hosted conversion would want batching because "one
  request beats several"; that guess is wrong and the comment has to change.
  `ConversionBatch` still fits: it reports per document, which is what a
  per-document request produces naturally.
- **`front_page` cannot be filled.** MinerU's content list classifies page
  furniture, which is where a paper stamps its arXiv id or DOI. Datalab
  returns markdown. So a Datalab conversion yields no front page, and
  identity has to come from what the user supplied. That is a real
  capability difference and belongs in the entry, not hidden.

### Sending a document to a third party is the user's decision

The key lives in `credentials.toml` like the OpenAI one, the backend is a
setting, and neither defaults to Datalab. `config init` asks, which is the
same consent mechanism as the embedding backend and the model download.

## What I expect to be uncertain or difficult

- **Whether the backend belongs in the derivation binding.** `future.md` 3
  raises it: two backends produce different markdown from one PDF, so if the
  binding does not record which converted it, a cached derivation is wrong
  after a backend change. I expect this to be real and to be out of scope
  here - recorded rather than fixed.
- **Testing without a key and without the network.** `httpx.MockTransport`
  for the polling protocol, and one `network`-marked live test that skips
  unless a key is present. The protocol is where the bugs are: the poll loop,
  the failure field, the header on the *second* request.
- **`default_converter()` takes no arguments** and three call sites use it.
  Making the choice a setting means reading settings there or threading them
  through; I expect reading them there, since `Settings()` is already how
  every other engine default is found.

## What actually happened that I did not expect

**The pipeline extra, not the package.** The bare `mineru` package has no
torch, so the very first real conversion failed with `No module named
'torch'` after five milestones of green tests. `mineru[pipeline]` is what the
default backend needs, and it exists in 3.4.5 - which makes #14 stale.

**Nothing had ever read a credential, so nothing had noticed it could not.**
`credentials.toml` was written by `config init` from the day it existed and
read by no code at all. `settings.py`'s own docstring says "which nothing
here reads", true of that module and easy to read as a design statement. The
effect was that choosing `openai` in the setup, typing a key and being told
it was written left the embedder failing for the want of that key. Datalab
needed the same mechanism, which is the only reason it surfaced. Concern
#131.

**The interface held; one comment in it was wrong.** `Converter` took the
second implementation without a change, and `ConversionBatch` fitted
unaltered. The module docstring's guess that hosted conversion would want
batching because "one request beats several" was the one part that did not
survive: there is no batch endpoint, so a batch is N requests, and per
document reporting is what made that a non-event.

**`front_page` is where the two converters genuinely differ**, and it is not
a gap to be closed later. MinerU's content list classifies page furniture,
which is where a paper stamps its arXiv id; Datalab returns markdown and
nothing else. So a hosted conversion cannot identify a local PDF from the
document itself. Recorded as a capability difference (#132) rather than
papered over, because the alternative - reading an identifier back out of
body text - is exactly what the identity rules refuse everywhere else.

**My first injection against the real conversion was wrong, and said so.**
Emptying `_FURNITURE_TYPES` changed nothing: `_front_page_of_v2` returns
`furniture + body`, so the set orders page one rather than filtering it. The
test was right and my model of the code was wrong, which is the failure mode
the injection rule exists to expose - it just exposed it in the injection
instead of in the test.
