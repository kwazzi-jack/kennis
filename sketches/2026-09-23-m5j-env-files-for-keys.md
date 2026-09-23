# Milestone 5, out of band: a key may arrive in a .env file

Milestone / step: Brian's request - "can you make it so that it can use .env
files if needed?", so that a Datalab key kept in `.env.keys` is found.
Date: 2026-09-23

Previous sketch: `2026-09-22-m5i-a-second-converter.md`.

## What I am about to do

Extend `credential()` in `src/kennis/engine/settings.py` so that a key may be
kept in a `.env` file in the configuration directory, not only exported into
the environment or written into `credentials.toml`. Nothing else changes:
`credential()` remains the single place a key is read, and `DatalabConverter`
already calls it.

## How I expect it to work

### The order of consultation

`credential("DATALAB_API_KEY")` returns the first non-empty value from:

| # | source | why it sits here |
|---|---|---|
| 1 | `os.environ` | a shell export or a CI secret is the deliberate, immediate act; a file written months ago must not shadow it |
| 2 | `<config_dir>/.env.keys` | the file Brian named. A dedicated secrets file, separate from ordinary settings |
| 3 | `<config_dir>/.env` | the conventional name, for anyone who keeps one |
| 4 | `<config_dir>/credentials.toml` | what `kennis config init` writes today |

Last, not first, for `credentials.toml`, because it is the file kennis writes
itself and so the one the user is least likely to have edited most recently.

### The parsing

`python-dotenv`'s `dotenv_values(path)` returns `dict[str, str | None]` and
does **not** touch `os.environ`. That matters: `load_dotenv()` would mutate
the process environment, which would make step 1 above indistinguishable from
steps 2 and 3, and the precedence would become an accident of call order
rather than something stated in one function. So `dotenv_values` it is, and
the ordering stays visible in kennis's own code.

`python-dotenv` is already resolved in the lockfile as a transitive
dependency of `pydantic-settings`. I will still `uv add python-dotenv`,
because kennis is about to import it directly and a direct import must not
rest on another package's dependency choice.

### What is deliberately not done

**No `.env` is read from the current working directory.** `kennis` is a
command run from whatever directory the user happens to be in, frequently a
checked-out repository. A `.env` there is that project's, not kennis's, and
reading it would mean an arbitrary repository could silently supply the key
kennis uses to send documents to a third party. The configuration directory
is the only place consulted.

### Failure paths

Every one of them yields `""` rather than raising, as the existing function
already does for `credentials.toml`: a missing file, an unreadable file, a
file that does not parse, a key present with a `None` value (dotenv's
representation of a bare `KEY` with no `=`). Only the command that needs the
key should fail for the want of one - `load_settings()` is called by every
command and must not fail because a secrets file has a stray quote.

### The docstring that is currently false

`credentials_path()` says "Nothing in this module reads it." `credential()`,
twenty lines below, reads it. That sentence was true when written and was not
revisited. Corrected here - same class of defect as concerns.md #82.

## What I expect to be uncertain or difficult

1. **Whether `dotenv_values` returns `None` values in practice**, and for
   which input shapes. I am asserting a `str` check either way, but the test
   should pin the actual behaviour rather than my belief about it.
2. **Whether the test for precedence can fail for the right reason.** A test
   that sets only the environment passes whether or not the file is read at
   all. The precedence test has to put a *different* value in each source and
   assert which one comes back - and the injection has to break the order,
   not the lookup.
3. **Permissions.** `credentials.toml` is written 0600 by `config init`. A
   `.env.keys` that the user writes by hand has whatever mode their umask
   gives it. kennis does not own that file and should not silently chmod it;
   whether it should *say* something is an open question I will note rather
   than decide.

## What actually happened that I did not expect

### The test I was most confident in was hollow, and only the injection said so

I wrote `test_an_env_file_that_does_not_parse_is_silent_and_not_fatal` with a
`capfd` assertion on stdout and stderr, having first *measured* that dotenv
writes "python-dotenv could not parse statement starting at line 1" to stderr
in a bare `uv run python`. The measurement was real and the test still proved
nothing, because the two conditions differ: pytest's logging plugin attaches
a handler to the root logger, so `logging.lastResort` never fires and nothing
reaches stderr under pytest whether kennis suppresses it or not. The test
passed before the implementation existed, passed after it, and passed with
the suppression deliberately removed.

Six of the seven injections were caught. This one reported MISSED, which is
the whole reason for running them. Measuring the behaviour in the right place
and then asserting it in the wrong place is a failure mode I had not named in
advance - it is not carelessness about the fact, it is carelessness about the
environment the assertion runs in.

The replacement is two tests. One asserts no log *record* is created, which
is a stronger claim than "nothing printed" and is checkable in-process
because the suppression works by level, so the record never exists. The other
spawns a subprocess with no logging configured - the condition the claim is
actually about - and asserts empty stderr. Both fail under injection.

### The noise was a finding, not a foreseen difficulty

I listed three uncertainties and none of them was this. python-dotenv
reporting a malformed line through `logging` means a single stray quote in a
secrets file would make *every* kennis command emit a line kennis did not
compose, because every command calls `credential`. That is a violation of
"the engine never prints" arriving through a dependency rather than through
kennis's own code, and `filterwarnings = ["error"]` would never have caught
it because it is a `logging` call and not a `warnings.warn`. Logged as #141.

### The three uncertainties, resolved

1. **`None` values are real.** A bare `NAME` parses to `None` and `NAME=` to
   `""`. Both guards earn their place; the injection that removes the
   `isinstance` check is caught.
2. **The precedence test can fail for the right reason.** Putting a different
   value in each of the four sources and walking down by deleting one at a
   time means both order injections - swapping the two env files, and
   hoisting `credentials.toml` to the front - are caught by the same test.
3. **Permissions are still open.** kennis does not own a hand-written
   `.env.keys` and does not chmod it. Whether it should say anything about a
   world-readable secrets file is undecided; logged as #142 rather than
   settled here.

### Two false docstrings, both written true

`credentials_path()` said "Nothing in this module reads it" and the module
docstring said keys live in credentials.toml "which nothing here reads". Both
were accurate on the day they were written and were not revisited when
`credential()` was added one commit later. Same shape as #82. Corrected.
