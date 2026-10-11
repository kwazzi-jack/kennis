# 12b. Settings: kennis's own configuration

Milestone / step: milestone 12, second half (`design/plan.md`), #410
Date: 2026-10-11

## What I am about to do

The second part of the settings page: kennis's configuration - the
settings the command line and the MCP server read too - written through
`engine/setup.py::apply_answers`, the writer `kennis config set` and
`config init` already use. Every setting says what a change costs; a
change that needs a rebuild offers to rebuild now, later, or to undo; a
credential shows only its variable's name and whether it is set; the
converter says whether MinerU is installed and, if not, the command that
installs it.

## How I expect it to work

**The questions are the engine's.** `setup_questions()` is the catalogue
`config init` walks, with the options, bounds, descriptions and current
values taken from the pydantic fields; its docstring already expects a
form to show them all and bind visibility to each question's `when`.
The page shows `questions_for(current)`; changing a choice re-fetches the
section through htmx with the form's values, so `questions_for(form)`
decides what applies - one rule, two renderings. Without a script, the
section is what applies to what is saved, and saving with a new backend
draws that backend's questions next.

**The cost is engine data** (#410): `engine/setting_costs.py`,
`costs_of(key, value) -> tuple[SettingCost, ...]` over
`next_search | next_add | rebuild | leaves_machine`. By value as well as
key, because `conversion.backend = datalab` and
`embedding.backend = openai` send text off the machine and the other
values do not. A test asserts every question in the catalogue has a cost
- a new setting with none fails. The words are in `render/settings.py`,
exhaustively matched, so `config set` can print the same line, and does:
the cost is not the window's.

**Saving.** `POST /settings/kennis` validates every answer with
`validate_answer` first and draws the section again with each refusal
beside its field and nothing written - `apply_answers` validates the
whole set too, but the page should say which field. Empty means keep, as
in `config init`. Secrets are password inputs, never pre-filled; the row
says `OPENAI_API_KEY: set` or `not set`, from
`setup.credential_status(key)` - the variable a key is read from is the
engine's to name.

**After a change that needs a rebuild**, the answer carries a panel:
what changed, that every index keeps using the model it was built with
until it is rebuilt - named per collection from the index's own
`binding.json` (a new `rag/index.py::read_binding`) - and three
controls: rebuild now (the existing `POST /index`, a job in the strip),
later (closes the panel), and undo (posts the previous values back, which
the panel carries as hidden fields).

**The converter row** asks `default_converter()` for its name,
`is_available()` and `install_hint()`; the words for each converter's
name ("MinerU (local)", "Datalab (hosted)") are the window's.

**`corpus.root` is not on the page.** Changing it from a window that is
showing that corpus moves the ground under every open page and every
running job; it stays a command-line setting.

## What I expect to be uncertain or difficult

- The secret questions have no `current`, and `credential_status` must
  name the variable the reader will actually be asked about.
  `setup._KEY_VARIABLES` writes `OPENAI_API_KEY` while embedding reads
  `settings.embedding.api_key_env`, so a renamed variable would be
  written where nothing reads it. Log it; do not fix it here.
- `validate_answer` validates one answer against the *saved* settings;
  two answers that are only valid together (a backend and its model)
  may be refused one at a time. Measure.
- Where the cost words go on a command line without crowding `Set x = y`.

## What actually happened that I did not expect

- **`validate_answer` one at a time was sound here.** The settings have
  no cross-field validator, so no pair of answers is valid only together.
  The pair that *should* be checked together, a backend and its model,
  is not checked by anything (#441).
- **The browser refuses a bad number before the server does.** The
  number fields carry the engine's own bounds as `min` and `max`, so a
  chunk size of 0 never leaves the page. The server's refusal path
  remains for a request without a script, and the tests drive it.
- **A filter enforced twice.** `answers_in` dropped keys the catalogue
  does not hold, and `changed_answers` only writes keys from `offered`.
  Removing the first filter was an inert injection (#318's shape).
  Only `offered` decides now, and an injection there is caught.
- **The cost lines read as reports of the present.** "Every index keeps
  its old setting until it is rebuilt", printed beside an unchanged
  value, sounds like news. Each cost now says what a change does
  ("takes effect in each index only once it is rebuilt"), which reads
  correctly both beside a field and after `Set chunking.size = 900`.
- **A hosted backend's cost was set like the others.** In the first
  screenshot the line "sends document text to a third party" was the
  same italic as "takes effect at the next search". It is now drawn in
  the warning role, measured as #8A5A00 in light and #D9A441 in dark.
- **The key's field is left out of a redraw.** A redraw is a GET, and
  `hx-include` on the whole form would have put a typed key into the
  address, the history and the access log. Only the fields marked
  `data-redraw` are included, and a test reads the selector from the
  page to check this. A key typed before changing a backend is lost on
  the redraw. That is the price, and it is the right way round.
- **`credential_status` and the writer disagree** about which variable
  holds the embedding key once `api_key_env` is changed (#440).
- The bundle's index is not listed in the rebuild panel. It is lexical
  by design, but `chunking.size` reaches it too. The panel lists
  corpus collections only.
- 21 injections in all: 20 were caught, and the inert one led to
  removing the duplicated filter.
