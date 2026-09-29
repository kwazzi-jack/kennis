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
from platformdirs import user_data_dir, user_state_dir

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = PROJECT_ROOT / "src"
ENGINE_ROOT = SOURCE_ROOT / "kennis" / "engine"

# Nothing in the engine may reach for a front end, or for a library that only
# a front end has any use for. `rich_click` and `prompt_toolkit` are named
# although they are not yet dependencies: the point of the rule is that adding
# one to the engine should fail here rather than at review.
FORBIDDEN_BY_THE_ENGINE = (
    "kennis.cli",
    "kennis.gui",
    "kennis.mcp",
    "kennis.render",
    "click",
    "rich",
    "rich_click",
    "prompt_toolkit",
)

# The renderer turns engine values into words. It may read the engine, and it
# must not reach for an interface library: the MCP server needs the same
# wording as the command line, and would otherwise have to import a
# command-line package to get it - which would make the second front end
# downstream of the first, the failure this separation exists to prevent.
FORBIDDEN_BY_THE_RENDERER = (
    "kennis.cli",
    "kennis.gui",
    "kennis.mcp",
    "click",
    "rich",
    "rich_click",
    "prompt_toolkit",
)

# The MCP server is a front end, so it may import an interface library of
# its own - `fastmcp` - and it renders through `render/`. What it may not
# do is import the other front end: two peers, neither privileged.
FORBIDDEN_BY_THE_SERVER = (
    "kennis.cli",
    "kennis.gui",
    "click",
    "rich",
    "rich_click",
    "prompt_toolkit",
)

# The graphical front end is the third peer. It may import its own
# interface libraries - fastapi, uvicorn, jinja2, pywebview - and it
# renders through `render/`. What it may not import is either of the
# other two, for the same reason neither of them may import it.
FORBIDDEN_BY_THE_INTERFACE = (
    "kennis.cli",
    "kennis.mcp",
    "click",
    "rich",
    "rich_click",
    "prompt_toolkit",
    "fastmcp",
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


def render_modules() -> list[Path]:
    return sorted((SOURCE_ROOT / "kennis" / "render").rglob("*.py"))


def server_modules() -> list[Path]:
    return sorted((SOURCE_ROOT / "kennis" / "mcp").rglob("*.py"))


def interface_modules() -> list[Path]:
    return sorted((SOURCE_ROOT / "kennis" / "gui").rglob("*.py"))


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


def test_the_renderer_has_modules_to_check():
    """A walk over an empty tree passes for the wrong reason."""
    assert render_modules()


@pytest.mark.parametrize("path", render_modules(), ids=module_name_of)
def test_render_module_imports_no_interface(path: Path):
    """The words belong to no front end.

    `render/` may import the engine - it renders engine values, so it must
    know their types - but never a front end or an interface library. The
    dependency runs cli -> render -> engine and never back.
    """
    imported = imported_modules(path)
    violations = sorted(
        name
        for name in imported
        for forbidden in FORBIDDEN_BY_THE_RENDERER
        if offends(name, forbidden)
    )
    assert not violations, f"{module_name_of(path)} imports {violations}"


def test_the_server_has_modules_to_check():
    """A walk over an empty tree passes for the wrong reason."""
    assert server_modules()


@pytest.mark.parametrize("path", server_modules(), ids=module_name_of)
def test_server_module_imports_no_other_front_end(path: Path):
    """The two front ends are peers, and neither may reach for the other.

    The MCP server needs the same things a command needs - where the
    corpus is, what a hit looks like - and it gets them from `kennis
    .context` and `render/`, not by importing `cli/`. If it imported the
    command line the command line would be the real kennis and this
    would be a wrapper, which is exactly what design section 20 says no
    front end is.
    """
    imported = imported_modules(path)
    violations = sorted(
        name
        for name in imported
        for forbidden in FORBIDDEN_BY_THE_SERVER
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


@pytest.mark.parametrize("path", interface_modules(), ids=module_name_of)
def test_interface_module_imports_no_other_front_end(path: Path):
    """`gui/` is a peer of `cli/` and `mcp/`, not a client of either.

    Written in unit 9a, before there was anything to get wrong. The
    graphical front end needs what the other two need - where the
    corpus is, what a hit looks like - and takes it from
    `kennis.context` and `render/`. Reaching into `cli/` for a helper
    is the easy mistake, and it would make the command line the real
    kennis with two wrappers, which design section 20 says it is not.
    """
    imported = imported_modules(path)
    violations = sorted(
        name
        for name in imported
        for forbidden in FORBIDDEN_BY_THE_INTERFACE
        if offends(name, forbidden)
    )
    assert not violations, f"{module_name_of(path)} imports {violations}"


def test_the_command_line_builds_without_the_gui_extra():
    """`kennis --help` works on an install that never asked for fastapi.

    The same property `serve` has and for the same reason: `gui` is an
    optional extra, so the deferred import inside `gui_command` is what
    keeps every other command runnable - and a deferred import is
    exactly the kind of thing that gets tidied to the top of a module.
    """
    program = """
import sys

BLOCKED = {"fastapi", "uvicorn", "webview", "starlette"}


class Refuse:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in BLOCKED:
            raise ImportError("the gui extra is not installed")
        return None


sys.meta_path.insert(0, Refuse())

from click.testing import CliRunner

from kennis.cli.__main__ import main

helped = CliRunner().invoke(main, ["--help"])
assert helped.exit_code == 0, helped.output
assert "gui" in helped.output, helped.output

opened = CliRunner().invoke(main, ["gui"])
assert opened.exit_code != 0
assert isinstance(opened.exception, ImportError), opened.exception
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


def test_the_command_line_builds_without_the_mcp_extra():
    """`kennis --help` works on an install that never asked for fastmcp.

    `mcp` is an optional extra, so someone who installed kennis to use
    it from the terminal or as a library has no fastmcp - and every
    command but `serve` must still run. The mechanism is that
    `serve_command` imports the server inside its body rather than at
    module scope, which is invisible to the static walk and is exactly
    the kind of thing that gets "tidied" into a top-level import.

    `serve` itself is expected to fail there, and fail with an
    ImportError naming fastmcp rather than with something obscure.
    """
    program = """
import sys


class Refuse:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] == "fastmcp":
            raise ImportError("fastmcp is not installed")
        return None


sys.meta_path.insert(0, Refuse())

from click.testing import CliRunner

from kennis.cli.__main__ import main

helped = CliRunner().invoke(main, ["--help"])
assert helped.exit_code == 0, helped.output
assert "serve" in helped.output, helped.output

served = CliRunner().invoke(main, ["serve"])
assert served.exit_code != 0
assert isinstance(served.exception, ImportError), served.exception
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


def test_the_typing_marker_is_there_to_be_shipped():
    """`Typing :: Typed` is a claim to a downstream type checker, and without
    this file mypy in another project silently treats every kennis import as
    `Any`. The classifier said so before the marker existed; this is what
    makes the two agree."""
    assert (SOURCE_ROOT / "kennis" / "py.typed").is_file()
    classifiers = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "Typing :: Typed" in classifiers


def test_a_test_does_not_run_in_the_repository():
    """The working directory is a test's, not Brian's.

    `find_bundle` walks **up from the working directory**, and under
    `pytest` that directory is this checkout unless something changes
    it. A test that ran `kennis context init` therefore created
    `.context/` in the repository, and every later test that wrote to
    a bundle found it and wrote a note into the working tree. That
    happened. The autouse `somewhere_else` fixture in `conftest.py`
    prevents it, and this is what fails if it is removed. Concern
    #325.
    """
    assert Path.cwd() != PROJECT_ROOT
    assert not (PROJECT_ROOT / ".context").exists()


def test_a_test_does_not_read_the_real_corpus():
    """The corpus a test resolves is a test's, not Brian's.

    `context.resolve_context` falls back to the platform's data
    directory when nothing names a corpus, and on this machine that
    is a real corpus of 55 documents. `build_app(TOKEN)` names none,
    so two interface tests read it - and passed for five units while
    asserting nothing, because the thing that made them pass was the
    developer's own data.

    All four CI jobs failed on exactly those two, which is what a
    test dependent on one machine looks like from another. The
    autouse `no_real_corpus` fixture points the variable at a path
    that does not exist, and this is what fails if it is removed.

    Concern #361.
    """
    from kennis.context import resolve_context

    resolved = resolve_context().corpus_root

    assert resolved != Path(user_data_dir("kennis"))
    assert not resolved.is_relative_to(Path.home() / ".local" / "share")
    assert not resolved.exists(), "a test was handed a usable corpus it did not build"


def test_a_test_does_not_write_to_the_real_state_directory():
    """The state directory is a test's, not Brian's.

    `gui/history.py` records every search under `KENNIS_STATE_DIR`,
    whose default is a real path on a real machine. A test driving
    the interface without it would append to Brian's own recent
    searches and nothing would say so - the same shape as concern
    #325 and the same remedy. The autouse `nowhere_real` fixture
    redirects it, and this is what fails if it is removed.
    """
    from kennis.gui.history import state_dir

    written_to = state_dir()

    assert written_to != Path(user_state_dir("kennis"))
    assert not written_to.is_relative_to(Path.home() / ".local" / "state")
