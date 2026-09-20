"""The constraints that hold the rest of the project in shape.

The engine/interface separation is enforced by a test rather than by
packaging, so this file is what makes the invariant true rather than
aspirational. It is checked two ways because the two fail differently: the
static walk sees a module no other test imports, and the runtime import sees
what a module reaches for while it is being executed.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = PROJECT_ROOT / "src"
ENGINE_ROOT = SOURCE_ROOT / "kennis" / "engine"

# Nothing in the engine may reach for a front end, or for a library that only
# a front end has any use for. `rich_click` and `prompt_toolkit` are named
# although they are not yet dependencies: the point of the rule is that adding
# one to the engine should fail here rather than at review.
FORBIDDEN_BY_THE_ENGINE = (
    "kennis.cli",
    "kennis.mcp",
    "click",
    "rich",
    "rich_click",
    "prompt_toolkit",
)

# Also refused to the engine at runtime, so that `import kennis.engine` is
# proven to work for a caller who installed kennis without the `mcp` extra.
BLOCKED_AT_RUNTIME = (*FORBIDDEN_BY_THE_ENGINE[2:], "fastmcp")

ASCII_SEARCH_ROOTS = (
    SOURCE_ROOT,
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "sketches",
)
ASCII_SUFFIXES = frozenset({".py", ".toml", ".md", ".yaml", ".yml", ".cfg"})


def engine_modules() -> list[Path]:
    return sorted(ENGINE_ROOT.rglob("*.py"))


def module_name_of(path: Path) -> str:
    """The dotted name `path` is importable under, given the src layout."""
    parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def package_of(path: Path) -> str:
    """The package a relative import inside `path` is resolved against."""
    module = module_name_of(path)
    if path.name == "__init__.py":
        return module
    return module.rpartition(".")[0]


def imported_modules(path: Path) -> set[str]:
    """Every absolute module name `path` imports, relative imports resolved.

    Both the module a name is taken from and the dotted name itself are
    reported, so `from kennis import cli` is caught as well as
    `import kennis.cli`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = package_of(path)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                ancestry = package.split(".")
                base = ".".join(ancestry[: len(ancestry) - node.level + 1])
                if node.module:
                    base = f"{base}.{node.module}" if base else node.module
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def offends(name: str, forbidden: str) -> bool:
    return name == forbidden or name.startswith(f"{forbidden}.")


def test_the_engine_has_modules_to_check():
    """A walk over an empty tree passes for the wrong reason."""
    assert engine_modules()


@pytest.mark.parametrize("path", engine_modules(), ids=module_name_of)
def test_engine_module_imports_no_interface(path: Path):
    imported = imported_modules(path)
    violations = sorted(
        name
        for name in imported
        for forbidden in FORBIDDEN_BY_THE_ENGINE
        if offends(name, forbidden)
    )
    assert not violations, f"{module_name_of(path)} imports {violations}"


def test_engine_imports_without_the_interface_libraries():
    """Every engine module imports with the front-end libraries unavailable.

    Run in a subprocess with a meta-path finder that refuses them, because an
    import performed inside a function body is invisible to the static walk
    above, and because the libraries really are installed in this environment.
    """
    program = f"""
import importlib
import pkgutil
import sys

blocked = {BLOCKED_AT_RUNTIME!r}


class Refuse:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in blocked:
            raise ImportError(f"{{fullname}} is not available to the engine")
        return None


sys.meta_path.insert(0, Refuse())

import kennis.engine

for module in pkgutil.walk_packages(kennis.engine.__path__, "kennis.engine."):
    importlib.import_module(module.name)
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def text_files() -> list[Path]:
    found = [
        path
        for root in ASCII_SEARCH_ROOTS
        for path in root.rglob("*")
        if path.is_file() and path.suffix in ASCII_SUFFIXES
    ]
    found += [
        path
        for path in PROJECT_ROOT.iterdir()
        if path.is_file() and path.suffix in ASCII_SUFFIXES
    ]
    return sorted(found)


@pytest.mark.parametrize(
    "path", text_files(), ids=lambda path: str(path.relative_to(PROJECT_ROOT))
)
def test_source_file_is_ascii(path: Path):
    """`grep -rnP '[^\\x00-\\x7F]'`, expressed where it will actually run."""
    content = path.read_bytes()
    offending = [
        (number, line)
        for number, line in enumerate(content.split(b"\n"), start=1)
        if any(byte > 0x7F for byte in line)
    ]
    assert not offending, f"{path} has non-ASCII bytes on lines {offending}"
