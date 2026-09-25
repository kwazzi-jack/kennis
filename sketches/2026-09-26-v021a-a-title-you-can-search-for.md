# A title you can search for

Milestone / step: v0.2.1, concern #243
Date: 2026-09-26

## What I am about to do

Make a remembered note's title searchable, by writing it into the note as a
heading. `search "solver"` currently misses `decisions/Solver choice.md`,
whose body is "We use quartical rather than cubical" and whose title is the
only place the word appears.

## How I expect it to work

### Only a title the caller chose

The obvious version - always prepend `# {title}` - is wrong, and seeing why
narrows the change to almost nothing.

`title_for(body)` derives a title from the body's first heading or its first
line, trimmed to 60 characters. Prepending *that* repeats the opening words
of the note back at itself:

    # Calibration is done in four-minute chunks because the

    Calibration is done in four-minute chunks because the ionosphere
    decorrelates faster than that.

A derived title is already in the body, by construction. Only
`--title "Solver choice"` over prose that never says "solver" adds words the
chunker would otherwise never see. So the rule is: **prepend the title when
the caller supplied one, and not when it was derived.**

Left alone, too, when the body already opens with an ATX heading: the caller
has supplied their own and two stacked headings is worse than a title that
lives only in the frontmatter.

`titled_body(title, body)` in `engine/remember.py`, beside `title_for`,
because both scopes need it and `remember.py` is where the note's shape
already lives.

### The digest has to stop being the body

This is the part that would break quietly. Both scopes deduplicate on the
digest of what was written:

- the corpus sets `Converted.sha256` from `body` explicitly and stores it in
  frontmatter, so it is already independent of what lands on disk - the only
  change needed is to compute the title before building `Converted`;
- a bundle has no such record. `_holding` hashes the **stored body** of every
  file and compares. Once a heading is prepended, remembering the same text
  twice would no longer be recognised, and `remember --context` would write
  a second copy of a note it already had.

So a bundle note gains `source.sha256`, which is what the corpus records for
the same reason. A file without one - anything hand-written - falls back to
hashing its body, which is right, because kennis never added a heading to it.

## What I expect to be uncertain or difficult

Whether the heading belongs in the snippet. It will appear in search output,
because the snippet comes from the chunk text. `# Solver choice` above the
prose is arguably an improvement; a reader can judge.

Whether `--title` differing from an existing first heading should still be
recorded somewhere searchable. It will not be: the body is left alone, and
the title stays in frontmatter only. I think that is right - the caller gave
two titles and the body's wins for display - but it leaves the original gap
open for that one case.

Whether the corpus wants this at all. A converted document almost always
carries its title as an H1 already, so the change should be a no-op there
except for `kennis remember --title`.

## What actually happened that I did not expect

**Narrowing the rule to a chosen title made it small, and the digest is
what nearly broke quietly.** The rule itself is four lines and behaved as
sketched. What the sketch caught only because it was written down first is
that both scopes deduplicate on a digest of what was *given*, and prepending
a heading makes the stored body a different string. The corpus was already
safe by accident - `Converted.sha256` is set explicitly from `body` - and
needed only the title resolved a few lines earlier so the markdown could
carry it. A bundle hashed the stored body and would have started writing a
second copy of every titled note that was remembered twice, silently, with
nothing failing.

`source.sha256` in a bundle note's frontmatter is the fix, and it is what the
corpus records for the same reason. A file without one falls back to hashing
its body, which is right for exactly the files that have none: hand-written
ones, to which kennis never added a heading.

**The snippet question answered itself in the output.**

    [1] Solver choice
        relevance: very high  path=.context/decisions/Solver choice.md
        # Solver choice We use quartical rather than cubical.

The heading in the snippet reads as a label rather than as noise, and it is
the thing the hit matched on. Leaving it.

**The corpus is unaffected in practice, as expected.** A converted document
carries its title as an H1 already, and `remember` without `--title` derives
the title from the body. Only `kennis remember --title X` changes, in either
scope, which is the case that was broken.
