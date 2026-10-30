"""Where the launcher and the service are started (14c, #508).

Nothing in the service may depend on the directory of the client that
happened to start it, so both processes are started in the corpus root.
Asserted on the `cwd` each start passes to `spawned`, which is portable;
the process tests cannot see a process's directory on every platform.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

import kennis.client.process as client_process
import kennis.service.launch as service_launch


class Started(Exception):
    """Raised by the stand-in once it has recorded the start."""


def recording(into: list[Path]) -> Callable[..., subprocess.Popen[bytes]]:
    def spawned(command: list[str], *, cwd: Path) -> subprocess.Popen[bytes]:
        into.append(cwd)
        raise Started

    return spawned


def test_the_service_is_started_in_its_corpus_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    corpus = tmp_path / "corpus"
    (corpus / ".git").mkdir(parents=True)
    started_in: list[Path] = []
    monkeypatch.setattr(service_launch, "spawned", recording(started_in))

    with pytest.raises(Started):
        service_launch.launch(corpus)

    assert started_in == [corpus]


def test_the_launcher_is_started_in_the_corpus_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    corpus = tmp_path / "corpus"
    (corpus / ".git").mkdir(parents=True)
    started_in: list[Path] = []
    monkeypatch.setattr(client_process, "spawned", recording(started_in))

    with pytest.raises(Started):
        client_process.start_detached(corpus)

    assert started_in == [corpus]


def test_on_windows_a_start_has_a_console_with_no_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`DETACHED_PROCESS` leaves a process no console, and Windows ignores
    `CREATE_NO_WINDOW` beside it; the real interpreter behind a uv tool's
    `python.exe` was then given a console of its own, visible, and closing
    that window ended the service (#5, #6). Asserted on the flags, since
    nothing here runs Windows; the constants are stand-ins, distinct bits."""
    import types

    import kennis.protocol.spawn as spawn

    flags = {
        "DETACHED_PROCESS": 0x8,
        "CREATE_NEW_PROCESS_GROUP": 0x200,
        "CREATE_NO_WINDOW": 0x8000000,
    }
    for name, value in flags.items():
        monkeypatch.setattr(subprocess, name, value, raising=False)
    monkeypatch.setattr(spawn, "sys", types.SimpleNamespace(platform="win32"))
    given: list[int] = []

    def popen(command: list[str], **options: object) -> None:
        creationflags = options["creationflags"]
        assert isinstance(creationflags, int)
        given.append(creationflags)
        raise Started

    monkeypatch.setattr(subprocess, "Popen", popen)

    with pytest.raises(Started):
        spawn.spawned(["kennis"], cwd=tmp_path)

    assert given[0] & flags["CREATE_NO_WINDOW"]
    assert not given[0] & flags["DETACHED_PROCESS"]
    assert given[0] & flags["CREATE_NEW_PROCESS_GROUP"]
