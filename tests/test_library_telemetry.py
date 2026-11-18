"""kennis turns off the telemetry of the libraries it runs (#687).

ONNX Runtime 1.29 and later, imported by `fastembed` and by MinerU, writes
a device identifier and a queue of events under the cache folder when it
is imported, and posts them to Microsoft. `ORT_DISABLE_TELEMETRY=1` in the
environment before it loads is the switch, and kennis sets it always,
whatever the person's environment says (Brian, 2026-11-18).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kennis.engine.corpus.converters import MineruConverter
from platforms import needs_a_telemetry_queue
from test_converters import a_pdf

# ONNX Runtime falls silent by itself when one of these is set, so a
# continuous integration runner would pass the test whether or not kennis
# did anything. Read from the strings of libonnxruntime 1.31.1.
_CI_VARIABLES = (
    "APPVEYOR",
    "BITBUCKET_BUILD_NUMBER",
    "BUILDKITE",
    "CI",
    "CIRCLECI",
    "CODEBUILD_BUILD_ID",
    "CONTINUOUS_INTEGRATION",
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "JENKINS_URL",
    "SYSTEM_TEAMFOUNDATIONCOLLECTIONURI",
    "TEAMCITY_VERSION",
    "TF_BUILD",
    "TRAVIS",
)

_IMPORT_TIMEOUT_SECONDS = 120


def queue_after_importing(code: str, home: Path) -> list[Path]:
    """What ONNX Runtime left under `home` after a fresh Python ran `code`,
    in an environment that asks for telemetry (`ORT_DISABLE_TELEMETRY=0`)
    and is not recognisably a CI runner."""
    environment = {
        name: value for name, value in os.environ.items() if name not in _CI_VARIABLES
    }
    environment.update(
        {
            "HOME": str(home),
            "XDG_CACHE_HOME": str(home / "cache"),
            "ORT_DISABLE_TELEMETRY": "0",
        }
    )
    home.mkdir()
    finished = subprocess.run(
        [sys.executable, "-c", code],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_IMPORT_TIMEOUT_SECONDS,
        check=False,
    )
    assert finished.returncode == 0, finished.stderr
    return sorted(path for path in home.rglob("*") if ".onnxruntime" in path.parts)


@needs_a_telemetry_queue
def test_importing_kennis_first_keeps_onnx_runtime_from_queueing_telemetry(
    tmp_path: Path,
) -> None:
    control = queue_after_importing("import onnxruntime", tmp_path / "control")
    # The control is what makes this a test: if ONNX Runtime stops writing
    # its queue here, the second half passes for free.
    assert control, "onnxruntime no longer writes a queue; the fixture is inert"

    after_kennis = queue_after_importing(
        "import kennis\nimport onnxruntime", tmp_path / "kennis"
    )

    assert after_kennis == []


def test_kennis_overrides_a_request_for_telemetry_in_the_environment(
    tmp_path: Path,
) -> None:
    environment = dict(os.environ) | {
        "ORT_DISABLE_TELEMETRY": "0",
        "MINERU_TELEMETRY_DISABLED": "0",
    }
    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, kennis\n"
            "print(os.environ['ORT_DISABLE_TELEMETRY'],"
            " os.environ['MINERU_TELEMETRY_DISABLED'])",
        ],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_IMPORT_TIMEOUT_SECONDS,
        check=False,
    )

    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.split() == ["1", "1"]


def test_the_converter_turns_telemetry_off_in_its_own_process(
    fake_mineru: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicitly, so the converter does not depend on which module was
    imported first in the process that starts it."""
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    monkeypatch.delenv("MINERU_TELEMETRY_DISABLED", raising=False)

    MineruConverter().convert([a_pdf(tmp_path / "paper.pdf")])

    log = fake_mineru.read_text(encoding="utf-8").splitlines()
    assert "onnx-telemetry=1" in log
    assert "mineru-telemetry=1" in log
