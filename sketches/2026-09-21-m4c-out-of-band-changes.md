# Milestone 4, step 3: changes made outside kennis

Milestone / step: `design/plan.md`, "Milestone 4", item 5.
Date: 2026-09-21

Previous sketch: `2026-09-21-m4b-index-freshness.md`. What it left: git
answers what changed since the index was built.

## What I am about to do

The corpus is a directory of real files, so someone will eventually edit,
delete or drop one in by hand. Design section 19 gives five rules for what
kennis does about it, and the governing principle is one sentence: **kennis
never loses data, and every out-of-band change is reported alongside the
command that would have done it properly.**

The detection mechanism is the same two git calls step 2 already makes, asked
a different question. What is new is deciding what each answer means.

## How I expect it to work

### The five rules

| what happened | `owner` | kennis does |
|---|---|---|
| edited | `pack:<id>` | report; never overwrite, never auto-revert; name `corpus restore` or `corpus claim` |
| edited | `user` | note only that the index is behind - it is theirs |
| deleted | `pack:<id>` | restore from history, report, name `corpus remove` |
| deleted | `user` | restore from history, report, name `corpus remove` |
| created | - | report as present but not a document; name `corpus add` |

Three of these are worth restating because they are the ones that look wrong
at first glance.

**An edit to a pack-owned document is never auto-reverted.** Reverting is a
resolution the user may choose, not the action kennis takes on noticing.
Silently discarding someone's edit on the next sync does not become
acceptable just because git could undo it afterwards.

**A deletion is restored rather than honoured, for both owners.** An
out-of-band delete carries no record of intent, and treating an accident as
an instruction is the more expensive mistake. Restoring costs an annoying
extra command; honouring costs a document. `corpus remove` exists and says
what it means.

**A hand-created file is inert, not adopted.** Guessing metadata for a file
someone dropped in would invent exactly the identity the rest of the design
refuses to invent.

### Reading the owner of something that is no longer there

The rules key on `owner`, which lives in the document's frontmatter. For an
edited file that is on disk. For a **deleted** file it is not, and the whole
point is to know what was lost - so the owner is read out of history with
`git show HEAD:<path>`.

That is the first place in kennis where a document is read from a commit
rather than from the filesystem, and it wants a lenient reader: a document
whose frontmatter will not parse still has to be reported as deleted, with
its owner unknown rather than with an exception.

### Packs do not exist yet, and the rules are implemented anyway

v0.1 has no packs, so every document's owner is `user` today. The owner
distinction is implemented regardless, because the schema already carries it
and the code is three lines - and retrofitting it during the pack milestone
means revisiting the one part of this that must not be got wrong quietly.

### Restoring

`git checkout HEAD -- <path>` puts a deleted document back. Two properties
matter:

- **Restoring is per path, not a whole-tree reset.** A reset would also
  discard the edits in the same working tree, which rule one says never to
  discard.
- **Restoration is reported, not silent.** The user deleted something and got
  it back; being told is the difference between kennis being trustworthy and
  kennis being haunted.

### What this does not do

It does not commit. Detection and restoration leave the working tree in a
state the caller then records, because the caller knows which operation it
was part of and this does not.

## What I expect to be uncertain or difficult

- **A file both edited and staged**, or a rename, produces porcelain codes I
  have not handled beyond step 2's needs. Step 2 taught me to read these as
  columns rather than fields (#74), so I expect the remaining surprises to be
  in which codes mean what rather than in parsing.
- **A created file that does have frontmatter.** The design says a hand-made
  file "has no frontmatter and no id, so no loader sees it" - but someone
  copying a document in from another corpus produces one that does. Reporting
  it as created is still right; whether the loader should then index it is a
  question the design does not answer.
- **Whether detection should scope to one collection or the whole corpus.**
  Freshness is per collection because an index is. An out-of-band change is
  not, and a user who deleted something wants to hear about it whichever
  collection it was in.
- **Restoring a wrapped document.** Deleting the directory removes several
  paths, and restoring must bring back all of them rather than just the
  `content.md` that identified the document.

## What actually happened that I did not expect

**Nothing failed, which has not happened before in this project.** Eighteen
tests, all green on the first run, and the three injected defects - honouring
a deletion, reading a deleted file's owner from disk, and restoring
everything rather than only deletions - were caught by six tests between
them. The reason is worth naming rather than enjoying: this step decides
*what changes mean*, and the mechanism it decides over was built and debugged
in step 2. The porcelain parsing that cost me two failures there is the same
code here.

**Reading a deleted document's owner from history is the whole trick, and it
is one line.** `git show HEAD:<path>` is the only place the frontmatter of a
deleted file still exists, and the rules key on `owner`, so without it the
delete rules could not be applied at all. I had written it in the sketch as
an aside and it turned out to be the part the step rests on.

**The created-file case is not as settled as the design sounds.** Section 19
reasons from "it has no frontmatter and no id, so no loader sees it", which
is true of a file someone typed and false of one copied in from another
corpus. kennis reports the copied file as "not a document" and the loader
then indexes it like any other, because nothing distinguishes it. Both
defensible fixes point in opposite directions, so it is concern #77 rather
than a decision made in passing.

**mypy objected to a guard I wrote out of habit.** `split_frontmatter`
returns `dict[str, Any]`, so my `isinstance(frontmatter, dict)` check was
unreachable and mypy said so. Removing it made the `try` block say what it
actually means: the empty mapping is a document with no frontmatter, and the
exception is YAML that will not parse, which are different things that I had
been collapsing.

**The two predicted difficulties I worried about most did not arise.**
Wrapped-document restoration works without special handling, because git
restores by path and a deleted directory is simply several deleted paths.
And the porcelain codes needed nothing beyond what step 2 already read - the
surprises there were spent.
