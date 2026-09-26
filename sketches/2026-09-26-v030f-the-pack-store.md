# The pack store

Milestone / step: milestone 7 (packs), unit 5
Date: 2026-09-26

## What I am about to do

`kennis pack add <path to a .ken.yml>`: validate the handed file, copy the
content it names into `<corpus root>/packs/<id>/`, and write `state.json`
last. Design sections 5 (steps 1, 2, 2a and 5) and 8.

## How I expect it to work

**The store is a cache, and the design says so twice.** Section 19's table
marks the pack store "no - re-derivable / re-pushed by the provider's next
run", and the git section says version control "does not apply to the pack
store, which is a cache of an immutable wheel". So `packs/` is gitignored.
The corpus `.gitignore` template gains the line, and the store writer
ensures it on a corpus that predates the feature - because the alternative
is a `corpus add` sweeping fifty-seven copied files into the user's history,
which is easy to do and tedious to undo.

**The write order is section 5 step 5, and `_atomic` already implements it.**
`replacing_directory` stages into a sibling, swaps with two renames, and
deletes the old one - which is exactly "stage, copy, `os.replace`, then
write `state.json`". `state.json` is written after the swap with
`replace_file`, so it is this subsystem's `latest.json`: a pointer that must
never be published before what it points at.

**The fast path takes its short circuit only when all four hold** (step 2):
the handed file's sha256 matches the recorded one; `schema_version` matches;
`applied_by` matches this kennis's major.minor; and **the store verifies** -
every path in the recorded digest map present under `packs/<id>/` with the
recorded digest. The fourth is the one the design spends its length on,
because without it a damaged store reads as a pack that ships nothing and
the next sync deletes the user's files.

**Repair at `add` time is simpler than section 5 step 2a reads**, and I
think the design's wording is aimed at a different caller. Step 2a offers
three recoveries - re-copy from `source_path`, else restore from git, else
refuse - but `pack add` is *handed* a live pack file with its content beside
it. A store that fails verification at add time is simply re-copied from
what is in hand, and the only thing that changes is the report: `repaired`
rather than `unchanged`. Refusing is for `corpus sync` and `context sync`,
which are handed nothing and must not read an empty store as a declaration
that the pack now ships nothing. Git cannot be the second recovery for the
store either, since the store is gitignored.

**`state.json` records only what something reads.** Section 8 lists a digest
of each document as kennis wrote it, for step 4a - and nothing materialises
a document until unit 7, so that map has no writer and no reader yet. An
always-empty field is a promise nothing keeps, so it arrives with the code
that uses it. The store is unversioned and re-derivable, so changing its
shape later costs nothing.

## What I expect to be uncertain or difficult

**Whether `pack add` needs the corpus lock.** It writes inside the corpus
root, so two providers syncing at once could interleave. `corpus_lock` is
`timeout=0`, so the second caller is told the corpus is busy - which for an
automated `boepie sync` means a failed provider run rather than a wait. I
expect to take the lock anyway and let the caller retry, because the
alternative is two processes staging into the same parent.

**What `applied_by` compares.** Section 5 says major.minor, so `0.2.1`
reading a store written by `0.2.0` takes the fast path and `0.3.0` does not.
Parsing that out of a version string is where an off-by-one lives.

**Whether the fast path should verify before or after hashing the file.**
Verification walks the store; hashing reads one small file. Cheapest first
says hash, and the design lists it first, so the order is already decided -
but only if hashing really is cheaper, and a pack file with a thousand
literature entries is not tiny.

## What actually happened that I did not expect

**Two of the three uncertainties were decided by reading rather than by
building, and the third produced the only hollow test of the milestone.**

The lock: taken, with `corpus_lock` around the whole install. A provider
whose run collides with another kennis command gets "another kennis command
is using the corpus" and a non-zero exit, which is a failure it can retry.
Writing my own expectation of that message into the test was wrong - I
asserted on the word "busy", which kennis does not use, and the test told
me so.

`applied_by` compares `major.minor`, and the off-by-one I expected did not
happen because the comparison is between two strings produced by the same
function rather than between parsed numbers.

The ordering question dissolved: I never needed to decide whether hashing
beats walking, because all three cheap comparisons are field equality on a
struct already in memory, and the walk is the fourth. Cheapest-first and
the design's order are the same order.

**The hollow test, which is the finding worth keeping.**
`test_first_applied_at_is_set_and_never_restamped` passed with
`first_applied_at=now` injected. Both installs happen inside one second and
the stamp has second resolution, so the two recorded strings were equal for
a reason with nothing to do with the code. The value it guards is the
tie-break that decides which pack owns a contested item, and the design is
explicit that getting it wrong flips ownership on every provider run. It is
rewritten to plant a distinctive value, force the slow path, and check the
value survived - and that version fails when the defect is injected.
Concern #264.

**A third rule 4.4 violation in one milestone, in the same shape as the
first two.** `pack add` ended with `nothing is in the corpus yet:
\`corpus sync\` is what materialises it` - backticked, so the highlighter
styled it as a command, and `corpus sync` is unit 7. I have now written
this mistake in unit 3 (a hint), unit 2 (a hint) and unit 5 (a guidance
line), each time while the rule was in front of me. What they have in
common is that the sentence was true and the command in it was the natural
next thing to say; what distinguishes a violation from a hint is only
whether the thing named exists yet, and that is not a property of the
sentence being written.

**One thing the design did not settle and reading it twice did.** The store
sits inside the corpus root, and the corpus is a git repository, so whether
`packs/` is committed had to be answered before anything was copied. It is
answered, in two places: section 19's table marks the pack store "no -
re-derivable", and the git section says version control "does not apply to
the pack store, which is a cache of an immutable wheel". So the template
gained the line and the store writer ensures it, because a corpus created
before packs existed would otherwise sweep the whole store into history on
its next `corpus add`.
