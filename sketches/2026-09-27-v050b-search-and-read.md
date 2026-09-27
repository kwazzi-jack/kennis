# v0.5 unit 9b: searching, and reading what a hit points at

Date: 2026-09-27

## 1. What I am about to do

The first thing a person can use. Search the four scopes, see ranked
hits, click one, read the document.

The plan said this unit would "find out what a document actually has
rather than assume", so I looked before sketching rather than after.
Three documents in the real corpus, and they disagree in ways that
decide the design.

## 2. How I expect it to work

**What the corpus actually holds**, measured on the three papers:

| document | route in | images | maths | table rows |
|---|---|---|---|---|
| AstroMLab 2 | arXiv HTML | 1, **absolute `https://arxiv.org/...`** | some | many |
| Radio interferometer ME | arXiv HTML | 0 | **343** | 172 |
| Dying for freedom | MinerU PDF | 4, **relative `images/<sha>.jpg`** | 0 | 0 |

Three consequences, and none of them was in the plan:

**Maths is not optional and markdown eats it.** Measured:
`$x*y*z$` renders as `$x<em>y</em>z$` through plain markdown-it,
because `*y*` is emphasis before it is TeX. So `mdit_py_plugins`'s
`dollarmath` is required rather than a nicety - it protects the span
into `<span class="math inline">` and KaTeX renders it in the browser.
The package is already in the resolved tree.

**Local figures are dangling.** `images/<sha>.jpg` is referenced four
times and no image file exists anywhere in the corpus - concern #134,
which said a converted PDF's figures are referenced and thrown away,
is live and now visible. The interface must not emit a broken `<img>`:
it renders a placeholder saying a figure was here and the conversion
did not keep it. That turns a silent ugliness into a legible fact, and
it is the honest rendering of what the document is.

**A remote figure is an outbound request the user did not make.**
Rendering the arXiv paper would fetch from `arxiv.org`, telling them
which paper is being read and when, from a tool whose rules say that
sending a document to a third party is never a default (rules.md 4.5).
This is not sending a document, but it is the same shape, so remote
images are **blocked by default** and shown as a placeholder naming
the host, with an explicit control to load them - which is what an
email client does, for this reason.

**`render/html.py` is the new shared renderer.** markdown-it-py with
tables and `dollarmath`, Pygments for fences, and the image rule
above. In `render/` and not `gui/` because markdown-it is a converter
rather than an interface library, so the layering allows it and a
second surface would want the same words.

**Hits reuse `render/hits.py::rendered_hit`.** It returns
`RenderedHit(headline, detail, body)` - three fields, not a joined
line - so the interface places them in elements without reformatting
what the other two front ends say.

**htmx for the search box.** One attribute on a form, a partial
template for results. No build step, no JavaScript written by hand,
which keeps the untested surface small.

KaTeX and htmx are vendored under `gui/static/vendor/`, which is the
directory unit 9a exempted from the ASCII rule - so this is where that
exemption earns itself.

## 3. What I expect to be uncertain or difficult

- Whether KaTeX renders `dollarmath`'s output without its auto-render
  extension. I think the spans need a small script to walk them, and
  that script is the hand-written JavaScript I said I would avoid.
- Whether Pygments' HTML classes can be styled from the semantic roles
  or need a palette of their own. The roles are nine colours and a
  syntax theme usually wants more, so this may be the first honest
  need for colour the registry does not name.
- How a document that is 172 table rows of a converted PDF actually
  looks. Probably bad, and worth seeing before deciding whether it is
  this unit's problem.
- Whether searching from the interface should hold the corpus lock at
  all. Reading does not mutate, so I expect not, but `search` loads an
  index and I have not checked whether that path takes one.

## 4. What actually happened that I did not expect

**The ASCII exemption I argued for in unit 9a excludes nothing, and I
removed it.** #308 reasoned that KaTeX "maps Unicode mathematical
symbols and cannot be anything else". Measured: `katex.min.js` and
`katex.min.css` contain no non-ASCII bytes at all, because a minifier
writes them as `\uXXXX` escapes, and the woff2 fonts are binary, which
both `grep -I` and pre-commit's `types: [text]` already skip. So the
check passes over the whole vendored directory with no exemption.

I removed it rather than keeping it for a future asset that might need
one, because the project's posture forbids keeping a path "just in
case" and because an exemption that excludes nothing is worse than
none - the next person reads it as licence to vendor anything.
Concern #313 supersedes #308.

Worth naming as a pattern: I reasoned from what KaTeX *is* rather than
from what the file *contains*, wrote a config change and an invariant
on that basis, and only found out by running the check. The whole
thing took one command.

**Measuring the corpus before sketching changed three decisions**, and
none of the three was in the plan. Maths was the sharpest: `$x*y*z$`
renders as `$x<em>y</em>z$` through plain markdown-it, because `*y*` is
emphasis before it is TeX, and one paper carries 343 inline spans. The
plan listed KaTeX as display polish; it is data integrity.

Local figures were the second: `images/<sha>.jpg` is referenced four
times in a converted paper and **no image file exists anywhere in the
corpus**, so concern #134 is not theoretical. Rendering an `<img>`
would have produced four broken icons that read as "this interface is
faulty" rather than "this document lost its figures".

The third was not in my sketch either until I saw the URLs: the arXiv
paper's figure is an absolute `https://arxiv.org/...`, so rendering it
tells arxiv.org which paper is being read and when. That is the shape
rules.md 4.5 forbids by default, so remote images are blocked, the
host is named, and loading them is a per-request choice.

**A test asserting "the page mentions the query" is not a test of
shared rendering.** I replaced the hit headline with the literal
string `"result"` and the suite stayed green, because the query words
also appear in the detail line and the snippet. #297 taught this for
two front ends and I rebuilt the same weakness for the third. The test
now compares whole headline lines against `kennis search`'s output,
and the injection is caught.

**Two type errors that were worth fixing rather than silencing.**
markdown-it's render-rule signature is untyped, and `-> Any` violates
ANN401; writing the five-argument signature out as a PEP 695 alias is
better anyway, because a rule with a wrong argument order is exactly
what survives review. And `Token.attrGet` is typed as returning a
number too, which is true of attributes in general and not of `src`.

**Searching needed the MCP server's private helpers**, which the
interface may not import. Moved to `kennis/retrieval.py` beside
`context.py` - concern #292's situation exactly, and its precedent
made the decision immediate rather than a debate.
