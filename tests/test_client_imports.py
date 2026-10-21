"""A client imports only what it uses (#499, #535).

Every command pays its imports before it asks the service anything, and
until this the command line's display pulled in the engine's retrieval,
pack and backup modules with numpy beside them: 0.41 s of a 0.48 s
`kennis --version`. Asserted by what a fresh interpreter has loaded, not by
a time, because a time is a statement about the machine.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

# What a client never needs to start: the engine's retrieval and its
# numerical libraries, the pack schema, the backup library, the document
# parsers, the operations, and the service's own server. Not pygments,
# which httpx's own `__init__` imports for its command line; a client
# without it is #535's second option.
NOT_FOR_A_CLIENT = (
    "numpy",
    "bm25s",
    "py7zr",
    "markdown_it",
    "pypdfium2",
    "uvicorn",
    "starlette",
    "fastmcp",
    "kennis.engine.rag.search",
    "kennis.engine.rag.index",
    "kennis.engine.rag.embedding",
    "kennis.engine.rag.chunking",
    "kennis.engine.pack.schema",
    "kennis.engine.backup",
    "kennis.engine.corpus.add",
    "kennis.operations",
    "kennis.retrieval",
    "kennis.service",
)


def loaded_by(module: str) -> list[str]:
    program = (
        f"import json, sys\nimport {module}\nprint(json.dumps(sorted(sys.modules)))\n"
    )
    shown = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    loaded: list[str] = json.loads(shown.stdout)
    return loaded


@pytest.mark.parametrize("module", ["kennis.cli.__main__", "kennis.client.api"])
def test_a_client_starts_without_what_it_does_not_use(module: str):
    loaded = loaded_by(module)

    present = [
        heavy
        for heavy in NOT_FOR_A_CLIENT
        if any(name == heavy or name.startswith(f"{heavy}.") for name in loaded)
    ]
    assert present == [], f"importing {module} loads {present}"
