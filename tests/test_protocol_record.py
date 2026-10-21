"""Where a corpus's service is: a lock that is the fact, a record that says
it (14b)."""

from __future__ import annotations

import stat
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kennis.engine.settings import state_dir
from kennis.protocol import record as records
from kennis.protocol.record import (
    ServiceRecord,
    corpus_key,
    find_service,
    is_held,
    owner_lock,
    read_record,
    record_path,
    write_record,
)
from platforms import needs_file_modes

RECORD = ServiceRecord(
    address="http://127.0.0.1:4242/",
    token="the-token",
    pid=42,
    started=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    version="0.9.0",
    corpus="/a corpus",
)


def held_elsewhere(root: Path) -> tuple[threading.Event, threading.Thread]:
    """The lock held by another thread, as another process would hold it."""
    holding = threading.Event()
    let_go = threading.Event()

    def hold() -> None:
        lock = owner_lock(root)
        lock.acquire()
        holding.set()
        let_go.wait(30)
        lock.release()

    thread = threading.Thread(target=hold)
    thread.start()
    assert holding.wait(30)
    return let_go, thread


def test_a_record_reads_back_as_written(tmp_path: Path):
    write_record(tmp_path, RECORD)

    assert read_record(tmp_path) == RECORD


@needs_file_modes
def test_only_this_account_may_read_the_record(tmp_path: Path):
    write_record(tmp_path, RECORD)

    mode = stat.S_IMODE(record_path(tmp_path).stat().st_mode)
    assert mode == 0o600


def test_the_record_is_where_the_platform_protects_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The part of the record's protection that holds on every platform
    (14f, as #389 for the credentials). Windows has no `0600`; the record is
    kept from other accounts there by the profile's own permissions, which
    is true only while it sits in the state directory and that directory is
    in the profile. Both are asserted here, the second with the redirect
    every test runs under taken away."""
    assert record_path(tmp_path).parent == state_dir()

    with monkeypatch.context() as unredirected:
        unredirected.delenv("KENNIS_STATE_DIR", raising=False)
        default = state_dir()
    assert default.is_relative_to(Path.home()), default


def test_a_record_with_nobody_behind_it_is_a_crash_s_and_is_removed(tmp_path: Path):
    write_record(tmp_path, RECORD)

    assert find_service(tmp_path) is None
    assert not record_path(tmp_path).exists()


def test_a_held_lock_makes_the_record_believed(tmp_path: Path):
    write_record(tmp_path, RECORD)
    let_go, thread = held_elsewhere(tmp_path)
    try:
        assert is_held(tmp_path)
        assert find_service(tmp_path) == RECORD
    finally:
        let_go.set()
        thread.join(30)
    assert not is_held(tmp_path)


def test_two_corpora_have_two_records(tmp_path: Path):
    assert corpus_key(tmp_path / "one") != corpus_key(tmp_path / "two")


def test_two_spellings_of_one_folder_are_one_key(tmp_path: Path):
    (tmp_path / "corpus").mkdir()

    assert corpus_key(tmp_path / "corpus") == corpus_key(
        tmp_path / "x" / ".." / "corpus"
    )


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_case_is_ignored_where_the_file_system_ignores_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str
):
    """APFS and NTFS ignore case by default, so `Corpus` and `corpus` are
    one folder and must find one service."""
    monkeypatch.setattr(records.sys, "platform", platform)

    assert corpus_key(tmp_path / "Corpus") == corpus_key(tmp_path / "corpus")


def test_case_is_kept_where_the_file_system_keeps_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(records.sys, "platform", "linux")

    assert corpus_key(tmp_path / "Corpus") != corpus_key(tmp_path / "corpus")


def test_an_unreadable_record_is_no_record(tmp_path: Path):
    record_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    record_path(tmp_path).write_text("{not json", encoding="utf-8")

    assert read_record(tmp_path) is None


def test_the_record_lives_in_the_state_directory(tmp_path: Path):
    assert record_path(tmp_path).parent.name == "state-dir"
