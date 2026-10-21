"""`python -m kennis.service --corpus <root>`: what a client starts (14b).

With `--launch`, this process is the launcher (`launch.py`): it starts the
service and exits once the service holds the corpus. Without it, this
process is the service.

The corpus is named on the command line and also set as
`KENNIS_CORPUS_ROOT` in the service, so every part of it that resolves the
corpus resolves this one, whatever the configuration says.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="kennis.service")
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--launch", action="store_true")
    arguments = parser.parse_args()
    corpus_root = arguments.corpus.expanduser().resolve()
    # Imported here, so the launcher does not import the server it starts.
    if arguments.launch:
        from kennis.service.launch import launch

        return launch(corpus_root)
    from kennis.service.serve import run_service

    os.environ["KENNIS_CORPUS_ROOT"] = str(corpus_root)
    return run_service(corpus_root)


if __name__ == "__main__":
    raise SystemExit(main())
