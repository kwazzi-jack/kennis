# A model belongs to its backend (#441)

Milestone / step: engine fixes logged during milestones 12 and 13 (#441)
Date: 2026-10-12

## What I am about to do

When the embedding backend is changed, offer that backend's own default
model and vector width, instead of keeping the previous backend's. Then
choosing OpenAI in `config init` or on the settings page writes a model
OpenAI serves. Today it keeps `BAAI/bge-small-en-v1.5`, which fails only
at the next index.

## How I expect it to work

**Two values per question, not one.** `Question.current` is what is in
force, and both front ends treat an answer equal to it as unchanged and
write nothing (`config._ask`, `configuration.changed_answers`). If the
suggestion went into `current`, accepting OpenAI's default would write
nothing and leave the wrong model in force. So `Question` gains
`suggested`: what a prompt defaults to and a field is drawn with.
`current` keeps deciding what is written.

**The rule.** The catalogue already asks `embedding.model` once per
backend, each under a `when` naming that backend. For a question whose
`when` names an embedding backend other than the one in force,
`suggested` is that backend's default if it has one. Otherwise
`suggested` equals `current`. A model name means something only to its
backend, so any in-force model belongs to the backend in force, and the
rule does not need the concern's narrower condition ("still the previous
backend's default").

**The defaults** live beside `EmbeddingSettings` in `settings.py`, as one
table: fastembed `BAAI/bge-small-en-v1.5` 384, ollama `nomic-embed-text`
768, openai `text-embedding-3-small` 1536. The field's own default reads
the fastembed row, so the two cannot drift.

**Dimensions too.** `embedding.dimensions` is asked only under
fastembed. It is a declaration of the model's width, not a request,
because no backend is passed it. It is recorded in `binding.json` and
used to shape an empty matrix. A switch to OpenAI that kept 384 would
record a false width beside 1536-wide vectors. So it is asked under each
of the three backends, with the same per-backend suggestion.

Front ends: `config init` prompts with `default=question.suggested` and
still compares with `current`; the window draws `answers.get(key) or
question.suggested`. The window's redraw sends only the backend selects,
so the model field arrives with the new suggestion.

## What I expect to be uncertain or difficult

- The CLI tests feed `config init` a fixed sequence of answers, and an
  extra dimensions prompt under openai shifts every later answer by one.
- Whether a front end reads `current` for display anywhere besides these
  two places.
- A person who already has the broken pairing (openai with a fastembed
  model in force) is not helped. The model question under openai, the
  backend in force, suggests the model in force. Catching that needs
  knowledge of which models a backend serves, which kennis does not
  have.

## What actually happened that I did not expect

- **The window's test asked a question the page never asks.** Every test
  passed and the browser still showed `BAAI/bge-small-en-v1.5` under
  OpenAI. The redraw includes every `[data-redraw]` field, so the model
  field travelled back holding fastembed's model, and the window read it
  as typed. The test had sent the backend alone. A `redrawn_from` helper
  now builds the request from the drawn form as htmx does, which is
  #432's rule ("submit the form the page drew") applied to a GET.
- **What the person typed and what the page offered look alike in a
  request.** The window now treats a field holding one of the page's own
  offers for that key (the value in force, or another backend's model or
  width) as unanswered, and anything else as typed. Treating only the
  value in force as an offer was not enough: ollama and then OpenAI kept
  ollama's model, which the field held by then. Leaving the conditional
  fields out of the redraw would have been simpler, and would have
  discarded a typed model whenever any other choice on the page changed.
- **The walk raced the page once.** Choosing a backend within
  milliseconds of the previous redraw sent nothing, because htmx had not
  yet bound the new select. Half a second between choices, which is
  still faster than a person, and every switch redrew. Saving before a
  redraw arrives would write the old model with the new backend. That is
  the same window, and too narrow to act on.
- Not helped, as expected: a configuration already holding openai with
  fastembed's model. The width is still never checked against the
  vectors, which `docs/how-to/embedding-backends.md` already says. Its
  `config set` recipes now set the width too, because `config set`
  offers nothing.
- Injections: twelve, all caught (nine in the engine and both front
  ends, three in the window's reading of a redraw).
