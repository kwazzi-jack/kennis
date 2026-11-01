"""A client older than its installation refuses rather than replacing the
service (#601).

A long-lived client - the MCP server - loaded kennis before a reinstall. A
service of the new build is not its own, so it once stopped that service
and started another from the new code on disk, which it could not read
either. When the build on disk is not the build this process loaded, the
client is the stale one, and only restarting it helps.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from kennis import __version__
from kennis.client import process
from kennis.engine.errors import ClientOutdated
from kennis.protocol.record import ServiceRecord

RECORD = ServiceRecord(
    address="http://127.0.0.1:1/",
    token="token",
    pid=1,
    started=datetime(2026, 11, 1, tzinfo=UTC),
    version=__version__,
    corpus="/corpus",
)


@pytest.fixture
def actions(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the client did to the service: stopped it, or started one."""
    done: list[str] = []
    monkeypatch.setattr(process, "build_of_this_process", lambda: "loaded")
    monkeypatch.setattr(
        process, "stop_service", lambda root, record: done.append("stopped")
    )

    def started(root: Path) -> ServiceRecord:
        done.append("started")
        return RECORD

    monkeypatch.setattr(process, "_started", started)
    return done


def a_service_of(build: str, monkeypatch: pytest.MonkeyPatch) -> None:
    found = iter([RECORD, None])
    monkeypatch.setattr(process, "find_service", lambda root: next(found))
    monkeypatch.setattr(
        process,
        "hello",
        lambda record: {"kennis": __version__, "build": build, "busy": False},
    )


def test_a_stale_client_leaves_a_new_service_alone(
    monkeypatch: pytest.MonkeyPatch, actions: list[str], tmp_path: Path
):
    a_service_of("installed", monkeypatch)
    monkeypatch.setattr(process, "build_on_disk", lambda: "installed")

    with pytest.raises(ClientOutdated) as refused:
        process.ensure_service(tmp_path)

    assert actions == []
    assert "/mcp reconnect kennis" in str(refused.value)


def test_a_stale_client_starts_no_service(
    monkeypatch: pytest.MonkeyPatch, actions: list[str], tmp_path: Path
):
    monkeypatch.setattr(process, "find_service", lambda root: None)
    monkeypatch.setattr(process, "build_on_disk", lambda: "installed")

    with pytest.raises(ClientOutdated):
        process.ensure_service(tmp_path)

    assert actions == []


def test_a_current_client_still_replaces_an_old_service(
    monkeypatch: pytest.MonkeyPatch, actions: list[str], tmp_path: Path
):
    a_service_of("older", monkeypatch)
    monkeypatch.setattr(process, "build_on_disk", lambda: "loaded")

    process.ensure_service(tmp_path)

    assert actions == ["stopped", "started"]


def test_a_client_of_the_service_s_build_does_not_look_at_the_disk(
    monkeypatch: pytest.MonkeyPatch, actions: list[str], tmp_path: Path
):
    a_service_of("loaded", monkeypatch)

    def looked() -> str:
        raise AssertionError("the disk was read on the common path")

    monkeypatch.setattr(process, "build_on_disk", looked)

    assert process.ensure_service(tmp_path) == RECORD
    assert actions == []
