"""Wording for what `pack validate` found.

The engine returns a `PackProblem` carrying a kind and the fields that kind
needs; the sentence lives here, because a front end that was handed the
sentence could not rewrap it, group it, or say it differently. Concern #81.
"""

from __future__ import annotations

from kennis.engine.pack.store import PackInstall
from kennis.engine.pack.update import PackUpdate
from kennis.engine.pack.validate import PackProblem, PackReport, VersionRefusal
from kennis.render.words import count_of

_DIGEST_SHOWN = 12


def describe_install(install: PackInstall) -> str:
    """What an install did, and the word `repaired` earning its place.

    Three outcomes rather than two, because "the provider shipped something
    new" and "what was here was damaged and has been put back" are
    different facts about the machine, and a reader seeing `repaired`
    twice in a row has something to investigate that `installed` would hide.
    """
    counted = count_of(install.files, "file")
    if install.outcome == "unchanged":
        return f"{counted}, already installed"
    if install.outcome == "repaired":
        return f"{counted}, restored after the store was found damaged"
    return f"{counted} installed"


def describe_declarations(install: PackInstall) -> str | None:
    """What the pack asked for that no file was copied for, or None.

    **Declared, never added.** Literature is fetched and documentation is
    crawled by a sync that does not exist yet, so a word implying the
    papers are in the corpus would promise something untrue.
    """
    parts = []
    if install.literature:
        parts.append(count_of(install.literature, "paper"))
    if install.docs:
        parts.append(count_of(install.docs, "documentation site"))
    if not parts:
        return None
    return f"{' and '.join(parts)} declared, not yet fetched"


def describe_unselected(count: int) -> str:
    """Files in a declared source that no `include` pattern matched.

    Said out loud because the default is `**/*.md`, so a PDF or a `.csv`
    an author dropped into the source is discarded by a pattern they may
    never have written. A file an explicit `exclude:` removed is not
    counted here: that one was intent.
    """
    # No pronoun. The first wording ended "so no digest was recorded for
    # it", which reads as "5 files ... for it" - the same slip as "1 file
    # disagree" earlier in this milestone. Avoiding the construction is
    # more reliable than conditioning on the count twice in one sentence.
    return f"{count_of(count, 'file')} matched no include pattern"


def describe_verdict(report: PackReport) -> str:
    """What a clean check actually established.

    **Two amounts of checking share one exit code.** A pack with no
    `generated` block is valid and had no digest compared, and reporting
    both as "valid" would use one word for two different assurances - which
    matters most in a release pipeline, where a forgotten `pack update` is
    exactly what this command is run to catch.
    """
    if report.digests_checked:
        return "valid, and the digests agree with the content"
    return "valid, and no digest was checked: there is no generated block"


def describe_recorded(result: PackUpdate) -> str:
    """What an update wrote, or found it did not need to write."""
    counted = count_of(result.files, "file")
    if result.outcome == "unchanged":
        return f"{counted} already recorded, so the file is untouched"
    return f"{counted} recorded"


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
    "describe_declarations",
    "describe_install",
    "describe_problem",
    "describe_recorded",
    "describe_refusal",
    "describe_unselected",
    "describe_update_needed",
    "describe_verdict",
    "remedy_for",
]
