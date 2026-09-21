# Milestone 4, step 4: reading history and rewinding a document

Milestone / step: `design/plan.md`, "Milestone 4", item 6.
Date: 2026-09-21

Previous sketch: `2026-09-21-m4c-out-of-band-changes.md`. What it left:
kennis records every change and notices every change it did not make.

## What I am about to do

The two verbs that read and rewind what the rest of the milestone wrote.
These are engine functions; the commands that call them are milestone 5.

## How I expect it to work

### `read_history`

`git log` with a machine-readable format, parsed back into the structure the
commit messages were written with. Step 1 chose `add(notes): 3 added` over
"update" precisely so this step could read it, and this is where that pays.

```
commit     the full identifier
when       the author date, as an aware timestamp
operation  "add", "remove", "index", "init"
scope      the collection, or "corpus"
summary    "3 added, 1 unchanged"
```

A message that does not parse is **kept, not dropped**. A corpus may contain
a commit a person made by hand, and a history view that silently omits what
it cannot categorise is worse than one showing a row with an unparsed
subject: the second is honest about what happened, the first invents a
history in which it did not.

Filtering by collection is `git log -- <collection>/`, which is git deciding
which commits touched those paths rather than kennis inferring it from the
scope in the message. Those can differ - a single commit can touch two
collections - and git's answer is the true one.

### `restore_document`

`git checkout <commit> -- <path>`, which step 3 already built for restoring a
deletion. This is the same operation reached deliberately rather than as
repair.

Two things it must do that the deletion path did not need:

- **Take a document identifier, not only a path.** A user restoring
  something says `corpus restore <id>`, and for a *deleted* document the path
  cannot be found by walking the corpus - it is not there. So the identifier
  is resolved against history: find the most recent commit where a file
  carrying that id existed, and take the path from it.
- **Report what it restored and from where**, so the caller can commit it
  with a message naming both.

### The index notices

The plan's last test for this milestone is that a restore is noticed by the
index. Nothing new is needed: restoring changes a file in the collection, so
`index_freshness` reports it changed and the index reads `stale`. Worth a
test precisely because it is a claim about two parts fitting together, and
those are the claims that quietly stop being true.

## What I expect to be uncertain or difficult

- **Finding the path for an identifier in history.** `git log -S<id>` finds
  commits where the identifier's occurrence count changed, which is close to
  but not the same as "where this document existed". I may need to walk
  candidate commits and read them.
- **Restoring to a commit where the document had a different path.** A
  document that was renamed has its content at the old path in an old commit.
  Restoring by today's path would find nothing there.
- **Timestamps.** `%aI` is strict ISO 8601 and should parse directly, but
  this is the first place kennis reads a time back rather than writing one.
- **A commit that touched two collections** appears under both filters, which
  is correct and may still look like duplication in a rendered history.

## What actually happened that I did not expect

**`git log -S` is the obvious tool for finding a document in history and it
answers a different question.** It finds commits where a string's occurrence
count *changed*, which gives the wrong answer for a commit that only moved
the document and no answer at all for one where the identifier was present
throughout. Listing the target commit's tree and reading each file's
frontmatter is more requests and exactly correct. I had flagged this as
uncertain in the sketch and the uncertainty resolved against the clever
option, which is becoming a pattern in this project. Concern #79.

**My own `.gitkeep` from step 1 changed the answer to a step 4 question.**
Filtering history to `literature/` returns the `init` commit, because that
commit really did create `literature/.gitkeep`. The behaviour is right - git
is answering which commits touched those paths, which is the entire reason
the filter asks git rather than reading the scope out of the message - and my
test was wrong. Concern #80, recorded because it is a consequence of a
decision made two steps earlier for an unrelated reason.

**I wrote a genuinely nonsensical line and the tests caught it.**
`if line.strip() == "---" and line is not content.splitlines()[0]` recomputes
the split on every iteration and then compares strings by identity, which is
not a thing that works. Six tests failed. Replacing it with the project's own
`split_frontmatter` was shorter, correct, and reused code that is already
tested - which is what I should have reached for first.

**The last test of the milestone needed no new code, which was the point.**
"The index notices a restore" is a claim about `restore_document` and
`index_freshness` fitting together, and it passed as soon as both existed.
Those are exactly the claims that quietly stop being true, so it is worth a
test even though - especially though - it asserts nothing new.

**Nothing about timestamps or renamed-path restores arose.** `%aI` parses
straight into an aware datetime with `fromisoformat`. The rename case is
handled for free by resolving the path *at the target commit* rather than
today, which I wrote for the deleted-document case without noticing it
covered the rename one too.
