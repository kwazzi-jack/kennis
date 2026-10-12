# The configuration file holds every setting (Brian, 2026-10-12)

Milestone / step: a decision following #441's report
Date: 2026-10-12

## What I am about to do

Make every write of the configuration produce the whole file: every
setting of every section, with its value, including values equal to
the default. `config init` on an existing file warns that it will be
replaced and asks first. Brian's reasons: a person expects the value
they chose to be the value saved, and a complete file can be synced
between machines. Compatibility and deprecation start at v1.0.0, so a
default kennis later changes need not reach a file that holds it.

This reverses a rule stated in three places: `config_template` writes
defaults commented out, `_write_config` merges only the answers, and
both front ends write nothing for an answer equal to the value in
force.

## How I expect it to work

**One renderer.** `settings.config_document(sections)` writes every
section and key with the comment lines `config_template` writes now
(description, options, range, examples), followed by the key as an
**active** line. `config init --defaults` writes it at the defaults.
Writing it at the defaults replaces the commented template.

**One writer.** `setup._write_config(answers)` builds the values as:
each section's defaults, then the file's values, then the answers. The
**environment is not a source**: an exported `KENNIS_EMBEDDING_BACKEND`
is a one-off override, and writing it into the file would make it
permanent. `Settings.model_validate` reads the environment (measured), so
each section is validated through its own model class (`EmbeddingSettings`
and the rest), which does not. Every writer goes through `apply_answers`:
`config set`, `config init`, the settings page and the backup folder.
So all of them leave a complete file.

**`config init` on an existing file** says the file will be replaced,
and that every value will be written including defaults, then asks
`click.confirm` with default No. That is the conventional default for
replacing a file. The questions still offer the values in force, so
pressing return throughout reproduces the configuration. `--defaults`
asks the same, because it now replaces the file too.

**What stays.** `Question.current` and `suggested` stay. The window
still compares with `current` to decide what *changed*, because that
decides whether a rebuild is offered and what Undo restores. It only
stops deciding what is written. The command line reports the changed
settings as now, and says the file was written in full.

**Tests:**
- `config set` on no file leaves a file that parses to every key of
  every section.
- An environment override is not written into the file.
- `config init` accepting everything writes the defaults as active
  values.
- `config init` on an existing file asks, and No leaves the file
  byte-identical.
- The window saving the form as drawn writes the full file. This
  reverses `test_an_unchanged_value_is_not_written`.
- `--defaults` output parses, and every key is active.

## What I expect to be uncertain or difficult

- Tests that assert a file is absent or holds only some keys
  (`config show` printing "defaults", `saved() == {}`, settings tables).
  Each is an assertion of the old rule, to be changed rather than
  worked around.
- `corpus.root` defaults to `""`, which kennis resolves at read time to
  the platform's data directory. Written as `""` it still means "the
  default place", so a synced file does not carry one machine's path.
- `backup.folder` is a path on one machine, and syncing it carries that
  machine's path. That is Brian's sync to decide, not this unit's.
- The order and formatting of a hand-edited file are lost when kennis
  rewrites it. The confirmation names that.

## What actually happened that I did not expect

- **The window wrote nothing on an unchanged save, by a second route.**
  The engine now writes the whole file whenever it is asked. But the
  route called `apply_answers` only when something had changed, so
  saving the page as drawn still left no file. The route now writes
  whenever nothing was refused, and "Nothing was changed, so nothing was
  written" became "Saved. No value was changed."
- **`config_template`'s string quoting would not have survived the
  change.** It wrote `f'"{value}"'`, which was harmless while every
  default was a plain word and commented out. With real values active, a
  Windows `backup.folder` or a quote in a folder name would have made the
  file unreadable. One escaping `toml_value` now serves both writers.
- **The confirmation's default needed its own test.** The test answering
  `n` passed whatever the default was. It now presses Return, so it is
  also a test that Return keeps the file.
- One test asserted the old rule as a side effect: the test that
  `corpus.root` cannot be written from the page also asserted the file
  stayed empty. Its real property is now asserted against the file,
  because the fixture's environment answers `load_settings`.
- Injections: eight, all caught.
