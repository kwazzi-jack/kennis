# Milestone 4, step 2: index freshness from a commit

Milestone / step: `design/plan.md`, "Milestone 4", item 4.
Date: 2026-09-21

Previous sketch: `2026-09-21-m4a-the-git-wrapper.md`. What it left: a corpus
is a git repository and every command can record what it did.

## What I am about to do

Replace "which documents changed" with a question git already answers.

Milestone 3's manifest records a digest per indexed document, and answering
freshness from it means walking the whole corpus and comparing each one.
Design section 19 replaces that: the index records **the commit it was built
from**, and freshness becomes

```
git diff --name-status <built_from> HEAD -- <collection>/
git status --porcelain -- <collection>/
```

That is `O(changed files)` rather than `O(corpus)`, exact rather than
digest-by-digest, and the added/changed/gone distinction survives intact
because it is precisely what `--name-status` returns.

## How I expect it to work

### Three states, and only one is a fault

boepie has four and the vocabulary is worth keeping:

| state | meaning |
|---|---|
| `in step` | nothing the index holds has changed |
| `stale` | at least one document is changed or gone, so hits are wrong |
| `unverifiable` | the recorded commit is not in this repository, or none was recorded |

boepie's fourth, `corpus absent`, does not arise here: the corpus and the
index are in one repository, so there is no case where the index survives and
the corpus does not.

**`unverifiable` is never read as fresh.** An index built on another machine
names a commit this repository has never seen, and the honest answer is that
the question cannot be answered - not that the answer is yes.

### Documents added do not make an index stale

boepie's rule, kept deliberately, and design section 15 restates it:
*incomplete is not wrong*. Between a `corpus add` and the `corpus index` that
follows it, the index holds nothing false - it simply holds less than the
corpus does. So serving decides on `stale` alone, while a caller asking "is
this index complete" reads `added` as well.

This is the distinction that makes a scheduler unnecessary. There is no third
state of "will be current later", which is the one that misleads, because it
stays true right up until the job did not run.

### Counting documents, not files

`--name-status` returns paths and kennis counts documents, and those are not
the same thing. A wrapped document is a directory holding `content.md` plus
its assets, so three changed paths under `notes/A Paper/` are one changed
document.

The rule, applied to each path below the collection:

- `.../content.md` - the document is the directory containing it
- `.../anything.md` - the document is that file
- anything else - the document is the directory containing it, because it is
  an asset sitting beside a `content.md`
- `.gitkeep` and anything resolving to the collection root itself is ignored

Derived from the path rather than from the filesystem, because a *deleted*
file cannot be examined, and deletions are exactly what this has to count.

### Uncommitted work counts

`git diff` between two commits misses anything not yet committed, and kennis
commits after each command - so a document added and not yet indexed is
committed, but a document a user edited by hand two minutes ago is not. Both
are changes the index does not know about, so `git status --porcelain` is
read as well and merged in.

That merge is also what makes step 3 cheap: out-of-band detection is the same
two commands with a different question asked of the answers.

### What the manifest records

`built_from` joins the manifest, and the per-document digest map **stays**.
Section 19 says the digest map "stops earning its place", and that is true
for *freshness*, but the vector cache keys on those digests and the manifest
is where a later `corpus status` reads them without re-chunking. Dropping
them would trade one cheap read for a corpus walk.

## What I expect to be uncertain or difficult

- **Whether `git status --porcelain` and `git diff --name-status` double
  count.** A file both committed-since and edited-since appears in each, and
  the counts must be of documents rather than of reports.
- **Rename detection.** `--name-status` reports `R100 old new`, which is one
  document moved rather than one gone and one added. Whether git detects it
  depends on similarity, so I expect the safe reading - treat the old path as
  gone and the new as added - and want to check what that does to the counts.
- **The index directory is inside the repository**, so a build commits a
  large binary change. Scoping every query to the collection keeps that out
  of the freshness answer, but I should check nothing else reads it in.
- **A corpus with one commit.** `git diff <first> HEAD` where they are the
  same commit is empty, which is right, but the first index is built at the
  same commit it records, and I want that to read `in step` rather than
  anything cleverer.

## What actually happened that I did not expect

**I parsed `git status --porcelain` as space-separated and it is
fixed-width.** Two tests failed immediately: the format is two status
characters, a space, then the path, and *either* status character may be a
space, so ` M notes/a.md` split on its first space gives an empty code and a
path of `M notes/a.md`. The effect was that no uncommitted change was
recognised at all, so a hand-edited document read as `in step` - the failure
direction that matters, an index reported current when it is not. Concern
#74, and the lesson generalises to the rest of this milestone: git's
porcelain formats are column-oriented *so that* they parse stably, and
reading them as whitespace-separated fields works until a field is empty.

**Both predicted difficulties were real and both were cheap.** Double
counting between the diff and the status does happen, and is fixed by
counting documents in sets and subtracting; renames do arrive as `R100` and
are read as a delete plus an add. I had expected at least one of these to be
harder than it was, which is the first time in this project that the
predictions have been both accurate and undramatic.

**Section 19 says the digest map is retired and I kept it, which took some
thought to justify.** The section lists "the per-item digest map" among what
git replaces. But the map it retires is the *pack store's*; the one in the
index manifest is doing a different job, because the vector cache keys on
exactly those digests. Dropping them would not remove the need for them, only
the record of which ones an index was built against. Concern #75, recorded so
a future reader comparing the two does not conclude one is wrong.

**The scoping test earned its place before I expected it to.** I wrote
"a change outside the collection does not disturb it" reasoning about the
index being in the same repository - and it is the test that would have
caught an unscoped query calling every index stale the instant it was
written, which is a mistake I would certainly have made had I written the
diff call without thinking about where the index lives.

**Nothing about the first-commit case mattered.** I had flagged that an index
built at the commit it records should read `in step` rather than anything
cleverer. `git diff <commit> <same commit>` is empty and that is the whole
answer; there was nothing to decide.
