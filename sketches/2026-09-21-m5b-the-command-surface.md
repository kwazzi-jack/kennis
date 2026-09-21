# Milestone 5, step 2: the command surface, logging, and reading a corpus

Milestone / step: `design/plan.md`, "Milestone 5", items 1 (read-only), 6.
Date: 2026-09-21

Previous sketch: `2026-09-21-m5a-settings-and-locking.md`. What it left:
settings resolved at the edge, and a lock to hold while writing.

## What I am about to do

The first commands. `corpus init`, `corpus status`, `corpus list`, `corpus
tree` - everything that reads, plus the one that creates. With them, the two
pieces every later command needs: the log sink, and the bridge from the
engine's event stream to the display.

This is where the milestone 0 display port is finally used for something.

## How I expect it to work

### The report is not the log

Design section 14 states it in one sentence and the whole shape follows.

| | report | log |
|---|---|---|
| audience | the person running the command | whoever is debugging afterwards |
| lifetime | the terminal session | rotated files on disk |
| content | what happened | why, and with what |

Conflating them is the classic failure: user-facing output emitted through
`logging.info` means log levels start controlling the interface, and `-v`
becomes the only way to learn what a command did.

**The library logs; the application configures.** `kennis/__init__.py` gains
a `NullHandler` and nothing else. The entry points install handlers.

```
src/kennis/logs.py     the file sink and where it lives
src/kennis/cli/sink.py the event stream, fanned out to display and log
```

`logs.py` sits at the top level rather than under `cli/` because `serve` will
need exactly the same file, and a second front end reaching into the first is
the coupling `render/` was just created to avoid.

**stdout is never a sink.** Under `kennis serve`, stdout is the JSON-RPC wire.
boepie was burned by precisely this - a library's module-level
`Console(file=sys.stdout)` put 567 bytes of INFO into the stream and the
client answered `Invalid JSON: trailing characters`. The file handler and the
console handler both avoid stdout, and the console one is on stderr.

### One stream, two subscribers

The engine emits typed events and does not know who is listening. The command
line subscribes twice:

- **the display**, which filters - it prints outcomes and diagnostics and
  drives the progress bar;
- **the log**, which does not - it writes every event.

Section 14's requirement is that the log records what the report omits:
*which* fifteen documents were skipped and why each one, not the count. With
an event stream that is a difference in filtering rather than a difference in
instrumentation, which is the argument for a stream over a progress callback.

### The commands

`corpus init` creates the corpus and its repository. `initialise_corpus`
already does the work; the command resolves the root from settings, takes the
lock, and reports.

`corpus status` answers: how many documents, in which collections, how many
kennis cannot read, whether the index is in step, and what changed outside
kennis. Four engine calls it already has - `survey`, `index_freshness`,
`detect_changes`, and the manifest.

**Concern #21 comes due here.** `DocumentInvalid.default_resolution` is
`kennis corpus status`, and milestone 2 recorded that this command must be
written against `contents()` rather than a strict reader "or it will die on
exactly the corpus it exists to diagnose". It is written against `survey()`,
which is the lenient one, and there is a test that puts a broken document in
a corpus and asks for status.

`corpus list` and `corpus tree` are the same walk rendered two ways: a flat
list of documents, and the group structure they sit in.

### What the commands do not do

They do not format. Every sentence comes from `render/`, per #81 - the
commands choose *what* to say and the renderer says it. A command that builds
its own sentence is the thing the last step was spent removing.

### The corpus root, resolved once

Settings supply it, the group resolves it, and every command receives it as
an argument. That is #87's rule, and this is the edge it names.

## What I expect to be uncertain or difficult

- **Testing a click command.** `CliRunner` is the obvious tool. The plan asks
  that every command be exercised "through the engine in one test and through
  the command line in another, and they agree", which means the command tests
  assert on output and exit status rather than re-testing behaviour.
- **Colour disappearing when stdout is not a terminal.** The plan names it as
  a test. rich detects this, so the test is really that nothing overrides the
  detection.
- **The log file in tests.** Every test that runs a command must not write to
  the developer's real log. The same override shape as `KENNIS_CONFIG_DIR`
  seems right, but a second environment variable for it is a cost.
- **What `corpus status` says about an index that was never built.** That is
  not an error and should not read like one - a fresh corpus has no index and
  the answer is "none yet", not "unverifiable".
- **Whether `tree` needs a library.** rich has one. Using it means the tree's
  shape is rich's rather than the display module's, which is the boundary
  milestone 0 drew carefully.

## What actually happened that I did not expect

**The display port lost `--quiet` in milestone 0 and nothing noticed for five
milestones.** `set_verbosity` stored `_quiet`; the only reader was
`progress_wanted`. boepie has six guards and the port carried none. This is
precisely what Brian asked not to happen - the decisions in `_display.py`
were to be neither re-litigated nor *lost* - and lost is the harder kind to
see, because every function was present and every test passed.

It survived because **nothing ran a command**. The milestone 0 display tests
call the line functions directly and none of them sets `--quiet` first; there
was no command to pass the flag to until today. The defect needed a caller.
Concern #88, and the generalisation: a port needs a check that each
*behaviour* crossed, not only each function.

**Fixing it exposed that I had bypassed the display's grammar.** Restoring the
guards did not fix `--quiet`, because my `corpus status` called `info` and
`muted` - the raw line printers - rather than `operation`, `detail` and
`note`, which are the reporting verbs the guards belong on. Rewriting it
fixed the flag and made the output obey a structure I had not realised was
there: operations at the margin, details indented beneath. Concern #89.

**My error handling was in a place the tests could not reach.** I caught
`KennisError` in the `run()` wrapper the console script calls, and every
command test failed with a traceback because `CliRunner` invokes the group
directly. The test was right. A handler only the entry point installs is one
the suite never exercises, which is how tracebacks reach users despite a
green build. Concern #91.

**Click 8.5 gives a group callback nothing to log.** `ctx.args` and
`ctx.protected_args` are both empty there and `invoked_subcommand` is only
one level down, so `kennis corpus init` logged as `corpus`. Checked rather
than assumed. The answer is better than what I was attempting: each command
logs itself with its own parameters, from a base class the group installs, so
a command added later is logged without anyone remembering. Concern #90.

**Concern #21 closed without difficulty, which is the point of having logged
it.** Milestone 2 recorded that `corpus status` must be written against the
lenient reader "or it will die on exactly the corpus it exists to diagnose".
I wrote it against `survey()` on the first attempt because the concern said
to, and the injected `contents().documents` version fails the test. Fifteen
milestone-steps between the note and the command, and none of it re-derived.

**My own fixture wrote invalid documents.** Four tests failed because my
hand-written notes omitted `source`, which the schema requires - so they were
read as unreadable, which is a different test from the one most of them are.
The third time in this project a fixture has been the thing that broke, and
concern #32 continues to hold.
