"""Milestone 13a: an encrypted `.7z` of the corpus, written to a folder.

The archive holds the corpus folder and its `.git`, but not `index/`,
which the history already holds and a restore checks out. It is AES-256 with the names
encrypted too, written under a temporary name, tested with the same
password, and only then renamed over the last backup. Restoring refuses
a target that is not empty and an archive that names anything outside
`corpus/`.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import py7zr
import pytest
from click.testing import CliRunner

from held import held_for_a_moment
from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine.backup import (
    BACKUP_NAME,
    check_backup,
    members_of,
    restore_backup,
    write_backup,
)
from kennis.engine.corpus.conversions import conversions_root
from kennis.engine.errors import (
    BackupRefused,
    BackupUnreadable,
    NothingToIndex,
)
from kennis.engine.events import Progress, Recorder
from kennis.engine.rag.index import load_index
from kennis.engine.staging import journal_path, staging_root
from kennis.operations import back_up_corpus

PASSWORD = "correct horse battery staple"
NOTE_TEXT = "Calibration converged after three rounds of selfcal."


def run(*arguments: str, given: str | None = None) -> str:
    result = CliRunner().invoke(main, list(arguments), input=given)
    assert result.exit_code == 0, result.output
    return result.output


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    run("corpus", "init")
    source = tmp_path / "calibration.md"
    source.write_text(f"# Calibration\n\n{NOTE_TEXT}\n", encoding="utf-8")
    run("corpus", "add", "-n", str(source))
    run("corpus", "index")
    assert (root / "index").is_dir()
    return root


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    chosen = tmp_path / "Dropbox" / "kennis"
    chosen.mkdir(parents=True)
    return chosen


def git_in(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    ).stdout


def names_in(archive: Path, password: str = PASSWORD) -> set[str]:
    with py7zr.SevenZipFile(archive, "r", password=password) as opened:
        return set(opened.getnames())


# ---------------------------------------------------------------------------
# What goes in
# ---------------------------------------------------------------------------


def test_the_members_are_the_corpus_and_its_history_but_not_the_index(corpus: Path):
    names = {name for _, name in members_of(corpus)}

    assert "corpus/.git/HEAD" in names
    assert any(
        name.startswith("corpus/notes/") and name.endswith(".md") for name in names
    )
    assert not any(
        name == "corpus/index" or name.startswith("corpus/index/") for name in names
    )
    assert "corpus/.kennis.lock" not in names
    assert all(name.startswith("corpus/") for name in names)


def test_what_kennis_keeps_only_while_it_works_is_left_out(corpus: Path):
    """A mirror being prepared in, a journal, and conversions kept for a
    retry live in `.git` but are no part of the corpus (#525): a kept
    conversion can be the text of a document a failed add never added."""
    mirror = staging_root(corpus) / "a-mirror" / "notes"
    mirror.mkdir(parents=True)
    (mirror / "half.md").write_text("Half prepared.\n", encoding="utf-8")
    kept = conversions_root(corpus)
    kept.mkdir(parents=True)
    (kept / "mineru-abc.json").write_text("{}", encoding="utf-8")
    journal_path(corpus).write_text("{}", encoding="utf-8")

    names = {name for _, name in members_of(corpus)}

    assert not [name for name in names if "kennis-" in name], sorted(names)
    assert "corpus/.git/HEAD" in names


def test_a_symbolic_link_is_neither_followed_nor_stored(corpus: Path, tmp_path: Path):
    outside = tmp_path / "private.txt"
    outside.write_text("not the corpus's", encoding="utf-8")
    (corpus / "notes" / "linked.txt").symlink_to(outside)

    names = {name for _, name in members_of(corpus)}

    assert "corpus/notes/linked.txt" not in names


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_a_backup_is_one_encrypted_file_whose_names_are_hidden(
    corpus: Path, folder: Path
):
    report = write_backup(corpus, folder, PASSWORD)

    assert report.path == folder / BACKUP_NAME
    assert sorted(path.name for path in folder.iterdir()) == [BACKUP_NAME]
    assert report.size == report.path.stat().st_size
    raw = report.path.read_bytes()
    assert b"calibration" not in raw.lower()
    assert b"HEAD" not in raw
    with (
        pytest.raises(py7zr.PasswordRequired),
        py7zr.SevenZipFile(report.path, "r") as opened,
    ):
        opened.getnames()


def test_the_archive_holds_what_was_listed(corpus: Path, folder: Path):
    report = write_backup(corpus, folder, PASSWORD)

    assert names_in(report.path) == {name for _, name in members_of(corpus)}
    assert report.members == len(members_of(corpus))


def test_progress_is_reported_per_member(corpus: Path, folder: Path):
    recorder = Recorder()

    report = write_backup(corpus, folder, PASSWORD, events=recorder)
    progress = recorder.events_of_type(Progress)

    assert progress, "nothing was reported"
    assert {event.total for event in progress} == {report.members}
    assert progress[-1].completed == report.members


def test_an_empty_password_is_refused_and_nothing_is_written(
    corpus: Path, folder: Path
):
    with pytest.raises(BackupRefused):
        write_backup(corpus, folder, "")

    assert list(folder.iterdir()) == []


def test_a_folder_that_is_not_there_is_refused(corpus: Path, tmp_path: Path):
    with pytest.raises(BackupRefused) as refused:
        write_backup(corpus, tmp_path / "unplugged-drive", PASSWORD)

    assert refused.value.resolution is not None
    assert "backup.folder" in refused.value.resolution


def test_a_backup_that_fails_its_test_leaves_the_last_one_alone(
    corpus: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
):
    write_backup(corpus, folder, PASSWORD)
    last_good = (folder / BACKUP_NAME).read_bytes()
    (corpus / "notes" / "later.md").write_text("# Later\n\nNew.\n", encoding="utf-8")
    monkeypatch.setattr(
        py7zr.SevenZipFile, "testzip", lambda self: "corpus/notes/later.md"
    )

    with pytest.raises(BackupUnreadable):
        write_backup(corpus, folder, PASSWORD)

    assert (folder / BACKUP_NAME).read_bytes() == last_good
    assert sorted(path.name for path in folder.iterdir()) == [BACKUP_NAME]


def test_a_second_backup_replaces_the_first(corpus: Path, folder: Path):
    write_backup(corpus, folder, PASSWORD)
    (corpus / "notes" / "later.md").write_text("# Later\n\nNew.\n", encoding="utf-8")

    write_backup(corpus, folder, PASSWORD)

    assert "corpus/notes/later.md" in names_in(folder / BACKUP_NAME)
    assert sorted(path.name for path in folder.iterdir()) == [BACKUP_NAME]


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


def test_a_check_without_a_password_reports_the_folder_and_the_file(
    corpus: Path, folder: Path
):
    assert check_backup(folder).archive is None
    report = write_backup(corpus, folder, PASSWORD)

    checked = check_backup(folder)

    assert checked.folder_exists and checked.writable
    assert checked.archive == report.path
    assert checked.size == report.size
    assert checked.modified is not None
    assert checked.verified is None  # not asked


def test_a_check_of_a_missing_folder_says_so(tmp_path: Path):
    checked = check_backup(tmp_path / "unplugged-drive")

    assert not checked.folder_exists
    assert not checked.writable
    assert checked.archive is None


def test_a_check_with_the_password_tests_every_member(corpus: Path, folder: Path):
    write_backup(corpus, folder, PASSWORD)

    assert check_backup(folder, PASSWORD).verified is True
    assert check_backup(folder, "not the password").verified is False


def test_a_damaged_archive_fails_its_check(corpus: Path, folder: Path):
    report = write_backup(corpus, folder, PASSWORD)
    raw = bytearray(report.path.read_bytes())
    middle = len(raw) // 2
    raw[middle] ^= 0xFF
    report.path.write_bytes(bytes(raw))

    assert check_backup(folder, PASSWORD).verified is False


# ---------------------------------------------------------------------------
# Restoring
# ---------------------------------------------------------------------------


def test_a_restored_corpus_is_the_corpus_with_its_history(
    corpus: Path, folder: Path, tmp_path: Path
):
    report = write_backup(corpus, folder, PASSWORD)
    target = tmp_path / "restored"

    restored = restore_backup(report.path, target, PASSWORD)

    assert restored.target == target
    note = next((target / "notes").rglob("*.md"))
    assert NOTE_TEXT in note.read_text(encoding="utf-8")
    assert git_in(target, "log", "--format=%H") == git_in(corpus, "log", "--format=%H")
    # The index is not in the archive and only its pointer is in history:
    # the restore checks the pointer out, so the working tree agrees with
    # HEAD, and the index itself is built again before a search.
    assert git_in(target, "status", "--porcelain") == ""
    assert (target / "index" / "notes" / "latest.json").is_file()
    with pytest.raises(NothingToIndex):
        load_index(target / "index", "notes")
    assert (
        sorted(path.name for path in tmp_path.iterdir() if ".restoring-" in path.name)
        == []
    )


def test_a_restore_refuses_a_target_that_is_not_empty(
    corpus: Path, folder: Path, tmp_path: Path
):
    report = write_backup(corpus, folder, PASSWORD)

    with pytest.raises(BackupRefused):
        restore_backup(report.path, corpus, PASSWORD)

    assert names_in(report.path)  # untouched, and the corpus too
    assert (corpus / "index").is_dir()


def test_a_restore_with_the_wrong_password_creates_nothing(
    corpus: Path, folder: Path, tmp_path: Path
):
    report = write_backup(corpus, folder, PASSWORD)
    target = tmp_path / "restored"

    with pytest.raises(BackupUnreadable):
        restore_backup(report.path, target, "not the password")

    assert not target.exists()
    assert (
        sorted(path.name for path in tmp_path.iterdir() if ".restoring-" in path.name)
        == []
    )


@pytest.mark.parametrize(
    "name", ["corpus/../escaped.md", "elsewhere/x.md", "/etc/kennis.md"]
)
def test_a_restore_refuses_a_name_outside_the_corpus(tmp_path: Path, name: str):
    archive = tmp_path / "crafted.7z"
    source = tmp_path / "payload.md"
    source.write_text("payload", encoding="utf-8")
    with py7zr.SevenZipFile(
        archive, "w", password=PASSWORD, header_encryption=True
    ) as writing:
        writing.write(source, "corpus/notes/fine.md")
        writing.write(source, name)
    target = tmp_path / "restored"

    with pytest.raises(BackupRefused):
        restore_backup(archive, target, PASSWORD)

    assert not target.exists()
    assert not (tmp_path / "escaped.md").exists()


# ---------------------------------------------------------------------------
# The operation
# ---------------------------------------------------------------------------


def test_the_backup_waits_for_a_publish_under_way(corpus: Path, folder: Path):
    """It holds the corpus to read, so it starts only once a publish has
    finished and never archives one half placed."""
    context = existing_corpus()

    with held_for_a_moment(corpus) as hold:
        back_up_corpus(context, folder, PASSWORD)
        finished = time.monotonic()

    assert finished >= hold.released
    assert len(list(folder.iterdir())) == 1


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_create_asks_twice_and_writes_to_the_folder_given(corpus: Path, folder: Path):
    told = run(
        "backup", "create", "--to", str(folder), given=f"{PASSWORD}\n{PASSWORD}\n"
    )

    assert (folder / BACKUP_NAME).is_file()
    assert PASSWORD not in told
    assert str(folder / BACKUP_NAME) in told


def test_create_uses_the_configured_folder(corpus: Path, folder: Path):
    run("config", "set", "backup.folder", str(folder))

    run("backup", "create", given=f"{PASSWORD}\n{PASSWORD}\n")

    assert (folder / BACKUP_NAME).is_file()


def test_create_without_a_folder_names_the_setting(corpus: Path):
    result = CliRunner().invoke(
        main, ["backup", "create"], input=f"{PASSWORD}\n{PASSWORD}\n"
    )

    assert result.exit_code != 0
    assert "kennis config set backup.folder" in result.output


def test_check_reports_and_tests_on_request(corpus: Path, folder: Path):
    run("backup", "create", "--to", str(folder), given=f"{PASSWORD}\n{PASSWORD}\n")

    told = run("backup", "check", "--to", str(folder))
    tested = run(
        "backup", "check", "--to", str(folder), "--test", given=f"{PASSWORD}\n"
    )

    assert str(folder / BACKUP_NAME) in told
    assert "every file" in tested


def test_a_restored_corpus_is_told_to_index_and_then_searches(
    corpus: Path, folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    run("backup", "create", "--to", str(folder), given=f"{PASSWORD}\n{PASSWORD}\n")
    target = tmp_path / "restored"

    told = run(
        "backup",
        "restore",
        str(folder / BACKUP_NAME),
        "--to",
        str(target),
        given=f"{PASSWORD}\n",
    )
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(target))

    # The index is rebuilt rather than restored, so the restore says so,
    # and the command it prints is the one that makes the corpus searchable.
    assert "kennis corpus index" in told
    run("corpus", "index")
    assert "selfcal" in run("search", "selfcal")


def test_a_corpus_never_indexed_is_told_to_index(
    tmp_path: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "bare"
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(root))
    run("corpus", "init")
    run("backup", "create", "--to", str(folder), given=f"{PASSWORD}\n{PASSWORD}\n")

    told = run(
        "backup",
        "restore",
        str(folder / BACKUP_NAME),
        "--to",
        str(tmp_path / "restored"),
        given=f"{PASSWORD}\n",
    )

    assert "kennis corpus index" in told


def test_the_password_never_reaches_the_log(corpus: Path, folder: Path):
    run("backup", "create", "--to", str(folder), given=f"{PASSWORD}\n{PASSWORD}\n")

    from kennis.logs import log_path

    assert PASSWORD not in log_path().read_text(encoding="utf-8")
    assert os.environ.get("KENNIS_LOG_DIR")  # the redirected log, not Brian's


def test_a_password_typed_differently_twice_writes_nothing(corpus: Path, folder: Path):
    result = CliRunner().invoke(
        main,
        ["backup", "create", "--to", str(folder)],
        input=f"{PASSWORD}\nsomething else\n",
    )

    assert result.exit_code != 0
    assert list(folder.iterdir()) == []


def test_a_check_that_fails_its_test_fails(corpus: Path, folder: Path):
    run("backup", "create", "--to", str(folder), given=f"{PASSWORD}\n{PASSWORD}\n")

    result = CliRunner().invoke(
        main,
        ["backup", "check", "--to", str(folder), "--test"],
        input="not the password\n",
    )

    assert result.exit_code != 0
    assert "the password is wrong or the archive is damaged" in result.output


def test_a_member_the_archive_lost_fails_the_backup(
    corpus: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
):
    """The names are compared after writing, so a member the library
    dropped without saying so is caught rather than shipped."""
    written = py7zr.SevenZipFile.write

    def dropping_head(self: py7zr.SevenZipFile, path: Path, name: str) -> None:
        if name != "corpus/.git/HEAD":
            written(self, path, name)

    monkeypatch.setattr(py7zr.SevenZipFile, "write", dropping_head)

    with pytest.raises(BackupUnreadable):
        write_backup(corpus, folder, PASSWORD)

    assert list(folder.iterdir()) == []


def test_a_damaged_archive_restores_nothing(corpus: Path, folder: Path, tmp_path: Path):
    report = write_backup(corpus, folder, PASSWORD)
    raw = bytearray(report.path.read_bytes())
    # Inside the data, past the 32-byte signature header and well before
    # the encrypted header at the end, so the names still read.
    raw[64] ^= 0xFF
    report.path.write_bytes(bytes(raw))
    target = tmp_path / "restored"

    with pytest.raises(BackupUnreadable):
        restore_backup(report.path, target, PASSWORD)

    assert not target.exists()
    assert [path for path in tmp_path.iterdir() if ".restoring-" in path.name] == []
