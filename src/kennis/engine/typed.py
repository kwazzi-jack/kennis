"""A path as a person typed it into kennis rather than into a shell (#4).

A shell removes the quotes around an argument; a prompt or a form field
receives them. Windows Explorer's "Copy as path" wraps a path in double
quotes, and a Linux terminal pastes a dropped file in single ones.
"""

from __future__ import annotations

_QUOTES = ('"', "'")


def without_quotes(typed: str) -> str:
    """`typed` without surrounding whitespace or one pair of matching
    quotes around the whole of it.

    Nothing else is unescaped: a backslash is a Windows separator. An
    unmatched quote is kept, because a name may begin with one.
    """
    answer = typed.strip()
    if len(answer) >= 2 and answer[0] == answer[-1] and answer[0] in _QUOTES:
        return answer[1:-1].strip()
    return answer


__all__ = ["without_quotes"]
