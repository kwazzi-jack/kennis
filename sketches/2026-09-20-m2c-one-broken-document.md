# Correction: one broken document must not cost the collection

Milestone / step: a correction to milestones 1 and 2, before milestone 2 step 5.
Date: 2026-09-20

Previous sketch: `2026-09-20-m2b-the-notes-add-path.md`, whose fourth heading
names the first of these two defects as a thing left undecided.

## What I am about to do

Two fixes, both to committed work.

1. **A document whose frontmatter is not parseable YAML raises
   `yaml.parser.ParserError`**, a library exception, straight out of
   `read_document`. The engine's contract is that it raises domain exceptions;
   a front end would render this as a traceback rather than as `error: ...`.
2. **One unreadable document makes every operation on the collection fail**,
   because `Collection.documents()` validates eagerly and `_Uniqueness.of`
   goes through it. Observed: a hand-added `tags:` key on one note makes
   `add`, `documents` and `resolve` all raise `DocumentInvalid` naming a
   document the user was not touching, and the error's own resolution -
   `kennis corpus status` - names a command that would hit the same wall.

## How I expect it to work

### The YAML fix

`document.py` gains one private loader that every read goes through:

```
_load(md_path) -> (mapping, body)      # raises DocumentInvalid, never yaml's
```

It translates three failures into `DocumentInvalid` with the path named: the
bytes could not be read, the frontmatter is not valid YAML, and there is no
frontmatter at all. `frontmatter.py` keeps raising `yaml.YAMLError`, because
it is a codec at the level of `json.loads` and translating is the job of the
module that owns the *document* concept.

`_refuse_overwriting_another_document` changes behaviour as a consequence: it
reads the file already at the target to compare identifiers, and until now an
unparseable one meant "no identifier found", which allowed the overwrite. It
should refuse instead. If kennis cannot tell whether the file in the way is
the same document, clobbering it is precisely the data loss the guard exists
to prevent.

### The uniqueness fix

The tension to resolve: skipping unreadable documents is *not* safe, because
an unreadable document is also absent from the uniqueness record, and then
`mint_id` can reissue its surrogate identifier and a re-add of its source is
not recognised as a duplicate. Milestone 1's strictness was defensible on
that.

It is resolvable because **the uniqueness facts do not need a valid
document**. `id` and `source.sha256` are plain YAML keys, readable from any
document whose YAML parses at all. So:

```
inspect_document(md_path, *, collection) -> DocumentFacts   # never raises
Collection.survey() -> list[DocumentFacts]
```

`DocumentFacts` carries the path, the wrapper directory, the identifier and
the checksum where they could be read, and `problem` - one line saying why the
document is not valid, or None. A document whose YAML will not parse at all
still contributes its path, so its *filename* stays reserved even though its
identifier cannot be.

Then:

- `Collection.documents()` stays strict. It promises validated documents and
  should keep that promise.
- `_Uniqueness` is built from the survey, so identifiers and checksums stay
  reserved whether or not a document validates.
- `add_notes` emits one `Diagnostic` per problem, naming the document. The add
  proceeds.

This keeps milestone 1's actual principle - a corpus with one broken document
is a thing to be *told about*, not to be silently served nine tenths of -
because the problems are reported rather than dropped. What changes is that
being told no longer costs the operation.

`reserved_filename` moves onto `DocumentFacts` as a property. `add.py`
currently computes it with a `getattr` against `object`, which is the shape of
a fact living in the wrong place.

### What this does not change

`corpus status` does not exist yet, so the circular resolution is only half
fixed: `DocumentInvalid` still says `kennis corpus status`, and that command
will have to be written against `survey()` rather than `documents()` when
milestone 5 arrives. Recorded here so it is not rediscovered then.

## What I expect to be uncertain or difficult

- **Whether `survey()` and `documents()` should share a walk.** They read the
  same files and parse the same YAML. Two passes over a collection is the
  obvious waste, but the only caller that wants both is one that wants the
  valid documents *and* the problems, and I am not sure that caller exists
  yet.
- **What `problem` should hold.** A string is enough to print and enough to
  put in a `Diagnostic`, but a caller wanting to distinguish "unparseable
  YAML" from "unknown key" would have to read English. I expect a string is
  right for now and will be wrong by the time there is a repair verb.
- **Whether refusing to overwrite an unparseable file is too strict.** It is
  the safe direction, but it means a corpus with one corrupt file has a
  filename that can never be written to again without manual intervention,
  and the error will not obviously say that is what happened.

## What actually happened that I did not expect

**The fix was smaller than the diagnosis.** `inspect_document` plus
`Collection.survey()` is about sixty lines, and `_Uniqueness.of` became
shorter rather than longer: it used to reach into a validated `Document` for
three facts through a `getattr` against `object`, and now takes them off a
record whose whole purpose is to carry them. The `reserved_filename` logic
that add.py was computing with `getattr(document, "wrapper_dir", None)` moved
onto `DocumentFacts` as a property, which is where it always belonged.

**The two readers share `_load` and nothing else, and that is the right
amount.** `read_document` validates and raises; `inspect_document` validates
and records. Both go through one loader, so the three ways a read can fail -
unreadable bytes, unparseable YAML, no frontmatter - are translated in exactly
one place. The duplication I was braced for did not materialise because the
difference between the two is what happens to a `ValidationError`, not how the
file is read.

**I deferred the third fix on a cost I had constructed rather than found, and
then closed it.** What follows is the reasoning as it stood and as it should
have stood, because the mistake is more instructive than the fix.
Re-running the original probe after the fix:

```
add an unrelated note    -> ok
list the collection      -> DocumentInvalid: .../Good note.md: tags: ...
resolve a handle         -> DocumentInvalid: .../Good note.md: tags: ...
```

`resolve()` was built on `documents()`, so reading *any* document by handle
still failed when an unrelated one was broken - the same defect, in the
command a user reaches for most. I priced closing it at "building the alias
map from raw mappings", which would mean reintroducing dotted-string field
access for `bib.citekey`, `bib.arxiv_id`, `docs.project` and `docs.page` into
a module milestone 1 deliberately built on typed models, and deferred it to
milestone 5 on that.

**That was the cost of one implementation, not of the change.** Having just
solved the uniqueness problem with `survey()`, I reached for `survey()` again
and then priced the deferral against it without looking for a second way. The
second way is simpler, and it turns on an observation the first one misses:
**a document kennis cannot validate cannot be returned by `resolve` anyway**,
because `resolve` hands back a `Document` with a validated frontmatter and a
body. The broken document contributes nothing to the answer either way. All
`resolve` needs is to walk past it.

So `contents()` replaces `documents()`: one walk, `read_document` per
location, and a `DocumentInvalid` sends that one file to `inspect_document`
instead of ending the walk. The alias map is still built from typed models,
from the documents that parsed. No dotted-string access anywhere, about thirty
lines.

Two things fall out of the survey work already done. The unreadable documents
are in the return value, so nothing is silently skipped. And a broken
document's *identifier* is still known, so `resolve` on that identifier raises
`DocumentInvalid` naming it and saying why, rather than the misleading
`DocumentNotFound` - asking for the broken document tells you it is broken,
asking for anything else works.

`documents()` is gone rather than kept alongside. A method named `documents`
that quietly returns nine tenths of them is the exact failure this correction
is about; `contents().documents` makes the existence of the other half visible
at every call site, which is twenty-four of them and all in tests.

The probe that opened this sketch, before and after:

```
before                                     after
add an unrelated note -> DocumentInvalid   add an unrelated note -> ok
list the collection   -> DocumentInvalid   list the collection   -> ok
resolve a handle      -> DocumentInvalid   resolve a handle      -> ok
```

`corpus status` still has to be written against `contents()` rather than
against a strict reader, and `DocumentInvalid.default_resolution` still names
it, so that much of the circularity waits for milestone 5.

**`survey()` and `documents()` do not share a walk, and no caller wants both.**
The waste I predicted has not appeared, because the two callers are disjoint:
a batch wants the survey, a reader wants the documents. `corpus status` will
be the first to want valid documents *and* problems, and it can have the
survey alone - a document with no problem is one `read_document` would return.

**Refusing to overwrite an unreadable file changed one existing test's
reasoning without changing its assertion.** The guard used to allow the
overwrite when no identifier could be found, which covered both "this file has
no `id`" and "this file cannot be parsed". Those are different, and only the
first is safe. The behaviour is now: no identifier means proceed, unparseable
means refuse. A corpus with one corrupt file therefore has one filename that
cannot be written to until it is repaired, which is the direction I want to
fail in but will read oddly the first time someone hits it.
