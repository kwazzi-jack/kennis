# A listing is not a detail

Milestone / step: v0.1.1, concerns #216 and #217
Date: 2026-09-25

## What I am about to do

Brian asked, before the release, whether anything else in the command line
would be better for colour, and whether `config init` is nicely formatted.
Running every read-only command and looking at the escape codes found two
defects rather than a wish list, and they are unrelated to each other.

**One: `display.heading()` prints with no style at all.** Not "the wrong
style" - none. `Role(bold=True)` is declared for it and never reaches the
terminal.

**Two: three commands whose entire output is a listing print that listing in
the styling meant for a footnote**, so `corpus list` dims the identifiers
that `corpus tree` and `search` both give full weight.

## How I expect it to work

### The heading

`display.heading(text)` is called with no `lead`, so `_line` takes its
`lead is None` branch and applies `heading.line` rather than `heading`. The
`.line` variant exists for a good reason - a whole sentence in bold colour
shouts, so the quiet variant drops the bold and keeps the colour - and it is
built by `Role.quiet()`, which is `replace(self, bold=False)`.

For the other four sentence roles something survives that:

    operation  bold green  -> green
    warning    bold yellow -> yellow
    error      bold red    -> red
    muted      dim         -> dim
    heading    bold        -> nothing at all

`heading` is the only one whose entire definition is the attribute `quiet`
removes. The fix is to the role, not to `quiet`: a heading that is a line of
its own is not competing with a sentence beside it, so it can carry a colour
the way a collection name does. `Role(colour="cyan", bold=True)` makes the
quiet variant cyan and leaves the full variant available for a lead.

Its one caller is `config init`'s section headings, which is why the wizard
currently shows `Embedding`, `Conversion`, `Retrieval` as undifferentiated
plain text in the middle of dim descriptions.

### The listing

`display.detail(marker, text)` is documented as "one item an operation
touched", and its design is deliberate: the marker carries the colour and
the name stays dim, because ten added paths should not shout as loudly as
the `Added` line they belong to. That is right for `corpus add`.

Four callers pass `" "` as the marker. Three of them are not reporting what
an operation touched - the listing *is* the command:

    corpus list      every document
    corpus history   every commit
    config get       every setting, when no key is given

For those the design inverts. The marker column is blank, so it carries no
information and still prints a bold space; and the content, which is the
whole point of the command, is dimmed. The visible consequence is that one
identifier has three appearances: bold magenta in `corpus tree`, magenta in
a `search` hit, flat dim in `corpus list`.

So `display` gets `row(identifier, text)`: no marker column, the identifier
at full weight in the `identifier` role, the rest muted. `corpus list` and
`corpus history` use it, with the commit hash as the identifier - it is what
gets pasted into `corpus restore`.

`config get` has no identifier column; its rows are `key = value`, which is
the shape `config show` already prints and already highlights. It gets
`setting_row`, styled with the same `TomlHighlighter`, so the two commands
that show settings stop disagreeing about what a number looks like.

The fourth caller, `credentials written to ...` in `config init`, stays a
`detail` - it really is a footnote to an operation.

## What I expect to be uncertain or difficult

Whether `heading` should gain a colour or whether `_line` should stop
quietening a lead-less heading. The second is more local but wrong: it would
make a heading bold and every other lead-less sentence quiet, which is a
special case in the renderer rather than a fact about the role.

Whether the commit message in `corpus history` deserves more than one
colour. It is a conventional-commit line, so `index(corpus):` could be split
from its subject. I expect that to be one distinction too many on a line
that already has a hash and a date, and to leave it.

Whether any test asserts on the current dim listing and will need changing
rather than fixing - if one does, it pinned a defect, and the entry it came
from is worth finding.

## What actually happened that I did not expect


**The fix was to `quiet()`, not to the role.** The sketch offered two
options - give `heading` a colour, or stop quietening a lead-less heading -
and took the first. It was wrong. `heading` is also what `tree_group` wears,
so colouring the role would have recoloured every group line in `corpus
tree`, a design Brian had reviewed two days earlier, as a side effect of
fixing something else.

The third option is better than either and was not in the sketch:

    quietened = replace(self, bold=False)
    if quietened.rich_style() == "none":
        return self
    return quietened

"Quietening lowers a voice; it does not remove one." That is a rule about
what the operation means rather than a special case about which role it is
applied to, it fixes any future bold-only role for free, and it changes
nothing that was already visible. Asked of `rich_style()` rather than field
by field so that a role gaining an `italic` later cannot slip past it.

**The existing test asserted the wrong half.** There already was a test over
every sentence role - `theme.styles[f"{name}.line"].bold is not True`. It
checked that the bold had been *removed* and never that anything remained,
so it passed for a role that had been quietened into nothing. The property
that was meant is one line: `ROLES[name].quiet().rich_style() != "none"`.
The same shape as #66 - an assertion that cannot distinguish the case it
exists for.

**`toml_key` was anchored to the margin and had never matched an indent.**
`^(?P<toml_key>[\w.-]+)` only ever fired for a key at column zero. That was
invisible while `config show` was its only caller, because in a template
every key sits behind a `# ` and none of them matched anyway. Putting a
`config get` row two spaces in made the gap obvious. Fixing it to `^\s*`
also lights up the keys of a real uncommented `config.toml`, which had been
plain since milestone 1.

**Highlighter spans stack, so an exclusion has to be written as one.**
`(unset)` came out dim *yellow*: the generic value pattern matched it and
contributed its colour underneath the dim laid over it. rich does not
replace a span, it adds one. The negative lookahead in `_SETTING_VALUE` is
what makes the value pattern not match in the first place.

**What `config init` needed turned out not to be colour.** The question was
whether the wizard is nicely formatted, and the answer was that its section
headings were the one thing in kennis printing with no style at all - a bug
rather than a matter of taste. The rest of it reads correctly: descriptions
dim, constraints at normal weight because they are what you need in order to
answer, and the prompt line itself left to `click.prompt`, which cannot be
styled.

Seven injections, all caught, no surprises among them.
