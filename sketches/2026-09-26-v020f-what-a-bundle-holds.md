# What a bundle holds

Milestone / step: v0.2.0 unit 5
Date: 2026-09-26

## What I am about to do

`kennis context status`: what the bundle holds, and whether its index is in
step. The plan says "the same question `corpus status` answers, one scope
down", and the interesting part is that one of the two mechanisms cannot
come down with it.

## How I expect it to work

### Freshness by digest, because there is no commit to diff against

`freshness.py` opens by saying why the corpus does it with git: the index
records the commit it was built from, so the question is
`git diff --name-status <built_from> HEAD -- <collection>/`, which is
`O(changed files)` rather than `O(corpus)`.

None of that is available here. kennis does not own this repository, so
`build_index` is passed no `Repository`, the manifest records
`built_from: null`, and `index_freshness` would answer `unverifiable` every
single time - which is not merely unhelpful, it is false: the question is
perfectly answerable, just not by git.

The manifest already carries what answers it. Unit 3 tested that
`documents: {id: digest}` is written, precisely so this unit could read it:

    manifest.documents     id -> digest at build time
    on disk now            id -> digest of the file's text

added   = on disk, not in the manifest
changed = in both, digests differ
gone    = in the manifest, not on disk

`O(bundle)` rather than `O(changed files)`, and a bundle is tens of files -
boepie's real one is 57. The digest is `document_digest`, the same function
the manifest was written with, so the comparison cannot drift from what was
recorded.

`Freshness` is reused rather than reinvented. It is the same value with the
same three counts, `describe_freshness` already words it, and the
`unverifiable` state simply never occurs for a bundle.

### What status reports

    Context     <path to the bundle>
    Documents   <n>, in <m> groups
    !           <file>: frontmatter could not be read
    =           the context index is in step
                (or the stale sentence, or no index yet)

The unreadable-file line is `corpus status`'s `fact.problem` one scope down,
and it is the only place a broken header in a bundle is ever reported
outside a build: `BundleLoader` emits a diagnostic during `context index`,
which a reader who has not indexed lately will not have seen.

### What it deliberately does not report

Whether the bundle is committed. It is a genuine question - the design says
the bundle is "committed with it if the user wants" - and kennis could
answer it by running `git status --porcelain .context/`. I am not doing it:
it reads a repository kennis does not own, it adds a subprocess and two
failure modes (no repository, no git) to a command that otherwise touches
nothing but the bundle, and `context index` already ends by naming the
commit as the reader's to make. `git status` is one command away and is
theirs.

### Engine and front end

`bundle_status(bundle) -> BundleStatus` in `engine/context/status.py`,
carrying facts only: the counts, the per-group counts, the unreadable paths,
and a `Freshness | None`. No sentences - the invariant says the engine names
and does not phrase, and `describe_freshness` in `render/` already holds the
words for the only sentence here.

## What I expect to be uncertain or difficult

Whether "added" should be a fault for a bundle. For the corpus it
deliberately is not: between `corpus add` and `corpus index` the index holds
less than the corpus, and incomplete is not wrong. The same argument
transfers, but the bundle case is different in one way - `remember
--context` does not index, so a bundle is *routinely* in the added-only
state, where a corpus is only briefly. If the status says "in step" with
three documents unsearchable, that is technically the corpus's rule and
practically a lie of omission.

Whether the per-group breakdown is worth printing at all. A bundle's
directories are the user's own invention and a fresh one has none, so the
line would be `Documents 3` on every bundle until someone makes a group.

Whether a file whose *body* is empty should be reported. `context index`
would count it as a document and produce no chunk for it; if every file were
like that, `_refuse_if_empty` fires on "documents and no text in any of
them", which is a message about a collection.

## What actually happened that I did not expect

**The digest comparison was the easy half; what it exposed in the corpus was
not.** Writing `context status` meant reading `corpus status` closely, and
the reading found two things wrong there.

The first: **a stale corpus index was reported with no command attached.**
`_report_freshness` printed the sentence and returned; the only
`kennis corpus index` in the command was for a corpus that had never been
indexed at all. So a reader was told something was wrong and not what to
type, which is precisely what the project rule about errors naming their
resolution exists to prevent. Fixed here rather than logged, because it is
four lines and because unit 5 was adding the identical line one scope down -
leaving the two inconsistent in the same release would have been the worse
choice. Concern #244.

The second is bigger and is **not** fixed. `build_index` records
`built_from = repository.head()`, and the index command's own commit happens
after. For a document added through `corpus add` that is harmless - the add
already committed it - but for one written into the corpus by hand, the
index command is what commits it, so `built_from` predates its arrival and
the diff counts it as added-since. The result is that `corpus status`
immediately after `corpus index` says "1 document not yet indexed" about a
document that was just indexed. Concern #245. It was invisible until now
because the freshness line printed as dim good news; making it carry a
command is what made the false one visible.

**Three of my own tests passed for the wrong reason, and one of them twice.**
The corpus stale test made its index stale by editing a file on disk - which
is also an out-of-band change, for which `status` already prints a remedy at
the end, so the test passed with its actual subject removed. Rewritten to
remove a document through `corpus remove`, which leaves the index stale and
the working tree clean. The digest test could not fail under any
content-based comparison, so the injection was changed to a real alternative
implementation - mtime - rather than a corrupted digest. And the
broken-header test had no file *without* a header in it, so it could not
distinguish "reports a broken header" from "reports every header".

**Both output uncertainties resolved by looking at it, in opposite
directions.** The per-group breakdown is worth printing, but only when there
is more than one group - otherwise the row repeats the line above it, which
is what a one-directory bundle produced. And the count line read `Documents
3 documents`: `corpus status` gets away with `Notes 1 document` because its
verb is the collection's name, and the analogue here needed a verb, so it is
`Holds`.

**The added-only question answered itself.** `describe_freshness` already
says "in step, with 1 document not yet indexed", written for the corpus and
exactly right for a bundle - where, because `remember --context` does not
index, that is the ordinary state rather than a brief window. What it lacked
was the command, which is the same gap as #244.

The third uncertainty - a file with an empty body - never came up and is
left alone: `build_index` refuses a bundle whose documents hold no text at
all, and one empty file among several costs a chunk nobody would have
matched.
