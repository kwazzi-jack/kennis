# A tree you can act on

Milestone / step: v0.1.1, concerns #188, #193
Date: 2026-09-23

## What I am about to do

Put each document's identifier beside it in `kennis corpus tree`, and make a
group look different from a document in it.

## How I expect it to work

`tree_command` walks the directory with `rglob` and prints `path.name`. It
needs one more thing: the identifier for each markdown file. `Collection.
survey()` already returns `DocumentFacts` for every document in the
collection, tolerant of ones that fail validation - which is the right source
here, because a tree is a picture of what is on disk and must show a document
kennis cannot read rather than omit it.

So: build `{md_path: identifier}` from `survey()` once per collection, then
print each walked path as either

    stimela/                                 <- a directory, heading role
      h0sj3vsndx  Recipe for-loops.md        <- a document, identifier then name
      ??????????  Broken.md                  <- a document with no readable id

The wrapper-directory case is the one to be careful about. A document with
assets is a *directory* named after the title, holding `content.md`, so the
walk must not print it as a group and then print `content.md` under it. The
survey's `reserved_filename` already knows which name a document occupies, so
the map is keyed by the name a listing shows rather than by the markdown
path.

For the styling, `display.detail` is the wrong primitive: its marker column
means added/removed/changed, and every entry here is unchanged. Two new
display functions instead, `tree_group` (heading role) and `tree_document`
(identifier role on the id, muted on the name), both indented by depth.

## What I expect to be uncertain or difficult

Whether the identifier should come before or after the name. Before lines the
identifiers up in a column, which is what makes them scannable and copyable;
after keeps the names aligned so the tree still reads as a tree. I expect to
have to look at both against the real corpus, which has a 12-page docs
project and two literature documents with long titles.

## What actually happened that I did not expect

The wrapper case was the one I flagged, and I still got it wrong on the first
pass - in a way the sketch's own wording caused.

The sketch said to key the map by "the name a listing shows", and
`DocumentFacts.reserved_filename` is the closest-sounding thing to that. It
is not that name. For a document with assets it returns `Foo.md` - the name
the wrapper *reserves* against a future document's filename - while the
directory on disk is `Foo`. Keying by it meant the wrapper matched nothing,
so the tree printed `Foo/` as a group and `content.md` under it as a document
with no identifier. Injecting that spelling back afterwards failed the test,
so it is now pinned.

The general shape is worth keeping: `reserved_filename` has a precise meaning
that is *almost* the one I wanted, and the docstring says so plainly. I read
the name and not the docstring.

The identifier-before-name question answered itself the moment I ran it
against the 12-page docs project: with the identifier first the identifiers
form a column that can be read straight down, and the names are ragged, which
is fine because a reader scanning for a name already knows what they are
looking for. The other order has ten-character identifiers scattered across
the width of the longest title.
