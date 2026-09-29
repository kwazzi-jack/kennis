# v0.6g: a snippet that reads, and highlighting that shows

2026-09-29

## 1. What I am about to do

Brian, answering concern #336 and asking for two more things at once.
Three pieces, and each is a case of work already being done and
thrown away.

**A hit snippet shows raw markdown.** `## V Inference Methodology`,
`###### Index Terms:`, `[[35](https://...)]`. That is #336, open
since 2026-09-28 and recorded as needing a decision rather than a
fix. The decision is taken: render it.

**Code is highlighted and the highlighting is invisible.** Measured:
`render/html.py` runs pygments on every fenced block with a declared
language and emits `<span class="k">`, `<span class="nf">` and the
rest. `gui/theme.py` has **no rule for any of them**. So every
document with code pays for a parse and a highlight and renders one
flat colour.

**Nothing says where the query matched.** A snippet is four lines of
prose and the reader has to find the words they typed in it.

## 2. How I expect it to work

### The code roles already exist, and are already the answer

`render/theme.py` names seven: `code_block`, `code_keyword`,
`code_string`, `code_number`, `code_comment`, `code_name`,
`code_operator`. The terminal uses them. `css_variables` already
emits `--role-code_keyword: #8A3382` and the rest.

So this is not a palette decision, it is a mapping: pygments' token
abbreviations onto the seven names. `k`, `kd`, `kn`, `kr` are a
keyword; `s`, `s1`, `s2`, `sb` are a string; `nf`, `nc`, `nb`, `bp`
are a name. No colour is chosen here, which is the invariant working
as written - `render/theme.py` decides which role wears which name
and `gui/theme.py` decides what the name looks like.

**One of the seven has no colour to emit.** `code_comment` is
`Role(dim=True)` with no `colour`, so the adapter produced
`--role-code_comment: inherit` and a comment renders as body text.
Dim is a terminal attribute and a browser has none, so the adapter
has to translate rather than transliterate - the same argument that
made `white` the foreground rather than `#FFFFFF`. A comment becomes
the muted grey.

**The test is the one that would have caught this in the first
place**: highlight a sample in several languages, collect every class
pygments actually emitted, and assert each has a rule. A mapping
written by reading pygments' documentation would miss whatever that
documentation does not mention.

### The snippet is prose, not a document

The obvious move - run `to_html` on the snippet - is wrong, and
seeing why decides the shape.

`snippet_of` does `" ".join(text.split())` and then truncates. The
block structure is already gone: `## V Inference Methodology` and the
paragraph after it are one line by the time anything could render
them, so a markdown parse would make an `<h2>` of the whole snippet.

So the window builds its own snippet from the chunk's text rather
than from `rendered_hit`'s string. Walk the markdown tokens, keep
what is inline - emphasis, strong, code spans, the *text* of a link -
drop what is block, join the blocks with a space, then truncate at a
word boundary the way `snippet_of` does.

That is #336's second option in spirit and its first in cost: the
window renders, `rendered_hit` goes on returning the plain string
that `cli` and `mcp` print.

**#297 narrows, and the narrowing is testable.** `headline` and
`detail` stay byte-identical across front ends and the existing
whole-line test goes on asserting it. `body` becomes "the same source
text, rendered for its medium", and the new test asserts every word
of the window's snippet appears in the command line's, in order. That
catches content drift, which is what #297 was protecting, without
demanding punctuation equality that the rendering deliberately
removes.

### Marking the query, without touching the markup

The marking must never see a tag. A query of "class" applied to
finished HTML would corrupt `class="basis"`, and a query of "em"
would eat the emphasis. So marking happens on the **text runs** as
the token walk produces them, before any escaping, and the escape and
the `<mark>` are applied after.

The rule, stated so its limits are visible: **whole-word,
case-insensitive occurrences of each whitespace-separated term of two
characters or more.** Two things it deliberately does not do. It does
not stem, so a search for "calibration" will not mark "calibrate" -
the index stems and this does not, and claiming otherwise by
prefix-matching would mark "calibrate" inside "recalibrated" too. And
it does not drop common words: a reader who searched "the" gets
"the" marked, which is the query's doing.

Snippets only. A document already marks the chunk a hit matched, from
v0.6b, and a second kind of mark inside the first is a claim about
two different things wearing one colour.

## 3. What I expect to be uncertain or difficult

**What the token walk does with a link.** `[[35](https://...)]` in
the corpus is a citation. Keeping the link text gives "[35]", which
is right; keeping the URL gives the noise this unit exists to remove.
But a link whose text *is* its URL - a bare autolink - then renders
as nothing useful. I expect to keep the text and find a case where
the text was the only thing worth having.

**Whether a snippet should carry live links at all.** Rendering
`<a href>` inside a hit would put a link to arxiv.org in a list of
search results, and the figure rule says kennis does not fetch on the
reader's behalf. A link is not a fetch until clicked, but it is still
an outbound path from a page that currently has none. I lean to text
without the anchor.

**The truncation and the tags.** Cutting at a word boundary is easy
on a string and awkward once the string is a run of tokens: the cut
can fall inside an emphasis, which then has to be closed. Truncating
the runs before rendering rather than after is the answer, but it
means the limit counts characters the reader sees rather than
characters in the source, so the window's snippet and the command
line's will not end at the same word. That is a visible difference
between front ends and it needs to be deliberate.

**Marking inside a code span.** A query term occurring inside
`` `gains` `` would get a `<mark>` inside a `<code>`. Probably
correct and probably ugly.

**Whether pygments' class set is stable.** The test collects classes
from real output, so it measures rather than assumes - but it
measures the languages I thought to sample, and a corpus document in
a language I did not sample can still emit a class with no rule. A
fallback that inherits is the honest floor.

## 4. What actually happened that I did not expect

**The largest defect in this unit was not one of the three I set out
to fix.** Chasing `code_comment`, which the adapter emitted as
`inherit`, showed that ten roles are dim-without-a-colour and `muted`
is one of them - and that `inherit` on a custom property declared at
`:root` has no parent to inherit from, so it resolves to the
guaranteed-invalid value. `color: var(--role-muted)` then fell back
to the inherited text colour. Measured in a real browser:
`--role-muted` came back *empty* and the nav, the hit margin, the
snippet and the back link all computed to `rgb(26, 28, 31)`, full
ink. Nine uses in the stylesheet, every page, since v0.6c.

The v0.6c unit measured contrast for every role that *had* a colour
and never asked what happened to the ones that did not. Two cases and
one bug: a dim role now becomes the muted grey, because dim is a
terminal attribute a browser has none of, and an uncoloured role
becomes `currentColor`, which is what `inherit` was trying to say.
Concern #351.

**Rendering the snippet could not be rendering the snippet.**
`snippet_of` collapses the whitespace before truncating, so by the
time there is a string, the heading and the paragraph after it are
one line - a markdown parse makes an `<h2>` of both. The structure
has to be read from the chunk's own text, which turned the cheap fix
into a small renderer. Section 2 half-saw this and wrote it down;
what I did not see is that it decides the whole shape.

**Then flattening the blocks created a run-on.** "Methodology To
quantify the performance" - the `##` that marked the boundary is
exactly what this unit removes. A separator would be text the corpus
does not contain, so a heading carries its own weight instead and
adds no characters. Found in a screenshot, after the tests passed.

**A sampling test cannot enumerate what pygments emits.** My first
regex was `[a-z]+`, which misses `s1`, `c1` and every compound class;
YAML's lexer produces `l-Scalar-Plain` and `p-Indicator` for token
types pygments has no short name for. So the mapping is generated
from `STANDARD_TYPES` by climbing each token's ancestry, plus a
prefix selector per root - and the test's coverage check had to learn
both mechanisms, because its first version looked for an exact
selector and reported two classes missing that were not.

**Two injections were not caught, and they failed differently.**

The word-boundary cut was **inert**: each `wordN ` is six characters,
so `text[:60]` landed exactly on a space and `rsplit` removed a
trailing space that the `rstrip` two lines later removed anyway. Both
paths produced the identical string. The fixture made the defect
unobservable, and the test now asserts every word shown is a whole
word of the source, at a limit that falls inside one. Concern #352.

The other was **a real coverage gap** wearing the same clothes.
Turning `without_title` off in `shown_document` changed the browser's
behaviour and nothing failed: `to_html` was tested and its caller was
not. That is the more useful of the two findings and only the
distinction between hollow and inert (#318) separates them.

**The duplicate title was recorded as fixed and never was.** v0.6c's
sketch lists "the title rendered twice" among the defects it fixed.
It is not fixed, nothing tested it, and 44 of the 45 crawled pages in
the corpus show it. A claim in a sketch is not a test, which is #82's
lesson arriving in a new place. Concern #353.

**And the highlighting I fixed does not show on the corpus it was
fixed for.** All 254 fenced blocks in the crawled documentation are
bare - no language declared - so pygments never runs on them. The
feature works; the crawler does not record what a block is written
in. Concern #354, and not fixed here.
