# The corpus is a git repository

`kennis corpus init` runs `git init`. Every operation that changes the corpus
commits, and the history is a first-class feature rather than a side effect.

## Why git

A corpus is a directory of markdown files, which is exactly what git is good
at. Using it buys three things kennis would otherwise have to build:

- **an undo**, per document and per commit;
- **a record** of what was added, when, and by which operation;
- **detection of changes made outside kennis**, because git already knows
  what the working tree should look like.

That last one matters more than it sounds. The corpus is ordinary files and
you are allowed to edit them in your editor. kennis notices:

```
kennis corpus status
```

## Linear history only

kennis uses `commit`, `log`, `diff`, `status` and `restore`. It does not use
merge, remotes, bundles, or any cross-machine synchronisation - those are
deferred, not forbidden, and the identifier scheme is built so that two
machines fetching the same paper write byte-identical files when the time
comes.

kennis shells out to the `git` binary rather than binding a library. It is a
system requirement, checked once at `corpus init`, with no fallback.

## What a commit looks like

```
kennis corpus history
```

```
  48f6d723  2026-09-24 11:52  index(corpus): 48 documents, 334 chunks
  9016f9bf  2026-09-23 19:11  add(literature): 1 added
  0f390d48  2026-09-23 18:34  init(corpus): create the corpus
```

The short commit is a handle, in the same column and the same colour as a
document identifier, because it is what you paste into a restore.

## Recovering a document

```
kennis corpus restore <document> --commit 9016f9bf
```

The document returns to its state at that commit, keeping its identifier -
which is the point of the identifier being surrogate.

## One writer at a time

A corpus takes a file lock for any operation that writes, with a zero
timeout. A second caller is told the corpus is busy rather than left blocking
on it, because a command that appears to hang is worse than one that declines
and explains. There is no background service.
