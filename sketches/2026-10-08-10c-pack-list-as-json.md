# `kennis pack list --json`

Milestone / step: 10c, rewritten - Brian reversed #401 on 2026-10-08
Date: 2026-10-08

## What I am about to do

Give `pack list` a `--json` option whose stdout is one JSON document built
from a pydantic model, so boepie reads fields instead of matching the
id column of a layout meant for a person. Supersede #401 and rewrite 10c.

## How I expect it to work

1. `list_command(as_json)` -> when set, `display.send_diagnostics_to_stderr()`
   first, before `existing_corpus()`, because the refusal that matters most
   ("no corpus") is raised there and `KennisGroup` prints it through
   `display.failure` -> `_diagnostic` -> stdout. The flag reroutes
   `_diagnostic` for the rest of the process; nothing else is printed in
   this mode, so stdout is the document or empty.
2. `list_installed(corpus_root)` -> `PackListing`, unchanged.
3. `render/machine_readable.py::pack_list_document(listing)` ->
   `PackListDocument(schema=1, packs=[ListedPack...], unreadable=[...])`,
   packs sorted by id as the rows are. A `ListedPack` carries facts, not
   the holdings sentence: `id`, `version`, `files` (count), `verified`,
   `name` and `description` (both None when the declaration will not
   parse). render/ because a JSON document is one more output form and the
   engine does not format; pydantic is already a dependency and is not an
   interface library, so the render import rule holds.
4. `display.plain(document.model_dump_json(indent=2))` - `plain` is the
   existing unstyled, unguarded write, so `--quiet` does not empty the
   payload (quiet suppresses a report, and this is not one).
5. Failure: exit 1, `error:` and `hint:` on stderr, stdout empty.

Tests: parse stdout with `PackListDocument.model_validate_json` for one pack,
none, and an unreadable directory; no corpus gives exit 1 and an empty
stdout; `--quiet --json` still prints; and one real subprocess, because
`CliRunner` mixes the streams unless asked not to and rich's console is
bound to the real stdout at import.

## What I expect to be uncertain or difficult

- Whether rich's `print` of a long line with `soft_wrap=True` is truly
  byte-faithful when stdout is a pipe (no wrapping, no markup parse).
  The subprocess test is what answers that.
- `CliRunner` and a module-level `Console` bound at import: whether the
  runner's stdout capture sees rich's output at all, or whether the
  existing tests rely on rich resolving `sys.stdout` lazily.
- `schema` as a field name shadows `BaseModel.schema` (deprecated v1
  method); pydantic may warn. Name it `format_version` if it does.

## What actually happened that I did not expect

- **The subprocess test was hollow as first written, twice over.** With no
  pack installed the document has no string containing a space, and with
  the stimela name (19 characters) rich moved the string whole onto its
  own 20-column line. rich wraps at a space, so every break fell between
  two JSON tokens and the wrapped document parsed. Caught only by
  switching `soft_wrap` off and watching the test pass; it now carries a
  31-character description and fails under that injection. Third instance
  of #352.
- The other two uncertainties did not bite. `CliRunner` sees rich's output
  because rich resolves `sys.stdout` at write time, and `click` 8.5 keeps
  `stdout` and `stderr` apart on the result. The field is
  `format_version` from the start, so whether pydantic warns about
  shadowing `BaseModel.schema` was never tested.
- Errors print on **stdout** in kennis (`display.failure`), and the
  failure for "no corpus" is printed by `KennisGroup` after the command
  has raised. So the reroute has to be module state that outlives the
  command, cleared by `set_verbosity` at the next invocation - a context
  manager inside the command would have exited before the error was
  printed.
