# Validating a pack file

Milestone / step: milestone 7 (packs), unit 2
Date: 2026-09-26

## What I am about to do

Turn unit 1's models into `kennis pack validate <path>`: read a file from
disk, apply the checks that need more than the models, and report what is
wrong in a way an author can act on. Four checks beyond parsing:

1. the two version refusals - a `schema_version` newer than this kennis, and
   a `min_version` above this kennis's version;
2. overlapping `source:` trees;
3. the filesystem half of path hygiene - every discovered file must resolve
   under the pack root, and symlinks are not followed;
4. the generated digests against what is on disk.

## How I expect it to work

**The engine answers, the command prints.** `validate_pack(path)` returns a
`PackReport` - the parsed pack, the checks it performed, and the problems it
found as values with fields. It does not raise for a content problem, because
`pack validate` must be able to report several at once; it raises `PackInvalid`
only when there is no pack to report on, which is the parse failure unit 1
already defines. `render/` words the report and `cli/commands/pack.py` prints
it. Exit code is non-zero when the report has any problem.

**The two version refusals are not the same as an invalid file**, and the
report says which it is. Section 5 step 1 is explicit: a pack needing a
feature that does not exist yet has a different fix - "upgrade kennis" -
from a file with a bad field. `min_version` is compared with
`packaging.version.Version`, never as a string, or `0.10` sorts before `0.2`.
`packaging` becomes a declared dependency; it is currently only transitive.

**Overlap is decided on the declared trees, not on the matched files.**
Section 5 keys content on `(section, source index, relative path)`, and two
sources where one is a prefix of the other could give one file two addresses.
Comparing declared prefixes is cheap and needs no walk; comparing matched
file sets would be exact but would make `validate` need the content present
for a check that is really about the declaration. So: normalise each
`source:` to a relative directory and refuse when one is a prefix of another,
including when they are equal.

**The walk is where path hygiene lives.** For each source, walk the directory
with `os.walk(followlinks=False)`, filter with `include` then `exclude`
through `globstar_regex`, and for every candidate compare
`path.resolve()` against `root.resolve()`. A file that resolves outside is
reported and not read. A symlink is not followed even when its target is
inside, because "not followed" is simpler to state than "followed when safe"
and a pack has no reason to ship one.

**Digests are sha256 of the file's bytes.** The design does not name the
algorithm for `generated.content`. `state.json` records `file_sha256`, and
the format is one other tools may compute without kennis, so sha256 of bytes
is the choice - not the corpus's blake2b over decoded text, which exists for
a different reason (chunking stability) and would be surprising in a
published format.

**What this unit does not do**: write a file. `pack init` and `pack update`
are units 3 and 4, and `validate` only reads. It also does not consult a
store - a pack file is validated on its own terms, before anything is
installed.

## What I expect to be uncertain or difficult

**Whether a missing `generated` block is a problem.** A pack that has never
had `pack update` run is valid, so its absence cannot be an error - but
`validate` in a release pipeline is exactly where a forgotten `update` should
be caught. I expect the answer is that the report names which checks it
performed, so "digests: not checked, no generated block" is visible rather
than silently passing, and the exit code stays zero.

**Reporting several problems without the report becoming a log.** The engine
names things and does not phrase them (#81), so each problem has to be a
value with fields - a kind, a path, and whatever the kind needs. I expect the
temptation to put a sentence in the engine to be strongest here, because the
problems are heterogeneous.

**Whether `validate` should refuse a `source:` naming a directory that does
not exist.** The plan says `update` refuses. For `validate` the same argument
applies less clearly: an author validating before writing content has a
declaration ahead of its content, which is a normal intermediate state.

## What actually happened that I did not expect

All three uncertainties resolved the way the sketch guessed, which is worth
recording as a result rather than skipped over - it is the first unit in a
while where naming the hard parts in advance did not change what I found.
The two things that did surprise me both came from running the command.

**The missing-source question answered itself once `pack init` was read
properly.** I worried that refusing a `source:` naming an absent directory
would make a freshly scaffolded pack fail validation immediately. It cannot:
section 3 says `init` writes the header and the identity block and no
sources at all, so the state I was protecting - a declaration ahead of its
content - only exists if an author writes it deliberately. Reported as a
problem, matching what unit 4 will do.

**Two defects that the 31 green tests did not see, both found by typing the
command.**

The first is a sentence: `1 file disagree with the generated block`. I
pluralised the noun with a conditional and left the verb alone. Every test
asserted on a substring that stopped before the verb.

The second matters more. The report ended with
`hint: kennis pack update <path>` - a command that does not exist, since
`update` is unit 4. Rule 4.4 says a printed command runs as printed, and
`render/words.py` already handles this exact situation for
`kennis corpus claim`, with a comment explaining why the command is withheld
until it is built. I had read that comment earlier in this same session
while looking at the wording style, and wrote the violation anyway an hour
later. The fix is the same shape: say what happened, name nothing to type,
and add the command in unit 4. Concern #258 carries the debt so unit 4 does
not have to rediscover it.

**A decision the design does not make.** Section 7 shows `generated.content`
holding digests and never says of what, by what algorithm. `state.json`
records `file_sha256` for the pack file, so I took sha256 of each file's
bytes, deliberately not the corpus's blake2b over decoded text - that exists
to keep chunking stable across whitespace, which is not this question.
Written down as #257 because a published interchange format silently
choosing a hash in an implementation is how two tools come to disagree about
the same file.
