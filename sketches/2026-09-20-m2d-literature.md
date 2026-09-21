# Milestone 2, step 5: literature

Milestone / step: `design/plan.md`, "Milestone 2", item 5.
Date: 2026-09-20

Previous sketch: `2026-09-20-m2c-one-broken-document.md`, a correction. Before
that, `m2b` built the notes add path. What they left: notes can be added, and
a collection survives a document it cannot read.

## What I am about to do

Literature is notes plus bibliographic processing. Four pieces, in the plan's
own order: `literature/identifiers.py` ported, front-page identifier
extraction, the arXiv metadata lookup, and citekey derivation - then
`add_literature` on top of the notes path.

## How I expect it to work

### The tree this adds

```
src/kennis/engine/literature/
  __init__.py
  identifiers.py       # recognising the ways a paper can be named. No network.
  citekeys.py          # minting a name for one. No network.
  metadata.py          # arXiv's Atom API. The only part that fetches.
```

boepie keeps `resolve_doi_to_arxiv` inside `identifiers.py` and admits it in
the docstring: "nothing here touches the network except". Splitting the two
network calls into `metadata.py` makes `identifiers.py` purely local, which is
the difference between a module that needs an injected client in every test
and one that needs none.

Citekeys are separate from identifiers because the two do opposite things:
`identifiers` *recognises* a name a paper already has, `citekeys` *mints* one
it does not. boepie has the minting in `manifest.py`, which kennis has no
equivalent of - manifests are pack territory.

### `identifiers.py`

Ported whole: the modern and legacy arXiv patterns, the DOI pattern, the ADS
bibcode pattern with its fixed-width dot-padded shape, the arXiv host list,
and the BibTeX parser.

The distinction to preserve, because it is the one that prevents a real
disaster: **`normalize_arxiv_id` searches and `arxiv_id_if_reference`
matches the whole argument.** Searching is right when reading an identifier
out of a paper's own page. It is wrong for something a user typed, because any
filename carrying a date-shaped run of digits - `my-paper-2409.19750.md` -
contains an arXiv identifier by that reading, and answering a mistyped path by
silently fetching an unrelated paper is the worst failure this module can
produce.

`find_paper_identifiers` returns **every** identifier a page offers, ranked by
kind then by appearance, and deliberately does not choose. A first page can
carry the paper's own arXiv stamp, its journal DOI, an ADS bibcode, and a DOI
belonging to something it cites, and no amount of pattern work distinguishes
the last from the first three.

The version suffix is dropped from an arXiv identifier. The corpus tracks a
paper, not a snapshot of one, and keeping it would make `2409.19750v1` and
`v2` look like two documents to duplicate detection.

### `citekeys.py`

`derive_citekey(authors, year, title)` is surname plus two leading title words
plus year, in the style a Zotero export already uses. `unique_citekey`
disambiguates with `a`, `b`, `c` as Zotero does, and past `z` numbers them -
title-derived keys, which is what a folder of PDFs with no bibliography
produces, collide far more readily than the author-and-year keys the
convention was written for, so the twenty-seventh is numbered rather than
fatal.

### `metadata.py`

`lookup_arxiv_metadata(arxiv_id, *, client=None)` and
`resolve_doi_to_arxiv(doi, *, client=None)`, both against arXiv's Atom API,
both taking a client so a test hands over a transport. Both return None rather
than raising on a network failure: the identifier is already in hand by then,
and refusing to add a document because arXiv was unreachable trades a small
loss for a total one.

A DOI resolves only as far as an arXiv preprint, and a bibcode not at all.
Resolving those needs Crossref metadata or an ADS key, neither of which kennis
asks anyone for. Both are recorded regardless, because identity is what
duplicate detection runs on even when metadata is unavailable.

### `add_literature`

The notes path with three additions.

**Bibliographic identity joins the uniqueness record.** `_Uniqueness` gains
`bib_identities`, mapping a lower-cased arXiv identifier, DOI or bibcode to a
document. This is the plan's "adding the same paper by arXiv identifier and by
`.bib` entry produces one document": the two routes derive different citekeys
and share no source checksum, so neither the natural key nor the content
digest catches the duplicate. Its bibliographic identity does, and that is the
only thing that does.

**The surrogate identifier is derived, not minted.** Milestone 1 built
`natural_key_for_literature` with the precedence arXiv, DOI, bibcode, and
`derive_id` over it; literature is the first caller. `id_from` records the key
so the derivation is auditable.

**Identity has to be established before the document can be written**, and
this is where the step's shape is decided. The order:

1. The argument is itself an identifier - an arXiv identifier, a DOI, a
   bibcode. Whole-argument matching, never a search.
2. The argument is a `.bib` file. Each entry is an input of its own, carrying
   its citekey, its arXiv identifier or DOI, and possibly a `file =` path to a
   local PDF.
3. The argument is a local document. It is converted with the batch, and its
   identity is read off the front page text the converter carried out.

For case 3 the rule is: **`--identifier` if the user supplied one; otherwise
the single highest-precedence candidate the page offers; otherwise refuse.**
Precedence deciding between one arXiv identifier and one DOI is not a guess -
it is the rule milestone 1 already wrote down. Two candidates *of the same
kind* is a guess, because one of them is likely something the paper cites, so
that is refused and both are named.

Refusal names both ways forward, which is the plan's third test:

```
no arXiv id, DOI or ADS bibcode found on its first page, so it has no
bibliographic identity and cannot go to literature. Supply one with
--identifier, or add it as a note instead: kennis corpus add -n '<path>'
```

Notes is a real answer there, not a consolation prize: notes have no natural
key *by design*, so a document with no bibliographic identity is exactly what
that collection is for.

**A `.bib` entry keeps its own citekey.** That is the plan's second test, and
the reason is that the citekey is what the user's own bibliography already
cites; deriving a new one would break every reference in their writing.
Derivation is only for a paper that arrived without one.

### What this step does not do

No review buffer. boepie puts an ambiguous front page in front of the user in
`$EDITOR`; design section 20 says interaction is supplied by the caller
through a decision channel, and section 21 specifies it. That is a mechanism
of its own and belongs with prompting in milestone 5. The engine refuses where
it would later ask, which is the honest non-interactive behaviour and leaves
exactly one place for the channel to be inserted.

No fetching of the paper itself from arXiv. `add_literature` here identifies
and records; pulling the PDF or the LaTeXML HTML is a fetcher, and the plan
puts fetchers in step 6 with docs.

## What I expect to be uncertain or difficult

- **Whether "the single highest-precedence candidate" is the right
  non-interactive rule.** It is defensible, but a page carrying the paper's
  own arXiv stamp and one cited arXiv identifier will be refused, and that may
  be the common case rather than the rare one. I will not know until there are
  real PDFs in front of it.
- **The ADS bibcode pattern.** Nineteen characters of dot-padded fixed width,
  and the comment says the qualifier stays letters-or-dot to avoid matching
  arbitrary runs of text. I am porting a regex whose false-positive rate I
  cannot measure without a corpus of real front pages.
- **`.bib` entries as inputs.** One argument expands to many documents, which
  the notes path has no equivalent of - a directory walk expands to many
  *files*, and `resolve_inputs` handles that. A `.bib` expands after
  resolution, inside the literature path, which means two expansion points in
  one command.
- **Testing the Atom API without the network.** `httpx.MockTransport` handles
  the request, but the response is XML I have to write by hand, and a fixture
  I invented will agree with my parser by construction.
- **`filterwarnings = ["error"]` meeting `xml.etree`.** Parsing untrusted XML
  is a place the standard library has historically emitted warnings.

## What actually happened that I did not expect

**A fake that answers every query identically makes distinct papers collide,
and the test that caught it was not looking for that.** The arXiv fixture
returns one Atom entry whatever is asked, so two `.bib` entries with different
DOIs both resolved through `resolve_doi_to_arxiv` to the *same* arXiv
identifier - and the second was correctly reported as a duplicate of the
first. Two tests failed and two others were passing for the wrong reason:
`the duplicate is found by doi too` was really observing an accidental arXiv
collision, not DOI matching.

The fix is a second fixture, `no_preprint_client()`, for every test with two
papers in it. The general lesson is sharper than the fix: a stub that ignores
its input is fine for one call and actively misleading for two, because it
turns "different inputs" into "same output" exactly where a test is asserting
that two things stay apart.

**boepie's `derive_citekey` and its own docstring disagree, and I followed the
docstring.** The code takes `words[:2]`, so its documented example
`smirnovRevisitingRadioInterferometer2011` - three words - is not something it
can produce. The real key comes from Zotero via Better BibTeX's
`shorttitle(3,3)`, and the whole point of the style is that a derived key sits
beside an exported one without looking out of place, so kennis takes three.
Recorded in `citekeys._TITLE_WORDS` rather than left as a silent divergence.

**The ADS bibcode pattern will not match a bibcode at the end of a sentence.**
Its trailing lookaround excludes a dot, and a bibcode both contains and may
abut one, so `...417H.` fails where `...417H ` succeeds. I found this by
writing a front-page fixture with ordinary punctuation in it and watching the
bibcode not appear. The pattern is unchanged - loosening the lookaround is how
it starts matching arbitrary 19-character runs - but the limit is now written
down where the next reader will see it, and it fails in the safe direction:
a missed identifier is a refusal, a false one is a wrong paper.

**The non-interactive identity rule held up better than I expected.**
Precedence between kinds is not a guess, so one arXiv stamp and one journal
DOI on the same page resolves cleanly to arXiv and records `id_from:
arxiv:...`. Only two candidates *of the same kind* refuse. The case I was
worried about - a paper's own stamp plus one it cites - does still refuse, and
I still do not know how common that is without real PDFs. It is the right
failure direction and exactly one place for the decision channel to be
inserted later.

**`_plan_binaries` had to stop taking identifiers and start taking paths.**
Notes derive the conversion batch from the arguments; literature derives it
from the `.bib` entries' `file =` fields as well, which are not arguments at
all. Handing it the candidate paths instead of the strings to filter made both
callers simpler, and the `converter` parameter `_binary_candidates` was taking
turned out never to have been used.

**`DocumentFacts` grew the bibliographic identities, on the same argument as
the checksum.** A literature document kennis cannot validate must still
reserve its arXiv identifier and DOI, or the same paper walks in again the
moment one document is hand-edited. That is the third fact the lenient reader
carries for exactly the same reason, which suggests the reason is the shape of
the thing rather than a special case: what a batch needs to stay consistent is
knowable from plain YAML, and validation is a separate question.

**A paper named only by an identifier is written as a stub.** Fetching the
preprint is step 6's fetchers, so what lands now is a body saying the text has
not been fetched, with the bibliography in frontmatter. That is enough to make
the citekey citeable and the identity deduplicable before any text exists, and
it means `source.from` is `arxiv:...` rather than a path - which section 4's
recoverability table already anticipated.
