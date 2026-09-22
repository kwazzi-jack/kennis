# Milestone 5, step 3: the commands that write

Milestone / step: `design/plan.md`, "Milestone 5", items 1 (mutating) and 5.
Date: 2026-09-22

Previous sketch: `2026-09-21-m5b-the-command-surface.md`. What it left: the
group, the log sink, the read-only commands, and a `corpus status` that
answers the index question with a constant.

## What I am about to do

`corpus add`, `remove`, `move`, `index`, `history` and `restore`. With them
the two things nothing has needed until now: the lock held across a write,
and the commit that follows one.

Milestone 4 built `Repository.commit` and nothing has ever called it from a
user action. This is where the history a person can read starts being
written by the things that person does.

## How I expect it to work

### One writer, and the commit that closes the write

Every command that changes a file does the same three things in the same
order:

```
with corpus_lock(root):        # refuses immediately if held
    report = <engine call>     # the only part that differs
    repository.commit(...)     # None when nothing changed
```

The lock is `timeout=0`, so the second caller is told the corpus is busy
rather than left with a terminal that has stopped. `history`, `status`,
`list` and `tree` do not take it: they read, and a reader blocking on a
writer would make `status` the command you cannot run when you most want to.

`commit` returns None when the working tree was already clean, which is what
re-adding a document kennis already holds looks like. That is not a failure
and must not be reported as one.

**The commit summary is engine-side, not render-side.** This looks like a
violation of #81 and is not. `read_history` parses these subjects back, so
the writer and the reader are two halves of one format; two front ends
writing different summaries would mean a corpus whose history parses
differently depending on which one touched it. The function goes next to
`_SUBJECT`, the regex that reads it.

### The report is what the command prints; the stream is what it watches

`add` and `index` take an `EventSink`. Two subscribers, as section 14 asks:

| subscriber | sees | does |
|---|---|---|
| `LogSink` | every event | writes all of it |
| the display sink | every event | draws the bar, surfaces diagnostics, prints nothing else |

The per-item lines are **not** streamed. They are printed afterwards from
the report, through `display.details`, which caps at `DETAIL_LIMIT`. A docs
add of three hundred pages would otherwise print three hundred lines above
the summary that was the answer. The log has all three hundred, which is the
division section 14 exists to draw.

So the display sink handles exactly three of the five events: `Progress`
advances the bar, `Diagnostic` becomes a `note` or a `hint` as it happens,
and `OperationFinished` closes the bar. `ItemStarted` and `ItemFinished` go
to the log alone.

The bar is opened lazily, on the first `Progress`, because a command that
turns out to have nothing to do should not flash one. That needs an
`ExitStack` held by the sink for the duration of the command.

### `corpus status` stops answering with a constant

Step 2 wrote:

```python
# No index yet is not an error and must not read like one.
display.note("the corpus has not been indexed yet")
```

True on the day it was written and false the moment `corpus index` exists.
Nothing else in the system can currently read an index's manifest, so
`read_manifest` is added beside `load_index` and `status` asks
`index_freshness` with the `built_from` it returns. The sentence comes from
`render.describe_freshness`, which milestone 4 wrote and nothing has called.

### `corpus add`, as boepie shaped it

`--collection` with `-n`, `-l`, `-d` as shorthands, and three rules worth
porting rather than rediscovering:

- naming a collection twice and differently is an error, not a precedence
  puzzle;
- an option that means nothing for the destination is an error, not a
  silently ignored flag - `--citekey` on a notes add is someone expecting a
  citekey to come out the other end;
- the destination is a single choice and never `all`, because a document is
  written to exactly one collection.

### `remove` and `move` address a document by handle

`Collection.resolve` already takes an identifier or an alias and already
refuses an ambiguous one. Without `--collection` the command tries all
three and refuses a handle that resolves in more than one, which is the same
rule one collection applies to its own aliases, applied once more at the
level above.

`move` recomputes the path from group and title with the same two functions
`add` uses - `title_filename` and `unique_filename` - so a moved document
lands where an added one would. Anything else means the corpus has two
naming rules and the second one is only reachable by moving.

`remove` confirms before deleting unless `--yes`. Recoverable through
`corpus restore`, so the prompt is a courtesy rather than the last line of
defence, but the deletion of a wrapped document takes its assets with it and
that is worth one keystroke.

## What I expect to be uncertain or difficult

- **The lazy progress bar inside an event handler.** `display.progress_bar`
  is a context manager and the sink needs to enter it from inside `emit`.
  `ExitStack` does this, but the sink then has a lifetime, which means the
  commands acquire it as a context manager too.
- **What `index` does with no embedding backend configured.** The binding
  allows `model=None` and the lexical-only path exists; the question is
  whether `embedding.backend = "none"` is the default a fresh install gets,
  and therefore whether `corpus index` on a new machine downloads a model
  without being asked. It must not.
- **Whether `move` between collections is allowed.** `move_document` keeps
  the identifier and the collection is a frontmatter-adjacent fact; moving a
  note into literature would need a citekey it has no way to derive. I
  expect to refuse it, but the design may have said otherwise.
- **Confirmation and #30.** The decision channel is still a concern and
  `click.confirm` is the CLI's answer to it. Whether `remove` should route
  through the same mechanism `_choose_identity` will need, or whether two
  prompts with different shapes is right, is the question #30 was logged to
  keep open.
- **Testing the lock through the command line.** Concern #86 records that a
  blocking lock announces itself by hanging the suite. The test takes the
  lock in the test process and asserts the command refuses; it must not be
  written so that a regression turns into a hang.

## What actually happened that I did not expect

**The corpus committed its own lock file, and only this step could have shown
it.** `locking.py` says the lock is "hidden and suffixed, so `.gitignore` can
name it". There was no `.gitignore`. Milestone 4 tested `commit` directly and
milestone 5 step 1 tested `corpus_lock` directly; the defect exists only
where the two meet, and nothing had made them meet. The same file now
excludes `index/*/vectors/`, which had not bitten yet only because the smoke
test ran lexical-only. Concern #92, and its general form: a docstring saying
*another file names this* is a claim about a file that may not exist.

**Giving `init` the lock broke a milestone 4 test within seconds.**
`corpus_lock` creates the root and the lock file inside it; `initialise_corpus`
locates git *first* so that a machine without git leaves nothing behind. The
lock turned a clean refusal into a partially initialised corpus. The race I
was closing was already closed, by the check for an existing `.git`. Concern
#98 - and the second time a milestone 4 test has caught a step 5 change that
looked purely additive.

**Two of the three uncertainties were answerable from what already existed,
and I had guessed one of them wrong.** The sketch says "I expect to refuse"
a cross-collection move; design section 3 says explicitly that a document can
be moved between collections. It is still refused, but for the real reason -
`move_document` takes the collection from the document rather than as an
input, so the destination schema is never consulted - rather than the reason
I assumed. Concern #93. The lesson is not about `move`: it is that the
sketch's third heading is worth answering from the design before writing
tests, because a guess there becomes a test that enforces the guess.

**The defect that no test found was found by running the commands.** After a
`corpus move`, status read "the notes index is stale: 1 document gone" and
said nothing about the arrival. Both halves were individually correct -
freshness computes gone and added, and the sentence correctly described the
counts it chose to name - and the `stale` branch simply did not mention
additions. Concern #95. Fifteen injected defects were caught by the suite;
this one needed a person to read a sentence and notice it was frightening.

**`index(corpus): nothing`, for the same reason.** `commit_summary` was
written over `Outcome`, and an index build has no outcome tally, so the one
command whose history entry most wants a number got the word "nothing". The
fix generalised the function to named counts and left an `outcome_summary`
wrapper over it, which is a smaller change than it sounds: the format was
always `<count> <name>`, and only the names were pinned to an enum.

**The progress bar never drew once.** Every operation in a test corpus
finishes in milliseconds, and `progress_wanted()` is False whenever stdout is
not a terminal, which under `CliRunner` it never is. So the lazily-opened bar
in `DisplaySink` is exercised by the suite only in the sense that nothing it
does raises. That is a real gap and it is the shape of #88 again - a
behaviour present, crossed, and untested because nothing drove it.

Closed rather than recorded, since #88 is exactly the concern that a noted
gap is a gap nobody returns to. `tests/test_cli_sink.py` substitutes a
recording context manager for `display.progress_bar` and asserts the bar's
whole lifetime: not opened without a `Progress`, opened once and advanced by
each one, closed at `OperationFinished`, reopened for a second operation, and
closed when the command raises. What it draws is rich's business; that it is
entered and left is the sink's.

**The console script never called `run()`.** `pyproject.toml` points at
`kennis.cli.__main__:main` - the click group itself - so the wrapper written
in step 2 to turn a cancellation into kennis's wording and exit 130 had been
dead code since the day it was written. Declining the `remove` prompt printed
click's `Aborted!` and exited 1.

#91 for the third time, and the sharpest: there the handler was somewhere the
tests could not reach, here it was somewhere *nothing* reached. What did not
catch it is the part worth keeping - my own test asserted `exit_code != 0`,
which cannot tell 1 from 130, and 130 was the point. Concern #100.

**Answering a question about a feature we are not building found three
defects in one we had.** Brian asked how a cross-collection move would get
its metadata. Checking what each collection actually requires meant reading
`_write_page`, which writes to `docs/<project>/` and derives the identifier
from `(project, page)` - and that immediately said `corpus move --group` was
wrong for docs. Writing the test for it found that `--title` alone relocated
any document to the collection root, and writing the test for *that* found
that a wrapped document moves by its leaf, whose stem is "content" for every
wrapped document in the corpus. Concern #101.

None of the three was reachable from the sketch. They came from reading the
code that a hypothetical feature would have had to interoperate with, which
is a cheaper way to find them than the feature would have been.

**One injection missed, and the miss was the useful part.** Substituting
`document.md_path.parent` for `_holding` left the wrapped-document test
green, because that test passes `--group` and so never reaches the default.
The uncovered case - retitling a wrapped document, where a wrong answer nests
the new wrapper inside the old - now has its own test. An injection that is
caught confirms a test; an injection that is missed names the case nobody
wrote one for, which is the more valuable of the two results.
