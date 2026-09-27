# v0.3 unit o: a diagnostic names its condition, render says the words

Date: 2026-09-27

## 1. What I am about to do

Concern #285. `Diagnostic.message` is a finished English sentence built
inside `engine/`, and `cli/sink.py` passes it straight to
`display.note()` - so for this one event type `render/` is bypassed
entirely and the three-layer discipline does not apply. Six sites do it.

Brian's framing, which I am adopting: a vocabulary of conditions, like
HTTP status codes - the engine defines what the condition *means* and
the front end decides how to convey it.

One refinement, which is the whole design question. **A bare code is not
enough.** `404` carries no URL; the useful part of an HTTP response is
the code *and* the body. If a diagnostic were only `"metadata-
unavailable"`, the identifier would be gone and a front end could say
nothing specific. So each condition is a small typed value carrying its
own fields, and the stable string code rides along for anything that has
to serialise - which is v0.4, the MCP server, and the reason to do this
now rather than after.

## 2. How I expect it to work

`Diagnostic` keeps its shape and loses one field:

```
Diagnostic(severity: Severity, detail: DiagnosticDetail, resolution: str | None)
```

`DiagnosticDetail` is a union of six frozen dataclasses, one per
condition, each with a `code: ClassVar[str]` and the fields that
condition has:

| code | fields | emitted from |
|---|---|---|
| `document-unsearchable` | `problem`, `path` | `rag/loaders.py` |
| `frontmatter-unreadable` | `path` | `context/index.py` |
| `title-dot-stripped` | `title` | `corpus/add.py` |
| `document-skipped` | `problem` | `corpus/add.py` |
| `metadata-unavailable` | `identifier` | `corpus/add.py` |
| `no-pages-discovered` | `base_url`, `mode`, `path_prefix` | `corpus/add.py` |

`document-unsearchable` and `document-skipped` are separate conditions
although both are an unreadable document, because the consequence
differs and the consequence is what the sentence is about: one will not
be searchable, the other was left alone.

`severity` stays on the envelope rather than moving onto each condition.
It is orthogonal - it says how loudly to say a thing, not what the thing
is - and it is what `sink.py` already switches on to choose `warning:`
against `hint:`.

`render/diagnostics.py` gains `describe_diagnostic(detail) -> str`, a
`match` over the union. mypy checks it for exhaustiveness, so a seventh
condition added later without a sentence fails the type check rather
than reaching a user as a blank line.

`cli/sink.py` calls it. That is the only change there: the severity
switch is untouched and the resolution still prints beneath.

## 3. What I expect to be uncertain or difficult

- Whether `severity` really belongs on the envelope. Every one of the
  six is a WARNING today, so the field is carrying no information and I
  cannot tell from the current code whether that is a coincidence or the
  rule. I am keeping it because removing it is a decision I can take
  later with evidence, and adding it back is not.
- The two "unreadable document" conditions take a `problem` string that
  is composed somewhere else. Splitting that further is a bigger job
  than this one and I expect to leave it, which means this unit removes
  the composition at six sites but not the sentence fragment two of them
  carry. Worth being honest about rather than claiming a clean result.
- Whether mypy actually catches a missing `match` arm here, or only
  warns on an unreachable one. If it does not, the exhaustiveness claim
  is worth nothing and the test has to do it instead. I will inject a
  missing arm and find out rather than assume.

## 4. What actually happened that I did not expect

**mypy does enforce it, and I checked rather than claimed.** Section 3
said the exhaustiveness argument is worth nothing if mypy only warns on
an unreachable arm. Two injections: removing a `case` from the match,
and adding a seventh member to the union with no arm for it. Both were
type errors. So the claim in the module docstring is one I have watched
fail.

**There was a seventh consumer I had not found.** `src/kennis/logs.py`
reads `event.message` to write the log file, and it is neither `engine/`
nor `render/`, so neither architecture test covers it and my survey of
"six sites" was a survey of *emitters* only. mypy found it immediately.
It now logs `code: sentence` - the code is what a reader greps for
across runs and the sentence is what tells them what it meant, and
having both is better than the sentence alone, which is what it had.

**Eleven existing tests asserted on the prose**, which I had not counted
and which is the real measure of how far the sentences had spread.
Rewriting them is what the change is *for*: `assert "dot" in
diagnostics[0].message` became `assert diagnostics[0].detail ==
TitleDotStripped(title=".bashrc")`, which says what the engine decided
rather than what a sentence happened to contain.

**One of those rewrites found a fact the substring hid.** The old
literature test asserted `"2101.11270" in message`, which passes whether
the identifier is `2101.11270` or `arXiv:2101.11270`. The typed
assertion failed and showed it is the second. Nothing is wrong with
that - the engine carries the identifier as the caller gave it - but the
test now records which, where before it could not tell.

**`beneath` became dead code in the engine**, and ruff said so. It was
the sentence fragment `" under '{prefix}'"`, built in `add.py` purely to
be interpolated into prose. Its disappearance is the clearest single
sign the change did what it was for: the engine now carries
`path_prefix` as a field and has nothing left to say about it.

**The terminal output is byte-identical.** I checked by running `kennis
corpus add -n .bashrc.md` and comparing. That was the intent - this is a
refactor of where words are chosen, not a change to the words - but it
is worth having confirmed rather than assumed, because a silent change
to every warning in the program would be a poor thing to discover
later.
