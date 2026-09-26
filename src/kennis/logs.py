"""The log file, and the event subscriber that fills it.

Design section 14 states the rule in one sentence: **the report is not the
log.** The report is for the person running the command and lives as long as
their terminal session; the log is for whoever is debugging afterwards and
lives in rotated files. Conflating them is the classic failure - user-facing
output emitted through `logging.info` means log levels start controlling the
interface, and `-v` becomes the only way to find out what a command did.

**The library logs; the application configures.** `kennis/__init__.py`
installs a `NullHandler` and nothing else; `start_logging` is called by an
entry point. This module sits at the top level rather than under `cli/`
because the MCP server will need the same file, and a second front end
reaching into the first is the coupling `render/` exists to avoid.

**stdout is never a sink.** Under an MCP server, stdout is the JSON-RPC
wire.
boepie was burned by exactly this: a library's module-level console put 567
bytes of INFO into the stream and the client answered `Invalid JSON: trailing
characters at line 1 column 5`. Nothing here writes to stdout.

**Nothing in kennis reads its own log.** It is a diagnostic record, not a
data source. A log that code reads becomes a second source of truth that can
disagree with the corpus.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from platformdirs import user_log_dir

from kennis.engine.events import (
    Diagnostic,
    Event,
    ItemFinished,
    ItemStarted,
    OperationFinished,
    Progress,
    Severity,
)

_LOGGER_NAME: Final = "kennis"
_LOG_FILE: Final = "kennis.log"
_LOG_DIR_VARIABLE: Final = "KENNIS_LOG_DIR"

_DEFAULT_MAX_BYTES: Final = 1_048_576
_DEFAULT_BACKUP_COUNT: Final = 3

# Timestamp, level, and the message. No colour and no layout: this file is
# read with `less` and grep, and `_display` owns everything a person sees in
# a terminal.
_FORMAT: Final = "%(asctime)s %(levelname)-8s %(name)s %(message)s"

_SEVERITY_LEVELS: Final[dict[Severity, int]] = {
    Severity.WARNING: logging.WARNING,
    Severity.ERROR: logging.ERROR,
    Severity.HINT: logging.INFO,
}

_installed: RotatingFileHandler | None = None


def log_dir() -> Path:
    """Where kennis keeps its log.

    `KENNIS_LOG_DIR` overrides the platform default, through the same
    mechanism a user gets rather than a back door only tests know about.
    """
    override = os.environ.get(_LOG_DIR_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(user_log_dir("kennis"))


def log_path() -> Path:
    return log_dir() / _LOG_FILE


def start_logging(
    *,
    level: int = logging.DEBUG,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
) -> Path:
    """Install the file handler and return where it writes.

    **Always on, not behind a flag.** The log is what you ask for when
    something went wrong, so it has to already exist by then.
    """
    global _installed
    stop_logging()

    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / _LOG_FILE,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.setLevel(level)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.addHandler(handler)
    # The root logger has its own handlers in some hosts, and stdout is
    # sometimes among them - which under `serve` is the JSON-RPC wire.
    logger.propagate = False
    _installed = handler
    return directory / _LOG_FILE


def stop_logging() -> None:
    """Remove the file handler, if one is installed."""
    global _installed
    if _installed is None:
        return
    logging.getLogger(_LOGGER_NAME).removeHandler(_installed)
    _installed.close()
    _installed = None


class LogSink:
    """An `EventSink` that writes **every** event to the log.

    The display subscribes to the same stream and filters; this does not.
    That asymmetry is the whole argument for a stream over a progress
    callback: section 14 requires the log to record what the report omits -
    which fifteen documents were skipped and why each one, rather than the
    count - and with a stream that is a difference in filtering rather than a
    difference in instrumentation.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(f"{_LOGGER_NAME}.events")

    def emit(self, event: Event) -> None:
        match event:
            case ItemStarted():
                self._logger.debug("%s started: %s", event.operation, event.item)
            case ItemFinished():
                self._logger.info(
                    "%s %s: %s%s",
                    event.operation,
                    event.outcome.value,
                    event.item,
                    f" ({event.reason})" if event.reason else "",
                )
            case Progress():
                self._logger.debug(
                    "%s progress: %s of %s",
                    event.operation,
                    event.completed,
                    event.total if event.total is not None else "?",
                )
            case Diagnostic():
                self._logger.log(
                    _SEVERITY_LEVELS.get(event.severity, logging.INFO),
                    "%s%s",
                    event.message,
                    f" [{event.resolution}]" if event.resolution else "",
                )
            case OperationFinished():
                self._logger.info(
                    "%s finished in %.2fs: %s",
                    event.operation,
                    event.elapsed_seconds,
                    ", ".join(
                        f"{outcome.value}={count}"
                        for outcome, count in event.counts.items()
                    )
                    or "nothing",
                )
