"""Refuse a commit message of more than one line.

The project rule is a subject line and nothing else: no body, no bullet list,
no `BREAKING CHANGE:` footer - `!` after the scope carries that signal - and
no trailers of any kind. Commitizen validates the subject's shape but permits
a body, so the one-line rule needs its own check.

Run by pre-commit at the `commit-msg` stage, with the path of the file git
wrote the message into.
"""

from __future__ import annotations

import sys
from pathlib import Path


def body_lines(message: str) -> list[str]:
    """Every line after the subject that is neither blank nor a comment.

    git's own commentary is stripped before the message is used, so a `#` line
    is not part of what the author wrote.
    """
    _, _, remainder = message.partition("\n")
    return [
        line
        for line in remainder.splitlines()
        if line.strip() and not line.startswith("#")
    ]


def main(paths: list[str]) -> int:
    for path in paths:
        offending = body_lines(Path(path).read_text(encoding="utf-8"))
        if offending:
            print(
                "error: a commit message is one line - "
                f"found {len(offending)} more:\n  " + "\n  ".join(offending),
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
