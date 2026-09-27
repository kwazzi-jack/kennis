"""The FastMCP server: what an agent connects to.

Design sections 11 and 20. The server is assembled here and does as
little as possible itself - it resolves what is installed, builds the
instructions block from it, and registers the tools.

**The tools are synchronous.** The engine is synchronous by design
(section 20), fastmcp accepts a plain function, and making the tools
`async def` would put an event loop between this front end and an engine
that has no use for one. boepie's are async; that is a difference taken
deliberately rather than a port half done.

**stdout is the JSON-RPC wire.** Nothing here, and nothing anything here
imports, may write to it. `tests/test_mcp_server.py` holds a real
subprocess to that.
"""

from __future__ import annotations

from fastmcp import FastMCP

from kennis.context import resolve_context
from kennis.engine.pack.installed import InstalledPack, list_installed
from kennis.mcp.instructions import instructions_for
from kennis.mcp.tools.corpus import list_corpus

SERVER_NAME = "kennis"


def build_server() -> FastMCP:
    """The server, with its instructions read from what is installed now.

    **The packs are read at startup, not per call.** An agent's client
    reads `instructions` once when it connects, so recomputing them
    would cost a store walk per request and change nothing the client
    would see. A pack added later is reflected when the server
    restarts, which is the same bargain every MCP client already makes
    with its server's tool list.

    A corpus that does not exist yet is not an error here: a server that
    refused to start on a fresh machine could not be registered before
    the corpus was made, and `list_corpus` says what is wrong when it is
    actually called.
    """
    server = FastMCP(SERVER_NAME, instructions=instructions_for(_installed()))
    server.tool(list_corpus)
    return server


def _installed() -> tuple[InstalledPack, ...]:
    """What the store holds, or nothing if there is no corpus to read.

    Deliberately forgiving. Starting the server is not the moment to
    refuse for want of a corpus - the tools say so when they are called,
    and an unstartable server cannot even be registered.
    """
    context = resolve_context()
    if not (context.corpus_root / ".git").is_dir():
        return ()
    return tuple(list_installed(context.corpus_root).packs)


def run() -> None:
    """Serve on stdio. The entry point `kennis serve` calls.

    **No banner.** fastmcp prints an ASCII-art logo and an upgrade
    notice on startup. They go to stderr, so they cannot corrupt the
    wire, but stderr is where an agent's client collects diagnostics and
    a logo is not one. Suppressed rather than tolerated.
    """
    build_server().run(show_banner=False)


__all__ = ["SERVER_NAME", "build_server", "run"]
