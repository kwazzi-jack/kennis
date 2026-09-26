# v0.3.0k - `corpus sync` for notes, and claiming a document

Milestone 7 unit 7, second half, first part. `corpus sync` converges the
corpus with every installed pack. Split again: **notes here, literature
and docs next**, because notes need no network and the other two need
both the fetchers and their failure modes.

Also here: `kennis corpus claim` and `kennis corpus disown`, which section
6 says are what make the protective rows reachable at all - "without
these, section 5's protective rows can never fire for a document that
started life in a pack".

## 1. What I am about to do

Reuse the resolution core from v0.3.0j against a second destination.
`engine/pack/resolve.py` does not change; `engine/corpus/sync.py` is the
corpus's answer to `engine/context/sync.py`.

## 2. How I expect it to work

### A corpus document answers for itself too, but differently

A bundle file is addressed by its path, so the address *is* where it
lives. A corpus note is not: its filename comes from its title, and its
identity is a minted surrogate identifier that every read handle depends
on. So the address has to be **recorded in the document** rather than
read off its location:

```yaml
source:
  from: pack:boepie/install/setup.md     # the pack id and the address
  via: pack
  format: markdown
  sha256: <the body kennis wrote>
  pack_sha256: <the store file it came from>
```

Three changes to the schema, all additive: `pack` joins `ConversionVia`,
`pack_sha256` joins `Source`, and `write_note` takes an `owner` instead
of hard-coding `user`.

`from: pack:<id>/<address>` rather than a separate field, because
`origin` already carries a scheme and its value, and the scheme is what
decides recoverability - a `pack:` document is refetchable from the
store, which is the same claim `url:` and `arxiv:` make.

**The identifier never moves.** A rewrite changes the body of an existing
document; it does not mint a new one. That is the whole reason the
address is recorded rather than recomputed - a sync that could not find
the document it wrote last time would write a second one.

### `claim` and `disown` are what make `yours:` reachable here

A corpus note has no address of its own, so the `yours:` row cannot fire
the way it does in a bundle - a user's note is simply not at any pack's
address. It fires for exactly one case: a document a pack supplied whose
`owner` is now `user`.

```
kennis corpus claim <handle>     # pack:<id> -> user
kennis corpus disown <handle>    # user -> pack:<id>, from its origin
```

`claim` changes `owner` and **leaves `source` alone**, which is what
keeps the document at its address: the next sync still finds it, sees
`owner: user`, and reports it under `yours:` rather than rewriting it.
`disown` reads the pack back out of `origin`, so it can only be used on a
document that came from one - handing a note the user wrote to a pack
would be a claim about provenance that is not true.

### Everything else is the same table

`resolve` is unchanged. The differences are all in the two functions
either side of it:

| | bundle | corpus |
|---|---|---|
| what is present | every `.md` under the bundle | every notes document whose `via` is `pack` |
| address | the path | `origin`, after the `pack:<id>/` prefix |
| write | a file at the address | `write_note`, minting an id, or a rewrite in place |
| delete | `unlink` + prune | `collection.remove` |
| after | nothing | a commit, because this *is* kennis's repository |

The damaged-pack refusal is carried across verbatim - #274 says it is the
same two lines, and this is the caller it was written down for.

### Reserved destinations, here

A bundle refuses a dot-prefixed address and `LANDING.md`. The corpus
reserves neither, because a pack note's address never becomes a path: the
filename comes from the title. So there is nothing to refuse, and I
expect `_refuse_reserved_destinations` to have no corpus counterpart.

## 3. What I expect to be uncertain or difficult

**The title of a pack note.** A bundle file keeps its path; a corpus note
needs a title, which becomes its filename. From the pack file's own
frontmatter when it has one, else from the first heading, else the
filename stem - `title_for` already does the middle one for `remember`.
The risk is a rewrite whose title changed: the document keeps its
identifier and its filename no longer matches its title. I think the
filename should follow, and that means a move, which `corpus move`
already knows how to do.

**Deduplication.** `write_note` records `converted.sha256` in
`record.checksums` and `remember` uses it to recognise the same prose
twice. A pack note shipping text a user has already remembered would be
deduplicated into the user's note - which is wrong: they are different
documents with different owners. I expect to have to write the pack note
anyway and to record why.

**A commit per sync.** `corpus add` commits once per invocation with a
summary of its counts, and sync should do the same. The risk is an empty
commit when nothing changed; `Repository.commit` already returns None on
a clean tree.

## 4. What actually happened that I did not expect

**The resolution core needed no change at all.** `engine/pack/resolve.py`
was written for the bundle and taken up by the corpus without a line
moving, which is the first time in this project that an abstraction
designed ahead of its second caller has fitted. I had written down in
v0.3.0j that I was accepting the risk of designing for a caller I could
not see; the risk did not materialise, and the reason it did not is that
the table is specified in the design independently of either destination.
That is the condition, not a general licence.

**The two-digest scheme transferred and so did its test.** I wrote the
corpus's "settles after one sync" test expecting it to fail the way the
bundle's had, and it passed first time - because I carried the scheme
across deliberately rather than rediscovering it. This is the first unit
in the milestone where running the command found nothing the suite had
not. The difference is that the defect had already been paid for once.

**The damaged-pack guard would have been written twice.** I wrote it into
`corpus/sync.py` first, from #274's note that it was "the same two
lines", and only then moved it to `engine/pack/installed.py` where both
callers import it. Recording it as a concern was what made the
duplication visible; without that note I would have had two copies and
one of them would eventually have drifted.

**Section 3's three worries, resolved differently from how I expected.**
The title question turned out to be easy - `title_for` already derives
one from prose and a pack's frontmatter supplies one when it has it - but
the *filename* question underneath it is real and I left it open (#276):
a rewritten note keeps the filename its old title gave it. Deduplication
went the way I expected and is now written down as an accepted cost
(#275). The commit was free, because `Repository.commit` already returns
None on a clean tree.

**`claim` is more load-bearing than section 6 makes it sound.** The
design presents it as a convenience for transferring ownership. It is
actually the *only* way the `yours:` row is reachable in a corpus: a
user's own note sits at no pack's address, so the row can only fire for a
document a pack supplied whose owner is now `user`. That is why `claim`
must leave `source` alone - a claim that erased the origin would make the
next sync write a second copy of the same note, and the injection
confirms it does exactly that.

**Two small things the editing found.** `ruff format` reflowed two
anchors between writing a patch and applying it, so a scripted edit
asserted and failed rather than silently half-applying - the #66
discipline earning its keep on ordinary edits, not just injections. And
`owning_pack` was written speculatively, had no caller, and showed up as
the single uncovered line; deleted rather than tested.

