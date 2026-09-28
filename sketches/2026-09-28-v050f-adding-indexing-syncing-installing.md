# v0.5 unit 9f: adding, indexing, syncing, installing

Date: 2026-09-28

## 1. What I am about to do

The rest of corpus management in the graphical interface: add,
index, `corpus sync`, `context sync`, and installing a pack. With
progress streamed from the event stream, and a repair form built
from 9e's refusals.

## 2. How I expect it to work

**Three parts, in this order, because each needs the one before.**

### The shared sequence, extracted

Every mutating command does the same four things: take the corpus
lock, undo hand deletions, call the engine, commit. That sequence
lives in `cli/commands/corpus.py` today, which is a front end, and
the graphical interface would have to copy it. `writing.py` already
set the precedent for one note; this does it for the rest.

New `src/kennis/operations.py`, beside `context.py`, `retrieval.py`,
`holdings.py` and `writing.py`:

| function | takes the lock | commits |
|---|---|---|
| `add_documents` | yes | yes |
| `build_indexes` | yes | yes |
| `synchronise_corpus` | yes | yes |
| `install_a_pack` | yes | no - the store is not the corpus |
| `synchronise_bundle` | no | no - that repository is the user's |

`_undo_hand_deletions` moves here and stops printing: it returns the
restored changes and each front end says what it says about them.
Concern #317 is the reason the command line is rewired in the same
unit rather than left alone - leaving it out last time hid that
`writing.py` had no commit coverage.

### Progress, as server-sent events

A `corpus add` of one PDF is twenty seconds of MinerU and a docs
crawl is minutes, so a POST that returns when the work is done is a
browser that appears to hang.

`gui/jobs.py` holds one job at a time - which is what the corpus lock
permits anyway. `start` runs the operation on a thread with a sink
that puts each event on a `queue.SimpleQueue`; `GET /job/{id}/events`
drains that queue as an `text/event-stream`, and the page draws it.

**Not a timer, so the focus invariant stands.** The server pushes as
events arrive and the stream ends when the operation does. The
invariant forbids polling a subprocess forever at an interval nobody
can choose; this is a bounded push for as long as one operation runs.

The event becomes JSON whose text is already rendered by `render/`,
so `static/progress.js` appends lines and moves a bar without
composing words. Written rather than vendored: `EventSource` is
built into the browser and htmx's SSE extension would be a new
vendored file for about forty lines of work.

### The pages, and the repair form

`/add`, `/index`, `/sync`, `/packs`, each a form that POSTs and hands
off to a job page. When an add finishes, every refused item is shown
with its sentence and its repair: `gui/repairs.py` turns a `Refusal`
into a form - a second exhaustive `match`, which is each front end
rendering for itself rather than duplication - so `NoIdentity` offers
"add it to notes instead" as a button with the path already filled,
and `AmbiguousIdentity` offers one radio per value it found.

`CorpusBusy` is a state with a retry button, not an error page.

## 3. What I expect to be uncertain or difficult

- Whether `EventSource` sends the token cookie. It should for a
  same-origin request, and the guard is middleware, so a failure
  here is a 401 on the stream and a page that shows nothing.
- Whether a thread running the engine while the request thread holds
  nothing causes trouble with `filelock` - the lock is taken *inside*
  the worker, so the thread that takes it is the thread that releases
  it, which is what `filelock` wants.
- How much of the command line moves without changing its output.
  Nine commands call `_undo_hand_deletions` or `_commit`.
- Whether one job at a time is too strict. Two adds at once would
  fail on the lock anyway, so the limit is honest, but it has to
  *say* so rather than silently drop the second.
- `pack add` takes the corpus lock and does not commit, and `context
  sync` takes neither. Those are two exceptions to a table with five
  rows, which is a lot of exceptions for one abstraction.

## 4. What actually happened that I did not expect

**The extraction was the easy part.** Nine call sites mentioned
`_undo_hand_deletions` or `_commit`; only four moved, because the
other five - claim, disown, move, remove, restore - are still command
line alone. The whole suite passed unchanged afterwards, which is the
evidence that code moved rather than behaviour. I had expected to
spend the unit's difficulty here and spent almost none.

**The five-row table with two exceptions turned out to be right.**
Section 3 worried that `install_a_pack` locking without committing
and `synchronise_bundle` doing neither was a lot of exception for one
abstraction. Writing them out made the opposite case: each exception
has a one-sentence reason that belongs in the code, and having the
three disciplines side by side is what makes them visible. Scattered
across three command bodies they were invisible.

**`EventSource` sends the cookie**, as expected, and the guard being
middleware meant the streaming route needed nothing added. The
injection that skipped the guard for `/manage` and `/job` was caught.

**The one-at-a-time test passed for the wrong reason first.** I held
the corpus lock to keep a job occupied - but a lock makes the
operation *fail*, and a failed job is a finished job, so the slot was
free again before the second request arrived. The honest version
holds the first job open on an event the test releases. This is #63's
lesson in another costume: the test has to fail for the reason it
exists, and "the lock is held" is not the same condition as "a job is
running".

**Three things were found by running the command, not by the suite.**

The first two were wording. A refusal showed a repair *button* and
the equivalent terminal command side by side, which asks the reader
to leave the interface to do what the interface does; and an add
ended with `kennis corpus index` printed on a page that has an Index
button six inches above it. Both are now a form where the interface
can act and a command only where it cannot.

The third was not wording. **The interface wrote nothing to the log.**
The command line hands the engine `FanOut(DisplaySink(), LogSink())`;
the job sink had one subscriber, a queue drained by a browser. So an
add made from the window left no record - and the browser's copy is
the most perishable one there is. Concern #326, and the third unit
running in which executing the command found what a green suite did
not.

**And one thing found by a test failing for an unrelated reason.** A
context sync outside a bundle started a job instead of refusing,
because `find_bundle` walked up from the working directory and found
a `.context/` in the *kennis repository* - created earlier the same
afternoon by an early draft of `tests/test_operations.py` that ran
`kennis context init` through `CliRunner`, which does not chdir. A
later test then wrote a note into Brian's working tree. Concern #325.
The fix is an autouse fixture that chdirs every test into its own
`tmp_path`, which is #253's shape exactly.
