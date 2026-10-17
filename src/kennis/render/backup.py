"""The words for a backup: what was written, what a check found, what came back.

Shared by the command line and the window, so both say the same thing
about the same archive. The engine reports facts - a path, a size, a
timestamp, whether every member tested - and these compose them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from kennis.engine.backup import BackupCheck, BackupReport, RestoreReport
from kennis.render.words import DOCS_SITE, count_of

BACKUP_PASSWORD_PROMPT: Final = "Backup password"
NO_BACKUP_FOLDER: Final = "no backup folder is set"
# What the backup holds, said where the folder is chosen (#413, #418).
BACKUP_CONTENTS: Final = (
    "The backup holds the full text of every document and its history, "
    "encrypted with your password."
)
# What encryption does not settle, drawn as a warning (Brian, 2026-10-17):
# a folder a cloud client synchronises is the expected case, and whether
# the material may be there is the law's and the institution's to say. The
# page explains what to check; kennis gives no legal advice.
BACKUP_CAUTION: Final = (
    "Encrypted personal data is still personal data. If the corpus holds "
    "any, such as research participants' details, data-protection law, an "
    "ethics approval or your institution's policy may decide whether a "
    "cloud folder may hold the backup. kennis cannot decide that for you."
)
BACKUP_CAUTION_LINK: Final = "What to check before using a cloud folder"
BACKUP_CAUTION_PAGE: Final = (
    f"{DOCS_SITE}how-to/back-up/#before-you-choose-a-cloud-folder"
)

_UNITS: Final = ("bytes", "kB", "MB", "GB", "TB")


def size_of(count: int) -> str:
    """A byte count as a reader compares it: 1 decimal, powers of 1000."""
    value = float(count)
    for unit in _UNITS:
        if value < 1000 or unit == _UNITS[-1]:
            return f"{count} bytes" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{count} bytes"


def when_of(moment: datetime) -> str:
    """A timestamp in this machine's time zone, to the minute."""
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def describe_written(report: BackupReport) -> str:
    return (
        f"{report.path} ({size_of(report.size)}, "
        f"{count_of(report.members, 'entry', 'entries')})"
    )


def describe_folder(check: BackupCheck) -> str:
    if not check.folder_exists:
        return f"{check.folder} is not there"
    if not check.writable:
        return f"{check.folder} cannot be written to"
    return f"{check.folder} is there and can be written to"


def describe_archive(check: BackupCheck) -> str:
    if check.archive is None or check.size is None or check.modified is None:
        return "no backup has been written there yet"
    return f"{check.archive}, {size_of(check.size)}, written {when_of(check.modified)}"


def describe_verified(verified: bool) -> str:
    if verified:
        return "every file in it opened and matched its checksum"
    return "the password is wrong or the archive is damaged"


def describe_restored(report: RestoreReport) -> str:
    return f"{report.target} ({count_of(report.members, 'entry', 'entries')})"


__all__ = [
    "BACKUP_CAUTION",
    "BACKUP_CAUTION_LINK",
    "BACKUP_CAUTION_PAGE",
    "BACKUP_CONTENTS",
    "BACKUP_PASSWORD_PROMPT",
    "NO_BACKUP_FOLDER",
    "describe_archive",
    "describe_folder",
    "describe_restored",
    "describe_verified",
    "describe_written",
    "size_of",
    "when_of",
]
