# What a document is called on disk

Milestone / step: v0.1.1, concerns #189, #190
Date: 2026-09-23

## What I am about to do

Two changes to filenames, asked for separately and reached by different code.

A note added from a local file takes its **filename**, not the first heading
in it. Brian added `kennis-readme.md` and got `notes/kennis.md`.

A paper takes `title - authors - year.md` rather than `title.md`.

## How I expect it to work

**The note.** `convert_local_file` in `intake.py` sets
`suggested_title=title_from_markdown(markdown, path.stem)` - the heading, with
the stem only as a fallback. The heading is right for a *converted* document
(a PDF's heading is the paper's title) and wrong for one a person wrote and
named.

So the filename is carried separately rather than by swapping the fallback
order: `Converted` gains `source_name`, set to the stem for every local file
and None for a URL, an arXiv fetch or `remember`'s inline text. Only the
**notes** path prefers it:

    title = options.title or converted.source_name or converted.suggested_title

Literature keeps its order, because `identity.title` comes first there and
the heading is the right second choice for a paper whose metadata is
missing.

**The paper.** `title_filename(title)` is what every writer calls, so the
change is to give the literature writer a different string to hand it:

    literature_stem("Dying for freedom", "Hallowes-Welman, Lari", "2026")
      -> "Dying for freedom - Hallowes-Welman - 2026"

First surname only, `et al` past one author, and each part dropped when it is
not known - so a paper with neither degrades to exactly today's filename
rather than to `Title -  - .md`. `_surname_part` in `citekeys.py` already
parses both author conventions and is reused rather than rewritten.

**The part that will disappoint.** Both documents in Brian's corpus have
empty `authors` and `year`, so this renames nothing for him. `_enrich` looks
up arXiv identifiers and nothing else, and a DOI found in a PDF is recorded
without a lookup - deliberately, as identity (#104), but with the side effect
that the fields this pattern needs are empty. That is #190 and it is his
decision to take, not mine.

## What I expect to be uncertain or difficult

Whether `source_name` should win over `--title`. It must not, and the order
above says so, but the same question arises for the *filename* of a note
whose title was given explicitly: today the filename is derived from the
title, so `--title X` on `kennis-readme.md` writes `X.md`, and I think that
is right - an explicit title is an instruction.

The second is renaming. Changing the rule does not move what is already on
disk, and there is no migration: the project's own posture is that a format
may change without one. Brian's two documents keep their names until he
removes and re-adds them.

## What actually happened that I did not expect

No surprise in the mechanism. Both changes went in as sketched, and
`source_name` as a separate field rather than a reordered fallback was the
right shape - it left the literature and URL paths untouched.

The surprises were all in the tests that had quietly been *depending* on the
old rule.

**Five tests failed that were not about naming at all**, and each one was a
fixture that had absorbed the heading-title rule without saying so: a walk
test asserting `{"Top", "X"}` for files named `top.md` and `x.md`, a loader
test naming a file `one.md` and heading it `# A Title`, a search fixture I
had written an hour earlier expecting `Rare.md` from `rare.md`. None of them
were wrong before; they were all *reading the heading through the title*
without intending to.

**One of them had a wart written into it as an explanation.** A test in
`test_cli_mutations.py` carried the comment "so a source called `Trees.md` is
titled `Trees.md` and lands as `Trees.md.md`" and asserted exactly that. The
comment is a clear-eyed description of a defect, sitting in a green test,
dated from whenever the fixture was written. The new rule removes it. I would
not have found it by looking for it.

**The dotfile diagnostic moved rather than disappeared.** It used to fire on
a `# .bashrc` heading; nothing can reach it that way now. The same hazard
exists through the filename (`.bashrc.md`) and through `--title`, so there
are two tests where there was one, and the route that replaced the old one is
named in the docstring.

**The literature half does nothing for Brian.** Both papers in his corpus
have empty `authors` and `year`, and a real conversion run today confirmed it
end to end: a PDF identified by its own DOI converted in 26 seconds and
landed as `Calibration of Radio Interferometers A Probe.md`, with no author
and no year to add. The pattern degrades exactly as designed, which is the
best that can be done without deciding #190.
