# Rewriting the generated block

Milestone / step: milestone 7 (packs), unit 4
Date: 2026-09-26

## What I am about to do

`kennis pack update <path>`: walk the content directories the file names,
honouring each source's `include` and `exclude`, and write the `generated:`
block. Restamp `at` and `by` **only when a digest actually changed**, so a
provider rebuild that altered nothing leaves the file byte-identical.

## How I expect it to work

**The byte-identical requirement decides the whole design.** Section 3 wants
a rebuild that changed nothing to leave the pack's own sha256 alone, because
that hash is the fast path in section 5 step 2. Two consequences:

- **When nothing changed, nothing is written at all.** Not "written with the
  same bytes" - not opened for writing. That is stronger than the design
  asks and strictly easier to be sure of.
- **When something changed, only the generated block may be rewritten.**
  Dumping the whole `Pack` back through `yaml.dump` would destroy every
  comment, including the editor header line unit 3 exists to write, and
  reorder keys the author chose. So the rewrite is textual: the generated
  block is the **trailing section** of the file, introduced by a marker
  comment, and `update` replaces from that marker to the end. Everything
  above it is untouched bytes.

That makes "the generated block is last" a rule of the format rather than a
convention of the example in section 7. It is already last in that example.
An author who moves it above their own content has their content eaten, so
`update` refuses when the marker is not the last section rather than
silently truncating - which means finding the marker is a parse of the text,
not of the YAML.

**One walk, shared.** `validate` already walks sources with `include` and
`exclude`, refuses symlinks, and resolves every file against the pack root.
If `update` had its own walk the two could disagree, and the failure mode is
the worst kind: `update` writes digests that `validate` then rejects. So the
walk moves to `pack/content.py` and both call it. `content.py` returns facts
- the digests, the escaping paths, the symlinks, whether the directory is
there - and each caller decides what they mean.

**`update` refuses where `validate` reports.** A missing source directory is
a problem in a report and a refusal in a rewrite, because writing an empty
digest map is indistinguishable from a pack that ships nothing, which is
the state section 5 step 2 spends its whole length defending against.

## What I expect to be uncertain or difficult

**Finding the marker without a YAML parse.** The file is text and the block
is delimited by a comment. A pack whose *content* contains that comment line
- a note about how packs work, say - is not a risk, because only the pack
file itself is scanned. A pack file with the marker twice is, and I expect
to refuse it rather than guess.

**What `by` should say.** `kennis 0.2.0` is the obvious reading, and it is
what section 7's example shows. The version here is the one that wrote the
digests, which section 5 step 2 compares against the running kennis's
major.minor to decide whether materialisation has changed - so it is load
bearing later, and getting the format wrong now is a rewrite of the
comparison then.

**Whether a source declared with no files should write an empty map or
nothing.** An empty map and an absent entry read differently in `validate`:
absent means the whole block predates this source, empty means it was walked
and held nothing. I expect empty is right and the distinction needs saying
out loud somewhere.

## What actually happened that I did not expect

**Nothing surprised me in the mechanism, which is itself the result worth
recording**: the three difficulties named above all resolved the way the
sketch predicted, and the textual splice was less delicate than expected
because the anchor check does the work. That is two units in a row where
naming the hard parts in advance made them ordinary, and the defects
instead came from the places I had not thought to name - which in unit 3
was an error's hint and in unit 2 was a verb.

Two things worth writing down anyway.

**The anchor rule fell out better than I designed it.** I planned to find
the marker comment. Making the anchor "the marker, or failing that a
top-level `generated:` line" costs three lines and means a block a provider
wrote by hand is rewritten rather than duplicated - and the same
`_refuse_trailing_content` check guards both cases, so "the block is last"
is enforced once for two ways of finding it.

**The shared walk is the change I would keep if I kept only one.**
`validate` and `update` now call `content.read_source`, and the test that
says why is `test_the_digests_it_writes_are_the_ones_validate_accepts`: two
walks that disagreed would have `update` write a block `validate` rejects,
which leaves an author stuck between two kennis commands with no way
forward. Extracting it also meant `validate` lost four private helpers and
got shorter, which was not the reason for doing it.

**One thing the tests did not decide and running did.** The block `update`
writes is byte-for-byte the shape of the example in design section 7 - key
order, quoting, two-space nesting. I only know that because I printed one
and compared them by eye. No test asserts it, and none should: a test
pinning the exact bytes of generated YAML would fail on every cosmetic
change and teach nothing. The parse-it-back tests assert what matters.
