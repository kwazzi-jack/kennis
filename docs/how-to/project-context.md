# Project knowledge

The corpus is machine-global. A **context bundle** is the other scope: a
`.context/` directory at the root of one project, holding what is true about
that project, committed with it so a fresh clone has working search with no
setup.

## Create one

```
kennis context init
```

It walks up from where you are to the nearest `.git` and creates the bundle
at the workspace root, so running the command three directories deep does
not bury it there. The path is reported for that reason. `--here` overrides
the walk and creates it in the working directory.

It scaffolds three things:

| file | what it is |
|---|---|
| `bundle.json` | the manifest that marks this directory as a bundle |
| `LANDING.md` | the entry point, written for an agent: read this first, then jump |
| `.skeleton.md` | the template a file at this level is copied from |

Re-running it is safe, and converging rather than merely harmless: a
scaffold file you deleted is written again, and anything you added is left
alone.

## Write something down

```
kennis remember --context "Calibration runs in four-minute chunks."
kennis remember --context --title "Solver choice" "We use quartical."
kennis remember --context --group decisions "Solved per scan, not per field."
```

`--title` names the file; without one the title is derived from the first
line. `--group` files it in a subdirectory, which is created if it is not
there yet. The same text twice writes one file - deduplication is on the
body, so the same prose under another name in another directory is still
recognised.

Every file carries `owner: user` in its frontmatter, which is what stops any
future pack from overwriting it.

**kennis does not commit for you.** The bundle lives in a repository kennis
does not own, so committing `.context/` is yours to do, whenever you want
it shared with the project.

## Index it

```
kennis context index
```

BM25 only, and offline. A dense index would turn setting a project up into a
model download, and a bundle is small enough that lexical search over it is
the right answer rather than a concession - a three-document bundle indexes
in about 4ms and produces under 3 KB.

The index is written **inside** the bundle, at `.context/.index/`. That is
the point: commit it with the project and a clone searches with no setup.

## What is and is not indexed

Two rules, and they are the whole of it:

- **A dot-prefixed path is never indexed or searched**, at any depth. That
  is why the templates are `.skeleton.md`: a template matches every query
  about its own section and answers none of them. Rename any file of your
  own to `.name.md` to keep it out of search without deleting it.
- **`LANDING.md` is not indexed either.** It is a map rather than an answer,
  and it has to stay discoverable to an agent told to read it first, so it
  cannot be hidden by the dot trick.

## Search it

```
kennis search "four-minute chunks"                    # every scope
kennis search "four-minute chunks" --collection context
```

A context hit's handle is `path=.context/...`, because a bundle file is a
file in your own project. There is no `kennis read` for one - open it with
your own tools.

See [Search and read](search-and-read.md) for how the scopes interact.
