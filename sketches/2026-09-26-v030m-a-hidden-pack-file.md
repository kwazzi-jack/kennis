# v0.3 unit m: a pack file the user hid is followed, not duplicated

Date: 2026-09-26

## 1. What I am about to do

Concern #247 says: a user renames a pack-written bundle file to a
dot-prefixed name to keep it out of the index, and the next sync writes
the declared address again, leaving two copies of the same content - one
indexed, one not. Unit 7a was written believing the refusal of
dot-prefixed *declarations* settled it. It does not: that refusal stops a
*pack* shipping a hidden destination, and #247 is about a *user* hiding a
file the pack already wrote. I reproduced it: after hiding `one.md` as
`.one.md`, a second `sync_bundle` writes `one.md` back and both exist.

The fix is to make a bundle file that kennis wrote say **which address it
is**, and to have the sync find such a file wherever it now sits.

## 2. How I expect it to work

Three changes, all in `engine/context/sync.py` apart from one line of
frontmatter.

- `_document` gains `source.address: <the declared address>`. The file
  already records who owns it, what it was built from and what was
  written; it does not record what it *is*, which is the one fact lost
  when the path changes.
- `_present` stops using `bundle_documents` alone. It walks every `*.md`
  under the bundle, `LANDING.md` and dot-prefixed paths included, and
  splits the results in two:
  - a file whose `source.via` is `pack` and which records an address is
    keyed by **that recorded address**, and carries the path it was found
    at;
  - every other file is keyed by its path relative to the bundle, as now.
  A pack file with no recorded address - one written before this change -
  falls into the second group and behaves exactly as it does today.
- `_applied` writes to the path the `Existing` was found at when there is
  one, and to `bundle / address` when there is not. `delete` unlinks the
  found path.

So `Existing` grows a `path: Path | None`. That is a value the resolution
table never reads - it decides on digests and owner - so `resolve` is
untouched and the corpus caller passes None.

Consequences I intend:

| the user does | before | after |
|---|---|---|
| hides `one.md` as `.one.md` | `one.md` written again; two copies | `.one.md` recognised, left alone, updated in place when the pack changes |
| renames `one.md` to `two.md` | `one.md` written, `two.md` deleted | `two.md` recognised and followed |
| deletes `one.md` | rewritten | rewritten - unchanged |
| edits `.one.md` | invisible | `edited`, protected, reported |

The rename row is a behaviour change beyond #247 and I am taking it
deliberately: the two are the same act on the same kind of file, and
resolving one by following the file and the other by destroying it would
be a rule nobody could state. Following is also the less destructive of
the two.

Two files recording the same address - the user copied one - is new and
has no row. I will prefer the one at the declared path if it is among
them, else the first in sorted order, and let the rest be keyed by their
own paths, where they resolve as pack-owned and undeclared, which is
`delete`, which is reported.

## 3. What I expect to be uncertain or difficult

- Whether `_present` should see `LANDING.md`. It is excluded from the
  index for its own reason, and a pack may not declare it, but if a user
  renamed a pack file *to* `LANDING.md` the same duplication follows. I
  think it should be seen and I expect that to feel wrong at first.
- Whether following a rename can strand a path something else depends on.
  `LANDING.md` is hand-written and may name a file by path; following a
  rename means the pack never restores that path. I think that is the
  user's business, but it is the argument against.
- A file written before this change has no `source.address` and is keyed
  by path, so the first sync after the change rewrites nothing and
  records the address as it goes. I expect that to be quiet, and I want
  to confirm it rather than assume it.

## 4. What actually happened that I did not expect

**The reset had the same hole, and I only found it by running the real
command.** `reset_bundle` also walked `bundle_documents`, so a reset left
a hidden pack file in place while reporting the bundle clean - the
sentence in #247 I had read as being about the sync alone. The unit test
for it passed the moment I widened the walk, and the *command* still did
nothing: `reset_command` computed the list of what would go with its own
copy of the ownership rule, saw nothing, and returned before calling the
engine at all. Two statements of one rule, and widening one of them made
them disagree. The engine now answers the question once, in
`removable_documents`, and the command asks it. Nothing in the suite
could have caught this: every reset test either called the engine
directly or had a file both copies agreed on.

**The scaffolding was protected by the wrong rule.** `LANDING.md` and
`.skeleton.md` survived a reset because the narrow walk dropped every
dot-prefixed path and `LANDING.md` has no frontmatter - not because
anything named them. `test_the_scaffolding_is_left_alone` already knew
this and says so: it marks both `owner: pack` on purpose so that only the
exclusion stands between them and deletion. Widening the walk turned that
test into the thing that made me add `SCAFFOLDING` rather than discover
the loss later.

**Naming the declared address became a lie.** With the file followed
rather than rewritten, `= conventions/naming.md: unchanged` named a path
that is not on disk. `BundleSync.moved` now carries `(address, where it
is)` and the command says it. Two wording defects in that line, both
found by reading the real output: it printed under `warning:` for
something nobody did wrong, and it said the file "was updated where it
is" on runs where nothing was written. It is `guidance` now, and phrased
for the standing arrangement rather than for the run.

**The rename row cost nothing extra.** I expected to argue with myself
about whether following a rename could strand a path `LANDING.md`
depends on. In practice the sync reports the move on every run, which is
the answer: the user can see the arrangement they created and undo it by
moving the file back.

**`ruff format` moved an injection anchor twice**, as in unit l - once in
`_present`, once when `removable_documents` was extracted. The assertion
caught both, which is the only reason I know the third and fourth
injections were real.
