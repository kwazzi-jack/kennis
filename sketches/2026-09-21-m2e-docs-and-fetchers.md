# Milestone 2, step 6: docs and the fetchers

Milestone / step: `design/plan.md`, "Milestone 2", item 6.
Date: 2026-09-21

Previous sketch: `2026-09-20-m2d-literature.md`. What it left: papers can be
added and identified, but a paper named only by an identifier is written as a
stub whose body says the text has not been fetched (concern #28), and docs
does not exist at all.

## What I am about to do

Two things the plan's one line puts together. Docs as a collection - project
grouping and page keys on top of the notes ingestion path - and the two
fetchers boepie has, one for documentation sites and one for arXiv papers.
The second closes concern #28 by filling the stubs.

## How I expect it to work

### The tree this adds

```
src/kennis/engine/literature/fetch.py   # arxiv.org/html then ar5iv. Fetches.
src/kennis/engine/docs/
  __init__.py
  sites.py        # what a docs site is, and what its project is called
  discover.py     # searchindex.js, sitemap.xml, bounded crawl. Fetches.
  fetch.py        # one page: fetch, select the container, convert
```

`docs/` sits beside `literature/` rather than inside `corpus/` because the
two are the same kind of thing: a collection's extra processing, above the
shared ingestion in `corpus/`. `add_docs` itself goes in `corpus/add.py` with
its two siblings, since all three drive the same uniqueness record and the
same write loop.

### What a docs page is

A docs page's identity is `(project, page)`, and milestone 1 already built
`natural_key_for_docs(project=..., page=...)` for it, so the surrogate
identifier is **derived, not minted**, exactly as literature's is. Re-adding a
site therefore produces `UNCHANGED` per page rather than a second copy, and
two machines that crawl the same site write byte-identical frontmatter.

`page` is boepie's docname: the URL's path relative to the crawl prefix, with
any `.html` suffix removed, so `.../en/latest/install/index.html` under prefix
`/en/latest/` becomes `install/index`. `project` is a directory name and so
must be a safe path component - `^[a-z0-9][a-z0-9_-]*$`, which rules out both
`..` and `../evil`. Supplied with `--project`, else derived from the base
URL's host by taking the first label (`stimela.readthedocs.io` -> `stimela`).

`DocsPage` in `corpus/schema.py` already has the fields: `project`, `page`,
`base_url`, `version`, and a `CrawlScope` recording `discovery`, `exclude`
and `path_prefix`. The crawl scope is written onto **every** page rather than
into a project-level file, which is the choice milestone 1 made and the
reason is that it is the one thing a page cannot reconstruct about itself;
re-crawling then needs no flags typed again and there is no second source of
truth to drift.

### Discovery: three modes, cheapest and most authoritative first

`probe_discovery_mode` tries them in order and the answer is recorded:

| mode | how the page list is obtained | cost |
|---|---|---|
| `sphinx` | `searchindex.js`, which lists every docname the site built | one request |
| `sitemap` | `robots.txt`'s `Sitemap:` directives, else `/sitemap.xml`, following `sitemapindex` nesting | one to a few |
| `crawl` | breadth-first link following from the base URL | up to `max_pages` |

The crawl is bounded on three axes - 300 pages, depth 5, 50 sitemap files -
and scoped to same-origin **and** same-path-prefix, because same-origin alone
sweeps a site's blog and marketing pages in beside its documentation. Links
are dropped by file extension before being requested and again by
`Content-Type` after, and the whole walk is deduplicated on a normalised URL
with fragment and query stripped and the trailing slash collapsed.

**One deliberate departure from boepie: robots.txt is consulted on the Sphinx
path too.** boepie checks it only on the sitemap and crawl paths, on the
reasoning that a site publishing `searchindex.js` has published its page list.
That conflates two statements - here is what exists, and here is what you may
fetch - and only the second is robots.txt's. It costs one extra request.

### Fetching a page, and why status 200 is not enough

`convert_page(html, page_url)` selects the rendered main container -
`[role="main"]`, else `div.document`, else `article`, which is where Sphinx
themes differ and agree in that order - strips the chrome that carries no
prose (heading anchors, sidebars, breadcrumbs, scripts), resolves every
`href` and `src` against the page URL so the markdown survives leaving the
site, and converts with `markdownify` and **escaping off**. Escaping off is
not cosmetic: it is what stops `input_ms` becoming `input\_ms` and putting a
backslash inside the identifiers BM25 will match on.

If no container is found it raises, and the page is reported failed rather
than written. That is the check concern #34 asks for. A bot-challenge page is
served as HTTP 200 with an HTML body, so status is no evidence at all; what
distinguishes it is that it has no documentation container in it, and this
already refuses on that basis.

### The arXiv fetcher, and closing concern #28

`fetch_paper(arxiv_id, *, client)` tries `arxiv.org/html/<id>` first, then
`ar5iv.labs.arxiv.org/html/<id>`. Both are LaTeXML renderings emitting the
same `ltx_*` DOM, so one converter serves both; arXiv's own is tried first
because it is authoritative and ar5iv has the broader historical backfill.
A 404 at one source is the expected "not rendered here" answer and falls
through; anything else falls through too, and a paper with neither is
reported unavailable rather than raising.

`convert_arxiv_html` differs from the docs converter in one respect that
matters: every LaTeXML `<math>` element carries its original LaTeX in an
`alttext` attribute, so replacing the element with `$...$` or `$$...$$` keeps
equations legible without parsing the MathML tree underneath.

The insertion point is a single function. `_converted_for` in `corpus/add.py`
currently returns `_stub(identity)` whenever `paper.path is None`. It will
instead try the fetcher when the identity has an arXiv identifier, and fall
back to the same stub when it does not or the fetch fails. The stub stays,
because a DOI-only or bibcode-only paper still has no reachable text - that
is concern #35's gap, and it is not being closed here.

`AddOptions` gains `fetch: bool = True` so the old behaviour is still
reachable, and the existing injected `arxiv` client is threaded down, so the
test suite stays offline by construction.

### What a fetch cannot do, and what it says instead

A publisher PDF behind a session token is not reachable from a standalone
process (concern #34). Nothing here tries. `add_literature` already refuses a
paper whose text it cannot obtain, and the refusal names the manual route:
download the file and add it with `--identifier`.

### Serial, not concurrent

Design section 20 recommends that the fetchers use concurrency internally and
present a synchronous interface. **I am keeping them serial**, with the 0.2
second politeness delay between requests. The reason is that concurrency and
the delay are in direct tension and the delay is the binding constraint: a
docs add targets one host, so parallel requests are precisely the traffic
pattern the delay exists to avoid. Concurrency would pay across many hosts,
which is `corpus sync` over several pack-declared projects - a later
milestone, and the right place to reconsider.

### Live tests

An opt-in `network` marker, registered in `[tool.pytest.ini_options]` because
`--strict-markers` is on, and `addopts` gains `-m "not network"` so the
default run stays offline and deterministic. `tests/test_live.py` holds a
small number of tests that hit real hosts: an arXiv paper that renders, one
that does not, a real Sphinx site, a real sitemap site, and - the one that
directly tests concern #34 - a publisher PDF URL, asserting that kennis
refuses rather than writing a challenge page as a document.

## What I expect to be uncertain or difficult

- **`filterwarnings = ["error"]` meeting BeautifulSoup and markdownify.**
  BeautifulSoup emits warnings on input that looks like a filename or a URL
  rather than markup, and markdownify has been moving its escaping options.
  Both become test failures here.
- **`time.sleep` in a test suite.** The delay is a parameter with a default,
  so tests pass zero, but every call site has to actually thread it or the
  suite acquires seconds of dead time invisibly.
- **The `_slug_from_url` collision case.** Two URLs differing only by a
  trailing slash or by `.html` normalise to the same page key. That is
  intended for deduplication but means a site serving both `a/` and `a.html`
  as different content loses one, and I do not know whether that occurs.
- **Whether robots.txt on the Sphinx path breaks a real site.** A docs host
  that disallows everything to unknown agents would now yield zero pages
  where boepie yielded all of them. This is the departure most likely to be
  wrong, and the live test is what will say.
- **`xml.etree` parsing third-party sitemaps.** Untrusted XML, and the
  standard library has historically warned here.
- **Threading `project` through `AddOptions`.** It is a third collection-
  specific field on a shared options object, after `identifier` and
  `citekey`. If the shape is wrong, this is where it will show.

## What actually happened that I did not expect

**The live tests earned their place on their first run, and what they caught
was not what they were written for.** They exist to settle concerns #14, #26
and #34 against real inputs. Seven of the eight passed, including the MNRAS
refusal. The eighth failed because arXiv answers a burst of API requests with
HTTP 406, and every network call in `literature/` degrades a failure to None
by deliberate design - so rate limiting arrives at the user as "this paper has
no metadata" rather than "you asked too fast". A `.bib` of fifty entries would
have landed as fifty stubs, silently. No offline fixture could have shown
this, because the behaviour being wrong is the *service's* response to a
pattern of requests rather than to any one of them. Fixed by pacing the batch;
recorded as concern #36, whose general form is that a degradation path correct
for one failure can conceal a systematic one.

**Three of the four things that actually broke were my own test fixtures, and
one repeated a mistake already written down.** The routing fixture in
`test_literature_fetch.py` matched hosts by substring, and
`ar5iv.labs.arxiv.org` contains `arxiv.org`, so the fallback answered the rule
written for the source it is a fallback for. The Sphinx site fixture keyed
pages by full URL, so the test that varies the host to check project naming
got nothing served. And `arxiv_client()` answered *every* request with the
Atom feed, including the newly-issued HTML fetch - which is exactly concern
#27, the stub that ignores its input, in a second place. Concern #32 predicted
this direction and it held again: roughly a fifth of my predicted difficulties
materialised, and the ones that did were fixtures.

**The Atom-feed-as-HTML fixture found a real defect, which is why it is worth
distinguishing a bad fixture from a bad test.** Handing XML to BeautifulSoup's
HTML parser emits `XMLParsedAsHTMLWarning`, and `filterwarnings = ["error"]`
raised it out of `fetch_paper`, a function whose contract is never to raise.
The fixture was wrong *and* the code was wrong: a fetch should check the
content type before parsing, which is the same rule the crawl already applied
to its links and the same rule concern #34 asks for. Concern #37.

**`filterwarnings = ["error"]` paid for itself, and not where I predicted.** I
expected trouble from markdownify's escaping options; there was none. The
warning that fired was about XML, from a path I had not thought of as
parsing-related at all.

**`RobotFileParser.allow_all` and `disallow_all` are real attributes that
typeshed does not declare**, so the ported code does not type-check and
`type: ignore` is not available. Parsing an equivalent robots body through the
public `parse()` is identical in behaviour and better code: an empty body
allows everything, `Disallow: /` forbids everything. The constraint produced
the better version, which is not what I expected from it.

**`Progress` has no free-text field and `Severity` has no informational
level.** I had written `Progress(done=..., note="12 pages found by sitemap")`
without checking, and neither half exists. That is the event vocabulary
refusing to become a logging call, which is what design section 20 says it is
for - an engine that "decides whether a warning is worth printing" is exactly
what it rules out. The page count went into `Progress(completed, total)` and
the discovery mode went nowhere, because it is already recorded on every page
written.

**Extending `_identities_of` to docs was smaller than extending it to
literature had been.** It reads the `docs` block from plain YAML and returns
the same natural key the identifier was derived from, so a docs page kennis
cannot validate still reserves its project and page. The argument is
identical to the one made for the checksum and then for the bibliographic
identifiers, which is now three times, and I think that means it is a property
of the lenient reader rather than a series of special cases: **what a batch
needs to stay consistent is knowable without validation.**

**The `page_key` collision I flagged as uncertain is real and I chose it.** A
site serving both `guide/` and `guide.html` yields one key, deliberately,
because two documents of the same content under two keys is the duplicate the
natural key exists to prevent. What I did not anticipate is the same mechanism
biting local files: a tutorial filed into a project is keyed by its filename
stem, so two files named `index.md` collide. Concern #40, and it wants an
explicit `--page`.

**I found an existing `# type: ignore` in the test suite**, in
`test_add_literature.py`, which CLAUDE.md forbids outright. It was mine, from
step 5. Replaced with an `isinstance` narrowing helper. Worth noting that the
rule was violated for four days without anything catching it - ruff does not
check for it and mypy is only run against `src`.

**Added after review, 2026-09-21.** Being asked to make the wait time a user
setting meant looking at where the wait actually happened, and two of the
three docs discovery modes did not have one. `crawl_site` slept between
requests; the Sphinx and sitemap paths knew every page up front and the write
loop fetched all of them back to back. So the mode that discovers pages
slowly was polite and the two that discover them instantly were not, which is
backwards, and it was backwards while the module header of `discover.py`
asserted that "every request is spaced by a politeness delay". The general
lesson is concern #41's: **a policy stated in a docstring is not a policy the
code has**, and I wrote both the docstring and the omission in the same hour
without noticing they disagreed.

The interval now lives in `AddOptions.request_delay_seconds` rather than in
two module constants, which is where every other per-add choice already was.
The keyword argument I had put on `add_literature` was reachable from no
front end at all, so as a user-facing setting it did not exist.
