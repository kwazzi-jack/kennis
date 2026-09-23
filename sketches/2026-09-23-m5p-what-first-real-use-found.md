# What the first real use of v0.1 found

Milestone / step: Brian ran kennis against his own machine after the v0.1.0
tag and reported four things. Investigating them found a fifth, which is the
serious one.
Date: 2026-09-23

Previous sketch: `2026-09-23-m5o-a-site-that-yielded-nothing.md`.

## What I am about to do

Five fixes, each with its cause established by reading his corpus and his
config rather than by reasoning about the code.

### A. `config init` writes an empty config.toml, so `config show` shows nothing

`~/.config/kennis/config.toml` is **0 bytes**. `apply_answers` filters out
every answer left unchanged, which is the design, and then calls
`_write_config({})` anyway - which reads nothing, merges nothing and writes
an empty TOML document. `config show` finds a file, prints it verbatim, and
prints nothing.

Two halves. `_write_config` returns early when there is nothing to write, so
an all-defaults setup leaves no file. And `config show` treats a file with no
settings in it the same as no file at all, because "there is a file" was
never the question - "are any settings set" is.

### B. the `config show` warning scrolls off the top

It goes to stderr before the template, so on a terminal it is the first of
some sixty lines and the reader has scrolled past it by the time the output
ends. Moving it after the body keeps `config show > config.toml` correct -
the note is on stderr either way - and puts it where it will be read.

### C. an add reported `+ kennis` for a file called kennis-readme.md

Correct, and confusing. `_report_add` shows `item.title or item.identifier`,
the README's first heading is `# kennis`, so the title is `kennis`. But the
second, duplicate add printed `= kennis-readme.md`, because an `UNCHANGED`
outcome carries no title and falls through to the identifier. One report,
two different kinds of name.

`DocumentFacts` gains a `title` - a plain frontmatter key, read by the survey
that already parses the mapping - so `Uniqueness` can carry titles and a
duplicate outcome can name the document it matched.

### D. the docs progress bar never moves

`add_docs` emits exactly one `Progress`, before the loop, with
`completed=0`. The loop emits `ItemStarted` and `ItemFinished`, which the
display sink deliberately ignores. So the bar opens at 0 of 20 and sits there
for sixty-nine seconds. One `Progress` per page fixes it.

The bar is also labelled `add`, because the label is the event's `operation`
verb. `render/` gains `progress_label`, so a bar says `Adding` and an engine
still says `add`.

### E. a paper that arrived while arXiv was down is named after its identifier

The one he did not report. His stored paper is

    title: arXiv:2101.11270
    bib:
      citekey: paperArxiv

while the body's first line is `# Xova: Baseline-Dependent Time and Channel
Averaging for Radio Interferometry`, with the five authors under it.

`lookup_arxiv_metadata` returned None, which I reproduced: arXiv answered
**HTTP 406 with an empty body** for several minutes and now answers 200 for
the identical request. A transient refusal, swallowed into None by design -
"every failure degrades to None rather than raising" - and the title chain
`options.title or identity.title or converted.suggested_title or
paper.identifier` fell all the way to the end.

It should not have. The chain has a step for exactly this case, and the
arXiv-fetched `Converted` at `add.py:1135` is the one construction site in
the codebase that does not set `suggested_title`. Every other one calls
`title_from_markdown`. So the correct title was in the first line of the very
markdown being written, and kennis threw it away.

Three parts:

1. Set `suggested_title` on the fetched paper, from its own heading. This is
   the fix that needs no network and would have made his document right.
2. Warn when the metadata lookup fails, naming the identifier. A degraded add
   that says nothing gives the user no reason to look, and #E is permanent:
   re-running `corpus add -l` reports the paper as a duplicate by identity
   and never retries the lookup.
3. The citekey then derives from a real title rather than from nothing.

## What I expect to be uncertain or difficult

1. **Whether `config show` should print the effective settings rather than
   the file.** I think not - the design's contract is that its output is a
   usable `config.toml`, and the template is that. But an empty file is
   neither the file nor the template, which is the actual bug.
2. **Whether the duplicate line should name the title or the argument.** A
   directory add of 47 files reads better as paths; an arXiv add reads better
   as titles. I am choosing consistency within one report over being right
   about which, because a report that mixes them is wrong either way.
3. **Whether to repair a document already stored with a placeholder title.**
   His corpus has one. A migration is out of scope and the project ships
   none; I expect to tell him the two commands instead.
4. Whether `Progress` per page makes the bar jump rather than move, since
   most of the sixty-nine seconds is the politeness delay between requests.

## What actually happened that I did not expect

### Two existing tests were asserting the bug

`test_pressing_return_throughout_changes_nothing` and
`test_the_count_is_of_what_was_written_not_what_was_asked` both read
`config.toml` and asserted `settings_in(...) == {}` - which requires the file
to exist and hold no settings. That is precisely the state that made
`config show` print nothing. Two tests, green since they were written, were
pinning the defect in place.

The lesson is not that they were badly written; `settings_in(...) == {}` is a
reasonable way to say "nothing was configured". It is that a test can state a
true thing about an artefact whose *existence* is the actual mistake. Both now
assert `not (isolated / "config.toml").exists()`, which is the stronger claim
and the one that was meant.

### E was in the codebase's own pattern, which is why it was invisible

Eleven `Converted` values are built across `intake.py` and `add.py`. Ten call
`title_from_markdown`. The arXiv-fetched one did not, and nothing marks it
out - it reads like the others and is three lines shorter. The defect only
becomes observable when `identity.title` is empty, which needs arXiv to fail,
which needs a real network on a bad day.

Brian's corpus has the artefact. Mine, added an hour later with arXiv
answering, reads

    title: 'Xova: Baseline-Dependent Time and Channel Averaging for Radio
            Interferometry'
    citekey: atemkengXovaBaselineDependent2021

against his

    title: arXiv:2101.11270
    citekey: paperArxiv

Same command, same identifier, two days' difference in what the corpus is
worth.

### Uncertainty 2 answered itself once the survey was read

I expected to have to weigh naming a duplicate by its title against naming it
by the argument. `DocumentFacts` already parses the frontmatter mapping, so
`title` is one dictionary lookup and no extra read, and `Uniqueness` already
exists to carry exactly this kind of fact. There was no trade to make.

### One injection missed, and the miss was mine

`test_a_config_file_with_no_settings_is_treated_as_no_file` survived the
injection aimed at it. Not a hollow test - it was one of the four that went
red before the fix - but the injection was wrong: with the `any(parsed.
values())` guard removed, an *empty* file's text is still empty, so the
caller's own `if settings` handles it and nothing breaks. The guard is what
covers a file of nothing but comments; the empty file is covered by the
caller's structure.

Restoring the original structure - `if path.is_file(): print it` - failed
both tests, which is the injection that verifies this one. Worth recording
because #66's rule is about an injection that matches nothing, and this is a
third variant: an injection that matched, applied, and could not reach the
behaviour it was aimed at.

### What I did not do

Two literature tests sleep 3.00s each, because they do not pass
`request_delay_seconds=0` and so pay the real politeness delay. Six seconds
on every run of the default suite. Noticed, not fixed - it is nothing to do
with what was reported, and changing tests for speed alone is how a delay
that mattered gets removed by accident. Concern #180.
