"""Wording for what `pack validate` found.

The engine returns a `PackProblem` carrying a kind and the fields that kind
needs; the sentence lives here, because a front end that was handed the
sentence could not rewrap it, group it, or say it differently. Concern #81.
"""

from __future__ import annotations

from kennis.engine.pack.validate import PackProblem, VersionRefusal

_DIGEST_SHOWN = 12


def describe_problem(problem: PackProblem) -> str:
    """One line about one finding, naming the file it is about."""
    if problem.kind == "overlapping-sources":
        return (
            f"{problem.path} and {problem.other} are the same tree or one "
            "contains the other, so a file under them has two destinations"
        )
    if problem.kind == "source-missing":
        return f"{problem.path} is declared and is not a directory in the pack"
    if problem.kind == "escapes-root":
        return f"{problem.path} resolves outside the pack and has not been read"
    if problem.kind == "symlink":
        return f"{problem.path} is a symlink, and a pack's files are not followed"
    if problem.kind == "digest-mismatch":
        return (
            f"{problem.path} has changed since the last update: the file "
            f"records {_short(problem.recorded)} and holds "
            f"{_short(problem.actual)}"
        )
    if problem.kind == "digest-absent":
        return f"{problem.path} has a recorded digest and is not in the pack"
    return f"{problem.path} is in the pack and has no recorded digest"


def describe_refusal(refusal: VersionRefusal) -> str:
    """Why this kennis may not read this pack, in its own words.

    Not a defect in the file, so the wording never suggests editing it.
    """
    if refusal.kind == "schema-too-new":
        return (
            f"this pack is written against schema {refusal.required} and this "
            f"kennis understands {refusal.available}"
        )
    return f"this pack needs kennis {refusal.required} and this is {refusal.available}"


def remedy_for(refusal: VersionRefusal) -> str:
    """The command that resolves a refusal.

    The same one for both kinds, because both mean the installed kennis is
    behind what the pack was written for. Rule 4.4: it runs as printed.
    """
    del refusal
    return "uv tool upgrade kennis"


def describe_update_needed(count: int) -> str:
    """The one line that says why every digest finding below it happened.

    Every digest problem has the same cause - the content changed and the
    generated block was not rewritten - so saying it once above the list is
    better than repeating it on every line.

    The command that fixes it - `kennis pack update` - is printed once
    beside this line rather than on every finding, for the same reason.
    """
    if count == 1:
        return "1 file disagrees with the generated block"
    return f"{count} files disagree with the generated block"


def _short(digest: str | None) -> str:
    """Enough of a digest to compare by eye, and no more."""
    if digest is None:
        return "nothing"
    return digest[:_DIGEST_SHOWN]


__all__ = [
    "describe_problem",
    "describe_refusal",
    "describe_update_needed",
    "remedy_for",
]
