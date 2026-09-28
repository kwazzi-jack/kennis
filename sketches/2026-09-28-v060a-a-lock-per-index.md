# v0.6 unit: a lock per index, and a note that is never lost

Date: 2026-09-28

## 1. What I am about to do

Concern #167, decided by Brian today. `remember` takes the
corpus-wide lock, so a note written while a terminal is indexing is
**refused and lost**. Design section 16 says it should write the note
- the durable part, and per-file atomic - and report `indexed:
deferred, run kennis index`.

Honouring that needs the second lock section 16 assumes and milestone
5 did not build: one per collection index, so that writing a document
and rebuilding an index can be refused independently.

It is worth doing now rather than in milestone 5 because there are
three front ends that can contend - a terminal, an agent and an open
window - where then there was one.

## 2. How I expect it to work

**Two locks, guarding two different things.**

| lock | at | guards | held for |
|---|---|---|---|
| corpus | `.kennis.lock` | the documents and the git repository | a write and its commit |
| index | `index/<collection>/.lock` | one index's build, swap and pointer | the build |

Section 16's own sentence, except for the half of it that is false as
built: it says git's `index.lock` serialises writers to the documents,
and it does not - kennis shells out one git command at a time, so
git's lock protects git's index during a command and nothing between
commands. The corpus lock stays for the documents. #167 records this.

**`build_index` takes the index lock itself**, rather than each
caller taking it. Section 16 says "held across build, swap and
`latest.json`", which is exactly that function's body, and three
callers each remembering is three chances to forget.

**`build_indexes` stops holding the corpus lock across the build.**
That is the change that makes the rest possible:

```
with corpus_lock:  restore hand deletions
for each collection:  build_index   # takes its own index lock
with corpus_lock:  commit
```

**`write_note` splits in two.** Corpus lock: write the note, commit.
Then index, and if the index lock is held, do not wait:

```
try:      with index_lock: build
except IndexBusy:  indexed = "deferred"
```

`IndexOutcome` gains a fourth value, `deferred`, beside `indexed`,
`unindexed` and `skipped`. `render/` gains its sentence, which is
where the words live.

**One hazard this opens, and it has to be closed.** Releasing the
corpus lock during a build means another process may commit while a
build is half-written - and `Repository.commit` stages with `git add
--all .`. `replacing_directory` stages at
`index/<collection>/.<index_id>.staging-XXXX`, a dotfile directory
git sees like any other. So a `remember` during a build would commit
a partial index. The staging and retiring directories get gitignored:
they exist for one build and are never part of a commit.

That pattern goes into `_GITIGNORE`, which is written at `corpus
init`. **An existing corpus will not have it**, and this project
writes no migrations, so that is two lines to add by hand.

## 3. What I expect to be uncertain or difficult

- Whether `build_index` taking the lock breaks the bundle's index,
  which has a different root and no corpus lock at all.
- Whether any test drives two builds and now deadlocks itself. A
  lock is per process *and* per thread with `filelock`; a nested
  `build_index` inside a held index lock would deadlock rather than
  raise, because `filelock` is reentrant by default.
- Whether `deferred` needs a fourth word everywhere `IndexOutcome` is
  rendered, and how many places that is.
- Testing contention honestly. The 9f lesson: holding a lock makes
  the operation *fail*, which is a different condition from the one
  being tested. Here failing is what I want to test, so a second
  thread holding the index lock is the right instrument.

## 4. What actually happened that I did not expect

**`write_note` needed no change at all.** Section 2 planned to split
it into a corpus-locked write and a separately locked index. It
turned out the split belonged entirely in `build_indexes`: once a
build stops holding the corpus for its duration, `remember` acquires
the corpus normally, writes, commits, and only its own index attempt
meets the contention. The engine call it makes was already shaped to
report what happened to the index.

**The lock cannot be the first thing taken.** `filelock` needs its
file's directory to exist, so taking the lock at the top of
`build_index` creates `index/<collection>/` - and a build refused for
an empty collection then leaves the scaffold of an index behind. A
test said it must not, and was right to: that is the first thing a
new user meets. The lock now goes after the emptiness refusal.
Everything before it reads.

**I had not thought about the vector cache.** It is written during
embedding, before the swap, and two concurrent builds would write the
same directory. So the lock cannot be narrowed to the swap alone even
though the swap is the part that looked dangerous.

**Releasing the corpus during a build makes a lock-ordering cycle.**
`remember` holds the corpus and wants an index; a build holds an
index and wants the corpus to commit. `timeout=0` on both means
neither deadlocks - but the build would raise at its commit after
minutes of work, and losing a build to a commit is the wrong trade.
`IndexBuild.committed` records it instead.

**And a staging directory can be committed by somebody else.** That
one I did predict, in section 2, and it was still the most
interesting: it is only reachable *because* of this unit, since
nothing else could hold the corpus mid-build before.

**Two injections missed, and they failed differently.** Setting the
index lock's timeout to 0.2s did not fail the refusal test - the
holder holds for thirty seconds, so 0.2s still refuses. That
injection was inert, not a hollow test, and the honest fix was a
loose timing bound separating "told now" from "queued behind a
rebuild". The second miss was a genuinely hollow spot: I had written
`deferred`'s sentence and tested nothing about it.

**The fifth unit running in which the real command found the defect.**
`kennis corpus index` against a held lock printed "nothing to index"
at a corpus with three notes in it, and pointed the reader at
`corpus add`. The branch had been correct since milestone 3 and
became wrong the moment a build could reach no collection for a
second reason. Concern #331 - and the general shape is worth keeping:
a counter reaching zero for a new reason gets reported with the old
reason's words.
