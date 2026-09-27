# v0.5 unit 9d: writing prose from the interface

Date: 2026-09-27

## 1. What I am about to do

`remember`, from a page. Into notes, or into this project's
`.context/` bundle. The first thing the graphical interface does that
changes the machine.

## 2. How I expect it to work

**The orchestration is extracted, for the third time and the same
reason.** Taking the corpus lock, calling the engine, committing when
something was written - `mcp/tools/remember.py` has it privately and
`gui/` may not import `mcp/`. `retrieval.py` and `holdings.py` are
already outside every front end for this reason (#292, #314), so this
becomes `kennis/writing.py`. Each front end keeps its own wording and
shares the sequence.

**A write is a POST.** Not because it is conventional but because a
GET that writes is a GET something will follow - a prefetcher, a link
checker, a history restore. The page uses htmx's `hx-post`.

**Cross-site protection is the cookie, and it is already there.**
`samesite="strict"` means a form on another site cannot make the
browser send the token, so such a POST arrives without it and is
refused by the middleware written in 9a. That is worth a test rather
than a comment: it is protection by a property of a cookie set for a
different reason, which is exactly the kind that gets removed.

**`CorpusBusy` is a state, not an error page.** The lock is
`timeout=0`, so a `corpus index` running in a terminal refuses this
write. The reply says the corpus is busy and the text is still in the
box, because losing what someone typed is worse than making them
press the button again. Concern #167 is about this lock.

**Two targets, one form.** A radio or select for notes against
context, matching `--context`. No bundle means a refusal that says
so, not a silent fall back to notes - the same rule the MCP tool
follows, for the same reason.

**No `--no-index` control.** The command line has one for a person
doing a bulk import. Someone typing a sentence into a box is not
doing that, and a note they cannot then find is a broken feature.
The MCP tool made this decision already (#301) and it holds here.

## 3. What I expect to be uncertain or difficult

- Whether to re-render the whole page or swap in a confirmation. A
  confirmation is what htmx is good at, but the holdings count in the
  header is now wrong, which is #311 arriving from the inside rather
  than from another process.
- Whether the note's own revision should update the page's
  `data-revision`, or whether the banner should appear for a change
  this window made. Appearing would be technically right and read as
  a fault.
- What the bundle path shows for a group, since a bundle has no
  collections and `--group` means a subdirectory there too.
- Whether the form should offer a title at all, or always derive one.
  The engine derives from the first line and caps at 60 characters,
  which is usually right and occasionally not.

## 4. What actually happened that I did not expect

**Four of eight injections were not caught, and sorting out why was
most of the unit.** Two were hollow tests, one was a gap, and one was
not a defect at all.

**An inert injection is evidence, not noise.** Twice I wrote a change
that altered no behaviour, and both times the reason was worth
knowing. `@app.api_route("/remember", methods=["POST"])` is exactly
`@app.post`, so nothing moved. And `if True:` around the commit
changed nothing because **`Repository.commit` already returns None on
a clean tree** - which made my own docstring's claim, that the guard
prevents an empty commit, false. That is #82's category: a comment
asserting a property the code does not have.

The guard does do one thing, and only after chasing the inert
injection did I find it: `commit` stages with `git add --all .`, so
committing on a repeated note would sweep any unrelated change
sitting in the corpus - a file someone dropped in - into a commit
labelled `remember(notes)`. The docstring now says that and a test
holds it.

So the rule to add beside #312: **when an injection is not caught,
establish whether the test is hollow or the change was inert before
touching the test.** Weakening a test to catch an inert change would
have been the worst available outcome.

**My empty-text test was hollow in a way that reads as thorough.**
The page guards empty text and so does the engine, with nearly the
same words - so asserting the words passed with the page's guard
removed. What differs is what each offers next: the engine's refusal
carries `kennis remember --help`, which is a command-line answer to
someone looking at a textarea. The test now asserts the role and the
*absence* of that command.

**The command line had been left out of the extraction, and that hid
the gap.** I moved the MCP server onto `writing.py` and left
`cli/commands/remember.py` with its own copy, reasoning as I had for
`retrieval.py` that the command line does something different. It does
not - search differs, writing does not. The consequence was that
`writing.py`'s commit rule had no test at all, because the test that
covers it lives in the command line's suite. Moving the command line
onto it fixed both. Concern #317.

**`write_note` needed three arguments the other front ends do not
pass** - `origin` for `--from`, `index` for `--no-index`, and `events`
for the progress bar. Recorded because it is the shape a shared
function takes when one caller is richer than the others, and the
alternative - leaving the command line out - is what caused the gap
above.
