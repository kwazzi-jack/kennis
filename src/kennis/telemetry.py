"""The telemetry of the libraries kennis runs, turned off (#687).

kennis sends nothing anywhere unasked, and that has to hold for what it
runs as well as for what it writes. ONNX Runtime 1.29 and later, which
kennis imports through `fastembed` and which MinerU imports in every
conversion, writes a device identifier and a queue of events under the
cache folder when it is imported, and posts them to Microsoft: the system,
the processor, and the full path of the Python that ran it, which names
the person's account. MinerU 4 keeps a telemetry of its own.

Each library reads its switch from the environment when it loads, so the
switches are written into `os.environ` when the `kennis` package is
imported, before any of its modules can import either library, and every
process kennis starts inherits them. They overwrite whatever the
environment held: the person asked kennis for no telemetry, not each
library separately (Brian, 2026-11-18).

Sources: ONNX Runtime's privacy notice, which says telemetry is on by
default in the official builds (https://github.com/microsoft/onnxruntime/blob/v1.30.0/docs/Privacy.md),
and an independent measurement of it on Linux, which found the variable
works and the Python call does not there
(https://research.strata2signal.com/onnx-runtime-telemetry-on-linux/).
Both agree with kennis's own traces (#687).
"""

from __future__ import annotations

import os
from typing import Final

# Each library's own switch and the value that turns it off. Measured on
# Linux for ONNX Runtime 1.31 and MinerU 4.2.3: with these set, no
# connection was made and nothing was queued. ONNX Runtime ignores its
# variable on Windows, where `refuse_onnx_runtime_telemetry` is the switch.
LIBRARY_TELEMETRY_OFF: Final[dict[str, str]] = {
    "ORT_DISABLE_TELEMETRY": "1",
    "MINERU_TELEMETRY_DISABLED": "1",
}


def refuse_library_telemetry() -> None:
    """Write every library's switch into this process's environment."""
    os.environ.update(LIBRARY_TELEMETRY_OFF)


def refuse_onnx_runtime_telemetry() -> None:
    """Turn ONNX Runtime's telemetry off through its own call, for Windows,
    where the environment variable is ignored. Call it after importing a
    library that imports `onnxruntime`; it imports nothing itself that is
    not already loaded, so a client that never embeds pays nothing."""
    import sys

    runtime = sys.modules.get("onnxruntime")
    if runtime is not None:
        runtime.disable_telemetry_events()


__all__ = [
    "LIBRARY_TELEMETRY_OFF",
    "refuse_library_telemetry",
    "refuse_onnx_runtime_telemetry",
]
