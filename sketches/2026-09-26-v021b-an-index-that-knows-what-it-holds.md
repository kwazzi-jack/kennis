# An index that knows what it holds

Milestone / step: v0.2.1, concern #245
Date: 2026-09-26

## What I am about to do

Stop `corpus status` reporting a document as unindexed immediately after
indexing it.

## How I expect it to work

### The diagnosis was incomplete, and the fix I proposed does not cover it

I recorded #245 as affecting a document **written into the corpus by hand**:
the index command is what commits it, `build_index` records
`built_from = repository.head()` before that commit, and the diff from
`built_from` to HEAD then lists it as added. I recommended committing
out-of-band changes before the build, mirroring `_undo_hand_deletions`.

Running it found the common case. `kennis remember` writes a note, indexes
it in the same call, and the command line commits afterwards - so every
single `remember` on an indexed corpus produces:

    Remembered Ionospheric screens ..., indexed, 2 chunks in 7ms
    warning: the notes index is in step, with 1 document not yet indexed
      hint: run `kennis corpus index`

The note is searchable. The warning is false, and it is the ordinary result
of the most-used command rather than an edge case. **My recommended fix does
nothing for it**: the note is not an out-of-band change, so there is nothing
for a pre-build commit to pick up. The write, the index and the commit are
one call and the ordering is internal to it.

Reordering to fix that would mean committing the document before indexing
and the index afterwards - two commits for one user action, which is the
thing `_commit`'s own comment says not to do.

### What actually answers the question

`built_from` is not the only thing the manifest records. It also records
`documents: {id: digest}` - every document that went into the build, and the
digest of its text at that moment. Unit 5 used exactly this to answer
freshness for a bundle, which has no commit at all.

So git keeps its job and stops being the only witness:

- **git narrows**, as now - `diff --name-status built_from..HEAD` plus
  `status --porcelain`, `O(changed files)` rather than `O(corpus)`;
- **the digest decides**, for each path git flagged:

      not in the manifest        -> added
      in it, digest differs      -> changed
      in it, digest matches      -> in the index, say nothing
      deleted, and in it         -> gone

The third line is the fix. A note committed after the build was still *in*
the build, and its digest proves it.

Reads are bounded by the size of the diff, not the corpus, so the
performance argument in `freshness.py`'s docstring survives.

### What stays

`built_from` and both `unverifiable` states: they answer "can this question
be asked at all", which is a different question from "what does the index
hold". An index built in another corpus is still unverifiable.

## What I expect to be uncertain or difficult

Reading a document to digest it means parsing frontmatter, and a document
whose frontmatter will not parse is exactly the one a corpus in trouble has.
Failing there would break the command that diagnoses it - concern #21's
lesson, one layer down.

Whether `changed` and `added` still mean what `describe_freshness` says once
a digest decides them. A document added to the corpus and indexed in the
same command is neither, and disappears from the counts entirely - which is
correct and makes the numbers smaller than the diff suggests.

## What actually happened that I did not expect

**The manifest was keyed by the wrong thing, and every existing freshness
test failed at once.** `indexed` is looked up with what `document_of`
returns - a path like `notes/trees.md`, derived from the path git reported -
and the manifest recorded `document.id`, which for a corpus is the surrogate
identifier and appears in no path. Nothing matched, so every flagged
document read as "not recorded" and therefore added. Three tests caught it
immediately, including two about moves and edits that had nothing to do with
this change.

The manifest now keys documents by `source_path`. For a bundle the two
strings were always equal - a bundle document's identity *is* its path - so
`bundle_freshness` was unaffected, which is a pleasant consequence of unit
2's decision rather than a coincidence.

One wrinkle survives and is handled with two lookups: `document_of` names a
wrapped document by its directory, while the index records the path of the
`content.md` inside it.

**The first real-command check reported a defect that was not one.** A
hand-written document still read as "1 document not yet indexed" after
`corpus index`, and I nearly went looking for a second bug. The manifest
showed why: the document was genuinely not indexed, because the frontmatter
I hand-wrote for the test failed validation and the strict reader dropped
it. The lenient reader counted it and the report was exactly right. A valid
hand-written document behaves correctly. The lesson is the one #21 already
records from the other direction - `survey` and `contents` disagree by
design, and a test fixture that only one of them accepts will look like a
bug in whatever you happen to be working on.

**`indexed=None` is kept as the old behaviour.** Not for a caller that
exists - both callers pass a manifest - but because the alternative is a
required argument that every test must construct, and because the fallback
is what the function did for five milestones and is still correct when
there is nothing better to hand.
