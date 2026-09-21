# Interlude: the engine names things, it does not phrase them

Milestone / step: between milestones 4 and 5. `design/concerns.md` #81, #23.
Date: 2026-09-21

Previous sketch: `2026-09-21-m4d-history-and-restore.md`, which finished
milestone 4. What it left: an engine that is structurally separate from every
front end, and that hands each of them finished English.

## What I am about to do

Brian asked whether the engine needs more abstraction so the command line is
not stuck with output shaped for another front end. The structural answer is
that it already is - the first invariant forbids the engine importing any
interface library, and a test enforces it. The real leak runs the other way:
**the engine composes sentences out of facts it already carries as fields.**

```python
OutOfBandChange(
    path=path,
    kind="deleted",
    owner=owner,
    document_id=identifier,
    message=f"'{path}' was deleted outside kennis and has been restored",
    resolution="kennis corpus remove",
)
```

Every word of that sentence is a field beside it. The sentence is redundant,
and it is what a front end will reach for because it is easiest - so the
abstraction stays real on paper and is bypassed in practice. The command line
then cannot put the path in its own theme role, cannot wrap it for a narrow
terminal, and cannot collapse three restorations into one line, because it
holds three finished sentences rather than three facts.

Milestone 5 is when these sentences are read for the first time. This is the
last moment before a front end is written against them.

## How I expect it to work

### Three layers, not two

```
engine/    facts        typed values, typed events, domain errors
render/    words        sentences built from those values. No rich, no click.
cli/       layout       colour, alignment, progress bars, terminal width
```

`render/` is new and is deliberately **not** under `cli/`. The MCP server in
0.2 needs the same wording and must not import a command-line package to get
it; putting the words in `cli/` would make the second front end downstream of
the first, which is the exact failure Brian asked about, arriving by a
different route.

The dependency direction is `cli -> render -> engine`, never back. Two new
architecture tests: `render/` imports no interface library, and `engine/`
imports nothing from `render/`.

`cli/theme.py` already holds library-neutral `Role` values, and on this
split it belongs in `render/` with them. Moving it is part of the work.

### The rule, stated so it can be applied

**Where a value already carries the facts as fields, it must not also carry a
sentence built from them.**

That is narrower than "no strings in the engine", and the narrowness is the
point - three kinds of string are staying:

- **`resolution`, where it is a command.** `"kennis corpus remove"` is data
  that happens to be readable. What is *not* staying is a resolution that is
  itself prose: `"kennis corpus restore X to discard the edit, or kennis
  corpus claim X to keep it"` becomes two command strings and lets the
  renderer join them.
- **`KennisError` messages.** An exception's message is its Python
  interface, a traceback has to read on its own, and they are already one
  line.
- **Text kennis is quoting rather than composing** - a converter's output,
  git's stderr, pydantic's complaint. The engine did not write those words
  and cannot structure them. They stay, and the field says so.

### What changes

| value | now | after |
|---|---|---|
| `OutOfBandChange` | `message`, prose `resolution` | drop `message`; `remedies: tuple[str, ...]` of commands |
| `Freshness` | `reason: str \| None` | `unverifiable: Unverifiable \| None`, an enum |
| `AddOutcome` | `reason: str \| None` doing two jobs | `reason: Reason \| None` for composed cases, `detail: str \| None` for quoted text |
| `DocumentFacts` | `problem` prefixed with the path | `problem` is the quoted complaint; the path is already `md_path` |

The last one is concern #23, which I recorded in milestone 2 as a local wart.
It is the same shape as the other three, and reading them together is what
showed that.

### What is deliberately not changing

**`Diagnostic.message` stays prose.** It is the event stream's general escape
hatch, emitted from a dozen places for a dozen reasons, and constraining it
would mean enumerating every diagnostic kennis will ever produce - a bigger
design decision than this one, and one that should be made when there are
enough of them to see the shape. Recording the exception so it is a decision
rather than an oversight.

`PaperText.reason` likewise: it accumulates what each arXiv source answered,
which is quoting rather than composing.

## What I expect to be uncertain or difficult

- **Every changed field has tests asserting on its wording.** About a dozen.
  They should become assertions on the *facts*, with the wording asserted
  once in the renderer's own tests - which is the shape I want anyway.
- **`AddOutcome.reason` is doing two jobs** and I am not certain the split is
  clean. "This paper is already in this collection" is composed; "MinerU
  produced nothing for page 3" is quoted. If the enum grows past a handful,
  the split is wrong.
- **Whether `render/` should know about collections.** Phrasing "3 added to
  literature" needs to know what a collection is. That is fine - it renders
  engine values and may import engine types - but it is the boundary most
  likely to erode.
- **Moving `theme.py` will touch the milestone 0 display port**, which is the
  one piece I was asked not to re-litigate. Moving a file is not
  re-litigating its decisions, but I want to move it without editing it.

## What actually happened that I did not expect

**The architecture test I wrote for `render/` failed on the module I moved
into it, and it was right.** `theme.py` has claimed since milestone 0 to name
no library. It holds the `Role` table, which genuinely does not - beside
`rich_theme()`, which imports `rich.style` and `rich.theme`. The claim was in
the docstring and false the whole time, and it could not matter until
something other than the command line needed the neutral half. The decision
was right and the packaging was wrong. Concern #82, and the shape worth
keeping: **a module is only as neutral as its imports, and a docstring
claiming neutrality is not a test.**

I had written in this sketch that I wanted to move `theme.py` without editing
it, because milestone 0's colour decisions are not mine to re-litigate. That
held: the split is at the import boundary, and not one colour or role changed.

**Three of my fifteen renderer tests failed for asserting exact wording.**
`"2 changed"` against "2 documents changed", `"elsewhere"` against "somewhere
else". The renderer was right every time. Rewriting them to assert that the
facts appear and that distinctions are preserved - a restored deletion must
read differently from an unrestorable one - is the shape a test over words
should have had from the start. Pinned phrasing makes every wording
improvement a test failure, which is how a codebase acquires wording nobody
dares touch. Concern #83.

**Stripping the prose made the engine tests better, not just different.**
`assert "corpus add" in change.resolution` became
`assert change.kind == "created"`. The first was checking the engine's
wording; the second checks what it decided. Five tests changed and every one
of them now says something about behaviour rather than about a string.

**The scope held, which I had doubted.** I expected `AddOutcome.reason` to
force a messy enum-versus-opaque split. It did not come up, because the two
values I stripped were the ones where every fact was already a field, and
`AddOutcome` is genuinely carrying quoted text some of the time. It stays on
the list for milestone 5 rather than being forced now.

**`Diagnostic` is the hole in the rule and I could not close it.** It is the
event stream's escape hatch, emitted from a dozen places, and constraining it
means enumerating every diagnostic kennis will produce. Concern #84 records
it as accepted - and notes that it is the exception most likely to erode the
others, because a call site that finds structuring awkward can always reach
for a `Diagnostic` instead.
