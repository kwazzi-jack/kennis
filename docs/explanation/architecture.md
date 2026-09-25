# Three layers

kennis is built as three layers with a one-way dependency, and the rule is
enforced by a test rather than by convention.

```
cli  ->  render  ->  engine
```

Nothing points back. A test walks the imports of every module and fails if
one reaches the wrong way.

## The engine knows what is true

Everything kennis can do lives under `kennis.engine`. It returns typed
results and raises domain exceptions. It never prints, never formats for a
particular interface, and never imports one - no `click`, no `rich`, no
`prompt_toolkit`.

Progress leaves through an event stream. An operation emits events; a front
end subscribes. Nothing in the engine knows what a progress bar is, which is
what lets the same indexing run report itself to a terminal, to a log, or to
nothing at all.

## The render layer chooses the words

`kennis.render` turns engine values into English. It may read the engine; the
engine may not read it.

This exists because of a rule that is easy to state and easy to violate:

!!! quote "The engine names things; it does not phrase them"
    Where a value already carries the facts as fields, it must not also
    carry a sentence built from them.

A sentence built in the engine is the one a front end would otherwise reach
for, and once it exists the command line can no longer restyle it, rewrap it,
or combine it with anything else. So `SearchResult` carries a score, a rank
and a chunk index; the phrase "relevance: high" is composed in `render`.

Three things are exempt, because each is quoted rather than composed: a
resolution that is a command string, an error's message, and text kennis is
repeating from a document.

## The command line decides the layout

`kennis.cli` handles arguments, indentation, colour and terminal width. It is
one front end and is not privileged - the MCP server planned for a later
version is another, and a graphical interface would be a third.

This is why a colour is named by role rather than by hue. `identifier`,
`md_fence`, `operation` are roles; the theme maps them to one of the eight
standard ANSI colours, never a 256-colour index and never a hex value, so
kennis's output resolves against whatever palette you have set.

## Why it is worth the discipline

The practical test is whether a second interface would be a *rendering* or a
*reimplementation*. The guided setup makes this concrete: which questions to
ask, and the knowledge that `openai` needs an API key while `fastembed` does
not, live in the engine. The command line only prompts. A web form would ask
the same questions in the same order without importing anything from `cli`.
