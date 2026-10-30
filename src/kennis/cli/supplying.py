"""Asking for a paper kennis could not fetch, after the job that tried.

Brian, 2026-10-26: a paper with no open copy is not the end of the matter -
the person may be able to download it through their institution - so once
`corpus sync` or `corpus add` has finished, each such paper is named with
its page and a path is asked for. The job is over by then, so nothing waits
on a person while the corpus is held; each answer is a write of its own.

Only on a terminal: a pipeline or an agent is never asked, and still has
the remedy the report prints. `interactive` and `read_path` are the two
seams a test stands in for.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from kennis.cli import display
from kennis.engine.refusals import Refusal, wanted_paper
from kennis.engine.typed import without_quotes
from kennis.render.refusals import (
    PATH_QUESTION,
    describe_asking,
    describe_not_a_file,
    describe_skipped_paper,
    describe_wanted_paper,
)


@dataclass(frozen=True, slots=True)
class Wanted:
    """A paper kennis has no copy of, by the identifier an add takes."""

    kind: str
    value: str
    # The pack's name for it, after a sync; None after an add of the
    # person's own.
    address: str | None = None


def wanted_papers(
    refusals: Iterable[tuple[str | None, Refusal | None]],
) -> list[Wanted]:
    """The papers a file would fix, by `engine.refusals.wanted_paper`'s
    rule, which the window asks by too."""
    wanted: list[Wanted] = []
    for address, refusal in refusals:
        paper = wanted_paper(refusal)
        if paper is not None:
            wanted.append(Wanted(kind=paper[0], value=paper[1], address=address))
    return wanted


def interactive() -> bool:
    """Whether a person is at both ends, as `remember` decides it."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def read_path(message: str) -> str:
    """One answer, with paths completed on Tab - the terminal's browse
    button."""
    from prompt_toolkit import prompt
    from prompt_toolkit.completion import PathCompleter

    return prompt(message, completer=PathCompleter(expanduser=True))


def ask_for_files(
    wanted: Sequence[Wanted],
    supply: Callable[[Wanted, Path], None],
    *,
    asked_again: bool,
) -> int:
    """Ask for a file for each paper in `wanted` and hand each to `supply`.

    Returns how many were supplied. An empty answer or the end of input
    skips one paper; an interrupt skips it and every one after it.
    `asked_again` says whether a skipped paper comes up again by itself, as
    it does at the next sync.
    """
    if not wanted or not interactive():
        return 0
    display.guidance(describe_asking(len(wanted)))
    supplied = 0
    for paper in wanted:
        display.note(describe_wanted_paper(paper.kind, paper.value))
        while True:
            try:
                answer = without_quotes(read_path(PATH_QUESTION))
            except EOFError:
                answer = ""
            except KeyboardInterrupt:
                display.detail("=", describe_skipped_paper(again=asked_again))
                return supplied
            if not answer:
                display.detail("=", describe_skipped_paper(again=asked_again))
                break
            path = Path(answer).expanduser()
            if not path.is_file():
                display.warning(describe_not_a_file(answer))
                continue
            supply(paper, path.resolve())
            supplied += 1
            break
    return supplied


__all__ = ["Wanted", "ask_for_files", "interactive", "read_path", "wanted_papers"]
