# v0.3.0j - the resolution table, and `context sync`

Milestone 7 unit 7, first half. Section 5 steps 4, 4a and 6: converge a
destination with the **union** of every installed pack's declarations.

Split from `corpus sync` deliberately. The resolution is shared and the
destinations are not, and a bundle is the destination with no network in
it - so this half can be written and tested end to end without a single
fetch. It also settles #247 and #267, which are both about what a
dot-prefixed file in a bundle means.

## 1. What I am about to do

Two engine modules and one command.

| module | what it is |
|---|---|
| `engine/pack/resolve.py` | the table of section 5 step 4, as a pure function |
| `engine/context/sync.py` | the bundle destination: read what is there, write what the plan says |

`kennis context sync` converges `.context/` with every installed pack's
`context:` content. No network, no lock on the corpus beyond reading the
store, and no commit - the bundle is in a repository kennis does not own.

## 2. How I expect it to work

### The declarations are a union, not one pack

`declared_content(packs, section)` walks every installed pack and returns

```
dict[str, Declaration]        # address -> what declares it
Declaration(address, pack_id, digest, store_path)
```

keyed by the destination address unit 6 already computes
(`_destinations`). When two packs declare one address the **incumbent**
wins - the earliest `first_applied_at`, exactly as `pack status` reports
it - and the loser is carried along as `deferred` so the report can say
so. Step 6 is the whole reason this is a union: `pack remove A` for an
item B also declares must leave B's declaration standing, and it does,
because the union is recomputed from what is installed.

### What is on disk answers for itself

A bundle needs no state file, and this is the part I did not expect. Every
question the table asks is answerable from the file:

| question | where the answer is |
|---|---|
| who owns this? | `owner:` in the frontmatter |
| did the user edit it? | `source.sha256` vs the digest of the body |
| did the pack change it? | `source.pack_sha256` vs the store's digest |

Two digests because there are two questions, and one field cannot answer
both: the body digest moves when the user types, and the pack digest moves
when the provider ships. Recording only one would make a kennis that
changes its own frontmatter template read every file as user-edited, which
is the failure section 5 step 2 warns about from the other side.

This also means section 8's "digest of each document as kennis wrote it"
in `state.json` is not needed: the document carries it. `store.py` already
records that the map "has no writer and no reader yet".

### The table, as a function

```
resolve(declared: dict[str, Declaration], present: dict[str, Existing])
    -> tuple[Action, ...]
```

`Existing(address, owner, body_digest, pack_digest, unreadable)`.
Every one of section 5's eleven rows is an `Action` with a `verdict`:

| declared | on disk | owner | verdict |
|---|---|---|---|
| yes | absent | - | `write` |
| yes | present | `pack:<this>`, unchanged | `keep` |
| yes | present | `pack:<this>`, pack changed, body untouched | `rewrite` |
| yes | present | `pack:<this>`, pack changed, **body edited** | `edited` |
| yes | present | `pack:<other>` | `defer` |
| yes | present | `user` | `yours` |
| no | present | `pack:<this>` | `delete` |
| no | present | `pack:<other>` | `keep` (never ours) |
| no | present | `user` | `keep` |
| any | present | unreadable owner | `refuse` |

Pure: no paths opened, no writes. That is what lets all eleven rows be
tested, which is the thing the design asks for and the thing a table with
no fall-through row is worth having.

`yours` is emitted **every run**, not only when the declaration moves.
That is the archived defect the design names: both reconcilers used to
`continue` past a user-owned document without counting it, so `sync` said
nothing and `status` called the project "not fetched yet".

### Writing into the bundle

A pack file lands as kennis frontmatter plus the pack's content:

```yaml
---
title: <from the pack's own frontmatter, else the filename>
description: ''
owner: pack:boepie
source:
  via: pack
  pack: boepie
  at: '...'
  sha256: <digest of the body below>
  pack_sha256: <digest of the file in the store>
---
```

The pack ships plain markdown. When its file happens to start with its own
`---` block, that block is read for `title` and `description` and the rest
is the body - never nested, and never two blocks in one file.

`refuse` raises rather than writing, and it raises before anything is
written, so a corpus with one corrupt `owner:` is not half-converged.

### #247 and #267, settled together

Both ask: is a dot-prefixed file in a bundle the user's, or is it
whatever put it there? **A pack may not ship one.** `context sync` refuses
an address whose destination is dot-prefixed at any depth, naming the file.
The bundle's rule that a dot-prefixed path is never indexed is documented
and load-bearing for users; a pack shipping into that space would land a
file that is copied, never indexed and invisible to search. Refusing at
the join is the only answer that leaves both halves intact - and it is a
provider-side mistake, caught where the provider can see it.

That also closes #247 from the other side: there can be no hidden
pack file for `context reset` to leave behind.

## 3. What I expect to be uncertain or difficult

**Whether `resolve` should be one function for both destinations, given
`corpus sync` does not exist yet.** The design says one implementation
serves both, and the table is the same. The risk is designing for a second
caller I cannot see. I am accepting it because the table is specified
independently of either destination and because eleven rows tested once is
worth more than eleven tested twice.

**Deletion.** `delete` removes a file from the user's repository. It is
the row I most want a test for that fails for the right reason, and the
one where being wrong is expensive - so a file whose body the user edited
is never deleted even when the pack dropped it. The table says `removed` +
`pack:<this>` is a delete; step 4a's protection is written for `changed`.
I think it must apply to `removed` too, and will record that as a concern
rather than silently widening the table.

**Group directories left empty by a deletion.** Not in the design. I
expect to remove a directory that a delete emptied, and to be careful that
it is one kennis created.

## 4. What actually happened that I did not expect

**The worst defect in this milestone was found by writing a test, not by
running the command**, and it is worth stating plainly: the first
`context sync` **deleted the user's bundle content when the pack store was
damaged.** `declared_content` correctly skips a pack whose stored
declaration will not parse; `resolve` then saw every file that pack owns
with nothing declaring it, took the `removed | pack:<this>` row, and
deleted all of them, reporting `removed` and naming no cause.

That is the failure section 5 step 2 spends its entire fast path
defending against, arriving through a door I had not thought to guard.
The design says so in one sentence - "`context sync` applies the same rule
from the other side" - and I read that sentence, wrote it into the
sketch's section 2 in passing, and then did not implement it. The same
shape as milestone 0's `--quiet`, whose six guards were carried across and
lost (#88). Concern #274, and `corpus sync` inherits the guard.

**I simplified two digests down to one, and the command told me within
thirty seconds.** Section 2 of this sketch says "two digests because there
are two questions". Writing the resolve tests, the fixture made one
digest look sufficient and I collapsed them. Running the real command:
every pack file carrying its own frontmatter was `rewrite` on every run,
forever, because the body kennis writes is not the bytes the store holds -
the header is read and replaced. The suite was green through all of it,
because the only two-run test used a file with no frontmatter.

So the design principle behind the two digests is sharper than I had it:
`sha256` is the body kennis wrote, `pack_sha256` is the store file it came
from, and they differ exactly when the pack ships a header. One recorded
value compares correctly against one of them and wrongly against the
other, and which one you lose depends on which you chose: the body digest
alone rewrites forever, the store digest alone makes a user edit
invisible.

**The bundle needing no state file held up completely.** Every question
the table asks is answered by the file itself, and that is worth more than
the convenience: a state file in the user's repository would go stale the
moment somebody edited a file outside kennis, and frontmatter cannot,
because it travels with the content. Section 8's "digest of each document
as kennis wrote it" in `state.json` is now provably unnecessary for this
destination.

**Two rows of the union-view table are not in the design's table**, and
both are collapses rather than additions. `adopt` is what "declaration
present, on disk owned by `pack:<other>`" becomes once the declarations
are a union: it is reachable only after the previous owner stopped
declaring the item. And "not declared, owned by `user`" - most of a bundle
- is not an action at all, where the design's `removed | user | leave,
report` implies one; without a state file kennis cannot tell "never
declared" from "no longer declared", and reporting every file the user
wrote would bury the line that matters.

**Section 3's worry about `delete` was the right worry and the wrong
row.** I expected the danger to be deleting a file the user edited, and
widened step 4a to cover the removed row for that reason (#272). The
actual danger was deleting a file nobody edited, because the store was
damaged - a much larger blast radius, and one the sketch did not
anticipate at all.

**Three smaller things, all found by running it.** "updated by the pack by
boepie", from a verdict word that already contained the preposition.
"2 files already in step" on a run where one file was held back, which
reports the protection as if it were agreement. And `display.note`
rendering the edit summary as `warning:`, when nothing is going wrong -
kennis protected the user's writing and is saying so.

**Writing the rule 4.4 guard first paid a second time.** `pack add` could
finally name `kennis context sync` instead of "the command that
materialises them is not built", and the guard confirmed the new sentence
resolves while `corpus sync` still does not.

