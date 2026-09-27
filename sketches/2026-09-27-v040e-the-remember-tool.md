# v0.4 unit 8d: `remember`, the one tool that writes

Date: 2026-09-27

## 1. What I am about to do

The MCP `remember` tool. Design section 12: "an agent must be able to
write, to both notes and context". Every other tool in this server
answers a question; this one changes the machine.

## 2. How I expect it to work

A thin adapter over two engine functions that already exist and are
already tested, chosen by one argument:

```
remember(text, title=None, group=None, to_context=False) -> str
    to_context=False  ->  engine/remember.py::remember, into notes
    to_context=True   ->  engine/context/notes.py::remember_in_bundle
```

The corpus path is the sequence every mutating command uses and the
command line already writes: take `corpus_lock`, call the engine,
`Repository.commit`. The bundle path takes no lock and makes no commit,
because a bundle lives inside a repository kennis does not own and
committing there would take over the user's version control.

**No interactive path, so everything unresolved is an argument.** The
plan says this is where the decision channel would first be wanted and
that the server implements it by refusing. `--from` and standard input
do not cross: both are ways of getting text into a *process*, and a
tool call already has the text.

Four decisions I expect to have to defend:

- **One note per call, not batched.** The read tools batch because
  reading four things is one intention. Writing four things is four
  intentions, and a batch multiplies what one misunderstanding writes
  into a machine-global store. Repetition is cheap anyway: `remember`
  deduplicates on the digest of the text.
- **No `no_index` parameter.** The command line has `--no-index` for a
  person doing a bulk import. An agent is not doing that, and an agent
  that writes a note it cannot then find has been handed a broken
  tool. Exposing the flag invites a wrong choice to save a cost the
  caller cannot measure.
- **The `document_id` is in the answer**, which the command line's
  report does not print. A person's next act is to read the file; an
  agent's is to pass the handle to `read_notes`.
- **A length cap**, which neither front end has now. A person typing
  prose is self-limiting and `--from` is deliberate; a model emitting
  a large blob into a machine-global corpus is an accident nobody
  asked for.

`render/words.py::index_state` phrases whether the note is searchable,
and both front ends call it. Not section 20's exception - that covers
hits and spans - just the ordinary rule that the words live in
`render/`.

**The path in the answer is relative to the corpus root**, per the
invariant added with #300. `kennis remember` currently prints an
absolute one (`display.detail("+", str(report.path))`), which is the
same defect #299 was, in a command that unit 8c did not look at. It is
fixed here rather than left, because this unit has to decide what the
tool prints and "the same as the command line" is the answer only if
the command line is right.

## 3. What I expect to be uncertain or difficult

- Whether `ContextNotFound` from `to_context=True` is the right
  failure, or whether the tool should fall back to notes. I think it
  must fail: an agent asked to record a project decision, and silently
  putting it somewhere machine-global is a worse answer than none.
- What the cap should be. 10,000 characters is a guess at "prose a
  model would reasonably tell kennis to keep" with room to spare. I
  have no measurement and will say so.
- Whether the corpus commit belongs in the tool or whether a
  long-lived server should batch commits. The plan defers commit
  batching while the command line is the only front end - that
  sentence is now out of date and the answer may still be "one commit
  per call", but it should be decided rather than inherited.
- Whether an agent will use this as a scratchpad. Nothing enforces
  otherwise; the docstring is the only lever, so it has to say plainly
  that this is durable and machine-global.

## 4. What actually happened that I did not expect

**The first test I wrote asserted a promise without its precondition,
and failing taught me the contract.** "It writes, and what it wrote can
be searched for without a second call" is section 12's promise and it
is conditional: `remember` indexes its own write **only into a
collection that already has an index**. The engine refuses to build a
first index for one remembered line, and its docstring gives the
reason - section 15 measures a first build at 50s for 1942 chunks, so
one sentence would pay for the whole corpus. My test ran against a
fresh corpus and got `NothingToIndex`.

That split one test into two, and the second is the more useful: on an
unindexed collection the note is written and is *not* findable, and
the agent has to be told, or it reports success to the user and a
later search comes back empty with nothing to explain it.

**The live run found two things the green suite did not**, which is
now three units in a row where that has been true.

The first: `[not indexed]` printed on one line and "It is not
searchable yet" on the next - one fact twice, because `index_state`
has a word for the outcome and I had written a sentence for it as
well. The state word is now dropped when the sentence appears.

The second: `remember(notes): 1 documents` in the commit subject.
That one is *not* a defect - `commit_summary` composes a storage
format that `_SUBJECT` parses back, so the key is a fixed field name
rather than wording - but it cost the time to establish that, which is
why it is in `concerns.md` as #303 rather than only here.

**I created a `.context/` bundle in Brian's repository by accident.**
A `cd` inside a compound shell command did not take effect, so
`kennis context init --here` ran in `/home/brian/PhD/kennis` instead of
the scratch project. Four scaffolding files, nothing tracked, removed
immediately. The lesson is not about kennis: a command that acts on
"here" is one to run with an explicit directory, or from a shell whose
directory has been verified in the same call - and a test harness is
not a substitute for that, because the harness always sets its own
root and the live run is exactly the run that does not.

**`remember`'s own report was printing an absolute path** - the same
defect as #299, in a command unit 8c never looked at, found only
because this unit had to decide what the tool should print. And the
test that should have caught it,
`test_the_report_says_where_it_went`, asserted only that the word
"Remembered" appeared. Concern #302, which also records why the
obvious fix to that test would have been hollow: a long `tmp_path`
wraps across terminal lines, so `str(corpus) not in output` passes on
precisely the output it exists to reject.

**The four refusals in section 3 all survived contact**, and the one
I was least sure of - the 10,000 character cap - is recorded as a
judgement rather than a measurement in #301, so that it is revisited
if a real refusal is ever hit rather than treated as a considered
number.
