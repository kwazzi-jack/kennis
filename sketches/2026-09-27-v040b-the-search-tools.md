# v0.4 unit 8b: four search tools, and the hit text both front ends share

Date: 2026-09-27

## 1. What I am about to do

`search_notes`, `search_literature`, `search_docs`, `search_context`.

The engine is already there and so is most of the rendering. The work is
almost entirely **moving the hit composition out of `cli/`**, because
design section 20 names exactly one deliberate exception to "each front
end renders for itself":

> Search hits and document spans are rendered by `tools/_retrieval` and
> shared byte-for-byte between the CLI and MCP, so a hit printed by
> `kennis search` and one returned by `search_literature` are the same
> bytes, one wearing ANSI. [...] it is load-bearing, because the
> byte-identical property is what makes CLI output a faithful proxy for
> what an agent sees.

Today that composition is private to `cli/commands/search.py`: `_Hit`,
`_hit_detail`, `_basis_phrase`, `_best_lexical`, `_summary`, `_around`
and `_score_style`. A second front end cannot reach any of it.

## 2. How I expect it to work

**`render/hits.py` gains the composition**, and the command line keeps
only layout.

| moves | becomes | why it is not layout |
|---|---|---|
| `_Hit` | `Hit` | which collection and which scale, not how to draw it |
| `_hit_detail` | `hit_detail` | the relevance phrase and the handle |
| `_basis_phrase` | `basis_phrase` | what a band is a band *of* |
| `_best_lexical` | `best_lexical` | the denominator of a lexical band |
| `_summary` | `summary_of` | "5 in docs, 2 in notes" |
| `_around` | `around` | the `--chunks` range a hint prints |

`_score_style` splits, because it does two things: it decides whether a
band can be produced, and it prints a note when it cannot. The decision
moves as `score_style_for(hits, asked) -> tuple[ScoreStyle, bool]`,
where the second value is "it degraded"; the sentence stays in the
command line.

**One new shared function is the whole point of the unit:**

```
rendered_hit(hit, *, rank, style, best, snippet) -> RenderedHit
    headline: str     what `hit_headline` already returns
    detail: str       what `hit_detail` returns
    body: str | None  the snippet, or None when none was asked for
```

Three parts rather than one string, because the command line styles each
differently and indents the body, while the server joins them. **The
text is identical and only the wrapping differs**, which is what "the
same bytes, one wearing ANSI" has to mean in practice.

The test is that property directly: run `kennis search` through the
runner, strip ANSI, call the tool on the same corpus, and assert each
hit's three lines appear in both.

**The tools.** One module, `mcp/tools/search.py`, four thin functions
over a shared `_searched(collection, question, ...)`. Each names one
collection, so a missing index is an error rather than a skipped scope -
the opposite of the command line's sweep, and right for a tool: an agent
told "no hits" for an index that was never built has been told something
false.

`search_context` differs, as section 11 says: it returns **file
locations**, because a bundle lives in the user's repository and the
agent has native file tools. So it renders the bundle handle and no
snippet.

## 3. What I expect to be uncertain or difficult

- Whether `RenderedHit` is the right seam, or whether the command line
  will turn out to need the parts in an order the server does not. I
  think three fields is the honest shape and one joined string would be
  the lie, but I will know when the CLI is rewritten against it.
- The byte-identity test needs the same corpus, the same index and the
  same query through two paths. Building that fixture is most of the
  work and I expect the embedding stub to be the awkward part.
- `search_context` outside a project. The command line has a whole
  vocabulary for scopes that were skipped; a tool has one caller and
  should just say there is no bundle here.
- Whether four near-identical tools should be four functions or one
  with a `collection` argument. Four, I think - the tool name is what an
  agent selects on and a docstring per collection is what tells it which
  to reach for - but it is duplication and I want to see it before
  committing to it.

## 4. What actually happened that I did not expect

**The byte-identity test was too weak, and an injection showed it.** I
extracted the tool's handle line and asserted it appeared *in* the
command line's output. But the command line prints `relevance: very
high  id=x chunk=0` and a tool that dropped the band would print `id=x
chunk=0` - a substring of it. Injecting exactly that passed. The test
now compares **whole lines for equality**, with only leading
indentation stripped, because indentation is the one thing the two
front ends are allowed to differ on. All five injections are caught
now, including the one that was missed.

**`RenderedHit` with three fields was the right seam**, which I was not
sure of in section 3. The command line styles each part and indents the
body; the server joins them with two spaces. Neither had to bend, and
the one joined string I was tempted by would have forced the command
line to accept the server's layout.

**The extraction was larger than "move six functions".** `_score_style`
turned out to do two things - decide whether a band can be produced,
and print a note saying it could not - so it split, with
`score_style_for` returning the decision and a `degraded` flag and the
sentence staying in the command line. And routing the command line
through `rendered_hit` rather than calling the parts separately was a
second step I nearly skipped: sharing the pieces would have let the two
front ends assemble them differently, which is exactly the drift the
rule exists to prevent.

**`ruff --fix` deleted an import I was about to use.** I added
`rendered_hit` to the import block before the code that calls it, ran
`ruff check --fix`, and it pruned the unused name - then 38 tests failed
on `NameError`. Ordering, not a defect, but worth remembering: add the
call first, the import second.

**An injected file could not be restored with `git checkout`**, because
`mcp/tools/search.py` is new in this unit and untracked. The injection
stayed in the working tree and the next run failed. The restore
assertion caught it immediately, which is the only reason it was one
command's delay rather than something I committed.

**Four tools rather than one with an argument was right**, and reading
the generated tool list settled it: an agent selects on the tool name
and reads its docstring, so "which collection" belongs in the name, not
in a parameter description read last.

**One wart noticed and left alone.** A hit headline reads `[1]
calibration - Calibration`, because `hit_headline` suppresses the
section only when it is exactly equal to the title and here they differ
by case. Pre-existing, shared by both front ends now, and logged as a
concern rather than fixed inside a unit that is about something else.
