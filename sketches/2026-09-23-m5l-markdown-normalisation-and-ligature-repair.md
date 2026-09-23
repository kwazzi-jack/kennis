# Milestone 5, out of band: what is stored is markdown, and ligature damage is repaired

Milestone / step: Brian on concerns #151-#154 - "I think the html tags are a
problem in general with mineru so something to address for it. Then, lets
implement that for now with the pypdfium2 vocab correction."
Date: 2026-09-23

Previous sketch: `2026-09-23-m5k-conversion-mode-and-cost.md`.

## What I am about to do

Two passes over a converter's output, both in the engine, both before the
markdown is written to the corpus.

1. **Normalise the markdown.** MinerU stores tables as raw HTML - 15% of the
   MNRAS paper's stored characters are tag characters, 2722 `<td>` alone.
   BM25 indexes `td` and `tr`; the dense leg embeds them; chunking splits a
   table mid-row. Convert `<table>` to pipe rows, and `<sup>`/`<sub>` to `^`
   and `_`.
2. **Repair ligature damage** against the PDF's own text layer, read with
   pypdfium2, using the two constraints #151 and #152 established.

Measured tag counts, both papers, both converters:

| | mineru p1 | mineru p2 | datalab p1 | datalab p2 |
|---|---|---|---|---|
| `table`/`tr`/`td` | 0 | 2986 | 0 | 0 |
| `sup`/`sub` | 72 | 146 | 18 | 166 |

So tables are a MinerU defect and `sup`/`sub` is a shared convention.
Normalisation therefore applies to **both** backends - what is stored should
be markdown regardless of who produced it - while the ligature repair is
MinerU-only, because Datalab showed zero damage on both papers and the pass
can only cost there.

## How I expect it to work

### Normalisation: `engine/corpus/markdown.py`

`normalise_markdown(text: str) -> str`, called by both converters on their
own output before building the `ConversionBatch`.

- `<table><tr><td>a</td><td>b</td></tr>...</table>` becomes a pipe table. The
  first row becomes the header and gets the `---` separator beneath it,
  because a markdown table without one is not a table and renders as a run of
  text with pipes in it.
- A cell's own content is escaped where it contains a pipe, and newlines
  inside a cell become spaces, since a pipe row cannot contain either.
- `<sup>2</sup>` becomes `^2`, `<sub>i</sub>` becomes `_i`.
- Fenced code, inline code and `$`-delimited maths are left alone, by the
  same protected-span approach the experiment used.

### Repair: `engine/corpus/ligatures.py`

Two functions, so the expensive one is callable without the cheap one.

    text_layer_vocabulary(pdf: Path) -> frozenset[str]
    repair_ligatures(text: str, vocabulary: frozenset[str]) -> tuple[str, int]

The vocabulary streams page by page and keeps only the word set, and joins
across the line-break glyph (U+FFFE here, U+00AD and U+FFFD elsewhere,
plus a hyphen before a newline) so that `numerical` does not enter as
`numer` + `ical`. Without that join, 4.5% of correct words look absent and
become repair targets - #152.

A token is repaired only when **all** of these hold:

1. It is four characters or longer.
2. It is not inside a protected span.
3. It is absent from the vocabulary.
4. Exactly one candidate is reachable by inserting one character that is
   `f`, `i` or `l` **and lands beside its own twin**.

Condition 4 is the whole safety argument. It is not spelling correction; it
is a statement about what the defect is - a ligature glyph resolving to one
character instead of two - so the pass only ever changes a word that looks
exactly like that damage. `column` -> `columns` is not that shape and is
refused, which matters because the reference is 4.5% blind and cannot be
trusted merely to be silent.

### Where they are called, and what is reported

`MineruConverter.convert` normalises, then repairs when the setting allows
and the source is a PDF. `DatalabConverter.convert` normalises only.

`ConversionBatch` gains `repairs: dict[Path, int]`, per document, because a
repair count is a direct per-document measure of converter quality - the
number that would have said something about #135 on the day it was
introduced. It travels to `AddReport` and the command line the way
`cost_cents` already does.

### The setting

`conversion.repair_ligatures: bool = True`. Its description has to say that
it applies to mineru only, for the same reason `conversion.mode` says it
applies to datalab only: a setting that silently does nothing is a promise.

## What I expect to be uncertain or difficult

1. **Nested or irregular HTML tables.** A `rowspan`, a `<th>`, a table with
   rows of differing length. A pipe table has one shape; MinerU's HTML may
   not. Ragged rows are the case I expect to get wrong.
2. **The control must become a permanent test.** #151's whole lesson was
   that testing on damaged input only would have shipped a corrupting pass.
   The test that matters asserts the repair is a **no-op on clean text**, and
   it needs a fixture that is genuinely clean.
3. **Getting the PDF into the repair.** `convert` takes paths, so the source
   is in hand - but the repair happens after MinerU has written markdown to a
   temporary directory, and I need to be sure the path I read the vocabulary
   from is the original document and not a staged copy.
4. **Cost of the vocabulary on a batch.** One pypdfium2 pass per document,
   0.7 ms/page. Negligible, but it must not be built once per token.

## What actually happened that I did not expect

### The suite was green and the command was wrong

`kennis corpus add` on the MNRAS paper put **1270 `<td>` into the corpus**
with all 1374 tests passing. The cause is a design flaw in the protection,
not a missing branch: one table had `$F _ { \mathrm { m e d } }$` in a
heading cell, and protecting maths by *splitting the text at it* put the
`<table>` and its `</table>` into different fragments, so the table regex
matched neither.

Every fixture I wrote had a table or some maths, never maths inside a table.
The fix is two protection sets rather than one - tables are protected from
code only, scripts from code and maths - because maths belongs inside cells
and a table never belongs inside maths. That asymmetry is the whole content
of the bug and it is now a comment in the module.

This is the fifth time in this project that running the command found what
the suite did not.

### The two constraints are interlocking, so the control could not test either

Two injections came back MISSED: removing the doubling check, and widening
the alphabet. Both should have been caught by the control, and neither was -
because each is individually harmless. With the alphabet still `fil`,
dropping the doubling check cannot reach `columns`, since `s` is never
tried. With the doubling check still in place, widening the alphabet cannot
reach it either, since `column` has no `s` to double against.

Only *both* corrupt. The control tests the conjunction and says nothing about
either conjunct, which is a gap I would not have found by reading it. Two
tests added that isolate them: `behal` -> `behalf` is a ligature letter that
does not double, and `sucess` -> `success` doubles a letter that has no
ligature. The second is the more interesting of the two, because the repair
it refuses is *correct English* - and accepting it is exactly how the
unconstrained rule turned `untargeted` into `untargetted`.

### One of my injections lied about what it did

The compound injection labelled "both constraints gone at once" widened the
alphabet and then defined an unused function. It changed nothing about the
doubling check, reported MISSED, and I nearly recorded that as a test gap.
Rule #66 is about a string replacement that matches nothing; this is the
neighbouring failure - a replacement that matched and did something other
than its label. The label has to be checked against the diff, not trusted.

### U+FFFE is a text-run boundary, not a hyphenation glyph

I described it as "this PDF's hyphenation glyph". Building a two-line test
fixture with reportlab showed pypdfium2 inserting U+FFFE between two separate
`drawString` calls on different lines with no hyphenation involved. It marks
where one text run ends and the next begins, which is *where* a hyphenated
break lands but is not the same thing. That explains 227 of them in a
19-page paper better than hyphenation does, and it makes the fixture easy.

The comment in the module now says this. It does not change the behaviour:
joining across run boundaries is still what recovers `numerical`.

### The three uncertainties

1. **Ragged tables were the case I got wrong first**, as predicted, and
   padding to the widest row fixed it. `<th>` needed only widening the cell
   pattern to `<t[dh]>`.
2. **The control is a permanent test now**, and it is the one that would have
   stopped the corrupting version. It needed reinforcing by the two isolating
   tests above.
3. **The original path was in hand.** `_collect` keys markdown by the caller's
   path, not the staged copy, so the vocabulary is read from the real
   document.
4. **One vocabulary per document**, built in `_repair` outside the token
   loop.

### What it does on real documents

    Added 1 document, 77 ligatures repaired in 36.1s    (arXiv paper)
    Added 1 document in 38.9s                            (MNRAS paper)

77 matches the experiment exactly. The MNRAS paper has no ligature damage and
the phrase is absent rather than zero. Its stored markdown went from 93785
characters to 85443 - 8342 characters of HTML tag removed, and 132 pipe rows
where 1270 `<td>` used to be.

### The ASCII check earned its place

I wrote the literal U+FFFE, U+00AD and U+FFFD codepoints into a regex instead
of their escapes, and `test_source_file_is_ascii` failed on exactly that
line. The file now holds the six ASCII characters `\ufffe` and Python decodes
them at parse time, which is what was meant.
