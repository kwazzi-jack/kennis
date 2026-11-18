"""Turning a binary document into markdown, behind one interface.

Two implementations: MinerU locally, Datalab hosted. The hosted one is never
a default, because choosing it sends the document to a third party - see
`rules.md` 4.5.

**A converter takes a batch, not a document.** That is the design rather than
a convenience: MinerU loads its model stack before it converts anything, and
a process per document pays that toll every time. Measured on a 19-page
paper, warm cache, pipeline backend on a GPU (concern #137):

    1 page  13.3s      5 pages  23.3s      19 pages  33.9s

So about 13s buys a loaded model stack and nothing else, then roughly 1.1s
per page - one page costs 40% of what nineteen cost. The same paper on the
CPU takes 307.5s, which is 9.1x, so the device dominates everything else
here.

Datalab wants batching for no reason at all: there is no batch endpoint, so
a batch is one request per document. `ConversionBatch` fits either way,
because it reports per document rather than per run.

**A batch reports per document.** A converter converts what it can and records
the rest, so a path missing from `markdown` is that document's failure alone
and must not cost the others. `failure_reason` is the process's own wording
when it exited badly, which is the only context a bare "produced nothing"
would lack.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, Protocol, runtime_checkable

import httpx

from kennis.engine.cancelling import cancellation_asked, pause
from kennis.engine.corpus.images import kept_images
from kennis.engine.corpus.ligatures import (
    repair_ligatures,
    text_layer_vocabulary,
)
from kennis.engine.corpus.markdown import normalise_markdown
from kennis.engine.corpus.schema import SourceFormat
from kennis.engine.errors import (
    ConversionFailed,
    ConverterRefused,
    ConverterUnavailable,
    TaskCancelled,
)
from kennis.engine.settings import credential, load_settings
from kennis.telemetry import LIBRARY_TELEMETRY_OFF


@dataclass(frozen=True, slots=True)
class ConversionBatch:
    """What one converter run produced, per document."""

    markdown: dict[Path, str]
    # Page-one text per document, page furniture included. Carried out of the
    # run's temporary directory because that is the only place it exists: the
    # content list is discarded with the run, and the markdown never had it.
    front_page: dict[Path, str] = field(default_factory=dict)
    # Page one's header, footer, margin and page number alone: where a paper
    # stamps its own identity, and so where an identifier is looked for
    # first. A footnote is not one - it is where a paper cites another
    # (#689).
    stamps: dict[Path, str] = field(default_factory=dict)
    # The process's own wording when it exited non-zero, whether or not it
    # still produced output for some documents.
    failure_reason: str | None = None
    # What the run cost, in cents, when the converter was told. `None` is
    # "nothing was reported", which is what a local converter always means -
    # not `0.0`, which is a claim about money. A hosted conversion of a
    # document the server has already seen genuinely does return `0.0`.
    cost_cents: float | None = None
    # Ligature repairs made per document. A count rather than a flag, because
    # it is a direct measure of how badly a converter handled this document -
    # the number that would have shown concern #135 the day it appeared.
    repairs: dict[Path, int] = field(default_factory=dict)
    # The images each document's markdown links, by the name the markdown
    # links them under (`images.kept_images`). Carried out of the run's
    # temporary directory for the same reason `front_page` is: nothing else
    # holds them once the run is over, and before this every figure link in
    # a stored paper pointed at nothing (#134). A document that links none
    # has no entry.
    images: dict[Path, dict[str, bytes]] = field(default_factory=dict)


@runtime_checkable
class Converter(Protocol):
    """What the add path needs from any converter.

    A Protocol rather than a base class so the engine needs no registry that
    imports every implementation - the hosted one will want an HTTP client and
    credentials, and nothing should pay for that to convert a PDF locally.
    """

    name: str
    # What else, beside the converter, decides the text it writes for one
    # document: MinerU's tier, Datalab's mode. A kept conversion is keyed by
    # it, so one made at another quality is not handed back (#526).
    variant: str
    formats: frozenset[SourceFormat]

    def is_available(self) -> bool:
        """Whether this converter can run at all on this machine."""
        ...

    def install_hint(self) -> str:
        """The command that would make it available."""
        ...

    def convert(self, paths: Sequence[Path]) -> ConversionBatch:
        """Convert a whole batch in one run."""
        ...


# ---------------------------------------------------------------------------
# MinerU
# ---------------------------------------------------------------------------
#
# Driven through its command line rather than its Python interface. MinerU
# loads its model stack at import time, which would make every kennis
# invocation pay for a dependency almost no command uses; a subprocess also
# keeps a model crash from taking the process down with it, and makes the
# tool's absence a fact to report rather than an ImportError.
#
# MinerU 4 (#683, #685): `mineru-kit parse <files> -o <dir> --format zip
# --tier <tier>` is a one-shot conversion that starts no server, and writes
# one `<stem>.zip` per input holding `markdown.md`, `images/` and
# `structured_content.json`. Plain markdown output embeds every image as
# base64 in the text, which is why the zip is asked for.

_MINERU_FORMATS: Final[dict[str, SourceFormat]] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
}

MINERU_FORMATS: Final[frozenset[SourceFormat]] = frozenset(_MINERU_FORMATS.values())

# mineru is a base dependency (#423), so a missing one is an install that
# did not finish - a sync that dropped it, or a platform where it failed to
# resolve - and the remedy is to install kennis again. Which command does
# that depends on how kennis itself was installed, and the two are not
# interchangeable: there is no project to sync for somebody who installed
# the tool, and `uv tool install` is not what a contributor with a checkout
# wants. Rule: an error names the command that resolves it, so it has to
# name the right one.
_SOURCE_INSTALL_HINT: Final = "uv sync"
_TOOL_INSTALL_HINT: Final = "uv tool install --reinstall kennis"


def _is_source_checkout(root: Path) -> bool:
    """Whether `root` is kennis's own source tree rather than a venv.

    Split from the caller so both answers are testable. The false case is the
    one that matters and the one a test cannot reach through `__file__`:
    a hint is only wrong when kennis is installed, and the tests run from a
    checkout.
    """
    return (root / "pyproject.toml").is_file() and (root / "src" / "kennis").is_dir()


def _from_source_checkout() -> bool:
    """Whether this kennis is running from its own source tree.

    True for a checkout, whether or not it is installed editable, because the
    module then sits at `<root>/src/kennis/engine/corpus/` with the project's
    own `pyproject.toml` above it. False for an installed copy, where the
    same walk lands inside `lib/python3.x/` and finds nothing.
    """
    return _is_source_checkout(Path(__file__).resolve().parents[4])


def _executable(name: str) -> str | None:
    """`name` on PATH, or failing that beside the interpreter kennis runs on.

    **`uv tool install kennis` never puts mineru on PATH.** It
    installs it into the tool's own virtual environment and links only
    kennis's entry point, saying so as it goes: `Installed 1 executable:
    kennis`. So a PATH-only check reports mineru missing on a machine that
    has just installed it, and then tells the user to install what they
    already have. The interpreter running kennis is inside that same
    environment, so its directory is the place to look next.

    **PATH is tried first, and the order is not arbitrary.** Prepending a
    directory to PATH is how a person substitutes one build of a tool for
    another, and how this suite substitutes a fake mineru for the real one;
    looking beside the interpreter first silently ignored both. The fallback
    is for when PATH has no answer at all, which is exactly the tool-install
    case.

    `shutil.which` with an explicit path rather than a manual join, so
    Windows still applies PATHEXT.
    """
    found = shutil.which(name)
    return found or shutil.which(name, path=str(Path(sys.executable).parent))


# Settings whose value is "auto" mean "let MinerU decide", which MinerU
# expects to be expressed by the variable being *absent*. Passing the literal
# string through is an error it rejects outright:
#   MINERU_MODEL_SOURCE=auto is not supported. Unset MINERU_MODEL_SOURCE to
#   use auto detection once, or set it to huggingface/modelscope/local.
# The variable is actively removed rather than merely not set, so an "auto"
# already exported in the user's shell cannot reach MinerU either.
_AUTO: Final = "auto"

# The executable. The converter's name stays `mineru`: it is what a
# document's `source.via` records and what a kept conversion is filed by.
_EXECUTABLE: Final = "mineru-kit"

type Quality = Literal["text-only", "fast", "best"]
type Device = Literal["auto", "cpu", "gpu"]

# `conversion.quality` to MinerU's tier. `advanced` is not offered: it adds
# tables of values estimated from charts, which a paper never states.
TIERS: Final[dict[str, str]] = {
    "text-only": "flash",
    "fast": "basic",
    "best": "standard",
}

# `conversion.device` to MinerU's two switches: its small models run on
# ONNX Runtime (`model.onnx_device`, set through the environment) and its
# reading model on llama.cpp. Vulkan is llama.cpp's graphics backend on
# Linux and Windows; MinerU ignores the variable on macOS, where Metal is
# native. `auto` removes both and lets MinerU choose.
_DEVICE_VARIABLES: Final[dict[str, dict[str, str]]] = {
    "cpu": {"MINERU_MODEL_ONNX_DEVICE": "cpu", "MINERU_LLAMA_CPP_BACKEND": "cpu"},
    "gpu": {"MINERU_MODEL_ONNX_DEVICE": "gpu", "MINERU_LLAMA_CPP_BACKEND": "vulkan"},
}
_THREAD_VARIABLES: Final = ("MINERU_INTRA_OP_NUM_THREADS", "MINERU_CPU_NUM_THREADS")
_MODEL_SOURCE_VARIABLE: Final = "MINERU_MODEL_SOURCE"

# MinerU 4 reports through a terminal library that wraps lines at the
# width it is told, eighty when it has no terminal; a failure's `Error:`
# line then arrives in pieces. Wide enough that it never wraps.
_REPORT_COLUMNS: Final = "1000"

# How long a run gets before kennis cancels it. Two terms, because the cost
# has two: the model stack loads once per run, then each document is
# converted. Without a timeout, one wedged conversion hangs the whole command
# with no output and nothing to interrupt but Ctrl-C.
#
# The point is to catch a converter that has stopped making progress, not to
# police a slow machine - and the margin here is much thinner than it looks,
# because the device changes the second term by an order of magnitude. A
# 19-page paper takes 34s on a GPU and 311s on a CPU (#137), so the
# per-document term is **below** one real measurement rather than a generous
# multiple of it. What saves a CPU-only machine today is the startup grace,
# which a single document also gets: 900 + 300 is 1200s against that 311s.
# A batch of long papers on a CPU is where this would first be too tight.
# Raising the per-document term is open (#138) rather than done, because it
# is a behaviour change and the measurements are one paper old.
_STARTUP_GRACE_SECONDS: Final = 900
_SECONDS_PER_DOCUMENT: Final = 300

# How much of the original filename a staged copy keeps. The index prefix is
# what makes the name unique; the rest is there only so MinerU's own error
# output names something the user recognises.
#
# Short because MinerU writes the stem into its output path twice - as the
# directory and again in each file's name - under the temporary directory.
# On Windows that directory is some 60 characters before the stem, and a
# path past 260 fails to open: at 100 a long filename came to about 300.
# At 40 the whole path stays under 200.
_STAGED_STEM_LIMIT: Final = 40

# Block kinds where a paper stamps its own identity: `arXiv:1805.03410v2
# [astro-ph.IM]` arrives as `aside_text`, a journal DOI as a `header`, an ADS
# bibcode on a scanned paper as a `header` too. MinerU 4's names.
_STAMP_TYPES: Final = frozenset({"header", "footer", "aside_text", "page_number"})
# Page furniture: the stamps, and the footnotes - furniture to MinerU, which
# leaves them out of the body, but where a paper cites others (#689).
_FURNITURE_TYPES: Final = _STAMP_TYPES | {"page_footnote"}


@dataclass(frozen=True, slots=True)
class MineruOptions:
    """The knobs MinerU takes, in the form it wants them.

    Settings will supply these in a later milestone; until then a caller
    passes them or takes the defaults.
    """

    quality: Quality = "best"
    device: Device = "auto"
    # 0 lets MinerU choose.
    threads: int = 0
    model_source: str = _AUTO

    @property
    def tier(self) -> str:
        return TIERS[self.quality]


class MineruConverter:
    """The local binary-document converter."""

    name = "mineru"
    formats = MINERU_FORMATS

    def __init__(
        self,
        options: MineruOptions | None = None,
        *,
        repair_ligatures: bool = True,
    ) -> None:
        self.options = options or MineruOptions()
        self.repair_ligatures = repair_ligatures
        self.variant = self.options.tier

    def is_available(self) -> bool:
        return _executable(_EXECUTABLE) is not None

    def install_hint(self) -> str:
        return _SOURCE_INSTALL_HINT if _from_source_checkout() else _TOOL_INSTALL_HINT

    def convert(self, paths: Sequence[Path]) -> ConversionBatch:
        """Convert every path in one MinerU process.

        The caller decides how large a run is, because MinerU writes nothing
        until the whole run finishes: a run is the unit of progress and the
        unit lost to an interruption.
        """
        if not paths:
            return ConversionBatch(markdown={})
        require_converter(self, paths)

        # A file a just-killed process still had open cannot be removed on
        # Windows until it lets go: the conversion's own error is the one to
        # report, not a cleanup's `PermissionError` raised over it.
        with tempfile.TemporaryDirectory(
            prefix="kennis-mineru-", ignore_cleanup_errors=True
        ) as temporary:
            staged_dir = Path(temporary) / "input"
            output_dir = Path(temporary) / "output"
            staged_dir.mkdir()
            output_dir.mkdir()
            staged = _stage(paths, staged_dir)

            completed = self._run(sorted(staged_dir.iterdir()), output_dir)
            markdown, front_page, stamps, images = _collect(
                staged, output_dir, Path(temporary) / "unpacked"
            )

        reason = _failure_reason(completed) if completed.returncode != 0 else None
        if not markdown and reason is not None:
            raise ConversionFailed(f"mineru failed: {reason}")

        markdown, repairs = self._finish(markdown)
        return ConversionBatch(
            markdown=markdown,
            front_page=front_page,
            stamps=stamps,
            failure_reason=reason,
            repairs=repairs,
            images=images,
        )

    def _finish(
        self, markdown: dict[Path, str]
    ) -> tuple[dict[Path, str], dict[Path, int]]:
        """Everything done to MinerU's markdown before it is stored.

        MinerU 4's own markup goes first, then normalisation, because the
        repair must not walk into an HTML attribute, and because a table
        cell's words should be repaired too.
        """
        normalised = {
            path: normalise_markdown(without_mineru_markup(text))
            for path, text in markdown.items()
        }
        return normalised, self._repair(normalised)

    def _repair(self, markdown: dict[Path, str]) -> dict[Path, int]:
        """Repair ligature damage in place, and report how much there was.

        Only PDFs: the reference is the document's own text layer, and there
        is no text layer to read in a DOCX or a spreadsheet. A document whose
        text layer cannot be read at all yields no vocabulary and so no
        repairs, which is the right answer rather than an error - a scanned
        paper has no reference and must not be rewritten from an empty one.
        """
        if not self.repair_ligatures:
            return {}
        counts: dict[Path, int] = {}
        for path, text in markdown.items():
            if path.suffix.lower() != ".pdf":
                continue
            try:
                vocabulary = text_layer_vocabulary(path)
            except Exception:
                continue
            if not vocabulary:
                continue
            markdown[path], counts[path] = repair_ligatures(text, vocabulary)
        return counts

    def _run(
        self,
        staged: list[Path],
        output_dir: Path,
    ) -> subprocess.CompletedProcess[str]:
        document_count = len(staged)
        # The resolved path, not the bare name: a subprocess given the name
        # resolves it against PATH again, which is exactly where it is not.
        # Never `--remote`, which uploads the document to mineru.net.
        command = [
            _executable(_EXECUTABLE) or _EXECUTABLE,
            "parse",
            *(str(path) for path in staged),
            "-o",
            str(output_dir),
            "--format",
            "zip",
            "--tier",
            self.options.tier,
        ]
        timeout_seconds = _STARTUP_GRACE_SECONDS + (
            _SECONDS_PER_DOCUMENT * document_count
        )
        try:
            return _run_as_group(
                command, env=self._environment(), timeout=timeout_seconds
            )
        except subprocess.TimeoutExpired as expired:
            # The remedy is the setting that sizes a run: "convert them in
            # smaller batches" named an option no command has. A single
            # document has no smaller run to suggest.
            if document_count == 1:
                raise ConversionFailed(
                    f"mineru did not finish converting 1 document within "
                    f"{timeout_seconds}s and was cancelled. Nothing was written.",
                    resolution=None,
                ) from expired
            raise ConversionFailed(
                f"mineru did not finish converting {document_count} documents "
                f"within {timeout_seconds}s and was cancelled. Nothing was "
                f"written.",
                resolution=(
                    f"kennis config set conversion.batch_size {document_count // 2}"
                ),
            ) from expired
        except OSError as error:
            raise ConversionFailed(f"could not run mineru: {error}") from error

    def _environment(self) -> dict[str, str]:
        """The child environment for one run."""
        # Explicitly, rather than trusting that the `kennis` package was
        # imported before whatever started this run (#687).
        environment = dict(os.environ) | LIBRARY_TELEMETRY_OFF
        environment["COLUMNS"] = _REPORT_COLUMNS
        for variables in _DEVICE_VARIABLES.values():
            for variable in variables:
                environment.pop(variable, None)
        environment |= _DEVICE_VARIABLES.get(self.options.device, {})
        for variable in _THREAD_VARIABLES:
            if self.options.threads:
                environment[variable] = str(self.options.threads)
            else:
                environment.pop(variable, None)
        if self.options.model_source == _AUTO:
            environment.pop(_MODEL_SOURCE_VARIABLE, None)
        else:
            environment[_MODEL_SOURCE_VARIABLE] = self.options.model_source
        return environment


# ---------------------------------------------------------------------------
# Datalab
# ---------------------------------------------------------------------------
#
# The hosted alternative, for a machine that will not carry the local model
# stack. It converts a document by **sending it to a third party**, which is
# why it is never a default: the backend is a setting and the key is a
# credential, so choosing it is two deliberate acts.
#
# Unlike MinerU, there is no batch endpoint. A batch is one request per
# document, and `ConversionBatch` fits that unchanged because it already
# reports per document. The module docstring's guess that hosted conversion
# would want batching because "one request beats several" was wrong.

_DATALAB_URL: Final = "https://www.datalab.to/api/v1/convert"
DATALAB_KEY_VARIABLE: Final = "DATALAB_API_KEY"

# What the API accepts. Narrower than its marketing copy, which says "PDFs,
# Word documents, spreadsheets and images" without naming extensions, so this
# lists only what kennis has a `SourceFormat` for anyway.
DATALAB_FORMATS: Final[frozenset[SourceFormat]] = frozenset(
    {"pdf", "docx", "pptx", "xlsx"}
)

# A submitted document is not converted when the response returns. The server
# hands back a URL to poll, and these bound the wait: 2s is the interval the
# API's own example uses, and 300 polls is its example ceiling, so a document
# gets ten minutes before kennis gives up. Unbounded polling is the one way
# an HTTP call becomes a hang, which is what the timeout rule forbids.
# What the hosted converter is asked to do, and what it costs. Measured on
# three-page documents the server had not seen: fast 0.40 c/page, balanced
# 0.40, accurate 1.00. `balanced` is the default because it costs what `fast`
# costs, so the default forgoes no saving. Concern #146.
type ConversionMode = Literal["fast", "balanced", "accurate"]
_DEFAULT_MODE: Final[ConversionMode] = "balanced"

_POLL_SECONDS: Final = 2.0
_MAX_POLLS: Final = 300
_REQUEST_TIMEOUT: Final = 120.0


class DatalabConverter:
    """The hosted binary-document converter.

    `front_page` is always empty and that is a capability difference, not an
    oversight. MinerU returns a content list that classifies page furniture,
    which is exactly where a paper stamps its arXiv id or DOI; this API
    returns markdown. A caller must not read the empty mapping as "this paper
    states no identity" - it means "this converter cannot tell".
    """

    name = "datalab"
    formats = DATALAB_FORMATS

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
        poll_seconds: float = _POLL_SECONDS,
        max_polls: int = _MAX_POLLS,
        mode: ConversionMode = _DEFAULT_MODE,
    ) -> None:
        self.api_key = credential(DATALAB_KEY_VARIABLE) if api_key is None else api_key
        self._client = client
        self._poll_seconds = poll_seconds
        self._max_polls = max_polls
        self._mode = mode
        self.variant: str = mode

    def is_available(self) -> bool:
        """A key is the whole requirement. There is nothing to install."""
        return bool(self.api_key)

    def install_hint(self) -> str:
        return "kennis config init"

    def convert(self, paths: Sequence[Path]) -> ConversionBatch:
        """Convert each path, one request each, and report per document."""
        if not paths:
            return ConversionBatch(markdown={})
        require_converter(self, paths)

        markdown: dict[Path, str] = {}
        reasons: list[str] = []
        # Costs of the documents that reported one. Left empty rather than
        # zeroed, so "nobody told us" stays distinct from "it was free".
        costs: list[float] = []
        client = self._client or httpx.Client(timeout=_REQUEST_TIMEOUT)
        try:
            for path in paths:
                try:
                    converted, cost = self._convert_one(client, path)
                except ConverterRefused:
                    # Every other document would be refused the same way.
                    raise
                except ConversionFailed as failed:
                    reasons.append(f"{path.name}: {failed}")
                    continue
                markdown[path] = converted
                if cost is not None:
                    costs.append(cost)
        finally:
            if self._client is None:
                client.close()

        reason = "; ".join(reasons) if reasons else None
        if not markdown and reason is not None:
            raise ConversionFailed(f"datalab failed: {reason}")
        return ConversionBatch(
            markdown={
                path: normalise_markdown(text) for path, text in markdown.items()
            },
            failure_reason=reason,
            cost_cents=sum(costs) if costs else None,
        )

    def _convert_one(
        self, client: httpx.Client, path: Path
    ) -> tuple[str, float | None]:
        check_url = self._submit(client, path)
        return self._await_markdown(client, check_url, path)

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    def _submit(self, client: httpx.Client, path: Path) -> str:
        try:
            response = client.post(
                _DATALAB_URL,
                headers=self._headers(),
                files={"file": (path.name, path.read_bytes())},
                data={"output_format": "markdown", "mode": self._mode},
                timeout=_REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as error:
            raise ConversionFailed(f"could not reach datalab: {error}") from error
        if response.status_code in (401, 403):
            # The key, not the document: said so, with the service's own
            # words, rather than as a refused document and `--help`.
            raise ConverterRefused(
                f"datalab did not accept the API key ({response.status_code}"
                f"{': ' + _detail_of(response) if _detail_of(response) else ''})"
            )
        if response.status_code >= 400:
            raise ConversionFailed(
                f"datalab refused the document ({response.status_code}"
                f"{': ' + _detail_of(response) if _detail_of(response) else ''})"
            )
        check_url = _as_text(_json_of(response).get("request_check_url"))
        if not check_url:
            raise ConversionFailed("datalab returned no url to poll")
        return check_url

    def _await_markdown(
        self, client: httpx.Client, url: str, path: Path
    ) -> tuple[str, float | None]:
        """Poll until the status settles, bounded. Returns the markdown and
        what the server said it cost, in cents, if it said anything.

        The key goes on this request too. It is a second, separate call and
        the service rejects an unauthenticated one, so a key sent only on
        submit converts nothing.
        """
        for _ in range(self._max_polls):
            try:
                response = client.get(
                    url, headers=self._headers(), timeout=_REQUEST_TIMEOUT
                )
            except httpx.HTTPError as error:
                raise ConversionFailed(f"could not reach datalab: {error}") from error
            # A refusal on the poll is final, not "still pending": a 401 or a
            # 429 whose body had no `status` was polled 300 times, ten
            # minutes a document. A server error is waited out like a
            # pending answer, within the same bound.
            if 400 <= response.status_code < 500:
                raise ConversionFailed(
                    f"datalab refused the poll ({response.status_code}"
                    f"{': ' + _detail_of(response) if _detail_of(response) else ''})"
                )
            if response.status_code >= 500:
                pause(self._poll_seconds)
                continue
            result = _json_of(response)
            if result.get("success") is False or result.get("status") == "failed":
                raise ConversionFailed(
                    _as_text(result.get("error")) or "datalab could not convert it"
                )
            if result.get("status") == "complete":
                converted = _as_text(result.get("markdown"))
                if not converted:
                    raise ConversionFailed("datalab returned no markdown")
                return converted, _as_cost(result.get("total_cost"))
            pause(self._poll_seconds)
        raise ConversionFailed(
            f"datalab did not finish converting {path.name} within "
            f"{int(self._max_polls * self._poll_seconds)}s and was given up on"
        )


def _json_of(response: httpx.Response) -> dict[str, object]:
    """A response's JSON object, or a refusal saying it was not one.

    An HTML error page from a proxy is not JSON, and its `JSONDecodeError`
    is neither an `HTTPError` nor a `ConversionFailed`: it crashed the whole
    batch, the other documents with it.
    """
    try:
        body = response.json()
    except ValueError as error:
        raise ConversionFailed(
            f"datalab answered with something that is not JSON ({response.status_code})"
        ) from error
    if not isinstance(body, dict):
        raise ConversionFailed("datalab answered with something that is not an object")
    return body


def _detail_of(response: httpx.Response) -> str:
    """The service's own `detail` or `error`, when it gave one."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    return _as_text(body.get("detail")) or _as_text(body.get("error"))


def _as_text(value: object) -> str:
    """A JSON field as a string, or empty when it is anything else.

    The response is other people's data: a field may be absent, null, or a
    number, and none of those should become the string "None" halfway down a
    document.
    """
    return value if isinstance(value, str) else ""


def _as_cost(value: object) -> float | None:
    """A JSON cost field in cents, or `None` when there is not one.

    `bool` is excluded explicitly because it is a subclass of `int` in Python
    and `True` would otherwise become a cost of one cent.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def require_converter(converter: Converter, paths: Sequence[Path]) -> None:
    """Fail now if `converter` is needed and missing, rather than once per file.

    A folder of fifty PDFs would otherwise produce fifty copies of the same
    install instructions, one at a time, over a run that cannot succeed. One
    message, built here, so intake's single-document path and the batch path
    cannot word it differently.
    """
    if not paths or converter.is_available():
        return
    formats = sorted({path.suffix.lstrip(".").upper() for path in paths})
    raise ConverterUnavailable(
        f"{converter.name} is required to convert {'/'.join(formats)} files "
        f"and is not installed. Convert the documents yourself and add the "
        f"resulting markdown instead, or install it.",
        resolution=converter.install_hint(),
    )


def default_converter() -> Converter:
    """The converter kennis uses when a caller names none.

    One indirection, so choosing between them is a change here rather than at
    every call site. The choice is `conversion.backend`, which defaults to
    the local one: sending a document to a third party is something a user
    opts into, never something a default does for them.
    """
    conversion = load_settings().conversion
    if conversion.backend == "datalab":
        return DatalabConverter(mode=conversion.mode)
    return MineruConverter(
        MineruOptions(
            quality=conversion.quality,
            device=conversion.device,
            threads=conversion.threads,
        ),
        repair_ligatures=conversion.repair_ligatures,
    )


def _stage(paths: Sequence[Path], staged_dir: Path) -> dict[str, Path]:
    """Present a batch as one directory, and map the output back.

    They are renamed on the way in because MinerU names its output after
    the input's stem: two `README.pdf` from different
    folders would otherwise write to the same place and one would silently
    win. Hard-linked where the filesystem allows it, since the alternative is
    copying every source into the temporary directory.
    """
    staged: dict[str, Path] = {}
    for index, path in enumerate(paths):
        # Without a trailing space or dot: MinerU names its output folder by
        # the stem, Windows drops either from a folder it creates, and
        # MinerU then looked for one that was not there (#3).
        kept = path.stem[:_STAGED_STEM_LIMIT].rstrip(" .")
        target = staged_dir / f"{index:04d}-{kept}{path.suffix.lower()}"
        try:
            os.link(path, target)
        except OSError:
            # A different filesystem, or one without hard links.
            shutil.copy2(path, target)
        staged[target.stem] = path
    return staged


def _collect(
    staged: dict[str, Path], output_dir: Path, unpacked: Path
) -> tuple[
    dict[Path, str], dict[Path, str], dict[Path, str], dict[Path, dict[str, bytes]]
]:
    """The markdown, page-one text, page-one stamps and linked images MinerU
    produced, keyed by original path.

    One `<stem>.zip` per document that converted; a document with none
    failed, and its absence is its failure alone. Each is unpacked into a
    directory of its own, because the images are read relative to **that
    document's** markdown, which is what its links are relative to: MinerU
    names a figure the same in two documents when it likes, so a name alone
    does not say whose it is.
    """
    markdown: dict[Path, str] = {}
    front_page: dict[Path, str] = {}
    stamps: dict[Path, str] = {}
    images: dict[Path, dict[str, bytes]] = {}
    for stem, original in staged.items():
        archive = output_dir / f"{stem}.zip"
        if not archive.is_file():
            continue
        folder = unpacked / stem
        try:
            with zipfile.ZipFile(archive) as opened:
                # `extractall` drops a member's leading `/` and its `..`
                # parts, so nothing is written outside `folder`.
                opened.extractall(folder)
        except (zipfile.BadZipFile, OSError):
            continue
        produced = folder / "markdown.md"
        if not produced.is_file():
            continue
        text = produced.read_text(encoding="utf-8", errors="replace")
        markdown[original], linked = kept_images(text, folder)
        if linked:
            images[original] = linked
        blocks = _page_one_blocks(folder / "structured_content.json")
        front_page[original] = _front_page_text(blocks)
        stamps[original] = "\n".join(
            content for kind, content in blocks if kind in _STAMP_TYPES
        )
    return markdown, front_page, stamps, images


# MinerU 4's wrapper around a footnote or a margin note in its markdown:
# `<small><span class="docvortex-page-footnote" data-block-type=...
# style="color:...">text</span></small>`. The text is the document's; the
# wrapper is presentation, and an inline style a page would refuse to draw.
_WRAPPED_NOTE: Final = re.compile(
    r"(?:<small>)?<span class=\"docvortex-[^\"]*\"[^>]*>(.*?)</span>(?:</small>)?",
    re.DOTALL,
)

# What the fastest tier writes after every figure instead of reading it:
# a block whose only sentence is a stock one. Removed only when it says
# exactly that, so a block that holds anything else is left alone.
_FIGURE_PLACEHOLDER: Final = re.compile(
    r"<details>\s*<summary>image content</summary>\s*"
    r"(?:Figure \S+\s+)?For image description, please refer to the figure "
    r"legend and surrounding text\.\s*</details>\n?",
)


def without_mineru_markup(text: str) -> str:
    """MinerU 4's markdown with its note wrappers unwrapped and the fastest
    tier's figure placeholders removed; nothing else changed."""
    return _FIGURE_PLACEHOLDER.sub("", _WRAPPED_NOTE.sub(r"\1", text))


# How often a converter's wait looks for a cancellation.
_CANCEL_STEP_SECONDS: Final = 0.25


def _run_as_group(
    command: list[str], *, env: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run `command` in a process group of its own, and end the whole group
    if it overruns `timeout`.

    `subprocess.run` kills only the process it started. MinerU starts helpers
    of its own - a model server among them - so a cancelled run left those
    running, holding the GPU and the output directory, after kennis had
    said the run was cancelled. `TimeoutExpired` is raised as `run` raises it.

    The wait is in steps, so a cancelled task ends the group within one
    step rather than after the conversion (Brian, 2026-10-27); `communicate`
    may be called again after its own timeout without losing output.
    """
    group: dict[str, Any]
    if sys.platform == "win32":
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        group = {"start_new_session": True}
    with subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # Not the locale's encoding: on Windows that is cp1252, and MinerU's
        # own UTF-8 log lines raised `UnicodeDecodeError`, which nothing here
        # catches.
        encoding="utf-8",
        errors="replace",
        env=env,
        **group,
    ) as process:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            try:
                stdout, stderr = process.communicate(
                    timeout=max(0.0, min(remaining, _CANCEL_STEP_SECONDS))
                )
                break
            except subprocess.TimeoutExpired:
                if cancellation_asked():
                    _end_group(process)
                    raise TaskCancelled() from None
                if remaining <= _CANCEL_STEP_SECONDS:
                    _end_group(process)
                    raise subprocess.TimeoutExpired(command, timeout) from None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _end_group(process: subprocess.Popen[str]) -> None:
    """Kill `process` and everything it started, then reap it."""
    if sys.platform == "win32":
        # The tree, by parent: a Windows process group cannot be killed as
        # one, only sent Ctrl-Break, which a model server may ignore.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    process.kill()
    # Bounded: a helper outside the group that inherited the pipes would
    # otherwise hold this open as long as it lives.
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.communicate(timeout=5)


def _failure_reason(completed: subprocess.CompletedProcess[str]) -> str:
    """The human-readable reason out of a failed run.

    MinerU 4 names each document it could not convert on an `Error:` line
    and ends with a summary that says only how many, so those lines are the
    reason. Otherwise a JSON blob's `error` field, then the last line of
    output, then the exit code when there is no output at all.
    """
    output = (completed.stderr or "") + "\n" + (completed.stdout or "")
    errors = [
        line.strip().removeprefix("Error:").strip()
        for line in output.splitlines()
        if line.strip().startswith("Error:")
    ]
    if errors:
        return "; ".join(errors)
    for line in reversed(output.strip().splitlines()):
        start = line.find("{")
        if start == -1:
            continue
        try:
            payload = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, str) and error.strip():
            return error.strip()

    lines = output.strip().splitlines()
    return lines[-1].strip() if lines else f"exit code {completed.returncode}"


def _page_one_blocks(structured: Path) -> list[tuple[str, str]]:
    """Page one's blocks from `structured_content.json`, as (kind, text),
    in page order; empty when the file cannot be read.

    A paper's own identifier is often *absent* from the converted markdown,
    because MinerU classifies the `arXiv:...` stamp as page furniture, and
    furniture is not body text. It survives here, which is the only reason
    a local PDF can be identified at all. Only page one: a bibliography
    offers dozens of other people's identifiers and every one of them is a
    wrong answer.
    """
    try:
        parsed = json.loads(structured.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    pages = parsed.get("pages") if isinstance(parsed, dict) else None
    if not isinstance(pages, list) or not pages or not isinstance(pages[0], dict):
        return []
    blocks = pages[0].get("blocks")
    found: list[tuple[str, str]] = []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        content = block.get("content")
        if isinstance(content, str) and content.strip():
            found.append((str(block.get("type", "")), content))
    return found


def _front_page_text(blocks: list[tuple[str, str]]) -> str:
    """Everything on page one, the furniture first, then the rest."""
    furniture = [content for kind, content in blocks if kind in _FURNITURE_TYPES]
    body = [content for kind, content in blocks if kind not in _FURNITURE_TYPES]
    return "\n".join(furniture + body)
