# Milestone 5, step 5: `kennis config`, and the setup the engine owns

Milestone / step: `design/plan.md`, "Milestone 5", item 3.
Date: 2026-09-22

Previous sketch: `2026-09-22-m5f-uniform-inputs.md`.

## What I am about to do

`kennis config` with `path`, `show`, `get`, `set` and `init`. The first four
are small. `init` is the guided setup Brian asked for, and it is the reason
this step matters beyond the command surface: it is where the **decision
channel** gets built, which #30, #96 and #102 have all been waiting on.

## How I expect it to work

### The engine owns what is asked; the front end owns how

This is #108's rule and the whole shape follows from it.

| layer | owns |
|---|---|
| `engine/setup.py` | the questions, their order, their validation |
| `cli/` | prompting, one question at a time, in a terminal |
| a GUI, later | the same questions, as a form |

Concretely, `config init` must not contain the knowledge that `openai` needs
a key while `fastembed` needs nothing. That is a property of the backend,
which is engine territory, and a GUI forced to re-derive it would be the
second front end re-implementing the first.

So the engine exposes a catalogue of `Question` values and a validator, and
takes back a mapping of answers. It never prompts.

### A question carries facts, not sentences

Per #81. A `Question` has a key, a kind, the value currently in effect, the
options where there are any, and the numeric bounds where there are any. The
`description` comes from the pydantic `Field` it was derived from, which is
schema metadata rather than composed prose - the same text `config_template`
already emits, for the same reason.

### Conditions, rather than a plan recomputed each step

Choosing `openai` makes `embedding.api_key_env` relevant and a credential
necessary; choosing `fastembed` makes both meaningless. Two ways to express
that: regenerate the plan after every answer, or let each question carry the
condition under which it is asked.

The second, because a GUI needs it. A form showing every field at once has
to know which to hide, and it cannot do that by asking for the next question
- it has to evaluate a predicate against the answers so far. So:

```
Question(key="embedding.api_key_env", when=(("embedding.backend", "openai"),))
```

A terminal walks the list and skips what does not apply; a form binds
visibility to the same predicate. One description, two renderings.

### Credentials are not settings

They go to `credentials.toml` at mode 0600, which `settings.py` already
names and nothing reads back. A `secret` question's answer must therefore
never reach `config.toml`, and `config show` must never print one.

### What `config show` prints

The plan asks for valid TOML on stdout, with the warning about a missing
config file on **stderr**. That is so `kennis config show > config.toml`
produces a usable file rather than one with a warning in the middle, which
is the same reason `serve` may not write to stdout.

## What I expect to be uncertain or difficult

- **Deriving the catalogue from the model, or writing it by hand.**
  `config_template` already walks `model_fields` for descriptions, options
  and ranges. Deriving is less to maintain; writing by hand lets the setup
  ask five good questions instead of thirty dull ones. I expect a hand-picked
  *order* over derived *metadata*.
- **`config set` and type coercion.** A TOML value is typed and a command
  line argument is a string. Validation has to happen through the pydantic
  model rather than by guessing from the string's shape.
- **Writing config.toml without destroying comments.** `config_template`
  writes every key commented out; `config set` has to change one value and
  keep the rest of the file, which argues for editing lines rather than
  dumping a model.
- **Whether `init` re-run is destructive.** Brian wants it re-runnable. The
  current values have to be the defaults offered, so re-running and pressing
  return throughout changes nothing.
- **Testing a prompt.** `CliRunner` takes `input=`, so the terminal half is
  testable; the engine half needs no terminal at all, which is the point.

## What actually happened that I did not expect


**The empty answer meant two things, and only one of them was implemented.**
Throughout the setup an empty string means "unchanged, write nothing" -
`apply_answers` filters on exactly that. `_applies`, which decides whether a
conditional question is asked, read it the other way: `settled.get(key)`
returned `""`, which is not `None`, so the fallback to the value currently in
effect never ran and `"" != "openai"` skipped the question. The consequence
was not small. On any re-run where the user kept `openai`, neither the model
nor the API key was asked for, so **there was no way to change an API key
through the setup at all** - short of switching the backend to something else
and back. Every test passed. It was found by running the command twice, which
is the fifth step `rules.md` 5.2 was written for after the last two of
these. Concern #119.

**Deriving the catalogue won, but not for the reason I expected.** The sketch
guessed a hand-picked order over derived metadata, and that is what was
built - but the deciding factor was not maintenance. It was that
`validate_answer` has to give the same answer `load_settings` would give.
Building the candidate settings through the model and letting pydantic refuse
it is the only way to be sure of that; a hand-written check is a second
implementation of the constraint that can drift from the first.

**Three defects were wording, and running it was the only way to see them.**
The setup announced `warning: press return to keep the value shown in
brackets`, which is guidance and not something going wrong; `display.note`
prints `warning:`, so a new guarded `display.guidance` was added rather than
misusing it. The closing line read `run `kennis corpus init` create the
corpus` - `next_step` appends its `note` bare, so the connector is the
caller's to supply. And the config template said API keys were handled by
`kennis auth --help`, a command that `design.md` describes at line 762 and
that **does not exist** - the same class of defect as #82, a false claim in
text a user reads. Concern #120.

**Writing that rule down found four more, and the first fix for them was
wrong too.** Grepping every command name kennis prints turned up `kennis
index <collection>`, printed by two engine modules and a renderer and never
a command; `kennis corpus claim`, designed and unbuilt; and a bare `kennis
corpus remove`, which requires a handle. Correcting the first to `kennis
corpus index notes` passed the guard test written for it and still failed
when run, because `corpus index` takes `--collection` and no positional
argument. The guard checked that the *name* resolved. Only parsing the
invocation - `make_context` against the resolved command - answers the
question that matters, and it found the bare `remove` immediately. Concerns
#124 and #125.

Three existing tests had been written against the wrong strings rather than
catching them. A test that restates what its subject produces cannot
disagree with it; what worked here was checking the string against a
different authority, the command line's own parser.

**The count was of the wrong thing.** `Configured 5 settings` was printed
after a run that wrote one, because it counted questions asked. Counting what
was written makes the zero case say `Changed nothing`, which took two
attempts: `Kept every default` is false on a re-run, where what is kept is
the previous answers and those are not defaults.

**`--quiet` and a prompt.** The report lines are suppressed and the prompts
are not, because `click.prompt` writes directly. That is the right behaviour
- a suppressed prompt is a command that appears to hang - but it means
`kennis -q config init` is a contradiction rather than a non-interactive
path. `--defaults` is the non-interactive path. Concerns #121 and #122.

**Eleven injections, all caught, and two tests that needed rewriting first.**
`test_a_rejected_answer_is_asked_again` asserted `"fastembed" in output`,
which is true whether or not anything was re-asked, because the options are
listed with every prompt - the same hollowness as #63. It now counts prompts
and requires exactly two. `test_the_setup_asks_about_the_backend_first`
asserted only that the key appeared somewhere, testing nothing about
"first"; it now compares positions. Concern #123.
