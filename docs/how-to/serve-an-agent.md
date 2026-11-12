# Serve an agent

`kennis serve` runs an MCP server over stdin and stdout, so an agent -
Claude Code, VS Code, Copilot - can search the corpus, read what it
finds, and write a note back.

```
kennis serve
```

It is started by the agent, not by hand. Running it in a terminal gives you
a process waiting for JSON-RPC, and nothing else: **standard output is the
protocol**, so the command prints no banner, no report and no confirmation.

Install the extra first, since the server is not part of the base package:

```
uv tool install "kennis[mcp]"
```

Without the extra, `kennis serve` refuses with one line on standard error
naming this command, and the agent reports only that the connection closed.

The agent keeps the server it started for as long as its session lasts, so
after upgrading or reinstalling kennis, restart the agent's session (in
Claude Code, `/mcp reconnect kennis`). Until then, its server is still the
earlier installation's code, and every tool refuses, saying the process was
started before kennis was reinstalled.

## Point an agent at it

For Claude Code, add it to `~/.claude.json`:

```json
{
  "mcpServers": {
    "kennis": {
      "command": "kennis",
      "args": ["serve"]
    }
  }
}
```

Any client that speaks MCP over stdio works the same way: the command is
`kennis` and the argument is `serve`.

## What the agent is told

The server's instructions are **generated from the packs installed on this
machine**, not written in advance. An agent is told about the knowledge that
is actually here - which collections hold something, which packs declared
it, what the corpus is for - rather than about kennis in the abstract.

Install a pack, restart the agent, and the description changes. See
[Author a pack](author-a-pack.md).

## The six tools

| tool | what it does |
|---|---|
| `list_corpus` | what the corpus holds, per collection or in summary, with each docs project's versions |
| `search` | search the collections its `collections` argument names, among them this project's `.context/` bundle, or all of them |
| `read` | read passages from notes, literature or documentation, several at once |
| `cite` | a citation, its reference and its `kennis://` link for each passage cited, several at once |
| `remember` | write one note |
| `tag` | tag passages or documents, or take tags off them, several at once |

`search` answers in one group per collection, each ranked on its own, as
`kennis search` does. Its arguments:

| argument | what it does |
|---|---|
| `collections` | required: `["all"]`, or any of `notes`, `literature`, `docs` and `context`. Under `all`, every one that has an index is searched, and one that has none is named with the command that builds it. A collection named here that has no index is an error. |
| `top_k` | how many hits each collection gives, 5 unless given |
| `version` | for `docs`: each project's current version is searched unless this names others, as `kennis search --version` does |
| `projects` | for `context`: `"all"` for every project on this machine, or a list of project names |
| `tags` | keeps the search to what carries every tag named; `list_corpus` names the tags in use |

A hit in `context` is a file in the project's own repository, so the agent
opens it with its own file tools; `read` is for the other three. `remember`
and `tag` are the only tools that write.

Before version 0.15 there were four search tools and three read tools, one
per collection. An agent's saved instructions that name `search_notes` or
`read_literature` need `search` and `read` instead.

`read` is **batched**: it takes a list of requests, each naming a document
and optionally a chunk and how much either side of it to include. Each
answer opens by naming the collection its document is in. An agent that has just run a search has several hits to follow, and
one round trip is better than five.

`cite` is batched the same way. The agent is told to cite through it rather
than write a citation or a link itself, so a citation always names a document
kennis holds and its link always opens the passage; see
[Cite a passage and open it](cite-and-open.md).

Each reply is capped, so a request for a long document returns what fits and
says that it did rather than filling the agent's context window.

## What `remember` will and will not do

`remember` writes one note per call
into the corpus: committed to its history, and searchable months from now.

It has **no interactive path**. Anything unresolved has to have been an
argument - there is no prompting, no reading from standard input, and no
fallback. `to_context=True` writes into this project's bundle instead, and
**fails when there is no bundle here** rather than quietly writing to notes,
because recording a project decision somewhere machine-global and reporting
success would be worse than not recording it.

The corpus write takes the corpus lock and commits. The bundle write does
neither, because that repository is yours.

## What `tag` will and will not do

`tag` names each passage as a search hit gives it - a `document_id`, or a
context hit's `path`, with its `chunk` - exactly as `cite` does, so it can
only tag what kennis holds. The agent is told to tag only when you ask it
to tag, bookmark or gather passages. If any passage in a call cannot be
found, nothing is tagged, and each problem is named at its position. Tags
are kept where `kennis tag` keeps them; see
[Tag passages and documents](tag-passages.md).

## Searching the same thing two ways

What the agent sees for a hit is byte for byte what `kennis search` prints
in a terminal. That is deliberate: it means you can use the command line to
see exactly what an agent is being told, without guessing.

```
kennis search "reciprocal rank fusion" --collection notes
```

## What the server does not do

- It does not register itself with any client. Adding it to a
  configuration file is yours to do.
- It reports progress in its replies rather than as protocol
  notifications, so a long operation is quiet until it finishes.
- It serves one machine's corpus over stdio. There is no network
  listener and no second server.
