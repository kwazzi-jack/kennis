# v0.4 unit 8a: the server, its instructions, and the stdout invariant

Date: 2026-09-27

## 1. What I am about to do

The first vertical slice of the MCP server: `kennis serve` starts a
FastMCP server whose `instructions=` block describes *this* installation,
with one tool registered so the wire can be tested end to end.

Three pieces, and the third is the one that outranks the others.

- **The holdings rendering**, shared. Design section 11 says the generated
  half of the instructions block is built from each installed pack's
  `name` and `description`, and that **the same bytes appear in `kennis
  pack list`**, so what a user reads and what a model reads cannot drift.
- **`list_corpus`**, as the first tool. Read-only, needs no index, and it
  is what an agent calls to learn what exists before filtering a search.
- **`test_serve_writes_nothing_to_stdout`**, which the design names
  itself: under `kennis serve`, stdout is the JSON-RPC wire. boepie lost a
  session to 567 bytes of INFO from a module-level
  `Console(file=sys.stdout)` and got back `Invalid JSON: trailing
  characters at line 1 column 5`.

## 2. How I expect it to work

```
render/packs.py      describe_holdings(packs) -> tuple[str, ...]
                       shared: the instructions block and `pack list`
mcp/instructions.py  instructions_for(packs) -> str
                       the generic half, plus describe_holdings
mcp/tools/corpus.py  list_corpus
mcp/server.py        build_server(corpus_root) -> FastMCP
cli/commands/serve.py  kennis serve
```

**`pack list` changes**, and that is the point rather than a side effect.
It prints the id, version and file count today and neither the name nor
the description, so section 11's shared-bytes claim is not true of the
code as it stands. Both sides now call `describe_holdings`, and the test
is that byte-identity rather than either one's prose.

**The generic half lives in `mcp/`, not `render/`.** `render/` is words
for every front end; the instructions block is words for exactly one, and
an MCP front end is entitled to phrase its own. What it must not do is
compose the holdings itself, which is why that half is in `render/`.

**The stdout test runs a subprocess.** In-process capture would prove
nothing about a library that writes at import time, which is the failure
mode being guarded. So: spawn `kennis serve`, speak enough JSON-RPC to
call a tool, and assert every byte on stdout parses as protocol.

**The engine stays synchronous** (section 20). fastmcp accepts sync
tools, so the tools are `def` rather than `async def` and nothing in
`engine/` learns about the event loop. boepie's are `async def`; that is
a difference I am taking deliberately rather than porting.

## 3. What I expect to be uncertain or difficult

- Whether fastmcp 3.4.7 accepts a plain `def` tool. The pin is the
  version boepie ran, and boepie's tools are all async, so this is
  untested territory for the pin rather than for fastmcp generally.
- How much JSON-RPC I have to speak by hand for the stdout test. fastmcp
  ships an in-process client, but an in-process client cannot see what a
  subprocess writes to fd 1, which is the whole point. I expect to write
  the initialise/initialized/tools_call handshake by hand and for that to
  be the fiddliest part of the unit.
- Whether `list_corpus` should need a corpus at all. A fresh machine has
  none, and an agent calling the tool then gets an exception where a
  sentence would serve it better. I think the tool answers "there is no
  corpus, run `kennis corpus init`" rather than raising, but I want to
  see the error path before deciding.
- Whether changing `pack list` breaks the milestone 7 tests in a way that
  says I have the shared rendering wrong rather than merely different.

## 4. What actually happened that I did not expect

**The invariant test was hollow, and injecting into it is the only
reason I know.** Both stray prints - one at import time, one inside a
tool - went straight through a green test. The cause is buffering:
stdout to a pipe is block-buffered, so a `print` in a short session sits
in an 8 KiB buffer and is *discarded* when the process exits. The
offending line never appears and the test passes. A print with
`flush=True` was caught, which is how I found it. The session now sets
`PYTHONUNBUFFERED=1`, so every write lands immediately and the guard
holds whether or not an offender flushes; in a real session the buffer
fills and flushes eventually, so the risk was always the same and only
the test's ability to see it differed. All four injections are caught
now. This is the milestone's most important test and it proved nothing
for the first hour of its life.

**`cli/context.py` had to move, and its own docstring said so.** The
MCP server needs to know where the corpus is, and importing
`kennis.cli.context` to find out would make the command line the real
kennis and this a wrapper. The module imports nothing from a front end
and its docstring already anticipated this - "the MCP server serving
several workspaces will be exactly that" - so it is now
`kennis/context.py`, beside `logs.py`, which is where the other
front-end-agnostic edge already lives. Six importers, all mechanical.
`tests/test_architecture.py` gained the matching invariant: nothing
under `mcp/` imports `cli/`.

**A synchronous tool needs the pipe held open.** My first session wrote
the whole conversation and closed stdin, and the tool call was never
answered while the handshake and `tools/list` were. fastmcp dispatches
a sync tool to a worker thread, and EOF on stdin shut the server down
before that thread finished. It looked like a broken tool and was a
broken test. The answer was a reader thread and a pause between
messages, not an `async def`: the engine is synchronous by design and
the tool works.

**`filterwarnings = ["error"]` caught me leaking three pipes.** The
`Popen` had no context manager, and the ResourceWarning failed four
tests for a reason that had nothing to do with the server. The strict
filter earning its place twice in two days.

**Two output defects found by reading rather than asserting.** fastmcp
prints an ASCII-art logo and an upgrade notice at startup - to stderr,
so the wire is safe, but stderr is where an agent's client collects
diagnostics and a logo is not one. Suppressed with `show_banner=False`.
And the generated block said "holds" twice: `## What this kennis holds:`
followed by `This kennis holds:`, with a stray colon on the heading.

**`pack list` was wrong in a way no test covered.** Section 11 says the
holdings lines are the same bytes `pack list` prints; `pack list`
printed the id, version and file count and neither the name nor the
description, so the claim was simply untrue of the code. Both sides now
call `describe_holdings`. Running it then showed the continuation line
sat at the id column's indent, so a one-word pack name read as another
pack id - aligned under the version column now, and there is a test for
the indentation because no assertion about content would have caught
it.
