# Pack through the report and the log

Milestone / step: milestone 7 (packs), after units 2 to 4
Date: 2026-09-26

**Written after the work, not before it.** This started as an audit Brian
asked for - "do not forget styling, formatting and logging if it is not
present" - so there was no prior belief to record and the fourth heading is
doing a different job from usual: it holds what the audit found rather than
what surprised me against a prediction. Noted so the file is not read as
though the method was followed.

## What I am about to do

Check the three pack commands against the conventions every other command
in kennis follows - `--quiet`, the theme, the operation column, and the
event stream - and close whatever is missing.

## How I expect it to work

The three channels are separate and only one of them is automatic:

- **`--quiet`** comes free, because `display.operation`, `detail`, `note`,
  `hint` and `guidance` each carry their own guard and `failure`
  deliberately does not. Nothing to do if the commands already use those.
- **Styling** comes free for the same reason: the theme is applied by the
  primitives, and `MessageHighlighter` runs over every line.
- **The log does not.** `cli/sink.reporting()` is what fans an operation's
  events out to the display and to `LogSink`, and an engine that emits no
  events reaches neither. Section 14's rule is that the log holds what the
  report leaves out, and `pack update` reports one line - "2 files
  recorded" - with no record anywhere of which two.

## What I expect to be uncertain or difficult

Whether the pack operations have anything worth logging, or whether the
report already says everything. `validate` names every problem it found, so
the log adds little; `update` is the opposite.

## What actually happened that I did not expect

**Two of the three were already right, and the audit was still worth it.**
`--quiet` behaves correctly - a clean run is silent, a failure is not - and
the theme applies without a line of work, using only the eight standard
colours. Confirmed by running with `--quiet` and with `FORCE_COLOR=1` and
reading the escape codes rather than by assuming.

**The log was entirely absent, and `--quiet` is what makes that matter.**
Under `--quiet`, `pack validate` prints `error: 1 problem in this pack` and
nothing else - that is the convention working as designed, the report
suppressed and the failure kept. But with no events emitted, *which* file
was wrong existed nowhere: not on the terminal, not in the log. A release
pipeline would get an exit code and no way to act on it. The three
operations now emit `ItemFinished` per item, which `DisplaySink` ignores by
design and `LogSink` writes, so the quiet failure is diagnosable:

    pack-validate failed: notes/one.md (digest-mismatch)
    pack-update changed: notes:notes/one.md
    pack-update removed: notes:notes/two.md

**A defect in the reporting I wrote, found while writing its test.** I
first keyed `update`'s events by the file's address relative to the pack
root. A pack may ship one tree to both `notes` and `context` - `validate`
allows it deliberately, because section 5's diff key carries the section -
so two distinct items collapsed onto one key and the count was halved. The
key is `section:path` now, which is the design's own diff key spelled out.

**Two formatting slips.** `display.operation` takes the past-tense verb for
what the command *did* and I passed `Valid`, which is a verdict; it is
`Checked` now, with the verdict on the line below. And the two verdict
lines - digests checked, digests not checked - were printed through
different primitives, so one indented under the operation and the other sat
at the margin. Both are `detail` now, the second with `>`, which is the
marker `sink.marker_for` already gives a skipped item.

**One thing left alone deliberately.** `>` has no entry in
`_MARKER_ROLES`, so it renders through the `marker` fallback while `+`,
`-`, `~` and `=` have colours. That is pre-existing - `Outcome.SKIPPED`
already maps to `>` and every command printing a skipped item hits it -
so changing it would restyle output beyond this milestone. Concern #261.
