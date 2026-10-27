"""The command line asks for a paper kennis could not fetch (Brian, 2026-10-26).

After `corpus sync` or `corpus add -l` has finished, and only on a terminal,
each paper with no open copy is named with its page and a word about
institutional access, and a path is asked for. An empty answer skips it, an
interrupt stops asking. A pipe is never asked anything.

The service is not what is tested here, so the client calls are replaced,
and the terminal is stood in for by `supplying`'s two seams.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from click.testing import CliRunner

import kennis.cli.supplying as supplying
from kennis.cli.__main__ import main
from kennis.client import api
from kennis.client.api import Written
from kennis.engine.corpus.add import AddOptions, AddOutcome, AddReport
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.events import Outcome
from kennis.engine.refusals import NoArxivText, NoPublisherText, Quoted, Refusal

DOI = "10.48479/bhpj-nz95"
BEHIND_A_PUBLISHER = NoPublisherText(kind="doi", value=DOI)

type Answer = str | BaseException


@pytest.fixture
def run() -> CliRunner:
    return CliRunner()


@pytest.fixture
def corpus(run: CliRunner) -> None:
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0


@pytest.fixture
def downloaded(tmp_path: Path) -> Path:
    path = tmp_path / "maccagni.pdf"
    path.write_bytes(b"%PDF-1.4 fake\n")
    return path


def a_terminal(monkeypatch: pytest.MonkeyPatch, answers: Sequence[Answer]) -> list[str]:
    """Standard input and output are a terminal, and the person types
    `answers` in turn; an exception is raised as typing it would be."""
    asked: list[str] = []
    replies: Iterator[Answer] = iter(answers)

    def read_path(message: str) -> str:
        asked.append(message)
        reply = next(replies)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr(supplying, "interactive", lambda: True)
    monkeypatch.setattr(supplying, "read_path", read_path)
    return asked


def a_sync_that_could_not_fetch(
    monkeypatch: pytest.MonkeyPatch, why: Sequence[tuple[str, Refusal]]
) -> None:
    result = CorpusSync(
        actions=(),
        counts={},
        deferred=(),
        copied=(),
        failed=tuple(address for address, _ in why),
        why=tuple(why),
    )

    def synced(root: Path, **kwargs: object) -> Written[CorpusSync]:
        return Written(result=result, restored=[])

    monkeypatch.setattr(api, "sync_corpus", synced)


def added_report(identifier: str, refusal: Refusal | None = None) -> AddReport:
    outcome = Outcome.ADDED if refusal is None else Outcome.FAILED
    return AddReport(
        outcomes=[AddOutcome(identifier=identifier, outcome=outcome, refusal=refusal)],
        elapsed_seconds=0.0,
    )


def supplied_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Path]]:
    calls: list[tuple[str, Path]] = []

    def supply(
        root: Path, address: str, path: Path, **kwargs: object
    ) -> Written[AddReport]:
        calls.append((address, path))
        return Written(result=added_report(str(path)), restored=[])

    monkeypatch.setattr(api, "supply_paper", supply)
    return calls


# ---------------------------------------------------------------------------
# After a sync
# ---------------------------------------------------------------------------


def test_a_sync_asks_for_each_paper_it_could_not_fetch(
    run: CliRunner, corpus: None, monkeypatch: pytest.MonkeyPatch, downloaded: Path
):
    a_sync_that_could_not_fetch(monkeypatch, [(f"doi:{DOI}", BEHIND_A_PUBLISHER)])
    asked = a_terminal(monkeypatch, [str(downloaded)])
    calls = supplied_calls(monkeypatch)

    result = run.invoke(main, ["corpus", "sync"])

    assert result.exit_code == 0, result.output
    assert len(asked) == 1
    assert f"https://doi.org/{DOI}" in result.output
    assert "institution" in result.output
    assert calls == [(f"doi:{DOI}", downloaded.resolve())]


def test_an_empty_answer_skips_the_paper(
    run: CliRunner, corpus: None, monkeypatch: pytest.MonkeyPatch
):
    a_sync_that_could_not_fetch(monkeypatch, [(f"doi:{DOI}", BEHIND_A_PUBLISHER)])
    a_terminal(monkeypatch, [""])
    calls = supplied_calls(monkeypatch)

    result = run.invoke(main, ["corpus", "sync"])

    assert result.exit_code == 0, result.output
    assert calls == []
    assert "skipped" in result.output


def test_a_path_that_is_not_a_file_is_asked_again(
    run: CliRunner,
    corpus: None,
    monkeypatch: pytest.MonkeyPatch,
    downloaded: Path,
    tmp_path: Path,
):
    a_sync_that_could_not_fetch(monkeypatch, [(f"doi:{DOI}", BEHIND_A_PUBLISHER)])
    asked = a_terminal(monkeypatch, [str(tmp_path / "nothing.pdf"), str(downloaded)])
    calls = supplied_calls(monkeypatch)

    result = run.invoke(main, ["corpus", "sync"])

    assert result.exit_code == 0, result.output
    assert len(asked) == 2
    assert calls == [(f"doi:{DOI}", downloaded.resolve())]


def test_an_interrupt_stops_asking_about_the_rest(
    run: CliRunner, corpus: None, monkeypatch: pytest.MonkeyPatch
):
    a_sync_that_could_not_fetch(
        monkeypatch,
        [
            (f"doi:{DOI}", BEHIND_A_PUBLISHER),
            (
                "arxiv:2511.10785",
                NoArxivText(named="2511.10785", arxiv_id="2511.10785"),
            ),
        ],
    )
    asked = a_terminal(monkeypatch, [KeyboardInterrupt()])
    calls = supplied_calls(monkeypatch)

    result = run.invoke(main, ["corpus", "sync"])

    assert result.exit_code == 0, result.output
    assert len(asked) == 1
    assert calls == []


def test_a_sync_off_a_terminal_asks_nothing(
    run: CliRunner, corpus: None, monkeypatch: pytest.MonkeyPatch
):
    a_sync_that_could_not_fetch(monkeypatch, [(f"doi:{DOI}", BEHIND_A_PUBLISHER)])
    asked = a_terminal(monkeypatch, [])
    monkeypatch.setattr(supplying, "interactive", lambda: False)
    calls = supplied_calls(monkeypatch)

    result = run.invoke(main, ["corpus", "sync"])

    assert result.exit_code == 0, result.output
    assert asked == []
    assert calls == []
    # The way out is still said, for a pipeline that is never asked.
    assert "--identifier" in result.output


def test_a_paper_refused_for_another_reason_is_not_asked_about(
    run: CliRunner, corpus: None, monkeypatch: pytest.MonkeyPatch
):
    """An unreachable host is not something a downloaded file answers; the
    next sync tries again."""
    a_sync_that_could_not_fetch(
        monkeypatch, [(f"doi:{DOI}", Quoted("the host did not answer"))]
    )
    asked = a_terminal(monkeypatch, [])

    result = run.invoke(main, ["corpus", "sync"])

    assert result.exit_code == 0, result.output
    assert asked == []


# ---------------------------------------------------------------------------
# After an add
# ---------------------------------------------------------------------------


def test_an_add_asks_and_adds_the_file_as_the_persons_paper(
    run: CliRunner, corpus: None, monkeypatch: pytest.MonkeyPatch, downloaded: Path
):
    adds: list[tuple[str, list[str], AddOptions]] = []

    def add(
        root: Path,
        destination: str,
        identifiers: Sequence[str],
        options: AddOptions,
        **kwargs: object,
    ) -> Written[AddReport]:
        adds.append((destination, list(identifiers), options))
        if len(adds) == 1:
            return Written(result=added_report(DOI, BEHIND_A_PUBLISHER), restored=[])
        return Written(result=added_report(identifiers[0]), restored=[])

    monkeypatch.setattr(api, "add", add)
    a_terminal(monkeypatch, [str(downloaded)])

    result = run.invoke(main, ["corpus", "add", "-l", DOI])

    assert result.exit_code == 0, result.output
    assert len(adds) == 2
    destination, identifiers, options = adds[1]
    assert destination == "literature"
    assert identifiers == [str(downloaded.resolve())]
    assert options.identifier == DOI
    assert options.owner == "user"
