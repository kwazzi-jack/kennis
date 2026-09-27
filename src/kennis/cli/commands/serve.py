"""`kennis serve`: run the MCP server on stdio.

The command is thin on purpose. Everything it does belongs to the server,
and the one thing it must get right is what it does *not* do: print.

**stdout is the JSON-RPC wire.** From the moment this command runs, a
byte written to standard output that is not protocol corrupts the
session - boepie lost one to 567 bytes of INFO from a library's
module-level console and got back `Invalid JSON: trailing characters at
line 1 column 5`. So there is no banner, no report and no confirmation,
and the import of the server is deferred into the function so that
merely building the command tree does not pull `fastmcp` in.
"""

from __future__ import annotations

import click

from kennis.cli.group import KennisCommand


@click.command(cls=KennisCommand, name="serve")
def serve_command() -> None:
    """Run the MCP server, speaking JSON-RPC on stdin and stdout.

    Started by an agent rather than by hand - Claude Code, VS Code,
    Copilot - which is why it prints nothing: standard output is the
    protocol.

    The server describes what this machine holds, built from the packs
    installed now, so an agent is told about the knowledge that is
    actually here rather than about kennis in the abstract.
    """
    # Imported here, not at module scope. `fastmcp` is the `mcp` extra,
    # and someone who installed kennis without it must still be able to
    # run every other command - which means building the command tree
    # must not import it. The failure is then an ImportError from this
    # one command, which is the honest place for it.
    from kennis.mcp.server import run

    run()


__all__ = ["serve_command"]
