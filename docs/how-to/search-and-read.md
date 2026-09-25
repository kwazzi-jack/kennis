# Search and read

## Search

```
kennis search "reciprocal rank fusion"
```

A hit looks like this:

```
Found 2 in docs

Docs relevance by cosine similarity
  [1] Recipe variable assignments - Step assignments
      relevance: high  id=yusk5agyfk chunk=3
      ## Step assignments Any step definition can contain an `assign`
      section of its own. Use this if you need to change the value of
      recipe variable just for that one step. ...
```

`id=` and `chunk=` are the coordinates you pass to `read`.

## Scopes: the corpus and this project

`kennis search` looks in two places, and the selector names both:

| scope | what it is |
|---|---|
| `literature`, `docs`, `notes` | the corpus, which is machine-global |
| `context` | this project's `.context/` bundle, found by walking up from where you are |
| `all` | every one of them that has an index - the default |

```
kennis search "query"                             # every scope (the default)
kennis search "query" --collection context        # this project only
kennis search "query" --collection notes,context  # comma-separated
```

**A scope you name is a promise; a scope you did not is not.** Asking for
`context` outside a project is an error. A default sweep outside a project
simply does not mention it, and the same goes for a machine with no corpus -
so `kennis search` works inside a project before `kennis corpus init` has
ever been run.

A scope that exists and has no index is reported, with the command that
builds it. A scope that does not exist, or that holds nothing, is not: an
empty collection is skipped by `kennis corpus index` itself, so naming that
command would change nothing.

**A context hit is addressed by path, not by an identifier.** There is no
`kennis read` for a bundle file - it is a file in your own project, so the
handle line gives you `path=.context/...` and you open it with your own
tools. See [Project knowledge](../how-to/project-context.md).

## Results are grouped by collection

Each scope gets its own group, its own ranking, and its own line saying
what its relevance levels are a band of.

That line matters. A collection indexed with an embedding backend is banded
on an **absolute cosine**; one without a dense leg is banded **relative to
its own best hit**, whose top result is therefore `very high` by
construction. Those are different claims, and printing them in one ranked
column would state a comparison kennis cannot make - see
[How retrieval works](../explanation/retrieval.md).

Two consequences:

- **`-k` applies per scope**, so `-k 5` on a three-collection corpus plus a
  project bundle can return up to twenty hits. Each group is a complete
  answer from its source rather than a truncated share of a blend, which is
  why the default is 3 rather than the 5 it was when one merged list was
  truncated globally.
- **Groups run in a fixed order** - context, literature, docs, notes - not
  best first. Ordering them by quality would reintroduce the comparison the
  grouping exists to avoid. The summary line tells you where the hits are.
  Context comes first because it is the nearest scope: one project rather
  than the whole machine. That is a fact about where knowledge lives, not a
  claim about which hit is better.

A collection that matched nothing gets no group.

### Narrow it

```
kennis search "query" --collection literature   # one scope
kennis search "query" --group 'physics/*'       # one group, shell-style
kennis search "query" --project stimela         # docs only: by project
kennis search "query" -k 20                     # more hits
```

Quote a group pattern. Your shell expands an unquoted `*` before kennis sees
it.

### Change what is shown

```
kennis search "query" --snippet none    # headlines only
kennis search "query" --snippet full    # the whole chunk
kennis search "query" --scores raw      # rrf, bm25 and cosine numbers
kennis search "query" --scores none     # no relevance column
```

### Change how it searches

```
kennis search "query" --mode hybrid   # both legs, the default
kennis search "query" --mode dense    # meaning only
kennis search "query" --mode bm25     # words only, needs no model
```

`--mode` does not apply to `context`. A bundle's index is BM25-only by
design - a dense one would turn `kennis context init` from an offline
scaffold into a model download - so a context group is always a lexical
search and its heading says the band is relative.

## Read

`read` takes anything that names the document - the identifier, the title,
the filename with or without `.md`, a citekey, an arXiv identifier or DOI, or
a docs page's `project/page`:

```
kennis read yusk5agyfk
kennis read "Recipe variable assignments.md"
kennis read stimela/fundamentals/variables
```

The same resolution `corpus remove` and `corpus move` use, so a handle that
works for one works for all of them.

### Read a passage

A search hit gives you `chunk=3`. To read around it:

```
kennis read yusk5agyfk --chunks 2:5
```

`--chunks` is a python slice over the document's own chunks:

| you write | you get |
|---|---|
| `3` | that one chunk |
| `0:3` | the first three |
| `2:` | from the third to the end |
| `:3` | the same as `0:3` |
| `-1` | the last |

There is no step, because a passage that is not contiguous is not a passage.

!!! note "Why an option and not `read x[0:3]`"
    `[` and `]` are glob characters. Your shell rewrites an unquoted bracket
    expression against whatever files happen to be in the working directory,
    silently, and differently from one directory to the next. `read
    abc123[0:3]` becomes `read abc1230` if a file named that exists.

### Reading does not need an index

Without `--chunks`, the document is read from the corpus, so a document that
has never been indexed is still readable. With `--chunks`, the passage is
stitched out of the index - so that form, and only that form, needs
`kennis corpus index` to have run.

### Piping

One output contract either way: **stdout is the text, stderr is the
provenance.**

```
kennis read yusk5agyfk > paper.md          # just the markdown
kennis read yusk5agyfk --chunks 3 | less   # just the passage
```

Colour is dropped when stdout is not a terminal, and no line is padded or
re-wrapped, so a redirect gives you the document byte for byte.

Add the YAML frontmatter when you want it:

```
kennis read yusk5agyfk --frontmatter
```
