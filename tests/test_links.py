"""kennis:// links: written, read, opened, and registered (#8, #593).

A link names a document and a chunk and nothing about where the service
listens, because the service's address and token change with every start
(#569). `kennis open` turns one into the window's address for this start.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.context import existing_corpus
from kennis.engine import scheme
from kennis.engine.errors import KennisError
from kennis.holdings import contents_of
from kennis.links import LinkTarget, NotAKennisLink, link_to, target_of
from kennis.protocol.record import ServiceRecord

RECORD = ServiceRecord(
    address="http://127.0.0.1:4242/",
    token="the-token",
    pid=1,
    started=datetime(2026, 1, 2, tzinfo=UTC),
    version="0",
    corpus="/a corpus",
)


# --- the link itself ------------------------------------------------------


def test_a_link_names_a_document_and_a_chunk():
    assert link_to("k7f2a9c1x0", 14) == "kennis://open/k7f2a9c1x0/14"
    assert link_to("k7f2a9c1x0", None) == "kennis://open/k7f2a9c1x0"


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("kennis://open/k7f2a9c1x0/14", LinkTarget("k7f2a9c1x0", 14)),
        ("kennis://open/k7f2a9c1x0/0", LinkTarget("k7f2a9c1x0", 0)),
        ("kennis://open/k7f2a9c1x0", LinkTarget("k7f2a9c1x0", None)),
        # A trailing slash is what some programs add to an address.
        ("kennis://open/k7f2a9c1x0/14/", LinkTarget("k7f2a9c1x0", 14)),
        ("kennis://open/k7f2a9c1x0/", LinkTarget("k7f2a9c1x0", None)),
        # Windows hands a registered handler the link as it was clicked,
        # and a scheme is case-insensitive.
        ("KENNIS://open/k7f2a9c1x0/3", LinkTarget("k7f2a9c1x0", 3)),
    ],
)
def test_a_link_is_read_back_as_what_it_names(text: str, target: LinkTarget):
    assert target_of(text) == target


@pytest.mark.parametrize(
    "text",
    [
        "https://open/k7f2a9c1x0/14",
        "kennis://read/k7f2a9c1x0/14",
        "kennis://open/",
        "kennis://open/K7F2/14",
        "kennis://open/../etc/14",
        "kennis://open/k7f2a9c1x0/-1",
        "kennis://open/k7f2a9c1x0/one",
        "kennis://open/k7f2a9c1x0/14/more",
        "kennis://open/k7f2a9c1x0/14?token=x",
        "kennis://open/k7f2a9c1x0/14#chunk-14",
        "k7f2a9c1x0",
    ],
)
def test_anything_else_is_not_a_kennis_link(text: str):
    with pytest.raises(NotAKennisLink):
        target_of(text)


def test_a_link_that_is_not_one_is_a_kennis_error_naming_the_form():
    with pytest.raises(KennisError) as refused:
        target_of("kennis://read/x/1")
    assert "kennis://open/" in str(refused.value)


# --- kennis open ----------------------------------------------------------


@pytest.fixture
def note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A corpus holding one indexed note; its identifier."""
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    runner = CliRunner()
    assert runner.invoke(main, ["corpus", "init"]).exit_code == 0
    written = runner.invoke(
        main, ["remember", "--title", "Gains", "Gains drift slowly."]
    )
    assert written.exit_code == 0, written.output
    (document,) = contents_of(existing_corpus(), "notes").documents
    return document.id


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import kennis.client.process as process
    import kennis.gui.browser as browser

    addresses: list[str] = []
    monkeypatch.setattr(process, "ensure_service", lambda root, **_: RECORD)
    monkeypatch.setattr(browser, "open_quietly", addresses.append)
    # Replaced too, so that opening loudly fails a test rather than starting
    # the real browser.
    monkeypatch.setattr(browser.webbrowser, "open", lambda *_, **__: pytest.fail())
    return addresses


def test_a_link_opens_its_document_at_its_chunk(note: str, opened: list[str]):
    result = CliRunner().invoke(main, ["open", f"kennis://open/{note}/0"])

    assert result.exit_code == 0, result.output
    (address,) = opened
    parts = urlsplit(address)
    assert f"{parts.scheme}://{parts.netloc}/" == RECORD.address
    assert parts.path == f"/document/notes/{note}"
    assert parse_qs(parts.query) == {"chunk": ["0"], "token": ["the-token"]}
    # The query marks the chunk; the fragment is what the browser scrolls to.
    assert parts.fragment == "chunk-0"


def test_a_window_already_open_shows_the_passage_and_no_tab_opens(
    note: str, opened: list[str], monkeypatch: pytest.MonkeyPatch
):
    """Brian, 2026-11-01: a click updates the kennis tab already open
    rather than opening another each time."""
    from kennis.client import api

    asked: list[tuple[str, str, int | None]] = []

    def shown(root: Path, collection: str, document_id: str, chunk: int | None) -> bool:
        asked.append((collection, document_id, chunk))
        return True

    monkeypatch.setattr(api, "show_in_window", shown)

    result = CliRunner().invoke(main, ["open", f"kennis://open/{note}/0"])

    assert result.exit_code == 0, result.output
    assert asked == [("notes", note, 0)]
    assert opened == []
    assert "open window" in result.output


def test_with_no_window_answering_a_tab_is_opened(
    note: str, opened: list[str], monkeypatch: pytest.MonkeyPatch
):
    from kennis.client import api

    monkeypatch.setattr(api, "show_in_window", lambda *_: False)

    result = CliRunner().invoke(main, ["open", f"kennis://open/{note}/0"])

    assert result.exit_code == 0, result.output
    assert len(opened) == 1


def test_no_browser_asks_no_window_either(
    note: str, opened: list[str], monkeypatch: pytest.MonkeyPatch
):
    from kennis.client import api

    monkeypatch.setattr(api, "show_in_window", lambda *_: pytest.fail())

    result = CliRunner().invoke(main, ["open", "--no-browser", note])

    assert result.exit_code == 0, result.output
    assert opened == []


def test_a_link_with_no_chunk_opens_the_document(note: str, opened: list[str]):
    result = CliRunner().invoke(main, ["open", f"kennis://open/{note}"])

    assert result.exit_code == 0, result.output
    (address,) = opened
    parts = urlsplit(address)
    assert parts.path == f"/document/notes/{note}"
    assert parse_qs(parts.query) == {"token": ["the-token"]}
    assert parts.fragment == ""


def test_a_handle_opens_as_kennis_read_would_find_it(note: str, opened: list[str]):
    """By title here: the resolution `kennis read` uses, so a citekey or a
    DOI works as well."""
    result = CliRunner().invoke(main, ["open", "Gains", "--chunk", "0"])

    assert result.exit_code == 0, result.output
    (address,) = opened
    assert urlsplit(address).path == f"/document/notes/{note}"
    assert parse_qs(urlsplit(address).query)["chunk"] == ["0"]


def test_without_a_browser_the_address_is_printed(note: str, opened: list[str]):
    result = CliRunner().invoke(
        main, ["open", f"kennis://open/{note}/0", "--no-browser"]
    )

    assert result.exit_code == 0, result.output
    assert opened == []
    assert f"/document/notes/{note}?" in result.output


def test_a_link_and_a_chunk_option_together_are_refused(note: str, opened: list[str]):
    result = CliRunner().invoke(
        main, ["open", f"kennis://open/{note}/0", "--chunk", "1"]
    )

    assert result.exit_code != 0
    assert opened == []
    assert "--chunk" in result.output


def test_a_link_to_a_document_no_longer_held_says_so(note: str, opened: list[str]):
    result = CliRunner().invoke(main, ["open", "kennis://open/zzzzzzzzzz/0"])

    assert result.exit_code != 0
    assert opened == []
    assert "zzzzzzzzzz" in result.output


# --- registering the scheme on Linux --------------------------------------


@pytest.fixture
def desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The XDG folders a desktop reads, under the test's own folder."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    # Not this machine's desktop database: nothing outside the folders above
    # may be touched.
    monkeypatch.setattr(scheme, "_refresh_desktop_database", lambda folder: None)
    return tmp_path


def entry_file(desktop: Path) -> Path:
    return desktop / "data" / "applications" / scheme.DESKTOP_ENTRY


def mimeapps(desktop: Path) -> Path:
    return desktop / "config" / "mimeapps.list"


def test_registering_on_linux_writes_an_entry_that_runs_this_python(desktop: Path):
    registration = scheme.register_on_linux()

    entry = entry_file(desktop).read_text(encoding="utf-8")
    # A Windows runner's interpreter path holds backslashes, which the entry
    # escapes; the rule itself is the next test's.
    quoted = sys.executable.replace("\\", "\\\\")
    assert f'Exec="{quoted}" -m kennis.cli.link_handler %u' in entry
    assert "MimeType=x-scheme-handler/kennis;" in entry
    assert registration.written == (
        str(entry_file(desktop)),
        str(mimeapps(desktop)),
    )


def test_the_entry_quotes_the_interpreter_as_the_specification_asks() -> None:
    # One relative part with no forward slash, so it prints alike everywhere.
    entry = scheme.desktop_entry(Path('my "py" $HOME `in\\python'))

    assert 'Exec="my \\"py\\" \\$HOME \\`in\\\\python" -m' in entry


def test_registering_makes_it_the_default_and_keeps_every_other_line(
    desktop: Path,
):
    mimeapps(desktop).parent.mkdir(parents=True)
    mimeapps(desktop).write_text(
        "# mine\n"
        "[Default Applications]\n"
        "text/html=firefox.desktop\n"
        "x-scheme-handler/kennis=old-kennis.desktop\n"
        "\n"
        "[Added Associations]\n"
        "image/png=eog.desktop;\n",
        encoding="utf-8",
    )

    scheme.register_on_linux()

    assert mimeapps(desktop).read_text(encoding="utf-8") == (
        "# mine\n"
        "[Default Applications]\n"
        "text/html=firefox.desktop\n"
        f"x-scheme-handler/kennis={scheme.DESKTOP_ENTRY}\n"
        "\n"
        "[Added Associations]\n"
        "image/png=eog.desktop;\n"
    )


def test_registering_adds_the_section_a_list_lacks(desktop: Path):
    mimeapps(desktop).parent.mkdir(parents=True)
    mimeapps(desktop).write_text(
        "[Added Associations]\nimage/png=eog.desktop;\n", encoding="utf-8"
    )

    scheme.register_on_linux()

    assert mimeapps(desktop).read_text(encoding="utf-8") == (
        "[Added Associations]\n"
        "image/png=eog.desktop;\n"
        "\n"
        "[Default Applications]\n"
        f"x-scheme-handler/kennis={scheme.DESKTOP_ENTRY}\n"
    )


def test_registering_twice_writes_the_same_files(desktop: Path):
    scheme.register_on_linux()
    first = (
        entry_file(desktop).read_bytes(),
        mimeapps(desktop).read_bytes(),
    )

    scheme.register_on_linux()

    assert (entry_file(desktop).read_bytes(), mimeapps(desktop).read_bytes()) == first


def test_removing_undoes_registering_and_nothing_else(desktop: Path):
    mimeapps(desktop).parent.mkdir(parents=True)
    before = "[Default Applications]\ntext/html=firefox.desktop\n"
    mimeapps(desktop).write_text(before, encoding="utf-8")
    scheme.register_on_linux()

    removed = scheme.remove_on_linux()

    assert not entry_file(desktop).exists()
    assert mimeapps(desktop).read_text(encoding="utf-8") == before
    assert removed.removed


def test_removing_leaves_another_program_s_kennis_handler_alone(desktop: Path):
    mimeapps(desktop).parent.mkdir(parents=True)
    theirs = "[Default Applications]\nx-scheme-handler/kennis=theirs.desktop\n"
    mimeapps(desktop).write_text(theirs, encoding="utf-8")

    removed = scheme.remove_on_linux()

    assert mimeapps(desktop).read_text(encoding="utf-8") == theirs
    assert not removed.removed


def test_the_link_commands_register_and_remove(
    desktop: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(scheme.sys, "platform", "linux")
    runner = CliRunner()

    registered = runner.invoke(main, ["link", "register"])
    assert registered.exit_code == 0, registered.output
    assert entry_file(desktop).exists()

    removed = runner.invoke(main, ["link", "remove"])
    assert removed.exit_code == 0, removed.output
    assert not entry_file(desktop).exists()


def test_macos_is_refused_naming_kennis_open(monkeypatch: pytest.MonkeyPatch):
    """Only an installed application can claim a scheme there, and no Mac
    has run the one #8 proposes."""
    monkeypatch.setattr(scheme.sys, "platform", "darwin")

    result = CliRunner().invoke(main, ["link", "register"])

    assert result.exit_code != 0
    assert "kennis open" in result.output


# --- registering the scheme on Windows ------------------------------------


def test_the_windows_command_runs_this_python_without_a_console():
    command = scheme.windows_command(Path(r"C:\tools\kennis\Scripts\python.exe"))

    assert command == (
        r'"C:\tools\kennis\Scripts\pythonw.exe" -m kennis.cli.link_handler "%1"'
    )


@pytest.mark.skipif(sys.platform != "win32", reason="the registry is Windows'")
def test_registering_on_windows_writes_and_removes_a_url_protocol():
    """Under a scheme of the test's own, so a person's registration is
    never touched by a run of the suite."""
    name = "kennis-test-registration"
    scheme.register_on_windows(name)
    try:
        assert scheme.registered_command_on_windows(name) == scheme.windows_command(
            Path(sys.executable)
        )
    finally:
        scheme.remove_on_windows(name)
    assert scheme.registered_command_on_windows(name) is None


# --- the handler the desktop runs ----------------------------------------


def test_the_handler_gives_absent_streams_somewhere(monkeypatch: pytest.MonkeyPatch):
    """Under `pythonw.exe` the standard streams are None, and the first
    line a command writes would raise."""
    from kennis.cli import link_handler

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    link_handler.give_absent_streams_somewhere()

    assert sys.stdout is not None
    assert sys.stderr is not None
    sys.stdout.write("")
    sys.stderr.write("")


def test_the_handler_is_kennis_open(monkeypatch: pytest.MonkeyPatch):
    import kennis.cli.__main__ as entry
    from kennis.cli import link_handler

    called: list[list[str]] = []
    monkeypatch.setattr(entry, "main", called.append)

    link_handler.handle(["kennis://open/k7f2a9c1x0/3"])

    assert called == [["open", "kennis://open/k7f2a9c1x0/3"]]


@pytest.mark.service
def test_a_clicked_link_starts_the_service_and_opens_the_browser_there(
    note: str, tmp_path: Path
):
    """The handler as the desktop runs it: a process of its own, with the
    link as its one argument, and nothing running yet. `BROWSER` names a
    program that writes down the address it was given, which `webbrowser`
    runs in place of a browser."""
    from kennis.protocol.record import find_service, is_held

    written = tmp_path / "opened.txt"
    browser = tmp_path / "browser.py"
    browser.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"Path({str(written)!r}).write_text(sys.argv[1], encoding='utf-8')\n",
        encoding="utf-8",
    )
    corpus = existing_corpus().corpus_root
    environment = {**os.environ, "BROWSER": f'"{sys.executable}" "{browser}" %s'}
    try:
        finished = subprocess.run(
            [
                sys.executable,
                "-m",
                "kennis.cli.link_handler",
                f"kennis://open/{note}/0",
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert finished.returncode == 0, finished.stderr
        record = find_service(corpus)
        assert record is not None
        parts = urlsplit(written.read_text(encoding="utf-8"))
        assert f"{parts.scheme}://{parts.netloc}/" == record.address
        assert parts.path == f"/document/notes/{note}"
        assert parse_qs(parts.query) == {"chunk": ["0"], "token": [record.token]}
    finally:
        record = find_service(corpus)
        if record is not None:
            os.kill(record.pid, signal.SIGTERM)
            deadline = time.monotonic() + 30
            while is_held(corpus) and time.monotonic() < deadline:
                time.sleep(0.05)
