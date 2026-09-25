# Searching two scopes

Milestone / step: v0.2.0 unit 4
Date: 2026-09-26

## What I am about to do

Make the bundle searchable from `kennis search`: `context` becomes a fourth
value of the existing collection selector, the selector becomes
comma-separated with `all` as its default, and a context-only search reports
on its own lexical band.

## How I expect it to work

### A fourth value, not a second axis

This is the plan's decision and it comes from boepie: `--context` as a
separate flag would make two axes where there is one question - which scopes
to search. So

    --collection all                    every indexed scope (the default)
    --collection context
    --collection notes,context
    --collection docs

click's `Choice` cannot express a comma-separated list, so the option takes a
string and a callback splits, strips and validates it, naming the offending
value and the four that are accepted. `multiple=True` is not used: repeating
a flag and splitting a value are two spellings of one idea and offering both
doubles what has to be explained.

### Four things stop being true once `context` is in the list

1. **A corpus is no longer required.** `search_command` opens with
   `existing_corpus()`. A project searched on a machine that has never run
   `corpus init` must still search its own bundle, so the corpus is required
   only when a corpus collection is in the selection. Settings are loaded
   either way - they are not the corpus.
2. **A bundle may be absent, and that is the same asymmetry.** No bundle
   under `--collection all` means context is not part of the answer, exactly
   as a missing index does. No bundle under `--collection context` is
   `ContextNotFound`, because it is what was asked for.
3. **`kennis read` cannot take a context hit's handle.** `hit_handle`
   prints `id=<document_id> chunk=<n>`, and a bundle document's identifier
   is its path, which `read` resolves against the corpus. Printing it would
   break rule 4.4 twice over - in the handle line and in the closing
   `kennis read ...` hint. A context hit's handle is its file path, which
   the reader opens themselves; the closing hint is anchored on the first
   **corpus** hit, and omitted when there is none.
4. **`--mode` is not a downgrade for context, it is the design.**
   `_fallback` prints "the context index has no dense leg, so this ran as a
   lexical search" - correct for a corpus collection part-way through a model
   change, and noise for a bundle, which is lexical by design so that
   `context init` stays an offline scaffold (design section 13). Suppressed
   for context; the group's own basis line already says the band is relative
   to the best lexical match.

### Group order

Fixed, as unit 0 established, and `context` goes first: nearest scope first.
That is an ordering by *how specific the scope is*, which is a fact about
where the knowledge lives, not a claim about which hit is better - the thing
unit 0 removed. A reader standing in a project asks about that project.

### What needs no change

The `--group` filter reaches context for free: `BundleLoader` records
`group` on every document, which is why unit 3 wrote it. The relevance band
is already right - `basis_for(model=None, dense_ran=False)` returns
`lexical`, and `relevance_phrase` says "relative to the best lexical match".
`_best_lexical` is already per group.

## What I expect to be uncertain or difficult

Whether `search` should refuse when a bundle exists and has no index, under
`--collection all`. By the rule it is "not part of the answer" - but the
message a corpus gets is `kennis corpus index`, and a bundle needs
`kennis context index`. The skipped line currently prints one command for all
of them, so either it learns to print two, or the two are reported
separately.

Whether the closing `kennis read` hint should be replaced rather than
omitted for a context-only report. "Open the file yourself" is not a command
and rule 4.4 governs commands, so a `guidance` line is available. I lean to
saying nothing: the handle line under each hit already is the path.

Whether `read --collection` should gain `context` and refuse it with a good
message, or keep rejecting it as an invalid choice. click's own "invalid
choice: context" is accurate but says nothing about why, and "why" here is a
design decision worth one sentence.

## What actually happened that I did not expect

**The sketch's three open questions all had the same answer, and it is a
rule rather than three decisions.** I expected to decide case by case what a
skipped scope should say. What emerged instead is one distinction that
covers every case: **a store that exists and has not been indexed is
reported; a store that does not exist, or holds nothing, is not.** The
justification is the module's own - "silently dropping a collection the user
believes was searched is the failure this exists to prevent" - read
carefully. Nobody believes a store they never created was searched. So a
missing bundle is silent, a machine with no corpus is silent, an empty
collection is silent, and an unindexed one with documents in it is reported.

That rule then produced a change to **shipped v0.1 behaviour**, which the
sketch did not anticipate at all. A fresh corpus has `literature` and `docs`
empty, so every single search printed

    warning: not searched, no index yet: literature, docs
      hint: run `kennis corpus index`

and `kennis corpus index` skips an empty collection, so running it changed
nothing and the warning came back on the next search. That is rule 4.4's
weaker sibling - a command that runs and does not do what the line said it
would - and it had been the normal appearance of every search since
milestone 3. One existing test asserted the warning was there; its real
subject was that the sweep does not fail, so it kept that and lost the
incidental assertion, with the two new tests named in its docstring.

**A sweep required a corpus, which would have made the bundle useless.**
`search_command` opened with `existing_corpus()`. With `context` in the
default sweep that means `kennis search` inside a project fails on a machine
that has never run `corpus init` - the exact machine a project bundle is
for. Found by an injection that *passed*: the test asserting no dense-leg
note for context passed with the note restored, because the command was
erroring out before it ever reached the fallback. The test was checking the
absence of a string in the output of a command that had failed.

The corpus is now required only when a corpus scope is **named**, which is
the same promise-versus-sweep asymmetry the rest of the command already uses.

**The read hint needed to be anchored, not omitted.** The sketch had this
right but understated it: since context prints first, `everything[0]` is
usually a context hit, so the closing `kennis read ...` would have been
built from a bundle path that `read` cannot resolve. What the sketch missed
is that the obvious test for it - "the hint does not contain `.context/`" -
proves nothing, because `chunk.document_id` for a bundle document is the
relative path with no prefix. The string would be absent either way. The
assertion is now that the hint carries no `.md`, and the companion test
replays the printed command.

**Four of my own tests passed with their defect injected.** The dense-leg
one and the `read --collection context` one (which asserted only that
"context" appeared in the output of a command that failed for an unrelated
reason), plus the two described above. That is the highest rate in this
milestone, and the common cause is that all four asserted the *absence* of
something - and absence is what you also get when the command never ran.

**`--mode` for context is documented and not enforced.** It is accepted and
has no effect, because the index has no dense leg to use; the note that
would normally report that downgrade is suppressed, since a bundle is
lexical by design. Whether `--mode dense --collection context` should be a
refusal rather than a silent no-op is a real question and I left it as the
softer behaviour: the same command with `--collection all` must still work,
and refusing it for one scope in a sweep would mean either failing the whole
search or explaining a per-scope exception on every run.
