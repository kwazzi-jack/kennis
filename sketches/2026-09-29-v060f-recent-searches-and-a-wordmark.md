# v0.6f: recent searches, and a wordmark

2026-09-29

## 1. What I am about to do

Brian, choosing between two readings of "a Recents section": **recent
searches**, not recently added documents. And the kennis wordmark
raised in the header, on every page, rather than added a second time
above the search bar.

The wordmark is layout. The recents are the interesting half, because
**kennis has never stored anything about how it is used.** Everything
the interface shows today is recomputed from the corpus on request.
This is the first persistent record of the user rather than of their
documents, and that is a different kind of file.

## 2. How I expect it to work

### Where the queries live, and why not in the corpus

Not in the corpus: it is a git repository that `Repository.commit`
stages with `git add --all .`, and a pack sync converges it. A search
history there would be committed, and later carried to wherever the
corpus goes. Not in the bundle either, for the same reason and worse -
that repository is the user's and kennis does not commit to it.

So: the state directory. `KENNIS_STATE_DIR`, defaulting to
platformdirs' `user_state_dir("kennis")`, which on Linux is
`~/.local/state/kennis` - the parent of `user_log_dir`, so the
history sits beside the log rather than inside it.

**A new environment variable is a hazard, and it is the same hazard as
#325.** A test that does not set it writes to the developer's real
state directory. The remedy is the one #325 established: an autouse
fixture that redirects it, and a test in `test_architecture.py` that
fails if the fixture is removed.

### Whose it is

`gui/history.py`, private to the front end that asked for it.

The rule in CLAUDE.md is that shared orchestration lives beside
`context.py` "because every front end asks and none owns the answer".
Here one front end asks and it does own the answer, and the other two
should not record. `kennis search` writing a file would make a read
command mutate the disk, and the MCP server's searches are an agent's,
not a person's - mixing them into a person's recents is the wrong
answer to "what did I look for". If a second front end ever wants
this, it moves, which is the #292 and #314 pattern.

### Collapsing the keystrokes

The search box fires on `input changed delay:400ms`, so typing
"calibration" is two or three searches, not one: "cali",
"calibratio", "calibration". Recording each would fill the list with
prefixes of one query.

**A new query replaces the most recent entry when one is a prefix of
the other**, and is appended otherwise. Both directions, because
backspacing from "calibration" to "cal" is the same interaction seen
from the other end, and the entry should keep whichever query the
reader stopped on.

**Within five minutes of the entry it replaces**, and appended
otherwise. Section 3 below started without a window and argued
itself into one: "gains" and then "gains calibration" a week later
are two searches the reader made and would want both of, while the
same pair typed in one breath is one search. Time separates those
two cases and nothing else available here does.

Five minutes is not a tuned number and does not need to be. Typing
is seconds and a separate sitting is hours, so any value from about
one minute to about fifteen behaves identically on both cases; the
constant is named so it can be argued with.

A reload of `/?q=...` records the same query again, and an identical
string is a prefix of itself, so recording is idempotent under
reload and under Back.

### What is recorded, and what is not

The query, the scope, the number of hits, and when. Not the results,
not the documents, not which hit was opened. Twenty entries, newest
first; the twenty-first pushes the oldest out.

**It can be cleared, and that is a requirement rather than polish.**
A query is the user's own words and there has to be a way to remove
one they regret typing. A POST to `/history/clear`, because a GET
that writes is one a prefetcher will follow.

### Where it shows

On the search page, when there is no query. When there is one the
results have that space. Each entry is a link to `/?q=...&scope=...`,
which re-runs it - the address already reconstructs a search, which
is what v0.6d bought.

### The wordmark

`header` becomes a wordmark above the navigation rather than the
first item in it. It stays a link to `/`, because that is how a
reader gets home from a document. One word, one place, on every page.

## 3. What I expect to be uncertain or difficult

**Prefix-collapse is a heuristic about typing, and it needed a
window.** Writing this section is what found the case: "gains" and
then "gains calibration" are one search when typed in one breath and
two when made a week apart, and a bare prefix test cannot tell them
apart. Settled before any test was written, by adding the five-minute
window described above. What I still cannot rule out is a reader who
refines a query slowly - reads for ten minutes, then extends it - and
gets two entries where they meant one. That is the benign direction.

**Concurrent writes.** Two windows, or a window and a reload, can
write the file at the same moment. `replace_file` is atomic, so
neither half-writes, but a read-modify-write can still lose an entry.
Losing one recent search is not worth a lock, and I want to say that
deliberately rather than discover it.

**Whether the file should be readable at all.** It is plain JSON in
the state directory, so anything running as the user can read what
was searched for. That is already true of the log, which records
every command and its arguments - so this adds no new exposure, but
it is the first file whose *purpose* is to remember the person.

**The empty state.** A first-run search page has no history and no
results, so it shows the form and nothing else, which is what it
shows today. I do not think "no recent searches" is worth saying.

## 4. What actually happened that I did not expect

**Running the interface once was not enough; running it twice was.**
The first walk looked right: eleven keystrokes of "calibration"
collapsed to one entry, a scope change collapsed into it, clicking a
recent re-ran it. The second walk rendered every query twice, because
the history outlives a launch and the collapse rule only ever looks
at the *most recent* entry. A query run again after others intervened
takes another slot, so the few queries a person actually runs fill
the list with themselves.

Two rules now, and they are about different things. An exact repeat
moves to the top, wherever it sits and however old it is, which is
about repetition. The query still being typed replaces the last one
inside the window, which is about a box that fires every 400ms.
Section 2 had only the second and thought it had the problem covered.
Concern #347.

**Every search reported "9 hits".** `default_top_k` is 3 *per scope*,
so an everywhere search over three indexed collections stops at 9 and
has no idea how many more there were. The number looked measured and
was a ceiling. It now reads "9+ hits" when any scope filled its
quota, which is most searches.

I had written the count into the sketch as an obvious field and never
asked what it would say. Seeing four different queries all reporting
the same number is what asked. Concern #348.

**The margin was empty and kennis's own words were in the column**,
which is the one layout rule this design has: what kennis composed
goes in the margin, what kennis is quoting goes in the column. A past
search is the reader's words in the column and the scope and count in
the margin, and I had put both in the column by using the wrong
class. Invisible in the template, obvious in a picture - the fourth
unit running where that is true.

Then "everywhere, at least 9 hits" wrapped between "9" and "hits" in
an 11rem margin, so the phrase became "9+ hits". A wording decision
forced by a measurement, which is the honest way round.

**Promoting `_atomic` was the right size after all.** `gui/history.py`
needs an atomic write and `replace_file` lived in `engine/_atomic.py`,
private to the engine and imported by seven modules there. The
choices were to reach into a private module, to duplicate ten lines,
or to rename. The rename was two commands and the suite verified it,
which is what "rework things properly" means when the alternative is
a concern entry explaining why something is slightly wrong.

**Section 3's four worries, answered.** The collapse window: settled
before the work, and then found to be the *less* important of the two
collapse rules. Concurrent writes: still unlocked, still deliberate,
and nothing exercised it. Readability: unchanged, the log already
records every command. The empty state: it shows the form and
nothing, and that still looks right - the recents fill it as soon as
there is anything to fill it with.

**The scratchpad lost its `node_modules` across the session
boundary** and the walk script could not import playwright. Two
minutes to reinstall, but worth knowing: the browsers in
`~/.cache/ms-playwright` survive and the driver package does not.
