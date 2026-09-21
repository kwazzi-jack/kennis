# Milestone 5, step 1: settings and the corpus lock

Milestone / step: `design/plan.md`, "Milestone 5", items 3 and 5, engine half.
Date: 2026-09-21

Previous sketch: `2026-09-21-m4e-names-not-phrases.md`. What it left: three
layers, with the engine holding facts and `render/` holding words.

## What I am about to do

Two modules the plan has marked `(planned)` since milestone 0 and that every
command needs before it can exist: the settings layer, and the lock that
stops two kennis processes writing to one corpus.

Milestone 5 has six items and splits like its predecessors:

| step | what |
|---|---|
| 1 (this) | `engine/settings.py`, `engine/locking.py` |
| 2 | the click group, the display and log sinks, and the read-only commands |
| 3 | the mutating commands, under the lock |
| 4 | `search` and `read` |
| 5 | `config`, `auth`, `remember` |

## How I expect it to work

### The library does not have the class the design names

Design section 13 specifies `ExactNameEnvSource` rather than
`env_nested_delimiter`. **That class does not exist in pydantic-settings
2.15.0**, and I checked before building on it, which is concern #33's habit.

The requirement behind the name is real, and I demonstrated it rather than
taking it on trust. With `env_nested_delimiter="_"`:

```
KENNIS_EMBEDDING_BACKEND      -> embedding.backend      works
KENNIS_EMBEDDING_API_KEY_ENV  -> embedding.api.key.env  matches nothing
```

The second is **silently ignored**. No error, no warning; the field keeps its
default. A user who set an environment variable and watched it do nothing
would have no way to find out why. So the source is written here: it walks
the model's own sections and fields and looks up `KENNIS_<SECTION>_<FIELD>`
by exact name, so a key containing an underscore is read correctly and a key
that does not exist is simply not found.

### The shape

```
engine/settings.py
  Settings            the sections, as nested pydantic models
  load_settings()     env > config.toml > default
  config_dir()        platformdirs, or KENNIS_CONFIG_DIR
  config_template()   the commented file, generated from the schema
engine/locking.py
  corpus_lock(root)   filelock, timeout=0, CorpusBusy on contention
```

### Only settings something reads

Design section 15 states the rule while retiring an example of breaking it:
*a setting nothing reads is hidden rather than offered*. So the sections here
are the ones with a reader today - `embedding`, `retrieval`, `corpus`,
`conversion`, `literature`, `logging` - and `ingestion.use_mcp_sampling`,
which the design itself marks deferred and hidden, is not among them.

Two of these close concerns opened earlier. `literature.request_delay` is the
value #42 made a parameter and could not yet make a setting. `retrieval.rrf_k`
is a constant in `search.py` that the design says is tunable.

### Concern #9, finally

Milestone 1 recorded that `Collection(root=...)` takes its root explicitly
and that "the settings layer will have to be plumbed through rather than
consulted", to be revisited "when settings exist, which is milestone 3 at the
earliest". Settings now exist.

**The answer is to keep threading it**, and the reason is now positive rather
than an accident of testability. Milestone 3 made the same choice for chunk
parameters under an argument that turned out to be forced: the vector cache
keys on the derivation binding, so the parameters must be a value at the
point the key is built, not a global something reads. The corpus root is the
same kind of thing one level up. Settings supply the **default at the edge** -
the command line resolves a root once and passes it down - and nothing below
the edge reads a global.

So #9 closes as a decision rather than a deferral.

### The configuration file is generated, never written by hand

`config init` writes every key, commented, at its default, with `Options:`
for a closed set, `Range:` for a bounded number and `Examples:` for a
free-form key. All three are derived from the model - a `Literal` yields the
options, `Field(ge=, le=)` the range, `Field(examples=[...])` the examples -
so the file cannot drift from what the model accepts.

**Commented, not live.** Writing defaults as active values freezes them at
install time, so a later kennis that improves a default would never reach
anyone who ran `config init`.

### Credentials are not settings

`config show` writes valid TOML to standard output by design, so a user
debugging will paste it into an issue. A key among the settings would make
every printing path need redaction, and redaction is what gets forgotten when
a new printing path is added. Credentials live in `credentials.toml` at mode
`0600`, which `config show` never reads - removing the requirement rather
than relying on remembering it. The `auth` commands are step 5.

### The lock

`filelock` with `timeout=0`, so a second invocation is told the corpus is
busy rather than waiting. `CorpusBusy` already exists from milestone 1 and
already names its resolution. The lock file sits beside the corpus and is not
committed.

## What I expect to be uncertain or difficult

- **Whether a `Literal` yields its options cleanly** through pydantic's
  `model_fields`, or whether I have to reach into `typing.get_args` on an
  annotation that may be wrapped in `Optional` or `Annotated`.
- **Round-tripping comments with tomlkit** when `config set` rewrites one key
  in a file the user has edited. This step only writes the template; the
  rewrite is step 5, but the template's shape decides whether it is possible.
- **`KENNIS_CONFIG_DIR` and test isolation.** Every test that touches
  settings must not read the developer's real config file, and the mechanism
  that guarantees that had better be the same one users get.
- **Whether the lock should cover reads.** A search while an index is being
  swapped in reads a directory that is being replaced. `replacing_directory`
  makes the swap atomic, so I expect not, but I want to have thought about it
  rather than discovered it.

## What actually happened that I did not expect

**The class the design names does not exist, and the problem it names is
worse than the design says.** I checked `ExactNameEnvSource` against
pydantic-settings 2.15.0 before building on it and found nothing of that
name. The design justifies avoiding `env_nested_delimiter` on grounds of
ambiguity; the actual behaviour is *silent loss*.
`KENNIS_EMBEDDING_API_KEY_ENV` splits as `embedding.api.key.env`, matches
nothing, and is dropped with no error and no warning. So is
`KENNIS_RETRIEVAL_DEFAULT_TOP_K`. The keys it loses are the ones with
descriptive names, which is most of them. Concern #85, and the fourth time
#33's habit has paid.

**Injecting the lock defect hung the suite for ninety seconds**, which is
both correct and instructive: the defect is blocking, so the test for it
blocks. Every concurrency defect has that shape - found by waiting - which is
why the cross-process test bounds its subprocess instead of trusting it to
return. Concern #86.

**Concern #9 closed as a decision rather than as a deferral, and the reason
came from milestone 3 rather than from here.** Chunk parameters had to be a
value because the cache keys on the derivation binding at the point the key
is built. The corpus root is the same kind of thing one level up, and the
argument generalises: an engine that reads a global is an engine two callers
cannot use differently in one process, which the MCP server serving several
workspaces will be. So configuration is resolved at the edge and threaded
down, and `load_settings` having no caller inside `engine/` is the correct
state rather than an oversight. Concern #87.

**Two of my predicted difficulties were not difficult and one did not come
up.** `Literal` options come out of `get_origin`/`get_args` cleanly, and the
`ge`/`le` bounds are readable from `field.metadata` without unwrapping
anything. Test isolation through `KENNIS_CONFIG_DIR` worked first time, and
using the same override users get - rather than a test-only back door - means
the isolation mechanism is one that is actually supported.

**I had not expected ruff to object to typing pydantic's own objects.**
`ANN401` forbids `Any` in a signature, and the base class's
`get_field_value(self, field: Any, ...)` is pydantic's own shape. Importing
`FieldInfo` and naming the real type was the fix, and it is better: the
helper functions that read `field.metadata` and `field.examples` now say what
they are reading.

**The lock question I flagged answered itself.** I wondered whether reads
need the lock. They do not: `replacing_directory` makes the index swap atomic,
so a search either sees the old directory or the new one, and a reader that
took the lock would be refused during every build for no benefit.
