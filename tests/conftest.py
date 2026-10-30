"""Fixtures shared across test modules.

Only the ones more than one module needs. A fixture used by a single file
stays in that file, where its reason for existing sits next to its use.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from in_process import InProcessServices
from kennis.client import connection
from kennis.engine.courtesy import forget_hosts
from kennis.engine.settings import state_dir
from kennis.protocol.record import find_service
from platforms import NO_POSIX_SHELL

# A fake MinerU. It parses the flags the converter passes, writes one markdown
# file per staged input in the nested layout the real tool produces, and can
# be told to fail one document or all of them.
FAKE_MINERU = r"""#!/bin/sh
set -e
while [ $# -gt 0 ]; do
    case "$1" in
        -p) input_dir="$2"; shift 2 ;;
        -o) output_dir="$2"; shift 2 ;;
        -b) backend="$2"; shift 2 ;;
        -s|-e) shift 2 ;;
        *) shift ;;
    esac
done
echo "backend=$backend" >> "$MINERU_FAKE_LOG"
echo "device=${MINERU_DEVICE_MODE-unset} source=${MINERU_MODEL_SOURCE-unset}" \
    >> "$MINERU_FAKE_LOG"
for staged in "$input_dir"/*; do
    stem=$(basename "$staged")
    stem=${stem%.*}
    case "$stem" in
        *$MINERU_FAKE_SKIP*) continue ;;
    esac
    mkdir -p "$output_dir/$stem/auto"
    printf '# %s\n\nConverted body.\n' "$stem" > "$output_dir/$stem/auto/$stem.md"
    printf 'tiny\n' > "$output_dir/$stem/auto/${stem}_small.md"
    printf '[{"type":"page_aside_text","page_idx":0,' > "$tmp_json"
    printf '"text":"arXiv:1101.1764v2 [astro-ph.IM]"}]' >> "$tmp_json"
    cp "$tmp_json" "$output_dir/$stem/auto/${stem}_content_list.json"
done
exit "${MINERU_FAKE_EXIT-0}"
"""


@pytest.fixture(autouse=True)
def refusing_as_windows_does(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Windows refuses to replace or delete a read-only file; POSIX asks
    only whether the directory is writable. So on Linux every step kennis
    takes to make a file writable before replacing or removing it is inert,
    and an injection removing one passes. Under this fixture the two calls
    every such path ends in refuse as Windows would, here too.

    For every test, not one file's (14f): five tests damaged a pack's store
    by deleting a file kennis had made read-only, passed here, and failed
    on Windows, which was the first place anything said so (#532)."""
    real_replace = os.replace
    real_unlink = os.unlink

    def is_read_only_at(path: str | Path, dir_fd: int | None) -> bool:
        try:
            mode = os.stat(path, dir_fd=dir_fd, follow_symlinks=False).st_mode
        except FileNotFoundError:
            return False
        return stat.S_ISREG(mode) and not mode & stat.S_IWRITE

    def replace(source: str | Path, target: str | Path) -> None:
        if is_read_only_at(target, None):
            raise PermissionError(13, "read-only, as Windows refuses", str(target))
        real_replace(source, target)

    def unlink(path: str | Path, *, dir_fd: int | None = None) -> None:
        if is_read_only_at(path, dir_fd):
            raise PermissionError(13, "read-only, as Windows refuses", str(path))
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "unlink", unlink)
    monkeypatch.setattr(os, "remove", unlink)
    yield


@pytest.fixture(autouse=True)
def offline_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches Hugging Face unless it asks to.

    `retrieval.corpus_method` defaults to `hybrid`, so `kennis corpus index`
    builds a dense index; `embed_texts` builds an embedder when the caller
    supplied none, and building one downloads the model. A test that drives
    the command line supplies none, so this setting is the only thing
    between the default suite and a 65 MB download.

    It was set per module in seven files and missing from an eighth, which
    nothing here could notice: the model is cached in
    `~/.cache/kennis/models` on a developer machine, so the download happens
    once, invisibly, and never again. It took a fresh CI runner to show it
    (concern #253). Autouse makes the safe case the default; a module that
    wants a real backend sets its own value, which runs after this and wins.
    """
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")


HOME_DIRNAME = "home-elsewhere"


def playwright_browsers_of(home: Path) -> Path:
    """Where `playwright install` puts its browsers for `home`, by
    Playwright's own default on each platform."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else home / "AppData" / "Local") / "ms-playwright"
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    cache = os.environ.get("XDG_CACHE_HOME")
    return (Path(cache) if cache else home / ".cache") / "ms-playwright"


@pytest.fixture(autouse=True)
def home_elsewhere(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A test's home is a folder no `tmp_path` lies inside.

    The command line shows a path under home from `~` (#575). On Windows the
    temporary folder is under the home folder
    (`C:\\Users\\runneradmin\\AppData\\Local\\Temp`), so every path a test
    built in `tmp_path` was shown from `~` there and six tests failed on CI
    while passing here, where `/tmp` is not under home. `Path.home()` reads
    `HOME` on POSIX and `USERPROFILE` on Windows, so both are set.
    `test_architecture.py` fails if this is removed.

    Playwright finds the browser `playwright install` put under the real
    home by reading home, so it is told that folder first; without it every
    browser test failed to launch on CI.
    """
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        monkeypatch.setenv(
            "PLAYWRIGHT_BROWSERS_PATH", str(playwright_browsers_of(Path.home()))
        )
    home = tmp_path_factory.getbasetemp() / HOME_DIRNAME
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


@pytest.fixture(autouse=True)
def nowhere_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test writes to the developer's own state directory.

    `gui/history.py` records searches under `KENNIS_STATE_DIR`,
    which defaults to platformdirs' `user_state_dir("kennis")` -
    a real path on a real machine. A test that drives the interface
    and does not set it would append to Brian's own recent searches,
    and nothing in the test would fail to say so.

    The same hazard and the same remedy as `somewhere_else` and
    concern #325: redirect it for every test, and have
    `test_architecture.py` fail if this fixture is removed.
    """
    monkeypatch.setenv("KENNIS_STATE_DIR", str(tmp_path / "state-dir"))


@pytest.fixture(autouse=True)
def no_real_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reads the developer's configuration or writes their log.

    `config_dir` and `log_dir` fall back to platformdirs' real paths.
    On this machine the configuration directory holds `.env.keys`,
    which `credential` reads, so a test that did not set the variable
    was offered Brian's own API key; and a test that ran `config set`
    would have written his `config.toml`. The log had 311 lines from
    test runs in it, the latest from a subprocess that inherited an
    environment with no override.

    The fourth of the kind, with the same remedy as `nowhere_real`,
    `no_real_corpus` and `somewhere_else`: redirect for every test,
    and have `test_architecture.py` fail if this is removed. A test
    that sets its own value runs after this and wins. Concern #442.
    """
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config-dir"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "log-dir"))


@pytest.fixture(autouse=True)
def no_real_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reads the developer's own corpus.

    `context.existing_corpus` resolves `KENNIS_CORPUS_ROOT`, then
    `corpus.root` in the configuration, then the platform's data
    directory. A test that builds an app without naming a corpus -
    `build_app(TOKEN)` does exactly that - therefore reached
    `~/.local/share/kennis`, which on this machine is Brian's real
    corpus of 55 documents.

    It passed here for five units and failed on every CI platform at
    once, because a runner has no corpus there. That is the tell:
    the outcome depended on the developer's machine, so the test was
    asserting nothing about kennis.

    Pointed at a path that does **not** exist, rather than at an
    empty corpus. A test that needs a corpus should say so and build
    one; being handed a usable one by accident is how this started.

    The third of the same kind, and the same remedy as
    `nowhere_real` and `somewhere_else`: redirect it for every test,
    and have `test_architecture.py` fail if this fixture is removed.
    Concerns #325 and #361.
    """
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "no-corpus-here"))


@pytest.fixture(autouse=True)
def somewhere_else(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test runs in the repository's own working directory.

    `find_bundle` walks **up from the working directory**, and under
    `pytest` that directory is this checkout. So a test that ran
    `kennis context init` created `.context/` in the repository, and
    every later test that wrote to a bundle then found it and wrote a
    note into Brian's working tree. That happened, in the session that
    added this. Concern #325.

    Autouse for the same reason `offline_embedding` is: the safe case
    is the default, and a test that wants a particular directory
    chdirs itself, which runs after this and wins.
    """
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def hosts_forgotten() -> None:
    """Each test starts with no host's robots.txt read and no request timed.

    `engine/courtesy.py` keeps both for the process, so without this a test
    inherits the rules a previous test's mock served, and waits on its clock.
    """
    forget_hosts()


# Addresses a test may reach: the window's own server, on this machine.
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


@pytest.fixture(autouse=True)
def no_real_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No test reaches a host unless it is marked `network`.

    Patched where every real `httpx` request passes and an
    `httpx.MockTransport` never does. `pytest.fail` rather than an `httpx`
    error, because kennis reads a failed request as "the host is down" and
    carries on - which is how a test that reached arXiv passed in silence.
    Concern #495.
    """
    if request.node.get_closest_marker("network") is not None:
        return
    real = httpx.HTTPTransport.handle_request

    def refused(
        transport: httpx.HTTPTransport, outgoing: httpx.Request
    ) -> httpx.Response:
        if outgoing.url.host in _LOOPBACK:
            return real(transport, outgoing)
        pytest.fail(
            f"a test reached {outgoing.url}: give it an httpx.MockTransport, "
            "or mark it `network`"
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refused)


@pytest.fixture
def fake_mineru(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a fake `mineru` first on PATH and return the log it writes.

    Skipped rather than marked, so every test that takes this fixture is
    covered and so is the next one somebody writes. The reason is in
    `tests/platforms.py` with the others. Concern #392.
    """
    if os.name == "nt":
        pytest.skip(NO_POSIX_SHELL)
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    script = binary_dir / "mineru"
    log = tmp_path / "mineru.log"
    script.write_text(
        FAKE_MINERU.replace("$tmp_json", str(tmp_path / "content.json")),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{binary_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("MINERU_FAKE_LOG", str(log))
    monkeypatch.setenv("MINERU_FAKE_SKIP", "__never_matches__")
    return log


@pytest.fixture
def no_mineru(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment with no `mineru` anywhere kennis looks.

    Both places, not just PATH. kennis falls back to the directory of the
    interpreter it is running on, because `uv tool install kennis`
    puts mineru there and never on PATH - and this checkout's own `.venv/bin`
    holds a real mineru, so emptying PATH alone left four tests asserting
    absence while the real converter ran.
    """
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    interpreter = empty / "python"
    interpreter.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(interpreter))


@pytest.fixture(autouse=True)
def service_in_this_process(monkeypatch: pytest.MonkeyPatch) -> InProcessServices:
    """Every command reaches a service built in this process (14c).

    Autouse for the reason the others are: a test that forgot would start
    a real service, outside every monkeypatch and guard here (#503), and
    `test_architecture.py` fails if this is removed. The `service` suite
    starts processes on purpose and calls `ensure_service` itself.
    """
    services = InProcessServices()
    monkeypatch.setattr(connection, "connect", services.connect)
    return services


@pytest.fixture(autouse=True)
def no_service_left_running(request: pytest.FixtureRequest) -> Iterator[None]:
    """A test not marked `service` that started a real service fails, and
    the service is ended (14c).

    A command run as a real process - the installed `kennis` in a
    subprocess - starts a real service for its corpus, outside every guard
    here, and that service stays for its idle timeout. One test did this
    and left a process waiting on a lock for every run of the suite. The
    records are under the test's own state directory, so only this test's
    services are seen.
    """
    yield
    if request.node.get_closest_marker("service") is not None:
        return
    # A record is a service only while its corpus lock is held, which is
    # what `find_service` asks: a test of the records writes records with
    # made-up process ids, and signalling one of those would signal
    # whatever process happens to have that id.
    running = []
    for path in sorted(state_dir().glob("service-*.json")):
        with contextlib.suppress(ValueError, OSError, KeyError):
            corpus = Path(json.loads(path.read_text(encoding="utf-8"))["corpus"])
            found = find_service(corpus)
            if found is not None and found.pid != os.getpid():
                running.append(found.pid)
    for pid in running:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM if sys.platform == "win32" else signal.SIGKILL)
    if running:
        pytest.fail(
            "a test not marked `service` started a real kennis service; "
            "mark it, or drive the command in this process with CliRunner"
        )
