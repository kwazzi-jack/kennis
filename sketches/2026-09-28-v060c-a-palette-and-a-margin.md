# v0.6c: a palette for the browser, and a margin for what kennis knows

2026-09-28

## 1. What I am about to do

The interface has no visual design. Measured before deciding, and the
numbers are the argument:

- the generated stylesheet holds **two** layout rules beyond the role
  classes - `body` and `main`;
- **17 of the 22** structural classes the templates use have no rule
  at all;
- `warning` renders as `#FFFF00` on white, a contrast ratio of about
  **1.07:1**, and `code_operator` renders as `white` on white.

The last two are defects rather than taste, and they have one cause.
`gui/theme.py` maps each of the nine ANSI colour names the role
registry may use onto a CSS colour *keyword*. In a terminal those
names resolve against whatever palette the user themed their terminal
with, which is exactly why `render/theme.py` restricts itself to
them. In a browser they resolve to the raw sRGB primaries, which
nobody chose.

Two pieces of work, and the second is the one with a point of view:

1. **A palette.** `gui/theme.py` decides what each of the nine names
   looks like in a browser, light and dark. `render/theme.py` goes on
   deciding which role wears which name, so no role's colour is
   declared twice. Decided with Brian on 2026-09-28.
2. **A layout**, described below, and a text face to set it in.

## 2. How I expect it to work

### The palette is a terminal palette, for a browser

This is the honest framing and it settles a lot. The adapter is not
inventing a brand; it is supplying, for one medium, the thing a
terminal's theme supplies for the other. It therefore has the same
obligations a terminal theme has: nine names, hues that stay
distinguishable from one another because roles rely on the difference
(`cyan` is a command, `magenta` an identifier, `yellow` a warning,
`red` an error), and legibility on a light ground and a dark one.

Two of the nine are not hues and are the interesting cases.

**`white` must become the default foreground, not `#FFFFFF`.** In a
terminal `white` *is* the ordinary foreground colour; it is only white
because the background is black. Transliterating it to the literal
colour is what made `code_operator` invisible. The same argument makes
`black` the foreground in light mode and the deepest available in
dark - and it means the light and dark maps are not each other's
inverses by accident but by construction.

**`bright_black` is the muted grey**, which it already was.

Contrast is measured, not asserted: a test computes the WCAG ratio of
every role's colour against the ground it is shown on and refuses
anything under 4.5:1 for text. That is the test that makes this unit
finishable - without it "looks fine to me" is the whole standard.

### The layout: a margin for what kennis knows

The distinctive thing about kennis is not search. It is
**provenance**: every hit states its collection, its document
identifier, its chunk, its relevance band, and the scale that band is
measured on. The engine already enforces a matching rule - words
kennis composed live in `render/`, and text it is quoting is passed
through untouched. The design should show that division rather than
flatten it.

So: a fixed left margin carrying what kennis knows, and a measured
column carrying what the corpus says.

```
+-----------------------------------------------------------------+
| kennis      search   held   remember   manage                    |
+-----------------------------------------------------------------+
|             |                                                    |
|  literature | [1] AstroMLab 2: AstroLLaMA-2-70B Model and        |
|             |     Benchmarking Specialised LLMs for Astronomy    |
|  relevance: |                                                    |
|  low        | V Inference Methodology. To quantify the           |
|  id=nwgsw.. | performance of specialized LLMs for astronomy we   |
|  chunk=20   | employed three distinct benchmarking methods.      |
|             |                                                    |
+-----------------------------------------------------------------+
     ^ monospace, muted,        ^ serif, measure under 70 characters
       right-aligned to the
       column's left edge
```

The rule, stated so it can be broken deliberately rather than by
drift: **if kennis composed it, it goes in the margin; if kennis is
quoting it, it goes in the column.** The margin is the terminal's
gutter, kept rather than disguised, and it is where the boldness of
this design is spent. Everything else stays quiet.

Type carries the same division: a monospace in the margin, because
that is genuinely what kennis's own output is, and a text face in the
column. One vendored face - Source Serif 4, drawn for reading on
screen, with a real italic rather than a slanted roman, and
proportions close enough to KaTeX's Computer Modern that an equation
does not jump out of its paragraph. The margin uses a system
monospace stack: short labels tolerate the variation between machines
that body prose does not, and vendoring a second family would double
the asset count for the half of the page that is least sensitive to
it.

### Three things the screenshots found

Running the interface under Playwright showed three defects that
reading the source did not.

**The document title is rendered twice** - once as the page heading
from the frontmatter, and once as the document's own `#` heading
below it. The frontmatter title is the one to keep, because the
document's own heading is text kennis is quoting.

**The rank is stated twice** - the `<ol>` marker prints "1." beside
the headline's own "[1]". The headline comes from
`render/hits.py::rendered_hit`, which is byte-identical across front
ends by design (#297), so the `[1]` is untouchable. The list keeps
its semantics and loses its marker.

**The relevance scale is dropped.** `kennis search` prints
"Literature relevance by cosine similarity" above each group, and the
window prints no group heading at all - so a reader sees "low" five
times with nothing saying what low is relative to. `relevance_phrase`
already composes the sentence and `Hit.basis` already carries the
answer. Principle: relevance is never shown without its scale.

### A rule that does not cross the medium boundary

A hit snippet in the window shows raw markdown: `## V Inference
Methodology`, `###### Index Terms:`, `[[35](https://...)]`.

That is `render/theme.py`'s rule working as written - markdown
markers are "styled where they stand and never consumed, because the
terminal shows the same characters the corpus holds and an agent
would read". Sound for a terminal. In a browser it produces literal
hashes and no styling, because the window has no styling layer over
plain text the way a terminal does.

The snippet is a place where the window renders rather than quotes.
This is a divergence between front ends and gets a concern rather
than a silent fix.

## 3. What I expect to be uncertain or difficult

**Choosing nine colours that are distinguishable *and* legible in
both modes.** Contrast against the ground is the easy half and a test
can enforce it. Keeping the hues apart from one another is the half
with no test I trust: `red` and `magenta` darkened far enough to pass
on white start to converge, and so do `green` and `cyan`. I expect to
measure the pairwise distances and find at least one pair too close.

**Whether `main`'s measure can shrink without stranding the tables.**
The holdings table and the job panel want width; body prose wants
under 70 characters. One container cannot do both, so either the
column is per-page or the tables sit outside it.

**The vendored font and the ASCII rule.** `woff2` is binary and the
existing KaTeX fonts already pass the checker, so I expect no
trouble - but #313 says an exemption that excludes nothing reads as
licence, and I should confirm the checker genuinely handles these
rather than assume the KaTeX ones were never tested.

**Testing a layout at all.** A stylesheet is not a value a test can
compare. What is testable: every class the templates use has a rule,
every role's contrast passes, the ground is declared, the dark block
exists, and no colour literal appears outside the adapter. What is
not testable is whether it looks right, which is what the screenshots
are for.

**The `role-command` overload.** It marks both a real link and text
that is only a command to copy, so a reader cannot tell which is
clickable. Colouring them the same was defensible when nothing had
affordances; with a palette it becomes a wrong statement.

## 4. What actually happened that I did not expect

**The hues did not collide, and I had predicted they would.**
Section 3 expected at least one pair of the six to be too close once
they were all darkened far enough to pass on white. Measured, the
closest pair is `blue`/`magenta` at dE 36.8 on light and
`blue`/`cyan` at 31.8 on dark, with the worst contrast 4.82:1. The
prediction was wrong in the useful direction, and only because I
wrote the measurement before choosing the values rather than after.

**Screenshots changed the work more than the stylesheet did.** Three
of the defects fixed in this unit were invisible in the source and
obvious in a picture: the title rendered twice, the rank stated
twice, and the relevance scale missing entirely. A fourth appeared
only after the first pass - the row gap put the same 1.75rem between
a headline and its own snippet as between the margin and the column,
so a hit read as two unrelated things. Reading the CSS I had just
written did not show it; the picture did immediately.

**The licence check landed exactly on #313, and did not need an
exemption.** Adobe's `LICENSE.md` writes a curly quote in "Reserved
Font Name", so vendoring it stopped the commit - which is precisely
the outcome #313 designed for, since it makes carrying the file a
decision. The decision turned out to be easy and not a rule change:
the binaries came from Google Fonts, and the licence Google Fonts
distributes with them is the canonical OFL text with an ASCII
copyright line. Concern #335. It also showed that KaTeX's MIT
licence had never been vendored at all, which is a condition on
distributing kennis rather than a formality, so the notice and two
licence files exist now.

**One test was hollow and the probe that found it was not the
harness.** `test_every_vendored_asset_is_accounted_for` asked
whether the family name appeared anywhere in the notice. Two string
injections failed to catch anything, and both were *inert* rather
than revealing - the notice names each family in its URL and its
licence filename as well as its heading, so removing one mention
left the others. Simulating the realistic failure instead - copying
a font in under a new name - showed the test was hollow: it passed
for an undocumented `Inter-Regular.woff2`, because `Inter` is inside
the word "interface" in the notice's first sentence.

That is worth keeping as a shape. **A substring test against prose
will match a short name by accident**, and the shorter the name the
likelier it is. The replacement compares against the filenames the
notice declares, treating an entry with a `*` as a glob, and a
second test asserts the other direction - that nothing is declared
which is no longer there - because a stale entry rots quietly.
Concern #337.

**The injection that mattered least was the one I could not write.**
Adding a file is not a string replacement, and the harness only does
replacements. The check that found the hollow test was three shell
commands run by hand. Worth remembering before trusting a harness's
count: it verifies the injections someone thought to express in it.

**What I did not fix, and it is the most visible thing left.** A hit
snippet still shows raw markdown - `## V Inference Methodology`,
`###### Index Terms:`. Rendering it would change the snippet's text,
and `render/hits.py::rendered_hit` is byte-identical across front
ends by design, which is what makes `kennis search` a faithful proxy
for what an agent sees (#297). Whether a third front end may render
what the other two quote is a decision about that invariant, not a
styling fix. Concern #336.
