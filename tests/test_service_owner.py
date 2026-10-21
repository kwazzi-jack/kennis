"""A starting service takes the corpus from a probe, and not from a service.

`is_held` asks whether a service owns a corpus by taking the owner lock and
letting go, and the launcher asks every 50 ms while a service starts. A
service that tried the lock once and gave up found a probe holding it,
took that for another service, and exited; the launcher then found nobody
holding the corpus and reported the start as failed. Seen once in CI, on
a loaded runner (#534).
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from click.testing import CliRunner
from filelock import FileLock

from kennis.cli.__main__ import main
from kennis.protocol.record import lock_path
from kennis.service import serve

SERVED = 7
PATIENCE = 30.0


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    # What it would serve is not the question; whether it gets to is.
    monkeypatch.setattr(serve, "_serve", lambda corpus_root: SERVED)
    return root


def held_for(root: Path, seconds: float) -> threading.Event:
    """The owner lock taken by another process's probe, for `seconds`."""
    holding = threading.Event()

    def hold() -> None:
        # A second `FileLock` object on the path, as another process has:
        # one `FileLock` shared within a process would be reentrant.
        probe = FileLock(str(lock_path(root)), timeout=0)
        lock_path(root).parent.mkdir(parents=True, exist_ok=True)
        with probe:
            holding.set()
            threading.Event().wait(seconds)

    threading.Thread(target=hold, daemon=True).start()
    assert holding.wait(PATIENCE)
    return holding


def test_a_probe_holding_the_lock_does_not_turn_the_service_away(corpus: Path):
    held_for(corpus, 0.3)

    assert serve.run_service(corpus) == SERVED


def test_a_service_holding_the_lock_does(corpus: Path):
    """The refusal the wait must not remove: a lock held for longer than any
    probe is another service's."""
    held_for(corpus, serve.OWNER_PATIENCE_SECONDS + 5)

    assert serve.run_service(corpus) == 0
