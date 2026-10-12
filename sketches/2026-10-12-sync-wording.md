# A sync reports once, in the words its lines use

Milestone / step: after milestone 11's realignment (#447)
Date: 2026-10-12

## What I am about to do

Brian, 2026-10-12, after a corpus sync in the window: the job read

    = c.md - keep
    = o.md - keep
    2 documents already in step
    = c.md - c.md: unchanged
    = o.md - o.md: unchanged

"it says 'X is in step'. Can we use better more systematic wording?"
Three defects and one wording question:

1. **Every document is listed twice**: the live lines, drawn from the
   event stream while the job runs, stay when the outcome arrives, and
   the outcome lists the same documents again.
2. **The live line says the engine's verdict name**, `keep`: the sync
   emits `Quoted(action.verdict)` and the stream prints it.
3. **The outcome line repeats its name**: `describe_action` begins with
   the address, for the command line, where the address is not
   otherwise on the line; the window puts the name first already.
4. **"In step"** is a third vocabulary beside the lines' (added,
   updated, removed, unchanged) and the window's index states
   (searchable, needs indexing).

**The system:** a sync's headline counts by the same words its lines
use, in a fixed order - added, updated, taken over, removed, unchanged,
left as yours - so `2 documents unchanged`, `1 document added, 2
unchanged`. An index that is current is **up to date** everywhere
(`the notes index is up to date`), and a moved file "is kept up to date
where it is". "In step" stays only as the engine's own state name,
which no reader sees.

## How I expect it to work

- `render/packs.py`: `describe_verdict(action)` is the line's words
  without the address; `describe_action` is `address: ` plus it, for
  the command line. `describe_sync` joins `count verdict-word` pairs,
  the noun on the first. `verdict_word(name)` words a verdict name for
  the stream.
- `gui/stream.py::as_message`: an `ItemFinished` from either sync
  operation words its quoted verdict with `verdict_word`.
- `gui/pages.py`: the outcome's item detail is `describe_verdict`.
- `progress.js`: when the outcome lists items (`.items`), the live list
  is removed - the outcome is the record, the live lines were progress.
- `render/words.py::describe_freshness`: "is up to date".

## What I expect to be uncertain or difficult

- Tests across the command line assert "in step" in `corpus status` and
  `context status`; they change to "up to date", and a negative
  assertion ("in step" not in an unindexed status) must change with
  them or it passes vacuously.
- The add job's outcome also lists items; removing the live lines there
  too is the same rule and should be checked to lose nothing (a refusal
  line with remedies is in the outcome).

## What actually happened that I did not expect
- **The name was taken.** `describe_verdict` already words what `pack
  validate` established; the address-less line is `describe_outcome_of`.
- The old headline counted only what changed (`2 files changed, of 6`);
  counting each kind in the lines' words says the same and more, and
  the protection rule holds - an edited file is "left as yours", never
  "unchanged", and a test injection merging the two is caught.
- The add job's outcome lists items too, so its live lines go as well;
  every live line has its counterpart in the outcome there (refusals
  carry their remedies only in the outcome), so nothing is lost.
- Not walked against Brian's corpus: a sync fetches and may commit, and
  a scratch corpus has no pack to sync. The script's rule is tested by
  reading it; the words by calling them.
- Injections: six, all caught.
