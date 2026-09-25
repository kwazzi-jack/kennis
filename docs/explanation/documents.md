# What a document is

A kennis document is a markdown file with YAML frontmatter, living in one of
three collections, addressed by a handle that never changes.

## Three collections

| collection | what goes in it |
|---|---|
| `literature` | papers - things with authors, a year, and usually a DOI or arXiv identifier |
| `docs` | documentation pages, typically crawled from a project's site |
| `notes` | what you write yourself |

The collection is fixed at the point a document is added and decides how it
is named and what metadata is expected of it.

## The handle does not change

Every document has a ten-character identifier, and that is what every command
takes and every result echoes back:

```
kennis read yusk5agyfk
```

The identifier is **surrogate**: it means nothing and is derived from nothing
you can see. That is deliberate, and it is what lets the filename be the full
human-legible title instead of a parseable key. Retitle a document, move it
to another group, move it between collections - the handle keeps working,
because nothing addresses a document by its path.

You can also address a document by title, filename or citekey, which is
convenient at a terminal:

```
kennis read "Recipe variable assignments.md"
```

Those can become ambiguous or go stale. The identifier cannot.

### Where the identifier comes from

Minting at random is what a surrogate key wants in the abstract, and it is
wrong the moment two machines hold the same corpus. Machine A fetches
`arxiv:1101.1764` and mints one identifier; machine B fetches the same paper
and mints another. The filename comes from the title, so both land at the
same path with different bytes, and git reports a conflict on every paper
both machines hold - with nothing in the content able to say the two are the
same document, because the only field that differs is the one deliberately
made arbitrary.

So an identifier is **derived from the natural key where one exists**: the
arXiv identifier, else the DOI, else the bibcode, in that order. Two machines
then mint the same identifier and write byte-identical files. Which key was
used is recorded in frontmatter as `id_from`, so the derivation is auditable
rather than assumed.

Notes keep random identifiers. A note has no natural key by definition, and
is not something two machines independently create.

## The shape on disk

The corpus is ordinary directories and ordinary markdown. Nothing is a
database, and you can read any of it without kennis.

Three rules decide what a path is, by filesystem shape alone - no metadata
field and no reserved directory name:

- a `.md` file is **a document**;
- a directory containing `content.md` is **a document with assets**, such as
  the images extracted from a converted PDF;
- any other directory is **a group**, and kennis descends into it.

A group is just a directory you made. `docs/stimela/` and
`literature/radio-astronomy/` are groups, and `--group` filters on them:

```
kennis search "beam" --group 'physics/*'
```

Quote the pattern. An unquoted `*` is expanded by your shell first.

## Naming

A note keeps the filename of the file it came from, because you chose that
name and it is how you will look for it again.

A paper is named `title - authors - year.md`, which is the form you scan a
directory listing for.

Neither is parsed to recover metadata. The frontmatter holds that; the
filename is for humans.

## Frontmatter

Each document carries YAML frontmatter recording what it is, where it came
from and when. `kennis read --frontmatter` includes it:

```
kennis read yusk5agyfk --frontmatter
```

Without the flag you get the body alone, which is what you want when piping
the document somewhere else.

## Seeing what is there

```
kennis corpus list      # every document, with its identifier
kennis corpus tree      # the directories as they really are
kennis corpus status    # what has changed since kennis last looked
```
