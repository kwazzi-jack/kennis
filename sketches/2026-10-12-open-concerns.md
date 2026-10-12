# The open concerns from the workbench, dealt with

Milestone / step: after milestone 11's realignment (#447)
Date: 2026-10-12

## What I am about to do

Brian, 2026-10-12: "Please deal with what is open then if it needs
doing." Read every `open` entry first. Three were finished by later
units and only need their status: #405 (11b), #410 (12b), #411 (11c).
Five are live:

1. **#457** - after a job, the strip's status and the pane's rows say
   what was true before it, until a reload.
2. **#455** - `forms/index.html` and `forms/remember.html` carry their
   choices' words in the markup.
3. **#426** - a chunk opening with the document's own title heading
   shows it in bold under a title that already says it. The section
   header dropped a heading equal to the *section*, and the first
   chunk's section is the title, which `hit_title_parts` turns into no
   section - so the heading stays.
4. **#434** - `AmbiguousIdentity` is worded with `--identifier` inside
   the sentence both front ends print.
5. **#422** - Ctrl-C at the terminal ends `kennis gui` with a job
   wherever it is, though Quit refuses while one runs.

The `watch` entries stay as they are: they are watched, not owed.

## How I expect it to work

1. Every job's outcome names three more parts of the page to redraw:
   `#strip-status`, `#pane-documents` (the pane's document count), and
   each collection's row `#pane-row-<name>` - the `<summary>`, not the
   `<details>`, so a folder the reader opened stays open. Each has a GET
   route drawing that element alone, from a template the page includes
   too, so the two cannot differ. `ShownJob.redraws` becomes a tuple of
   pairs; the backup's pair stays. `progress.js` already redraws only
   what the page has.
   The strip's status is drawn even while a job runs, so a job that
   finishes on the page has a status line to redraw.
2. The words move to `gui/words.py` and reach the templates as globals.
3. `passage_html` drops a leading heading equal to the section *or* to
   the document's title; `shown_hits` passes the title.
4. The sentence says what is ambiguous; the flag is a remedy, which
   `remedies_for_refusal` returns for the terminal. Check what the CLI
   prints.
5. On the first Ctrl-C with a job running, `kennis gui` says so and
   keeps serving; a second Ctrl-C ends it. With no job, one ends it.

## What I expect to be uncertain or difficult

- A redraw of a row replaces the `<summary>` inside a `<details>` that
  htmx has processed; the new summary needs nothing from htmx, so that
  should hold, but measure it in a browser with a folder open.
- #434: whether `--identifier` is printed anywhere as a remedy today,
  or whether the sentence was the only place it lived.
- #422: `_wait_for_quit`'s loop and how a second interrupt is told
  from the first; tested with a fake job registry and a raised
  `KeyboardInterrupt`.

## What actually happened that I did not expect
- **#426 was still live under the section header.** The first chunk's
  section equals the title, `hit_title_parts` turns that into no
  section, so nothing was dropped; the passage now also drops a leading
  heading equal to the title, in any case, as the head compares them.
- **#434 had a prior decision in the way of the obvious fix.** A test
  forbids `--identifier` in any remedy, because one would choose the
  paper for the reader. Every candidate as its own command chooses none
  - it is the window's radios with none checked - so it is a separate
  function, `choices_for_refusal`, and the remedies are untouched.
- **A missed injection in #422, and the harness was right.** Letting
  the second Ctrl-C escape raised `KeyboardInterrupt` inside the test,
  which stops pytest's whole run rather than failing a test, and the
  run read "13 passed". The test now catches it and fails.
- #457 walked in a scratch corpus: with the notes folder open, an index
  turned its dot from none to current and the status from "3 documents
  need indexing" to the index's change, the folder still open; a note
  written from the dialog moved both counts to 4 at once. One SIGINT
  with no job still exits 0. A Ctrl-C *during* a job was tested only
  through `_wait_for_quit` with a fake event: no job here runs long
  enough to interrupt by hand without MinerU or the network.
- Not redrawn: an opened folder's *contents* (its documents' U/M marks)
  stay as loaded until it is reopened on another page. The row, the
  count and the status are what #457 named.
- Injections: eleven, all caught after the fix above.
