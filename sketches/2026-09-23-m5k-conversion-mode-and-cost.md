# Milestone 5, out of band: the conversion mode is a setting, and a hosted conversion says what it cost

Milestone / step: Brian on concern #146 - "it is probably a good idea to have
these as settings and also report this if needed? Maybe just at least mention
remaining usage?"
Date: 2026-09-23

Previous sketch: `2026-09-23-m5j-env-files-for-keys.md`.

## What I am about to do

Three things, and one thing I am deliberately not doing.

1. **`conversion.mode` becomes a setting.** `DatalabConverter` sends
   `mode: "balanced"` because I typed it when writing the converter and never
   said so. It is a price decision (`accurate` is 2.5x `fast` per page) and
   belongs where a user can see and change it.
2. **`ConversionBatch` carries what the conversion cost.** The API returns
   `total_cost` in cents and kennis discards it.
3. **`kennis corpus add` reports that cost** when there is one. The engine
   names the number; `render/` phrases it; the command line prints it.

**Not doing: remaining account credit.** There is no endpoint for it - the
documentation offers a dashboard and nothing programmatic. kennis can report
what it has spent, not what is left, and it must not imply otherwise.

## How I expect it to work

### The mode setting

`ConversionSettings.mode: Literal["fast", "balanced", "accurate"]`, default
`"balanced"`. Measured prices, one page:

| mode | cents/page | runtime |
|---|---|---|
| `fast` | 0.4 | 1.3s |
| `balanced` | 0.4 | 1.5s |
| `accurate` | 1.0 | 2.5s |

`balanced` stays the default because it costs what `fast` costs on this
evidence. The setting exists so the choice is visible and so `accurate` is
reachable, not because the default is in doubt.

The setting is read where `backend` already is - in `default_converter()` -
and passed to `DatalabConverter.__init__`, so a directly constructed
converter in a test takes its mode as an argument and never reads settings.
MinerU ignores it: the field describes the hosted backend and the
description must say so, because a setting that silently does nothing for
the default backend is the kind of promise the settings docstring warns
against.

### The cost

`ConversionBatch` gains `cost_cents: float | None`. `None` means "no cost was
reported", which is what MinerU always means - not zero, because zero is a
claim about money and MinerU makes no such claim. `DatalabConverter` reads
`total_cost` from the completed poll response and sums it across the
documents in the run.

Then it travels: `_convert_batch` accumulates into the `ConversionPlan`, the
plan's total reaches `AddReport.cost_cents`, and `_report_add` prints it.

A repeat conversion of a document the server has already seen returns
`total_cost: 0.0`, which is a real answer - the cache hit genuinely cost
nothing - and is distinct from `None`.

### The words

The engine hands over a number of cents. It does not build a sentence,
because #81 says the engine names and does not phrase. `render/words.py`
gets a function that turns cents into what a person reads, and the command
line appends it to the existing `Added N documents in 1.4s` line rather than
printing a line of its own.

Sub-cent amounts are the normal case - a 19-page paper is 7.6 cents - so the
phrasing has to stay readable there rather than rounding to `$0.08`.

## What I expect to be uncertain or difficult

1. **Whether the mode actually changes the price on a real document.** I
   measured one synthetic page. A cache hit returned `0.0` and `0.1s`, so any
   re-measurement on the same file is worthless; each mode needs a document
   the server has not seen.
2. **Where the cost should be summed.** A batch is several documents in one
   API call per document; the plan already loops. Getting the total right
   when a document in the run fails is the case I expect to get wrong first.
3. **Whether `AddReport` is the right carrier.** It is frozen and has a
   `counts` property; adding a field is easy, but `add` has three entry
   points (`_ADDERS`) and I do not yet know that all three route through the
   same plan.
4. **The architecture test.** `render/` may not import a front end, and the
   cost phrasing has to live there rather than in `display.py`, which is
   `cli/`.

## What actually happened that I did not expect

### An injection found a missing test rather than a hollow one

Nine injections; eight caught on the first pass. The one that was not -
"drop the cost on its way out of the batch" - was not a hollow test but an
**absent** one: I had tested that the converter produces a cost and that
`render/` phrases it, and never that the number survives the journey between
them. The injection is what noticed, which is a different service from the
one it performed in the previous sketch. There the test existed and proved
nothing; here the coverage simply stopped short, and nothing in a green suite
of 1324 would have said so.

Three tests added, and the second of them (`batch_size=1`, two runs) then
justified a ninth injection - keeping only the last run's cost - which the
single-document test could never have caught.

### My test was wrong about Python, not about kennis

I asserted `conversion_cost(812.5) == "$8.13"`. Python's `.2f` rounds half to
even, so it is `$8.12`. The implementation was right and my expectation was
arithmetic I had not checked. Rather than quietly change the number I pinned
the tie in a test of its own with the reason for leaving it: reaching for
`Decimal` to move half a cent on a **displayed** figure would buy a real
dependency for nothing, and if kennis ever bills from this number that test
is where to start.

### The mode is part of the cache key

The 19-page paper had already been converted at `balanced`. Re-adding it at
`fast` cost the full 7.6c and took 41.5s, so the server did not treat it as
the same request. This matters for #146's caching note: a cache hit needs the
same document *and* the same mode, so switching mode to save money on a
re-conversion saves nothing and spends again.

### The three uncertainties

1. **Mode prices confirmed on uncached documents**, which the sketch said was
   necessary because a repeat returns `0.0`. Three fresh three-page PDFs:
   fast 0.40 c/page, balanced 0.40, accurate 1.00. The single-page figures
   held.
2. **Summing was the awkward part, as expected**, but not where I thought. I
   expected trouble with a failed document in a run; the actual care was
   needed in `convert`, where a failure used to fall through to the next
   iteration by assigning `markdown[path]` in a `try`. Restructuring it to
   `continue` on failure made the cost accumulation correct by construction.
3. **`AddReport` has three construction sites, not one.** `add_notes` and
   `add_literature` have a plan; `add_docs` fetches over the web and converts
   no binary, so it keeps `None`. Patching by enclosing function rather than
   by text match was what made this safe to automate.

### The architecture held without effort

Uncertainty 4 was whether the phrasing would fight the layering. It did not:
`conversion_cost` went into `render/words.py`, the command line appends it to
the operation line, and the engine passes a float. The one judgement was
putting the cost *on* the `Added ...` line rather than a line of its own, so
a free local conversion reads `Added 1 document in 36.1s` rather than showing
a blank where a number belongs. Verified by running both.
