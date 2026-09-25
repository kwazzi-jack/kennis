# Project knowledge

The corpus is machine-global. A **context bundle** is the other scope: a
`.context/` directory at the root of one project, holding what is true about
that project and committed with it, so the knowledge travels with a clone.

The **index** does not travel. It is derived from the documents beside it,
rebuilt in milliseconds, and specific to whoever built it, so `context init`
gitignores it and a clone runs `kennis context index` once.

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
| `.gitignore` | one line, `.index/`, keeping the index out of the repository |

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

`retrieval.context_method` changes it, and defaults to `bm25` for that
reason. Setting it to `hybrid` or `dense` gives the bundle a model-specific
index and needs an embedding backend; with none configured, asking for
`hybrid` still produces a lexical index rather than an error. The setting is
yours alone - the index is not shared, so nobody else in the project is
affected by it.

The index is written **inside** the bundle, at `.context/.index/`, and
`context init` gitignores that directory. Inside so that it travels with the
bundle if you move the project; ignored because it is derived and because
what it was built with - your chunk settings, and your embedding model if
you configured one - is yours rather than the project's.

**A fresh clone has the documents and no index.** `kennis search` says so
and names this command; run it once and the clone searches with your own
settings.

## What is and is not indexed

Two rules, and they are the whole of it:

- **A dot-prefixed path is never indexed or searched**, at any depth. That
  is why the templates are `.skeleton.md`: a template matches every query
  about its own section and answers none of them. Rename any file of your
  own to `.name.md` to keep it out of search without deleting it.
- **`LANDING.md` is not indexed either.** It is a map rather than an answer,
  and it has to stay discoverable to an agent told to read it first, so it
  cannot be hidden by the dot trick.

## Check on it

```
kennis context status
```

What the bundle holds, broken down by group when there is more than one,
and whether the index is in step with it.

Freshness is answered differently here than for the corpus. A corpus index
records the commit it was built from and the question is a `git diff`;
kennis does not write to your repository, so a bundle index records no
commit and the comparison is made against the document digests the index
stored. Same three counts either way:

| line | what it means |
|---|---|
| `in step` | the index matches the bundle |
| `in step, with N not yet indexed` | you have written since the last build - the index holds less, not something wrong |
| `stale: N changed, N gone` | the index holds something false |

`remember --context` does not index, so the middle line is the ordinary
state of a bundle rather than a brief window.

A file whose frontmatter block could not be read is listed with a `!`. It is
still indexed - a bundle document's identity is its path, so a broken header
costs its metadata and not the file.

## Start again

```
kennis context reset
```

Removes the index and anything kennis owns, and keeps your own files. It
asks first and names what will go; `-y` skips the question.

**Today that is the index and nothing else.** Files kennis owns are files a
pack applied, and there are no packs yet - everything `remember --context`
writes is `owner: user`, and so is anything you wrote by hand, including a
file with no frontmatter at all and one whose header kennis cannot read. The
two mistakes do not cost the same: keeping a pack's file costs a stale file
the next sync overwrites, and deleting yours costs your writing.

`LANDING.md`, `.skeleton.md`, `bundle.json` and `.gitignore` are left alone
even though kennis wrote them, because you are expected to edit the first
two. `kennis context init` puts back any one of them you delete.

There is no undo inside kennis. A bundle lives in your repository and kennis
keeps no history of it, so `git checkout` is the way back - if you
committed.

## Search it

```
kennis search "four-minute chunks"                    # every scope
kennis search "four-minute chunks" --collection context
```

A context hit's handle is `path=.context/...`, because a bundle file is a
file in your own project. There is no `kennis read` for one - open it with
your own tools.

See [Search and read](search-and-read.md) for how the scopes interact.
