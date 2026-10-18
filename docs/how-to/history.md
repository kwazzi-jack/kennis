# Inspect and recover

The corpus is a git repository, so everything here is backed by a real
commit. See [The corpus is a git
repository](../explanation/corpus.md).

## What is in there

```
kennis corpus list                        # every document, with identifiers
kennis corpus list --collection notes     # one collection
kennis corpus tree                        # the directories as they really are
```

`tree` is the one to use when you want to see grouping. `list` is the one to
pipe.

## What has changed

```
kennis corpus status
```

This compares the corpus on disk against what kennis last recorded, so it
catches edits you made in your editor. The corpus is ordinary markdown and
you are allowed to do that.

It also reports whether each collection's index is in step with its
documents. If it is not, reindex:

```
kennis corpus index
```

## What happened

```
kennis corpus history
kennis corpus history --collection docs --limit 50
```

```
  48f6d723  2026-09-24 11:52  index(corpus): 48 documents, 334 chunks
  9016f9bf  2026-09-23 19:11  add(literature): 1 added
  0f390d48  2026-09-23 18:34  init(corpus): create the corpus
```

The short commit in the first column is what `restore` and `return` take.
Every line is a point the corpus can be returned to.

## Put a document back

```
kennis corpus restore <document-id>                      # from HEAD
kennis corpus restore <document-id> --commit 9016f9bf    # from there
```

The document returns to its state at that commit **keeping its identifier**,
which is what the identifier being surrogate is for. Anything that referenced
it still resolves.

## Return the whole corpus to a point

```
kennis corpus return 9016f9bf
kennis corpus return 9016f9bf --yes    # do not ask
```

This makes every document as it was at that commit: a document changed
since goes back to how it was, one added since is removed, one removed
since is put back. It says which first, by title, and asks.

Nothing is lost by it:

- **What is not yet recorded is recorded first**, as its own commit, so an
  edit you made in your editor is in the history before the return
  replaces it.
- **The return is a commit too.** To undo it, return to the commit before
  it; `corpus history` lists both.

Two things it leaves alone:

- **The index.** Search still reads the index built before the return, and
  `corpus status` says which documents it is behind on. Run
  `kennis corpus index` afterwards.
- **Installed packs.** They are not in the corpus history, so the next
  `kennis corpus sync` writes a pack's documents again if the return took
  them away.

In the window, the Activity page lists the same history. Each line but the
newest has **Return to this point**, which says what would change before it
does anything, and a removal lists what it removed, each with **Put back**.

## Rename or regroup

```
kennis corpus move <handle> --title "A better title"
kennis corpus move <handle> --group radio-astronomy
kennis corpus move <handle> --group ""          # back to the collection root
```

`--title` renames the file on disk to match. The identifier does not change,
so handles you have written down keep working.

## Remove

```
kennis corpus remove <handle>
kennis corpus remove <handle> --yes    # do not ask
```

It asks first unless you pass `-y`. Assets are removed with the document. It
is a commit, so it is recoverable through `restore` at an earlier commit.

In the window, a document's menu in the tree has **Remove**, which asks
first. The Activity page then lists the removal with **Put back**.

## When the corpus is busy

A corpus takes a file lock for any operation that writes, with a zero
timeout. A second command is told the corpus is busy rather than left
hanging, because a command that appears to have frozen is worse than one that
declines and says why.

## The log

```
kennis config path      # the config directory
```

kennis logs every run. When something went wrong, the log already exists -
its path is on the second `hint:` line of any error.
