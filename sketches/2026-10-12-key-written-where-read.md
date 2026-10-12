# A key is written under the variable it is read from (#440)

Milestone / step: engine fixes logged during milestones 12 and 13 (#440)
Date: 2026-10-12

## What I am about to do

Make the setup file an API key under the name its reader asks
`credential` for, so that `config init` and the settings page never
report a key as saved that nothing will read.

## How I expect it to work

Today two tables answer one question. `credential_status(key)` names
the variable the reader consults: `settings.embedding.api_key_env` for
embedding, `DATALAB_KEY_VARIABLE` for conversion. `_write_credentials`
asks `_KEY_VARIABLES[_backend_for(key)]` instead, a fixed
`OPENAI_API_KEY`. They agree only while `api_key_env` is its default.

One function, `_key_variable(key, settings)`, answers it, and both
callers ask it. **The writer passes the settings the answers produce**,
not `load_settings()`: `apply_answers` validates the merged answers
first, and if the same answers change `embedding.api_key_env` the key
belongs under the new name. `credential_status` passes the settings in
force. `_KEY_VARIABLES`, `_backend_for` and the `"API_KEY"` fallback go,
because a secret key the function does not know is a defect that should
raise, not a key filed under a name nobody reads.

`credential` searches every section of `credentials.toml` for the
variable, so the section the writer files it under does not matter to
the reader. It stays the key's own section for a person reading the
file.

Tests, through `apply_answers` and read back with `credential`, which
is the reader's own call rather than a look at the file:

- with `embedding.api_key_env` set beforehand, the key is read back
  from that variable and not from `OPENAI_API_KEY`;
- with the variable and the key in the same answers, the key is read
  back from the new variable;
- `credential_status` says `is_set` afterwards. That is the property the
  page relies on.

## What I expect to be uncertain or difficult

- Whether `embedding.api_key_env` passes through `_validated` and
  `_write_config` as an ordinary answer. It is not in the catalogue, but
  `_field_of` reads the model, so it should.
- An existing `credentials.toml` that holds the key under
  `OPENAI_API_KEY` while `api_key_env` names something else. The fix does
  not move it. Nothing reads it there now, and moving a secret between
  names without being asked is the kind of repair that surprises.

## What actually happened that I did not expect

- **The writer's choice of settings cannot be tested, because it cannot
  matter.** Injected: the writer asking `load_settings()` instead of the
  settings the answers produce. Nothing failed, and not because the test
  was hollow: `apply_answers` writes `config.toml` before the
  credentials, so by then the settings in force already hold the new
  variable. The comment claiming the difference was removed (#318); the
  test stays, as a statement of the outcome.
- **A new section would have been a silent regression.** The first draft
  filed every key under `[keys]`. `credential` returns the first section
  holding the name, and `[embedding]` sorts before `[keys]`, so a key
  written by an earlier version would have kept answering after a new
  one was saved. Caught before the run, and a test now writes an old
  `[embedding]` key and replaces it.
- Injections: three, two caught, one inert as above.
- Brian's `config.toml` sets no `api_key_env`, so his key was never
  misfiled. `credentials.toml` itself is behind a deny rule and was not
  read.
