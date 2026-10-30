"""The words for a path Windows cannot hold (#573).

One function, because `pack validate` reports the finding and `pack add`
refuses the input, and the two must say the same thing about one name.
"""

from __future__ import annotations

from kennis.engine.portable import PORTABLE_PATH_LIMIT, PortabilityProblem


def describe_unportable(path: str, problem: PortabilityProblem) -> str:
    """Why `path` cannot be shipped, naming the part of it at fault."""
    return f"{path} cannot be held on Windows: {_reason(problem)}"


def _reason(problem: PortabilityProblem) -> str:
    match problem.kind:
        case "reserved-character":
            return f"Windows does not allow '{problem.character}' in a name"
        case "control-character":
            code = ord(problem.character or "\0")
            return (
                f"Windows does not allow the control character 0x{code:02X} in a name"
            )
        case "reserved-name":
            return f"'{problem.segment}' is a device name on Windows"
        case "ends-in-dot-or-space":
            return f"Windows drops the dot or space that ends '{problem.segment}'"
        case "too-long":
            return (
                f"it is longer than {PORTABLE_PATH_LIMIT} characters, which "
                "leaves no room for where kennis keeps it within Windows' 260"
            )


__all__ = ["describe_unportable"]
