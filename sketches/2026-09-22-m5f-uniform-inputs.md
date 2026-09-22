# Inputs behave the same in every collection

Milestone / step: not a plan item. Arising from Brian's question on
2026-09-22 about whether a URL behaves the same in notes and literature.
Date: 2026-09-22

Previous sketch: `2026-09-22-m5e-literature-without-stubs.md`.

## What I am about to do

Brian's model is that `add_literature` is `add_notes` with a pre-step and a
post-step. That is *almost* what the code is, and the two places it is not
are both defects:

1. **A URL is always treated as HTML.** `convert_url` calls `convert_html`
   on `response.text` with no look at the content type, so a URL serving a
   PDF is stored as its raw bytes decoded as text, labelled `via: html`.
2. **Literature refuses URLs outright.** `_papers_of` classifies an argument
   as a bib file, a reference, or a local path; a URL is none of those, so it
   is refused with a message listing what it is not.

Then the thing he asked for: `rules.md`, holding the rules these discussions
have produced, with a table of every allowed input and what it resolves to.

## How I expect it to work

### One question decides a URL: what did the server send

```
GET the url
  content-type says html      -> convert_html        (via: html)
  content-type says pdf/docx/
    pptx/xlsx                 -> write to a temp file, convert_local_file
                                                     (via: mineru)
  content-type says markdown
    or plain text             -> verbatim            (via: verbatim)
  anything else               -> refuse, naming the type
```

The suffix is **not** what decides, unlike a local file. A local path is a
name the user typed and vouched for; a URL is a request whose answer only
the server knows, and a URL ending `.pdf` that returns an HTML paywall page
is the common case rather than the exotic one. This is the MNRAS behaviour
Brian raised in milestone 2, arriving in a different place.

### The shared core, stated

| stage | notes | literature |
|---|---|---|
| resolve arguments | `resolve_inputs` | `resolve_inputs`, then `_papers_of` |
| reserve what exists | `_Uniqueness.of` | same |
| plan conversions | `_plan_binaries` | same |
| **establish identity** | - | `_choose_identity`, `_enrich` |
| get markdown | `_convert` | `_converted_for` |
| dedup | checksum | identity, then checksum |
| **bibliography** | - | `_citekey_for`, `bib` block |
| write | `_write` | `_write_paper` |

So Brian is right, and the shared middle is where both defects live: one
stage is shared in principle and duplicated in fact. Fixing #113 was the
first of these; the URL dispatch is the second, and both were places where
literature had its own copy of something notes already did.

### `rules.md`

Not a design document and not a concern log. The rules as they currently
stand, each with the date it was decided and a line on why, so that a rule
can be changed by editing one entry rather than by finding the discussion it
came from. An allowed-inputs table is one section of it.

## What I expect to be uncertain or difficult

- **Whether to sniff content when the server lies.** A server sending
  `application/octet-stream` for a PDF is common. I expect to check the
  first bytes for `%PDF` as a fallback and nothing more elaborate.
- **Temporary files for a fetched binary.** `convert_local_file` takes a
  path, so a fetched PDF has to be written somewhere before MinerU sees it.
  Where it goes, and that it is removed even when conversion raises.
- **Whether literature should accept a URL with no identifier.** A URL is a
  document, not an identity, so it still needs `--identifier` - the same
  rule a local PDF already follows.
- **How many input combinations there really are.** Three collections, six
  argument kinds, and options that only apply to some. The table is the
  deliverable, and writing it is how I will find the combinations nobody
  has tried.

## What actually happened that I did not expect

**`_Page` has modelled this correctly since milestone 2.** It carries `url`
*and* `path` - a docs page is either something to fetch or something on disk,
and the rest of the code branches on which. `_Paper` carried only `path`, so
literature had no way to represent "a document reached over the network" and
refused URLs for not being any of the three things it did know. The fix was
one field, and the design it belongs to was already written down next door.

**The content-type dispatch is the MNRAS problem again, in a new place.**
Milestone 2 established that a publisher PDF cannot be fetched because the
link hands back a session-gated page. `convert_url` then took every response
as HTML - so the paywall page was converted and stored as though it were the
paper, and a genuine PDF was stored as `%PDF-1.4 ...`. One rule settles both:
what the server sent decides, not what the link ends with.

**My first test for it was written to pass either way.** It asserted "either
no `%PDF` in the body, or a failure mentioning pdf", because I did not know
whether MinerU would be available in the test environment. Both injections
missed it: refusing the PDF for an unknown content type satisfies the second
branch just as well as converting it satisfies the first. Rewritten against
the `fake_mineru` fixture, it asserts the only thing that is actually right -
`via: mineru`, `format: pdf`, and `origin` the URL rather than the temporary
file. **A test that tolerates two outcomes tests neither**, which is #105's
lesson arriving one more time and from a direction I did not expect: the
hedge was about the environment, not about the behaviour.

**Moving two fixtures to `conftest.py` cost three attempts.** The slice I
took from `test_converters.py` included `a_pdf`, which is not a fixture and
is used by seventeen tests there. Restoring the file from git and slicing on
an explicit end marker took less time than the two repairs did. The general
form: when extracting, name the *end* of the extraction, not just its start.

**Fixtures were the thing that broke twice more** - two files with identical
bodies deduplicating correctly, and a helper whose body begins with a heading
so every document it writes is titled after the heading rather than the file.
Concern #32 now has six instances.
