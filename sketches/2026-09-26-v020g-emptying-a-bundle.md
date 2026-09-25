# Emptying a bundle

Milestone / step: v0.2.0 unit 6
Date: 2026-09-26

## What I am about to do

`kennis context reset`: empty the bundle of everything kennis put there and
leave the user's own files alone. The plan adds a warning worth taking
seriously - "until packs exist that is almost everything, which is worth
stating rather than discovering".

## How I expect it to work

### What "everything kennis wrote" turns out to mean

Three candidates, and only two of them qualify.

**The index, `.context/.index/`.** Unambiguously kennis's, entirely derived,
and rebuilt by one command. Removed.

**Any document whose `owner` is not `user`.** This is the reason the command
exists: `reset` is what returns a bundle polluted by pack content to a clean
state before re-applying. Today nothing writes such a file -
`remember --context` sets `owner: user` and there are no packs - so this
removes nothing, and **that is the thing to state rather than let a reader
discover**.

**The scaffolding - `LANDING.md`, `.skeleton.md`, `bundle.json`.** Written
by kennis and *not* removed, which needs an argument because it contradicts
the plan's phrasing. `LANDING.md` holds a table the file itself instructs
the reader to keep current, and `.skeleton.md` is a template a project is
expected to adapt; both are kennis-written and user-maintained. Deleting
them would destroy edits a reset was never asked to touch. `context init`
already restores a missing one, so a reader who wants them fresh has a
command that does exactly that and nothing else.

So `reset` is: delete the index, delete non-user documents, and say what it
did in terms a reader can check.

### Ownership is read leniently

`owner` is read from frontmatter. Three cases and one rule: a file that says
`owner: user` is the user's; a file with no frontmatter, or one whose header
will not parse, is **also** treated as the user's. A hand-written file is
the most likely thing to lack a header, and the failure modes are not
symmetric - keeping a pack file costs a stale file that the next sync
overwrites, deleting a user's file costs their writing.

### Confirmation

`-y/--yes`, matching `corpus remove`. Asked whenever anything would be
removed, which today means whenever an index exists. Unlike `corpus remove`
this is **not** recoverable through kennis: a bundle is in the user's
repository and kennis has no history of it, so `git checkout` is the only
undo and only if they committed. That asymmetry belongs in the prompt.

Nothing to remove means no prompt and no work - it says so and exits zero.

## What I expect to be uncertain or difficult

Whether `reset` should exist at all in v0.2. Its whole purpose is packs, it
removes nothing but the index today, and a command whose documented effect
is "nothing, for now" invites being run to see what it does. The counter is
that the plan lists it, and that a reset which currently only drops the
index is still the honest way to force a full rebuild.

Whether dropping the index alone deserves a prompt. It costs 4ms to rebuild.
But a prompt whose presence depends on what the command found is itself
confusing, and the command will delete documents once packs land.

Whether the count to report is documents or files. `2 documents removed` is
what a reader thinks in; the index is not a document and needs its own
clause.

## What actually happened that I did not expect

**"Everything kennis wrote" is not a workable definition, and finding that
out was the unit.** The plan's phrase covers the scaffolding, and the
scaffolding must not be removed: `LANDING.md` holds a table the file itself
instructs the reader to keep current, and `.skeleton.md` is a template a
project is expected to adapt. Both are kennis-written and user-maintained,
which is a category the phrase does not have. The workable definition is
ownership plus the index, and `bundle_documents` already excludes the
scaffolding because it excludes dot-prefixed paths and `LANDING.md` - so the
rule that keeps templates out of the search index also keeps them out of
reset, for a different reason and by accident.

**The scaffolding test passed with its subject removed, because two guards
covered the same case.** `LANDING.md` as written has no frontmatter and
`.skeleton.md` says `owner: user`, so the ownership rule protects both
regardless of the exclusion rule. Replacing the exclusion with a raw glob
changed nothing observable. Both files are now marked `owner: pack` in the
test - which they never are in practice - so that only the exclusion stands
between them and deletion, and the injection fails as it should. Two
independent guards is a good thing to have and a bad thing to test through.

**The report read inside-out on the first run.** The index line and its
rebuild hint came before the list of removed documents, so a hint about the
index sat above a list it had nothing to do with. Documents first, each
under its own heading, index last with its command beside it.

**The uncertainties.** Whether `reset` should exist yet: it should, and
running it settled that - forcing a full rebuild is a real use today, and
the pack behaviour is now written and tested before the thing that triggers
it exists, rather than landing untested alongside packs. Whether dropping
the index alone deserves a prompt: yes, because the prompt names what will
go, so it is informative rather than ceremonial, and because a prompt that
appears only sometimes is harder to predict than one that always does.
Documents against files: `2 documents` and `the context index` as separate
clauses, which is also how the prompt reads.

**One thing left for packs.** A pack file the user renamed to `.naming.md`
to keep it out of search is not a document by `bundle_documents`, so reset
leaves it - and the next sync would write `naming.md` beside it. Hiding a
file is documented as a way to keep it out of the index, not as a claim of
ownership, so this is arguably wrong. Left as it is: the conservative
direction, and it is speculation about a feature that does not exist.
