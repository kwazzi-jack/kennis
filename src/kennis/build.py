"""What the installed code is, beyond its version (#537).

A reinstall from the same checkout keeps `__version__` and replaces the
code and its dependencies. A service left running from before it holds
the old modules in memory and imports new ones from disk as it goes, and
the two need not fit: one failed asking an old `filelock` for a name only
the new one has. The build names the code, so a client can tell that a
service is not its own.

A digest of the kennis files (path, size, modification time) and of the
modification time of the folder the dependencies are installed in, which
changes when a reinstall swaps a package's metadata directory. Stat calls
only: about 7 ms for the whole package, paid once per process.
"""

from __future__ import annotations

import functools
import hashlib
import sysconfig
from pathlib import Path


def build_of(package: Path, installed: Path) -> str:
    """The build of the package at `package` with its dependencies at
    `installed`."""
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        stat = path.stat()
        relative = path.relative_to(package).as_posix()
        digest.update(f"{relative}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    digest.update(f"{installed.stat().st_mtime_ns}".encode())
    return digest.hexdigest()[:16]


@functools.cache
def build_of_this_process() -> str:
    """The build of the kennis this process imported, taken the first time
    it is asked and kept: the service asks at its start, so it names the
    code it loaded, not what is on disk later."""
    return build_of(
        Path(__file__).resolve().parent, Path(sysconfig.get_paths()["purelib"])
    )


__all__ = ["build_of", "build_of_this_process"]
