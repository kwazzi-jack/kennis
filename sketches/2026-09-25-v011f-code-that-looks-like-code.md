# Code that looks like code

Milestone / step: v0.1.1, concern #214
Date: 2026-09-25

## What I am about to do

Give `read` and `search` output real syntax highlighting: pygments for a
fenced block that names its language, and a plain code colour for one that
does not.

## How I expect it to work

**No new dependency.** `rich` already requires `pygments (>=2.13,<3)`, so it
is installed and `rich.syntax.Syntax` is available.

**No guessing, and that is measured rather than assumed.** Brian's corpus has
262 fenced blocks and **not one** carries a language tag, so guessing is the
only thing that would highlight any of them. `pygments.lexers.guess_lexer`
over those 262 returns MySQL (55), Text (53), GDScript (29), scdoc (28),
Carbon (23), Transact-SQL (22), Objective-C (21), Tera Term macro (16) and
verilog (11) for content that is plainly YAML and shell. Nothing usable, and
two of the samples are prose the converter fenced. So a block with no
language is coloured as code and not lexed.

**A splitter whose output reassembles.** `render/markdown.py` gets
`split_blocks(text) -> list[Block]` with `kind` in `prose`, `fence`, `code`.
Fence lines are their own blocks rather than being consumed, which keeps the
rule that the terminal shows the characters the corpus holds - and gives the
property worth testing: `"".join(block.text for block in blocks) == text`,
exactly, for any input.

The command line then renders each kind:

    prose  -> the existing BodyHighlighter
    fence  -> the md_fence role, as now
    code   -> Syntax(language, theme=<kennis roles>) when the fence named one,
              otherwise the code_block role with no lexer

**The theme stays inside the eight colours.** `render/theme.py` says only the
eight standard ANSI colours, never a 256-colour index or a hex value, so the
output resolves against the user's own palette. Every pygments style breaks
that. `rich.syntax.ANSISyntaxTheme` takes a `{TokenType: Style}` map instead,
so the token colours are declared in the role table like everything else and
the invariant holds.

Snippets are untouched. `snippet_of` collapses a hit to one paragraph, so
there are no blocks in it to find.

## What I expect to be uncertain or difficult

Whether a whole block in one colour is actually easier to read than a block
in none. The fence lines already delimit it; the colour is there to say
"this is not prose", and twenty lines of cyan YAML may be worse than twenty
lines of plain YAML. I expect to have to look at it against a real page
rather than decide it here.

The second is the round-trip property under the awkward cases: a fence inside
a fence, an unterminated fence at the end of a document, an indented fence,
and `~~~` - all of which appear in real markdown and any of which could make
the splitter drop or duplicate a character.

## What actually happened that I did not expect



**Parsing is not guessing, and it answers for 95 of the 137.** The sketch
treated "no language tag" as the end of the matter, and it is not. Guessing
asks "which lexer scores this text highest", which always answers and was
wrong 262 times out of 262. Parsing asks "is this text a YAML document",
which is decidable: `yaml.compose` either builds a node graph or raises.
Over the corpus's 137 unlabelled code blocks that identifies 95 as YAML and
makes no other claim; the 42 it declines are YAML fragments with undefined
anchors or stimela's `(cultcargo)` key syntax, which are genuinely not YAML
documents. Without this the feature does nothing at all on Brian's corpus -
every block would have taken the one-colour path - so the sketch as written
would have shipped a highlighter that highlights nothing.

The guard that makes it safe is requiring a *nested* value. `Note: this
matters.` on two lines is a valid two-key mapping, and a code fence can hold
prose, so the parse alone is not enough. Requiring one value to be a mapping
or a sequence rejects that and cost nothing measurable: 95 of 137 with the
requirement and 95 without. JSON is tried first, because JSON is a subset of
YAML and the YAML lexer would otherwise be handed a JSON document.

**`rich.syntax.Syntax` pads every line out to the console width.** This is
the same defect that `rich.padding.Padding` had for snippets, found in the
same way and forgotten in between: trailing spaces that are invisible on
screen and land in the file when `read` is redirected. It also emits one
spurious blank line for text ending in a newline. Both make `read` produce a
document the corpus does not hold, which is the one thing it must not do. So
`Syntax` is not used: the token stream from `lexer.get_tokens` is turned into
a `rich.Text` directly, with `stripnl=False, ensurenl=False` - without those
pygments strips leading blank lines and appends a final newline, and the
round trip fails on exactly the blocks that have neither.

Keeping `ANSISyntaxTheme` anyway was worth it for `get_style_for_token`,
which walks the token hierarchy, so `Name.Builtin.Pseudo` finds the style
declared for `Name.Builtin` and the role table stays eight entries long.

**The round trip was the whole feature, not a property of the splitter.**
The sketch put `"".join(block.text) == text` on `split_blocks`, tested it
there, and was satisfied. But the splitter was never where it would break -
`_block` then printed each piece with rich's default `end="\n"`, adding one
newline per block, and the three prose branches used `.rstrip("\n")`, which
removes *all* trailing newlines and so deletes blank lines the document has.
The test that found this asserts against the rendered output, not the blocks:
`capture(lambda: display.body(document)) == document`. Six of its twelve
cases failed the first time it ran. All 49 real documents pass now.

**The uncertainty resolved for, narrowly.** One flat colour does beat none:
the fence markers are `dim` and nearly invisible on some terminals, so an
uncoloured block is not distinguishable from prose, and cyan is already what
inline code spans use. The wrinkle the sketch did not foresee is that a
single document now shows both kinds - green-keyed YAML where it parsed,
flat cyan where it did not - because "did this parse" is not a distinction a
reader can see the reason for. It reads acceptably; it is a taste question
and it is Brian's.

**Nine injections, one initially missed.** Dropping `stripnl=False,
ensurenl=False` was not caught, because every test case had a
declared-language block that both began and ended with a newline. Two cases
were added - a lexed block with leading blank lines, and one with no final
newline - and it is caught. This is the same shape as #63: the property was
tested somewhere that could not fail.
