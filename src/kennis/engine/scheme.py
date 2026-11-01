"""Registering `kennis://` with this account's desktop (#8, #594).

A clicked link is handed by the program it was clicked in to the operating
system of the machine the person sits at, which runs whatever is registered
for the scheme. On Brian's machine Warp, GNOME Terminal, VS Code's terminal
and Claude Code all hand it on (#594). This writes that registration, for
the current account only, and removes exactly what it wrote.

- **Linux**: a desktop entry in `$XDG_DATA_HOME/applications` declaring
  `x-scheme-handler/kennis`, made the default in `$XDG_CONFIG_HOME/
  mimeapps.list`. That file is the person's, so it is edited as lines: one
  line is set or removed and every other line, comment and section stays.
- **Windows**: a URL protocol under `HKEY_CURRENT_USER\\Software\\Classes`.
- **macOS** is refused: only an installed application can claim a scheme,
  and no Mac has run the applet #8 proposes.

**The handler runs this interpreter by its absolute path**, because a
desktop starts a handler without the shell's PATH, and `uv tool upgrade`
keeps the tool's environment where it is. On Windows it is `pythonw.exe`,
so a click opens no console window (#5).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Final

from kennis.engine.atomic import remove_file, replace_file
from kennis.engine.errors import KennisError

SCHEME: Final = "kennis"

# What the handler runs: `python -m` this module, with the link.
HANDLER_MODULE: Final = "kennis.cli.link_handler"

DESKTOP_ENTRY: Final = "kennis-link.desktop"

_MIME_TYPE: Final = f"x-scheme-handler/{SCHEME}"
_DEFAULTS: Final = "[Default Applications]"
_ADDED: Final = "[Added Associations]"
_DATABASE_SECONDS: Final = 30


class SchemeUnavailable(KennisError):
    """This platform's desktop cannot be given the scheme by kennis."""

    default_message = "kennis cannot register kennis:// links on macOS yet"
    default_resolution = "kennis open <link>"


@dataclass(frozen=True, slots=True)
class Registration:
    """Where the registration was written: files, or a registry key."""

    written: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Removal:
    """What a removal took away; empty when nothing was kennis's."""

    removed: tuple[str, ...]


# Each platform in its own arm of one `if`: mypy checking for another
# platform calls a statement after a platform branch unreachable, and leaves
# one inside an arm alone (as `protocol/spawn.py` does).


def register() -> Registration:
    """Register the scheme on this platform, for this account."""
    if sys.platform == "win32":
        return register_on_windows()
    elif sys.platform == "darwin":
        raise SchemeUnavailable()
    else:
        return register_on_linux()


def remove() -> Removal:
    """Remove what `register` wrote on this platform, and nothing else."""
    if sys.platform == "win32":
        return remove_on_windows()
    elif sys.platform == "darwin":
        raise SchemeUnavailable()
    else:
        return remove_on_linux()


# --- Linux and the other free desktops ------------------------------------


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _exec_argument(argument: str) -> str:
    """One argument of a desktop entry's `Exec`, quoted as the specification
    asks: double quotes, with `"`, `` ` ``, `$` and `\\` escaped inside."""
    escaped = "".join(
        f"\\{character}" if character in '"`$\\' else character
        for character in argument
    )
    return f'"{escaped}"'


def desktop_entry(python: Path) -> str:
    """The desktop entry that hands a clicked link to `python`."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=kennis link\n"
        "Comment=Opens a kennis:// link in the kennis window\n"
        f"Exec={_exec_argument(str(python))} -m {HANDLER_MODULE} %u\n"
        "NoDisplay=true\n"
        "Terminal=false\n"
        f"MimeType={_MIME_TYPE};\n"
    )


def register_on_linux() -> Registration:
    entry = _data_home() / "applications" / DESKTOP_ENTRY
    replace_file(entry, desktop_entry(Path(sys.executable)))
    mimeapps = _config_home() / "mimeapps.list"
    existing = mimeapps.read_text(encoding="utf-8") if mimeapps.exists() else ""
    replace_file(mimeapps, with_default(existing, _MIME_TYPE, DESKTOP_ENTRY))
    _refresh_desktop_database(entry.parent)
    return Registration(written=(str(entry), str(mimeapps)))


def remove_on_linux() -> Removal:
    removed: list[str] = []
    entry = _data_home() / "applications" / DESKTOP_ENTRY
    if entry.exists():
        remove_file(entry)
        removed.append(str(entry))
        _refresh_desktop_database(entry.parent)
    mimeapps = _config_home() / "mimeapps.list"
    if mimeapps.exists():
        existing = mimeapps.read_text(encoding="utf-8")
        kept = without_entry(existing, _MIME_TYPE, DESKTOP_ENTRY)
        if kept != existing:
            replace_file(mimeapps, kept)
            removed.append(str(mimeapps))
    return Removal(removed=tuple(removed))


def _refresh_desktop_database(folder: Path) -> None:
    """Rebuild the folder's cache of which entry takes which type, where the
    desktop has the program; the default in `mimeapps.list` does not need
    it, and a desktop without it reads the entries themselves."""
    program = shutil.which("update-desktop-database")
    if program is None:
        return
    subprocess.run(
        [program, str(folder)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=_DATABASE_SECONDS,
        check=False,
    )


def _section_bounds(lines: list[str], header: str) -> tuple[int, int] | None:
    """The first line after `header` and the line ending its section."""
    for position, line in enumerate(lines):
        if line.strip() == header:
            end = position + 1
            while end < len(lines) and not lines[end].lstrip().startswith("["):
                end += 1
            return position + 1, end
    return None


def with_default(text: str, mime_type: str, entry: str) -> str:
    """`mimeapps.list` text with `entry` as the default for `mime_type`.

    The line for the type is replaced where it is, or added after the last
    line of the section that is not blank, or the section is added at the
    end; nothing else in the text changes.
    """
    lines = text.splitlines()
    line = f"{mime_type}={entry}"
    bounds = _section_bounds(lines, _DEFAULTS)
    if bounds is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([_DEFAULTS, line])
        return "\n".join(lines) + "\n"
    start, end = bounds
    for position in range(start, end):
        if lines[position].split("=", 1)[0].strip() == mime_type:
            lines[position] = line
            return "\n".join(lines) + "\n"
    last = end
    while last > start and not lines[last - 1].strip():
        last -= 1
    lines.insert(last, line)
    return "\n".join(lines) + "\n"


def without_entry(text: str, mime_type: str, entry: str) -> str:
    """`mimeapps.list` text with `entry` no longer named for `mime_type`.

    A default naming another program is left as it is, and so is every
    other line.
    """
    lines = text.splitlines()
    for header in (_DEFAULTS, _ADDED):
        bounds = _section_bounds(lines, header)
        if bounds is None:
            continue
        start, end = bounds
        for position in reversed(range(start, end)):
            key, separator, value = lines[position].partition("=")
            if not separator or key.strip() != mime_type:
                continue
            named = [name for name in value.strip().split(";") if name]
            kept = [name for name in named if name != entry]
            if kept == named:
                continue
            if kept:
                ending = ";" if value.strip().endswith(";") else ""
                lines[position] = f"{mime_type}={';'.join(kept)}{ending}"
            else:
                del lines[position]
    return "\n".join(lines) + "\n" if lines else ""


# --- Windows --------------------------------------------------------------

_CLASSES: Final = r"Software\Classes"
_REGISTRY_ONLY: Final = "the registry is Windows' alone"


def windows_command(python: Path) -> str:
    """The command Windows runs for a clicked link: `pythonw.exe` beside
    `python`, so no console window opens, with the link as one argument."""
    interpreter = PureWindowsPath(str(python))
    if interpreter.name.lower() == "python.exe":
        interpreter = interpreter.with_name("pythonw.exe")
    return f'"{interpreter}" -m {HANDLER_MODULE} "%1"'


def register_on_windows(scheme: str = SCHEME) -> Registration:
    if sys.platform == "win32":
        import winreg

        root = rf"{_CLASSES}\{scheme}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"URL:{scheme} link")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        command = windows_command(Path(sys.executable))
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, rf"{root}\shell\open\command"
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
        return Registration(written=(rf"HKEY_CURRENT_USER\{root}",))
    else:
        raise SchemeUnavailable(_REGISTRY_ONLY)


def registered_command_on_windows(scheme: str = SCHEME) -> str | None:
    """The command registered for `scheme`, or None if there is none."""
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, rf"{_CLASSES}\{scheme}\shell\open\command"
            ) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except FileNotFoundError:
            return None
        return str(value)
    else:
        raise SchemeUnavailable(_REGISTRY_ONLY)


def remove_on_windows(scheme: str = SCHEME) -> Removal:
    """Remove the scheme's key if its command is kennis's handler; another
    program's registration of the name is left alone."""
    if sys.platform == "win32":
        import winreg

        command = registered_command_on_windows(scheme)
        if command is None or HANDLER_MODULE not in command:
            return Removal(removed=())
        root = rf"{_CLASSES}\{scheme}"
        # A key with subkeys cannot be deleted, so the deepest goes first.
        deepest_first = (
            rf"{root}\shell\open\command",
            rf"{root}\shell\open",
            rf"{root}\shell",
            root,
        )
        for path in deepest_first:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        return Removal(removed=(rf"HKEY_CURRENT_USER\{root}",))
    else:
        raise SchemeUnavailable(_REGISTRY_ONLY)


__all__ = [
    "DESKTOP_ENTRY",
    "HANDLER_MODULE",
    "SCHEME",
    "Registration",
    "Removal",
    "SchemeUnavailable",
    "desktop_entry",
    "register",
    "register_on_linux",
    "register_on_windows",
    "registered_command_on_windows",
    "remove",
    "remove_on_linux",
    "remove_on_windows",
    "windows_command",
    "with_default",
    "without_entry",
]
