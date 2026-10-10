# 11b. Feedback in three time ranges

Milestone / step: milestone 11, unit 11b (`design/plan.md`), concerns #405, #412
Date: 2026-10-10

## What I am about to do

Make the window say what it is doing at every time scale: the button
changes on click, the strip names the item in hand and how long the job
has run, a job stays visible on every page until it ends, and a page
lists what ran. And close #412: a POST sent without htmx answers a page.

## How I expect it to work

**Immediate (under 0.1 s).** Every form that posts - the four job
forms and the note form - carries `hx-disabled-elt="find button"`, so
htmx disables its button for the request's lifetime. htmx also puts
`htmx-request` on the form while it waits; the stylesheet gives a busy
button a progress cursor and a small spinner drawn in CSS. No script.

**Seconds.** `stream.py::as_message` stops dropping `ItemStarted` and
sends `{"kind": "current", "text": "Adding arXiv:1101.2268"}` - the
participle from `render/words.py::progress_label`, the one already on
the command line's bar, or `fetching_model` for a model download.
`Jobs.stream` already wakes every 0.25 s on an empty queue to check
whether the job is done; it now also yields an `Elapsed` once a second,
which `as_message` turns into `{"kind": "elapsed", "text": "41s"}` with
the words from a new `render/words.py::running_for`. `progress.js` puts
`current` in the step line and `elapsed` beside it - it composes
nothing. `Elapsed` is the stream's own record, defined in `gui/jobs.py`,
not an engine event: the engine does not know a page is watching.

**Long, or elsewhere.** `base.html` asks a Jinja global
`job_now(request)` for the running job, from `request.app.state.jobs`,
and when there is one renders `job.html` into `#job` - so a page drawn
mid-job attaches to its stream and the job survives navigation.
`progress.js` watches *every* unwatched `.job[data-job]` rather than the
first, because the job page and the strip can both carry one. Idle, the
strip is a status line: the corpus's short revision, how many
collections are searchable, how many need indexing (from `pane_now`,
which the page already computed), and the last job as a link.

**Activity.** `GET /activity` lists the jobs the registry keeps for an
hour, newest first: kind, state, when, a link to `/job/{id}`. A pane
entry under kennis, called what its page is called.

**#412.** A POST that did not come from htmx: the job routes answer
`303` to `/job/{id}`, and `GET /job/{id}` without htmx answers the job
panel inside the shell; a refusal answers `problem.html`; `/remember`
answers the note page with its outcome; `/history/clear` answers `303`
to `/`. One helper, `_from_htmx(request)`, decides, as `_action` already
does for GETs. 303 because it is the answer to a POST that tells the
browser to GET, and a reload then does not post twice.

**Tests that post** do so as the htmx form does, through a per-file
helper sending `HX-Request: true`; the new tests post without it.

## What I expect to be uncertain or difficult

- `hx-disabled-elt="find button"` needs htmx 2; the vendored copy is
  2.0.4, which has it, but `find` resolution on a form is unverified.
- A page drawn mid-job: the job may finish between rendering and the
  script connecting. The stream then yields nothing and closes, and
  `progress.js` fetches the outcome - I expect that path to already
  work, but it has only been exercised for a job started on the page.
- Elapsed ticks are a second stream of messages on the same connection.
  A test that consumes a stream to its end must not now wait a second
  per tick; the tick must be cheap and the job must still end it.
- Thirty-three test posts change shape; the risk is a test that was
  asserting the fragment and now passes on a page for the wrong reason.

## What actually happened that I did not expect

- **A job's events were a queue each watcher consumed.** Walking the
  window found it: the strip on a page drawn mid-job attached after the
  item had been named and showed an empty step line, and two pages
  watching at once would have split the events between them. It was
  correct only while one page ever watched a job, which the strip on
  every page ended. Now an append-only history under a condition
  variable, read from each watcher's own position; a test with a late
  watcher, injected by starting the watcher at the end (#424). No test
  written from the sketch could have seen it - the sketch did not know
  the queue was consumed.
- The sketch's second uncertainty, a page drawn just as the job ends,
  is answered by the same change: a late watcher replays the history
  and then closes.
- The idle strip does not show the corpus's revision. The page already
  carries it in `#corpus-changed`, and a hash in the strip says nothing
  a reader acts on; the counts and the last job do.
- One injection was incomplete rather than the test hollow: removing
  the busy cursor left the spinner rule, which also satisfies "a rule
  for `.htmx-request` exists". Removing all three rules was caught.
- **The headless shell's screenshot omits a modal `<dialog>`**: the
  busy-button picture showed no dialog while `getBoundingClientRect`
  had it open and centred. Measure the top layer; do not trust the
  picture of it.
- Measured in the browser: the submit button is disabled while its
  request is out; the strip shows "Adding arXiv:1101.2268", the clock
  and "0 of 3" on one page and still after navigating, with the clock
  advancing; Activity lists the running job; no script errors.
- Thirteen injections, all caught once the busy-style one was made whole.
