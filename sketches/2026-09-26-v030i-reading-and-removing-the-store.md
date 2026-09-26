# v0.3.0i - reading and removing the store

Milestone 7 unit 6: `pack list`, `pack status`, `pack remove`. The store
can be written and not inspected, which is the harder half to debug.

The plan says this is where the v0.3 release cut is decided. It is
decided: these ship in v0.3 alongside unit 7, because a store a user can
write and cannot read is worse than one that does not exist - the four
fast-path conditions are invisible from outside, and the only way to see
why `pack add` said "Unchanged" is a command that says what is recorded.

## 1. What I am about to do

One engine module, `engine/pack/installed.py`, that reads the store and
removes from it, plus its renderer and three commands.

| verb | question it answers |
|---|---|
| `pack list` | which packs are installed, and at what version |
| `pack status` | what each one recorded, whether the store still verifies, and every overlap between packs |
| `pack remove` | drop one pack from the store |

## 2. How I expect it to work

**`list_installed(corpus_root) -> PackListing`.** Walks `packs/`, reads
each `state.json` through the existing `read_state`, and parses each
stored `pack.ken.yml` through the existing `load_pack`. Returns

```
PackListing(packs: tuple[InstalledPack, ...], unreadable: tuple[str, ...])
```

`unreadable` is the directory names under `packs/` with no state file that
parses. A partial install must be visible: `read_state` already returns
None for one, and today nothing would ever say so. The packs are sorted by
id so two runs print the same order.

`InstalledPack` carries `state: PackState`, `declaration: Pack | None` and
`verified: bool`. `verified` is the fourth fast-path condition, run here
for reporting rather than for a decision - `pack status` is exactly where
a user should find out that the store is damaged, before a sync acts on
it. `declaration` is None when the stored pack file will not parse, which
is corruption of a file kennis itself copied.

**Overlaps.** Section 5 step 4 says an overlap is persistent state
reported by `pack status`, not a line printed once inside an automated
run. An overlap is two installed packs declaring the same item, keyed by
step 3's diff key:

| section | key |
|---|---|
| `corpus.literature` | `arxiv_id`, else `doi`, else `bibcode` |
| `corpus.docs` | `project` |
| `corpus.notes` | `(group, relative path)` - the destination in the notes collection |
| `context` | the relative path under `.context/` |

The **incumbent** is the pack with the earliest `first_applied_at`, ties
broken by pack id so the answer is stable. `applied_at` cannot serve: a
provider calls `pack add` on every run.

Content keys need the relative path, which lives in `state.files` as
`<source>/<relative>`. The source prefix is stripped and the group
prepended, so two packs shipping `notes/setup.md` under group `install`
collide and two shipping it under different groups do not.

**`remove_pack(corpus_root, pack_id) -> PackRemoval`.** Deletes
`packs/<id>/` with `shutil.rmtree` and reports how many files were
recorded. Raises a new `PackNotInstalled` when there is no such directory,
with `kennis pack list` as its resolution.

It does **not** touch corpus documents or any workspace. Design section 9:
kennis keeps no registry of a user's projects, so it cannot clean
`.context/` in N checkouts, and those converge on their own next sync.
Said out loud by the command, because a user running `remove` will
reasonably expect the content to be gone.

**Rendering.** `render/packs.py` gains `describe_installed`,
`describe_overlap`, `describe_removal`, `describe_unreadable`. The engine
returns fields; the sentences live there (#81).

**Reporting.** `remove` goes through `reporting()` like every other
mutation, emitting one `ItemFinished` for the pack and an
`OperationFinished`. `list` and `status` read and emit nothing: no other
read command in kennis emits, and `corpus status` is the precedent.

`remove` takes the corpus lock; `list` and `status` do not, matching
`corpus status`.

## 3. What I expect to be uncertain or difficult

**Whether `status` should verify by default.** Walking every recorded file
of every installed pack is the fourth fast-path condition again, and for
one pack of ~57 files it is milliseconds. For ten packs it is still
milliseconds. I expect to just do it, and to be wrong only if a pack turns
out to ship thousands of files.

**The content overlap key is the part I am least sure of.** The design
says "the full destination address: (section, source index, relative
path)", and *source index* cannot be right across packs - pack A's source
0 and pack B's source 0 are unrelated. I am reading "destination address"
as the thing it resolves to on disk, which is what makes two packs
collide, and treating the source index as an intra-pack detail of step 3's
diff rather than part of the cross-pack identity. If that is wrong the
symptom is a reported overlap that is not one.

**Rule 4.4 under the new guard.** `remove` wants to say "run
`kennis context sync` in each project", and `context sync` does not exist
until unit 7. The guard added in v0.3.0h will fail on it, which is the
correct outcome: the sentence must not name it yet.

## 4. What actually happened that I did not expect

**Every one of the four defects in this unit came from running the
commands, and the 51 green tests found none of them.** That is now true of
every unit in this milestone, without exception.

1. `pack list` printed `alpha  1.2.0` above `beta   0.4.1` with the
   versions not lining up. `corpus list` uses the same helper and does not
   have this problem, because a surrogate id is fixed width and a pack id
   is whatever the provider called itself. Padded in the command, since
   column width is layout and not wording.
2. The overlap sentence read "declared by alpha, beta", which mid-sentence
   sounds like the list was cut off. Added `joined` to `render/words.py` -
   `a`, `a and b`, `a, b and c` - which is general enough that it should
   have existed already.
3. `pack status` reported a damaged store and named no command. That is
   concern #244's defect exactly: a reader told something is wrong and not
   told what to type. The store records `source_path`, so the repair is one
   command when that file is still there - and when it is not, there is
   nothing local to repair from and the honest answer names the provider
   instead. Both branches now exist, and neither was in the sketch.
4. `pack remove` on a half-written install said "0 files dropped from the
   store". True and misleading: nothing recorded what was in that
   directory, which is not the same claim as the directory having been
   empty. `PackRemoval` gained `recorded` and the two are worded
   differently.

**The type checker found a bug the tests could not.** `overlaps_between`
bound `key` twice in one function - once to an `ItemKey` tuple in the
collection loop and once to a `str` when unpacking the result - and mypy
refused it. Both loops worked, so the suite was green; the name was simply
lying about what it held in half the function.

**The content overlap key needed a decision the design does not contain.**
Section 5's "(section, source index, relative path)" cannot be a
cross-pack identity, because pack A's first source and pack B's first
source are unrelated. Read as the destination the address resolves to,
which is #270 - written down because the symptom of getting it wrong is a
reported overlap that is not one, and that is hard to recognise as a bug
rather than as a surprising pack.

**Writing the rule 4.4 guard first paid immediately.** `pack remove`
wanted to close by naming `kennis context sync`, and I did not write that
sentence, because the guard would have rejected it and I knew that before
typing it. The sentence it closes with instead - "any project that has
this pack's content" - says the same thing without promising a command
that does not exist, and it will not need rewriting when unit 7 lands.

**One thing from section 3 was simply not a problem.** Verifying every
recorded file of every pack on every `status` is milliseconds, as expected,
and I did not have to make it optional.

