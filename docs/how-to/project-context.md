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

A bundle is written and indexed by the kennis service, which belongs to a
corpus, so this needs one on the machine: run `kennis corpus init` first if
there is none. It is offline and takes a moment. The bundle itself stays in
your project and is never copied into the corpus.

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

## In the window

The window manages projects from the pane's Context section. The button at
the right of the Context heading adds a project: choose its folder, and
kennis lists it if it already has a `.context/` folder, or creates one there
and lists it. The window uses the folder you chose; unlike `kennis context
init`, it does not walk up to the repository's root.

Each project's menu, the button at the right of its row, has:

| entry | what it does | the command |
|---|---|---|
| Packs this project uses | a checkbox per installed pack; saving declares exactly what is checked, then opens the sync dialog. A pack the project declares that this machine has not installed is shown checked, so saving keeps it | `kennis context packs` |
| Sync this project's context | says which pack files it will copy in or update and which it leaves, then copies them; the copies of a pack the project no longer uses go only if you tick "Remove them" | `kennis context sync` |
| Index this project's context | builds its index, as a task in the strip | `kennis context index` |
| Reset this project's context | lists what goes, then removes it | `kennis context reset` |
| Forget this project | takes it off the list; its files stay | `kennis context forget` |
| Delete this project's context | deletes `.context/`, after asking | `kennis context delete` |

A project whose folder has gone is listed as missing, with Forget alone.

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

Three rules, and they are the whole of it:

- **A file with no frontmatter is not indexed.** The header - the block
  between two `---` lines at the top - is what makes a file a note kennis
  can describe, so a README or an export kept beside your notes stays out
  of search. Everything kennis writes has one. A header that is empty or
  cannot be read counts as none. To index such files too, set
  `"index_without_frontmatter": true` in `bundle.json`; `kennis context
  init` writes the key, set to `false`, so you can find it.
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

A file whose frontmatter block could not be read is listed with a `!`, and
the files with no frontmatter are listed after a note saying they are not
indexed. Neither is indexed unless `bundle.json` says
`"index_without_frontmatter": true`; then a broken header costs only its
metadata, since a bundle document's identity is its path.

## Start again

```
kennis context reset
```

Removes the index and anything kennis owns, and keeps your own files. It
asks first and names what will go; `-y` skips the question.

Files kennis owns are the files a pack applied - the ones carrying
`owner: pack:<id>`. Everything `remember --context` writes is `owner: user`,
and so is anything you wrote by hand, including a file with no frontmatter at
all and one whose header kennis cannot read. The two mistakes do not cost the
same: keeping a pack's file costs a stale file the next sync overwrites, and
deleting yours costs your writing.

`LANDING.md`, `.skeleton.md`, `bundle.json` and `.gitignore` are left alone
even though kennis wrote them, because you are expected to edit the first
two. `kennis context init` puts back any one of them you delete.

There is no undo inside kennis. A bundle lives in your repository and kennis
keeps no history of it, so `git checkout` is the way back - if you
committed.

## Stop listing a project

```
kennis context forget <name>
```

Takes the project off kennis's list of projects, which is what the window's
pane and `kennis context list` show. Nothing in its folder is changed: the
bundle keeps every file. kennis lists the project again the next time a
kennis command runs in that folder. In the window, the same is "Forget this
project" in the project's row menu in the pane, which asks first.

## Delete a project's context

```
kennis context delete <name>
```

Deletes the project's `.context/` folder - every file in it and its index -
and takes the project off the list. **kennis cannot undo this.** The bundle
lives in your repository and kennis keeps no history of it, so what you
committed comes back with `git checkout`, and nothing else comes back. The
rest of the project is not touched.

It asks first, naming the folder and how many files it holds; `-y` skips the
question. It refuses a project whose bundle is no longer there, and a listed
folder that is not a `.context` folder holding `bundle.json`, and names
`kennis context forget` for both. In the window, the same is "Delete this
project's context" in the project's row menu, which asks in a dialog first.

## Use a pack

```
kennis context packs <id>       # declare it; --drop <id> to stop
kennis context sync             # copy its context in
```

A **pack** is knowledge that arrives from outside, as data - see
[Author a pack](author-a-pack.md). `kennis pack install` puts it in this
machine's store. A project declares the packs it uses in `bundle.json`,
which is committed, so whoever clones the project declares the same ones.
`kennis context sync` then copies the context of each declared pack into
`.context/`, at the paths the pack gives, and the project indexes and
searches those copies as its own files.

**Nothing reaches a project except through its own sync.** Declaring a pack
copies nothing, and a new release of a pack changes no project until you
run `sync` there. What it changed is then a diff in your repository, to read
before you commit. **Offline**: the content is already on this machine.

Each file it writes carries `owner: pack:<id>`, which is what tells kennis's
files from yours:

| the file | what sync does |
|---|---|
| anything with `owner: user`, or no frontmatter | never touched |
| a file with `owner: user` at a path a pack ships | left alone, and said |
| a pack's copy you have edited in place | left alone and named; your edit stays |
| a pack's copy you have not touched | replaced when the pack ships a change |
| a copy of a pack the project no longer declares | kept, and said, until you sync with `--remove-undeclared`; an edited one is kept even then |
| a copy of a pack the project declares and this machine has not installed | kept: whoever has the pack relies on it |

**To make a pack's file yours, say so in its header.** Change `owner:` to
`user`: from then on no release reaches it. A copy you edited without doing
so is left as it is and named on every sync, with that instruction; delete
it to take the pack's text again.

**A damaged pack stops the sync rather than emptying your bundle.** If a
pack's store is missing content, or its stored declaration will not parse,
kennis refuses and names the pack. `kennis pack status` says what is wrong
and how to repair it.

Two things a pack may not do, both refused with the file named:

- **ship a dot-prefixed file.** A dot-prefixed path is never indexed, so the
  file would be copied and then invisible to search.
- **write `LANDING.md`.** It is the entry point, and it is yours.

When two declared packs ship the same path, the one installed first keeps
it, and the sync says so.

`sync` does not index. It names `kennis context index` when it changed
something, for the same reason `remember --context` does.

**kennis does not commit**, here either.

## Search it

```
kennis search "four-minute chunks"                    # every scope
kennis search "four-minute chunks" --collection context
```

A context hit's handle is `path=.context/...`, because a bundle file is a
file in your own project. There is no `kennis read` for one - open it with
your own tools.

See [Search and read](search-and-read.md) for how the scopes interact.
