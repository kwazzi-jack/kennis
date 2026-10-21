"""What the installed code is, beyond its version (#537).

A reinstall from the same checkout keeps the version and changes the code,
and a service left running from before it once failed half way into the
new code. The build is what tells a client the service is not its own.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kennis import build
from kennis.build import build_of, build_of_this_process
from kennis.render.words import waiting_for_another_version


def a_package(root: Path) -> tuple[Path, Path]:
    package = root / "kennis"
    (package / "engine").mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "engine" / "rag.py").write_text("x = 1\n", encoding="utf-8")
    installed = root / "site-packages"
    installed.mkdir()
    return package, installed


def later(path: Path) -> None:
    """Move a modification time on, as a rewrite would, whatever the
    filesystem's resolution."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def test_the_same_files_are_the_same_build(tmp_path: Path):
    package, installed = a_package(tmp_path)

    assert build_of(package, installed) == build_of(package, installed)


def test_a_rewritten_file_is_another_build(tmp_path: Path):
    package, installed = a_package(tmp_path)
    before = build_of(package, installed)

    later(package / "engine" / "rag.py")

    assert build_of(package, installed) != before


def test_a_new_module_is_another_build(tmp_path: Path):
    package, installed = a_package(tmp_path)
    before = build_of(package, installed)

    (package / "engine" / "modes.py").write_text("", encoding="utf-8")

    assert build_of(package, installed) != before


def test_a_dependency_reinstalled_is_another_build(tmp_path: Path):
    """What #537 was: kennis's files and `filelock`'s both replaced. The
    folder the dependencies live in changes when a package's metadata
    directory is swapped for another version's."""
    package, installed = a_package(tmp_path)
    (installed / "filelock-3.32.7.dist-info").mkdir()
    before = build_of(package, installed)

    (installed / "filelock-3.32.7.dist-info").rename(
        installed / "filelock-4.2.4.dist-info"
    )
    later(installed)

    assert build_of(package, installed) != before


def test_a_process_keeps_the_build_it_started_with(
    monkeypatch: pytest.MonkeyPatch,
):
    """The service names the code it loaded, even after the files change
    under it, so it is asked once and kept."""
    first = build_of_this_process()
    monkeypatch.setattr(build, "build_of", lambda package, installed: "on disk now")

    assert build_of_this_process() == first
    assert first != "on disk now"


def test_waiting_for_an_earlier_installation_does_not_name_a_version_as_other():
    """A busy service of this version but another build is not "version
    0.10.0" to someone running 0.10.0."""
    same = waiting_for_another_version("0.10.0", "0.10.0")
    other = waiting_for_another_version("0.9.0", "0.10.0")

    assert "earlier installation of this version" in same
    assert "0.10.0" not in same
    assert "is version 0.9.0" in other
