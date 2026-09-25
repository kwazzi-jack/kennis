# Finding a workspace

Milestone / step: v0.2.0 unit 1, concerns #225, #227
Date: 2026-09-26

## What I am about to do

`kennis context init`, and the thing every other context command needs
first: deciding which directory a `.context/` bundle governs.

## How I expect it to work

### The walk

`find_bundle(start)` walks from `start` (default: the working directory,
read **at call time**) up to the filesystem root, returning the first
`.context/` that carries a `bundle.json`. boepie's `find_bundle` is the
model and three of its decisions are taken directly:

- **Keyed on a manifest inside the directory**, not on the directory
  existing. A half-made or stray `.context/` does not hijack the walk.
- **Resolved per call.** A long-lived MCP server's working directory is
  wherever the client launched it, and a project's bundle may be created
  after the server starts. 0.4 needs this; building it now costs nothing.
- **`KENNIS_CONTEXT_DIR` is honoured first but still manifest-checked**, so
  a mistyped override fails as "no bundle" rather than silently serving a
  different project's knowledge.

It walks to the filesystem root and **not** to `$HOME`: a workspace inside a
home directory is ordinary, and stopping there would fail it.

`find_bundle` returns `None` rather than raising. "No bundle anywhere" and
"a bundle with no index" have different fixes, so the caller renders the
error. The CLI's error is `ContextNotFound`, resolution
`kennis context init`, which is the `CorpusNotFound` pattern one scope down.

### Where `init` puts it

Not the working directory: `.context/` belongs at the **root of a
workspace**, and running `kennis context init` three directories deep should
not bury it there. So `workspace_root(start)` is the nearest ancestor
holding a `.git`, else `start` itself. `init` reports the path it chose,
because a command that silently created a directory somewhere other than
where you stood is worse than one that asks.

Re-running is not an error. An existing bundle is reported as found, and
anything missing from it is filled in - the same shape as `config init`
being re-runnable.

### What it scaffolds

    .context/
      bundle.json      the manifest, and what the walk keys on
      LANDING.md       the entry point, written for an agent
      .skeleton.md     the template, dotted so it is never indexed

`LANDING.md` follows boepie's `index.md` in shape - read this first and
jump, a table of question-shape to destination, a layout list - but not in
content, because boepie's is about stimela and kennis is domain-agnostic. It
ships the *convention*: subdirectories are yours to name, each may carry its
own `.skeleton.md`, and the frontmatter is `title`/`description`/`owner`.

**`.skeleton.md` is dotted, and that is the whole exclusion mechanism.**
boepie carried `_NOT_KNOWLEDGE = {apply-log.md, index.md, skeleton.md}`
*and* a dot-prefix rule, because an undotted skeleton "matches every query
about its own section and answers none of them". Dotting it collapses the
two into one rule that works at any depth and needs no list. `LANDING.md`
is the single reserved name that survives, because it has to stay
discoverable to an agent told to read it first.

**No `.gitignore`.** boepie wrote one to exclude `.index/`; design section
19 reverses that deliberately, because committing the bundle's index is what
gives a fresh clone working search. If `corpus.track_index` is ever false
the ignore belongs with the indexing unit, not here.

### The AGENTS.md pointer

One idempotent line naming the bundle, so an agent that reads `AGENTS.md`
finds the knowledge without being told. Written by default and reported;
`--no-pointer` skips it. It touches a file outside the bundle, which is why
it is reported rather than silent.

## What I expect to be uncertain or difficult

Whether `init` from a subdirectory should really walk up to the git root. It
is what "the root of a workspace" means and it is what a user wants nine
times in ten; the tenth is someone who deliberately wants a bundle for a
subproject and is surprised. Reporting the path covers the surprise, and
`--here` can exist later if it turns out to be wanted.

Testing the walk without touching the real filesystem above `tmp_path`.
`tmp_path` is nested well below `/`, so a test for "walks to the root" would
walk over the real machine and could find something. The honest test is that
it walks *past* a directory with no bundle and stops at one with a manifest,
plus one asserting it does not stop at `$HOME` by pointing `$HOME` at a
`tmp_path` ancestor.

Whether `bundle.json` needs anything now. Packs will extend it to which
packs, which versions, applied when. Today it is a schema version and a
created-at, and its real job is being the marker the walk keys on - which
means it must exist even though it says almost nothing.

## What actually happened that I did not expect

**Two of the tests could not fail for the reason they existed**, and both
were found by injection rather than by reading.

*The `$HOME` test.* It set `$HOME` to `tmp_path` and put the bundle at
`tmp_path/projects/thesis`, starting from `thesis/chapters`. The walk found
the bundle on its second step and never reached `$HOME` at all, so an
injection that returned None on reaching `$HOME` passed. Rewritten with the
bundle *above* `$HOME` and the start below it, so the walk has to pass
through `$HOME` to succeed. This is #63's shape - a test of an ordering
property has to fail *between* the two events it orders.

*The overwrite test.* Two tests protected files the user **added**
(`mine.md`, `conventions.md`), and the scaffold loop never touches those, so
removing the `if path.exists(): continue` guard passed both. The file most
likely to be edited is the one `init` wrote: `LANDING.md` tells its reader
to keep its table current, so editing it is the *expected* use, and a re-run
that rewrote it would delete exactly the work the bundle exists to hold. A
test that edits a scaffold file was missing entirely.

**The hint broke rule 4.4 the moment it was written.** `init` ended with
`next_step("kennis remember --context ...")`, which is unit 2 and does not
exist - a printed command that does not run as printed. Replaced with the
landing file, which does exist and is what a new bundle actually wants read.
Caught by running the command, not by the suite; nothing checks that a
printed command is a real one.

**A path inside prose gets wrapped, and a wrapped path is not a path.**
`guidance` wraps like the prose style it is, and the absolute bundle path is
long enough to break across three lines. `display.path` exists precisely for
this and soft-wraps, but a bare path loses the sentence around it. Printing
`.context/LANDING.md` relative to the bundle the line above just named in
full is shorter, copyable, and unambiguous. The test now asserts it is on
*one* line, which is the part that would silently regress.

**`display.note` prints `warning:`.** Three informational lines went out as
warnings - "already complete" is not something going wrong. `guidance`
exists for exactly this and says so in its own docstring; I reached for
`note` because it was the one I had used most recently.

**The git-root walk needed a real repository to test.** A fake `.git` file
would have passed `Path.exists()` and proved nothing about the case that
matters, so the CLI fixture shells out to `git init`.
