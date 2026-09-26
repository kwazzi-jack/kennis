# v0.3.0l - the declarations a fetch resolves

Milestone 7 unit 7c, and the last of the milestone. A pack declares
`corpus.literature` and `corpus.docs`: papers by identifier and
documentation sites by project. Neither is content the store holds, so
neither is copied - they are resolved by fetching.

This is the only part of the milestone that touches the network.

## 1. What I am about to do

Extend `corpus sync` so that a pack's papers and documentation projects
are fetched, kept, or removed with the same table the notes use, reusing
`add_literature` and `add_docs` to do the fetching.

## 2. How I expect it to work

### A declaration has a digest too, and that is what makes the table fit

`resolve` compares three digests: what the pack declares now, what the
document recorded, and what the document's body is. For content those
are digests of bytes. For a declaration there are no bytes - so the
declaration's **own fields** are digested:

| section | key | digest of |
|---|---|---|
| `corpus.literature` | `arxiv:`/`doi:`/`bibcode:` + its value | citekey, title, authors, year |
| `corpus.docs` | `project` | project, base_url, exclude |

The document records that digest in `source.pack_sha256`, exactly as a
pack note does. Then:

- declared, absent -> **fetch**
- declared, present, digest unchanged -> **keep**, and no refetch
- declared, present, digest changed -> **rewrite the fields**, not the
  document: section 5 step 3 is explicit that a changed citekey against
  an unchanged identifier is a *rename*, and re-fetching would delete a
  paper and pull the identical one down again
- declared, present, `owner: user` -> **yours**
- no longer declared, pack-owned -> **delete**
- unrecognised owner -> **refuse**

`body_digest` and `written_digest` are both left out (`written_digest`
is None), so the `edited` row never fires. That is correct rather than a
gap: kennis never claims to own a fetched paper's prose, so there is
nothing for a user edit to be protected from - the only thing a rewrite
touches is the bib block.

### The owner has to reach two writers that hard-code it

`_write_paper` and `_write_page` both set `owner="user"`. `AddOptions`
gains an `owner`, which is the field every adder already receives, and
both writers read it. `corpus add` passes nothing and keeps `user`.

### A documentation project is many documents under one declaration

The unit of declaration is the project; the unit on disk is a page. So:

- **present** means the project has at least one pack-owned page, and
  the recorded digest is read off any of them (they are written by one
  crawl and agree).
- **delete** removes every page of that project.
- **keep** does not re-crawl. A crawl is hundreds of requests, the
  design's diff key for docs is the project alone, and refreshing a site
  is what `corpus add --docs` is for. Recorded as a concern rather than
  assumed.

### Fetching needs clients, and the engine must not reach for them

`sync_corpus` takes what it needs as arguments - `AddOptions` and the
two `httpx` clients `add_literature` already accepts - so an offline
caller supplies clients that say so. Concern #87's rule: an engine that
consults a global is an engine two callers cannot use differently in one
process. The tests supply transports that never leave the machine, so
nothing in the suite reaches a host.

## 3. What I expect to be uncertain or difficult

**Whether `rewrite` for literature can be done without refetching.** It
has to be: the point of keying on the identifier is that a citekey
correction is not a delete-then-add. So the rewrite reads the document,
replaces the `bib` fields the declaration carries, and writes it back
with the identifier and the body untouched. The risk is the filename,
which is derived from `title - authors - year` and will disagree after
a title correction. Same shape as #276 for notes, and I expect to take
the same answer.

**A pack declaring a paper the user already has.** The corpus already
holds it as `owner: user`, and the identity map will find it. That is
the `yours:` row and the declaration must not fetch a second copy - but
`add_literature`'s own duplicate detection would report `UNCHANGED`
rather than letting the sync report `yours`. I expect to have to consult
the collection myself before calling the adder, which is what the
resolution needs anyway.

**Failure.** A fetch that fails is not a resolution outcome - the
declaration still stands and the document is still absent. It has to be
reported without stopping the run, because one unreachable host must not
prevent the other nine papers from arriving.

## 4. What actually happened that I did not expect

**The worst finding was again about a document kennis could not read,
and again it was a duplicate rather than a deletion.** `contents()`
returns the documents that validate and the ones that do not, in two
lists. Every reader so far has been a reader, and skipping the second
list is right for a reader. A sync is a writer: a document that did not
validate is not on disk as far as the table can see, so its declaration
reads as unfetched and the sync writes a **second copy**. The realistic
cause is the exact case section 6 names - `owner: managed_by:boepie`
fails the `owner` pattern, so the document never reaches the table that
was written to refuse it.

I found it by writing the refusal test and watching it not raise. The
refusal I had written was for `resolve`'s `refuse` verdict, which that
document can never produce. Concern #278.

**Running the command found the citekey.** Section 3 worried about the
*rewrite* path and I built it carefully; the defect was in the *write*
path, which I had not thought about at all. `add_literature` derives a
citekey from the title when none is given, so the first fetch of a
declared paper landed under `paperAstromlabAstrollamaB` instead of the
citekey the pack declared - the handle the provider's own prose cites.
`AddOptions.citekey` already existed and simply was not passed.

That also settled a question the sketch left open without noticing it:
the declaration is authoritative for the citekey and for **nothing
else**. arXiv knows the paper's own title better than a one-line
declaration does, so the pack's title, authors and year fill gaps rather
than overwrite. My first `_rewrote_bibliography` had it the other way
round.

**The sandbox has a network, and that was useful rather than alarming.**
The real run fetched arXiv 2409.19750 and rendered it, which is how the
citekey defect became visible at all - a mocked run would have shown the
same thing, but I only ran the mock because the real one surprised me.
Nothing in the suite reaches a host; every client in the tests is an
`httpx.MockTransport`.

**A test declared two `corpus:` keys in one YAML document.** The second
silently wins, so the test that was meant to declare a paper *and* a
documentation site declared only the site, and then asserted about the
paper. `extra="forbid"` cannot catch this - it is a duplicate mapping
key, which YAML resolves before pydantic sees it.

**Threading the owner was three functions deeper than expected.**
`AddOptions` reaches the adders, but `_write_paper` and `_write_page` do
not receive it, and `_add_page` did not either - so the owner and the
declaration digest became explicit parameters on both writers with
`user` as the default. `corpus add` passes nothing and is unchanged.

**One thing from section 3 turned out not to be a problem.** I expected
to have to consult the collection myself before calling `add_literature`
so that a paper the user already owns is reported as `yours` rather than
`UNCHANGED`. The plan already does that - resolving against what is held
is what the table *is* - so the adder is only ever called for a `write`.

