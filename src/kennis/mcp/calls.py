"""One line in the log for every tool call an agent makes (#711).

Brian, 2026-11-27: kennis logged `kennis serve` starting and nothing after
it, so an agent's refused calls (#710) could be seen only from the
agent's side. A fastmcp middleware rather than a wrapper on each tool,
because a call the schema refuses never reaches the tool: it reaches the
middleware as a raised `ValidationError`, measured before this was
written.

The line goes to `kennis.mcp`, beneath the `kennis` logger that
`start_logging` installs and that does not propagate to the root - under
`serve`, stdout is the JSON-RPC wire.

**The level says kennis's own condition** (Brian, 2026-11-28). A refusal -
the schema's, or a `KennisError` - is kennis working, and is a warning,
as the command line logs `refused: ...`. Any other exception is a defect
in this process: an error, with its traceback. A defect in the service
reaches here as the `KennisError` the wire rebuilds, and the service logs
its own traceback.
"""

from __future__ import annotations

import logging
import time

import mcp_types
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from pydantic import ValidationError

from kennis.engine.errors import KennisError

# The log says what was asked, not a second copy of it: `remember`
# carries a whole note and `read` a list of requests.
_LONGEST_VALUE = 80

_logger = logging.getLogger("kennis.mcp")


def _shown(value: object) -> str:
    said = repr(value)
    if len(said) <= _LONGEST_VALUE:
        return said
    return said[: _LONGEST_VALUE - 3] + "..."


def _described_call(params: mcp_types.CallToolRequestParams) -> str:
    arguments = params.arguments or {}
    shown = " ".join(f"{name}={_shown(value)}" for name, value in arguments.items())
    return f"{params.name} {shown}" if shown else params.name


def _raised(error: Exception) -> Exception:
    """The exception that says what went wrong, beneath fastmcp's own.

    fastmcp raises its `ValidationError` from pydantic's, and wraps a
    tool's exception - kennis's `NothingToIndex`, or a defect's - in
    `ToolError`.
    """
    if isinstance(error, ValidationError):
        return error
    return error.__cause__ if isinstance(error.__cause__, Exception) else error


def _reason(raised: Exception) -> str:
    """What went wrong, in one line.

    For the schema's refusal, each error's location and type - `query
    missing_argument` - which is the part of pydantic's message that says
    what to change; the rest is a link and the input repeated.
    """
    if isinstance(raised, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in detail['loc'])} {detail['type']}"
            for detail in raised.errors()
        )
    first_line = next(iter(str(raised).splitlines()), "")
    return f"{type(raised).__name__}: {first_line}"


class LoggedCalls(Middleware):
    """Logs each tool call once it has answered, been refused or failed."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mcp_types.CallToolRequestParams],
        call_next: CallNext[mcp_types.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        described = _described_call(context.message)
        started = time.perf_counter()
        try:
            result = await call_next(context)
        except Exception as error:
            raised = _raised(error)
            elapsed = time.perf_counter() - started
            if isinstance(raised, ValidationError | KennisError):
                _logger.warning(
                    "%s refused in %.2fs: %s", described, elapsed, _reason(raised)
                )
            else:
                _logger.error(
                    "%s failed in %.2fs: %s",
                    described,
                    elapsed,
                    _reason(raised),
                    exc_info=raised,
                )
            raise
        _logger.info("%s answered in %.2fs", described, time.perf_counter() - started)
        return result


__all__ = ["LoggedCalls"]
