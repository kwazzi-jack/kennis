# Milestone 2, step 4: the notes add path

Milestone / step: `design/plan.md`, "Milestone 2", item 4.
Date: 2026-09-20

Previous sketch: `2026-09-20-m2a-inputs-and-intake.md`. What it left: an
argument can be expanded into concrete files, and a file can be turned into
markdown plus provenance - with nothing joining the two to the corpus.

## What I am about to do

Write `engine/corpus/add.py`: the path from a list of identifiers to documents
on disk, for notes. Hash first, convert second, one converter process per
batch rather than per document. This is also the first operation to emit into
the event stream milestone 0 declared and nothing has used since.

## How I expect it to work

### The shape

```
add_notes(collection, identifiers, options, *, converter=None, events=None)
    -> AddReport
```

`collection` is milestone 1's `Collection`, so the walk, the validation and
the alias map come for free. `AddReport` carries one `AddOutcome` per
identifier plus the elapsed time, and the per-outcome vocabulary is
`events.Outcome` rather than a second enum of its own.

**A duplicate is `Outcome.UNCHANGED`.** That is not a stretched fit: the
corpus already holds the document, nothing was written, and `UNCHANGED` is the
`=` marker that carries no colour because it is the absence of news. A batch
that re-adds a folder should read as a column of `=` rather than as anything
that happened.

**A batch never aborts on one failure.** One unreachable URL among twenty must
not cost the other nineteen, so every identifier produces an outcome and the
caller reports them together. The exceptions to that are the ones raised
before the batch starts - an argument that names nothing, a converter that is
absent - because those mean the command as typed cannot be carried out at all.

### The order of work, which is the whole design

1. `resolve_inputs` expands the arguments. Files the walk declined become
   `SKIPPED` outcomes immediately, rather than being dropped in silence.
2. The collection is walked **once** into a `_Uniqueness` record: the
   identifiers in use, the filenames in use, and a checksum-to-identifier map.
   Once per batch rather than once per document, because walking and
   validating a collection per item would make adding fifty notes quadratic.
   Every write updates it in place, so the second document in a batch sees the
   first.
3. Every local binary file in the batch is **hashed and compared against the
   collection before anything is converted**. That is the plan's "the
   duplicate is detected before any conversion runs", and the reason it
   matters is arithmetic: re-adding a folder of fifty PDFs costs fifty file
   reads instead of fifty conversions whose results are then thrown away.
   Duplicate detection worked in boepie too - it simply worked after the
   expensive part.
4. What survives is converted **in runs of `batch_size`**. One run over a
   whole folder would report no progress and keep nothing if interrupted,
   because the converter writes nothing until a run finishes; chunking costs
   one extra model load per run and buys back both.
5. The write loop walks the resolved inputs in order, taking prepared markdown
   where the batch produced it, converting text-shaped sources as it goes, and
   checking the checksum again for the sources that were never candidates for
   the batch pass - a URL, a `.md` file.

### Events

The first real consumer of `engine/events.py`. Per identifier: `ItemStarted`,
then one `ItemFinished` carrying the outcome and, when there is one, the
reason. Per conversion run: a `Progress` with the run number and the total,
because a run is the only moment there is to report - the converter writes
nothing until one finishes. At the end, one `OperationFinished` with the
per-outcome counts and the elapsed time.

A `Diagnostic` for the one non-fatal remark this path can produce: a title
that looked like a dotfile name and had its leading dot stripped. The file on
disk is then not named what the title says, which is worth saying once.

`events` defaults to a sink that discards, so a caller that wants only the
report does not have to build one.

### What `_write` does

Mints a random identifier with `mint_id(taken)` - notes have no natural key by
definition, which is exactly why they are safe to mint randomly. `id_from` is
absent, which is how a reader tells a minted identifier from a derived one.
`owner` is `user`. The filename is the title, uniquified collection-wide. The
`source` block comes straight off `Converted`. When the original bytes were
kept, they are written as an asset, which makes the document a wrapped one.

`--group` is a **prefix** rather than an override once a directory is being
walked: collapsing every walked file into one flat group would undo the thing
the mirrored structure is for, which is keeping a `README.md` per
subdirectory apart.

### What this step does not do

No locking - the plan puts `filelock` in milestone 4, and until then a second
concurrent add is simply not defended against. No literature and no docs:
`bib`, citekeys and identifier extraction are step 5, project grouping and
fetchers are step 6. No commit: git is milestone 4 too.

### Tests

The two of the plan's eight that belong here, plus the batch-level half of a
third:

- adding the same file twice produces one document, and the second add reports
  it as a duplicate rather than failing;
- the duplicate is detected *before* any conversion runs - asserted by
  counting the converter's calls, not by timing;
- a converter failure fails only its own document; the rest of the batch
  proceeds.

Plus: the walk's skipped files reach the report, groups mirror subdirectories
under a `--group` prefix, a title comes from the source and can be overridden,
a dotfile title produces a diagnostic, kept originals become assets, two notes
added in one batch get different identifiers, and the event stream says what
happened in the order it happened.

## What I expect to be uncertain or difficult

- **Whether `UNCHANGED` really is the right outcome for a duplicate.** It
  reads correctly in a report, but a caller asking "did my add do anything"
  now has to distinguish `ADDED` from `UNCHANGED` rather than from a
  `duplicate` status that says so in its name. I may find the vocabulary is
  one term short.
- **The second checksum check.** A local binary is hashed in the survey and
  its `Converted` carries the same hash to the write loop, where it is checked
  again. For a URL or a `.md` file only the second check exists. Two checks in
  two places for one property is how they come to disagree, and I have not yet
  found a shape that has one.
- **Duplicates within a single batch.** The same file named twice in one
  command is deduplicated among the binary candidates, but two *different*
  files with identical content in one batch are not obviously handled: the
  first writes and updates the state, so the second should see it - but only
  if the state update happens before the second is examined, which the write
  loop's ordering decides rather than states.
- **Emitting events and returning a report is saying everything twice.** The
  design asks for both, and I believe the reason, but the write loop now
  appends to a list and emits an event at the same three points. If they ever
  disagree it will be because someone added a case to one.
- **`Collection.documents()` raising on a broken document.** One
  unparseable file in the collection makes every add fail rather than the
  add of that one document. Milestone 1 decided that deliberately; this is
  the first place it has teeth, and I may find it is too strict here.

## What actually happened that I did not expect

**mypy found a real defect in milestone 1's schema, three sessions late.**
`Source.origin` used `Field(alias="from")` with `populate_by_name=True`, which
works at runtime and is what boepie does. But pydantic's metaclass carries
`dataclass_transform`, so a type checker synthesises `__init__` from the field
definitions and honours the `alias` - meaning the constructor it advertises
takes a keyword argument named `from`, which is a Python keyword and therefore
cannot be written. `Source(origin=...)` type-checked as an error until now
only because nothing had ever constructed a `Source` in Python: every previous
test went through `model_validate` on a mapping, where the alias is the right
answer.

The fix is `validation_alias="from"` and `serialization_alias="from"` in place
of the single `alias`, with `populate_by_name` kept. On-disk spelling is
unchanged, `model_dump(by_alias=True)` still emits `from`, and the constructor
now takes `origin`. It cost one intermediate failure: dropping the plain alias
without keeping `populate_by_name` made mypy happy and thirty tests fail,
because validation then accepted only `from`.

Worth recording as a pattern rather than a one-off: a model that is only ever
*parsed* never exercises its own constructor, so the first code that builds
one is where a whole class of typing mistakes surfaces.

**`UNCHANGED` for a duplicate reads better than I expected.** The worry was
that a caller asking "did my add do anything" would have to distinguish
`ADDED` from `UNCHANGED` rather than from something named `duplicate`. In
practice `report.counts` answers that directly - `{ADDED: 1, UNCHANGED: 1}`
says it plainly - and re-adding a folder produces a column of `=` markers,
which is exactly what the display grammar wants it to look like. No extra term
was needed.

**Duplicates within one batch fell out for free, and for a reason worth
naming.** Two different files with identical content in one command produce
one document, because `_write` updates the checksum map before the next item
is examined. That is not a special case anywhere in the code; it is a
consequence of the uniqueness record being mutable and per-batch. The test is
there to hold the ordering, not because anything implements it.

**The double checksum check is still two checks, and I now think that is
right.** A local binary is hashed in the survey and again in the write loop
via its `Converted`. They cannot disagree - both hash the same bytes with the
same function - and the survey check exists to skip conversion while the write
check exists to catch sources the survey never saw, a URL or a `.md` file.
Collapsing them would mean hashing every text source up front too, which is
the same work moved earlier with no conversion saved.

**Emitting events and returning a report did not turn out to be saying
everything twice.** The write loop appends one `AddOutcome`, and the caller
emits `ItemFinished` from that same value rather than constructing a second
one. The only place the two are built independently is the skipped-inputs
path, which is where I would expect them to drift.

**One thing I left as boepie has it and am not sure about.**
`_Uniqueness.of` calls `Collection.documents()`, which raises `DocumentInvalid`
on the first unparseable document. So one broken file in the notes collection
makes every add fail rather than only the add of that file. Milestone 1 chose
that deliberately and I have not overridden it, but this is the first place it
has teeth and the failure message will name a document the user was not
touching.
