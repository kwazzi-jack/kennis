# Search and read

## Search

```
kennis search "reciprocal rank fusion"
```

A hit looks like this:

```
Found 5 passages, relevance by cosine similarity
  [1] [docs] Recipe variable assignments - Step assignments
      relevance: high  id=yusk5agyfk chunk=3
      ## Step assignments Any step definition can contain an `assign`
      section of its own. Use this if you need to change the value of a
      recipe variable just for that one step. ...
```

The first line says which scale the relevance levels are on, which is worth
reading - see [How retrieval works](../explanation/retrieval.md). The
`id=` and `chunk=` are the coordinates you pass to `read`.

### Narrow it

```
kennis search "query" --collection literature   # one collection
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
