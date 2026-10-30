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
from platformdirs import user_config_dir, user_data_dir, user_log_dir, user_state_dir

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
# interface libraries - fastapi, uvicorn, jinja2 - and it
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


def protocol_modules() -> list[Path]:
    return sorted((SOURCE_ROOT / "kennis" / "protocol").rglob("*.py"))


# What the wire's own modules may import from kennis: the errors it writes
# and reads, where the state directory is (for the service's record), and
# itself. An allow-list rather than a list of what is forbidden, because
# every client imports `protocol/`, and a client that imports the engine's
# actors pays for them on every command (#499).
ALLOWED_TO_THE_PROTOCOL = (
    "kennis.engine.errors",
    "kennis.engine.settings",
    "kennis.protocol",
)


def test_the_protocol_has_modules_to_check():
    """A walk over an empty tree passes for the wrong reason."""
    assert protocol_modules()


@pytest.mark.parametrize("path", protocol_modules(), ids=module_name_of)
def test_protocol_module_imports_only_the_errors_and_itself(path: Path):
    """The wire writes the engine's values without importing what makes
    them: a value arrives already built, and its class is found among the
    subclasses of the type the caller expects (14a)."""
    imported = imported_modules(path)
    violations = sorted(
        name
        for name in imported
        if offends(name, "kennis")
        and not any(offends(name, allowed) for allowed in ALLOWED_TO_THE_PROTOCOL)
        and name != "kennis.engine"
    )
    interfaces = sorted(
        name
        for name in imported
        for forbidden in FORBIDDEN_BY_THE_RENDERER
        if offends(name, forbidden)
    )
    assert not violations, f"{module_name_of(path)} imports {violations}"
    assert not interfaces, f"{module_name_of(path)} imports {interfaces}"


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


def test_a_test_s_home_holds_none_of_its_temporary_folders(tmp_path: Path):
    """Home is the autouse `home_elsewhere` folder, never the person's.

    Asserted as being that folder rather than as `tmp_path` lying outside
    home, because on Linux `/tmp` is outside the real home too and the
    weaker check would pass with the fixture gone. Windows put the
    temporary folder under home and six tests failed there (CI,
    2026-10-30).
    """
    from conftest import HOME_DIRNAME

    assert Path.home().name == HOME_DIRNAME
    assert not tmp_path.is_relative_to(Path.home())


def test_a_test_does_not_read_the_real_configuration():
    """The configuration a test reads is a test's, not Brian's.

    The real directory holds a key file `credential` reads. The
    autouse `no_real_configuration` fixture redirects it, and this is
    what fails if that is removed. Concern #442.
    """
    from kennis.engine.settings import config_dir

    assert config_dir() != Path(user_config_dir("kennis"))
    assert not config_dir().is_relative_to(Path.home() / ".config")


def test_a_test_does_not_write_to_the_real_log():
    """The log a test writes is a test's. 311 lines of test runs were
    found in the real one, from a subprocess with no override."""
    from kennis.logs import log_dir

    assert log_dir() != Path(user_log_dir("kennis"))
    assert not log_dir().is_relative_to(Path.home() / ".local" / "state")


def test_a_test_does_not_reach_a_host():
    """A request a test did not mock fails the test, naming the address.

    kennis catches `httpx.HTTPError` wherever a request may fail, so a test
    reaching a real host whose answer did not matter passed - slowly, and
    only while the host was up. The autouse `no_real_network` fixture
    refuses every request outside loopback in a test not marked `network`,
    with an exception no `except Exception` catches, and this is what fails
    if it is removed. Concern #495.
    """
    import httpx

    outcome = pytest.fail.Exception
    with pytest.raises(outcome, match=r"example\.invalid"), httpx.Client() as client:
        client.get("https://example.invalid/robots.txt")


def test_a_command_does_not_start_a_real_service():
    """Every connection is to an application in this process (#503).

    A command that reached a started service would run its work outside
    every monkeypatch and guard of the suite. The autouse
    `service_in_this_process` fixture binds `connect` to an in-process
    application, and this is what fails if it is removed.
    """
    from kennis.client import connection

    # Asked of the function, never by calling it: called unpatched, it
    # would start the very process this guards against.
    assert connection.connect.__module__ != "kennis.client.connection"


# Where the person works is a client's to know (#508). Every other module
# is handed a bundle, because the service's own directory is whichever
# client started it.
_READS_THE_WORKING_DIRECTORY = {"cwd", "find_bundle", "workspace_root"}
_CLIENTS = ("kennis.cli", "kennis.mcp")


def working_directory_readers(path: Path) -> list[str]:
    """The calls in `path` that read where the process runs."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        name = (
            called.attr
            if isinstance(called, ast.Attribute)
            else called.id
            if isinstance(called, ast.Name)
            else ""
        )
        if name in _READS_THE_WORKING_DIRECTORY:
            found.append(f"{name} at line {node.lineno}")
    return found


def is_client(path: Path) -> bool:
    """A module of `cli` or `mcp`, matched by whole package name: a bare
    prefix would take `kennis.client` for `kennis.cli`."""
    name = module_name_of(path)
    return any(name == client or name.startswith(f"{client}.") for client in _CLIENTS)


def non_client_modules() -> list[Path]:
    return [
        path
        for path in sorted((SOURCE_ROOT / "kennis").rglob("*.py"))
        if not is_client(path)
    ]


def test_there_are_modules_that_are_not_clients():
    assert len(non_client_modules()) > 50


@pytest.mark.parametrize("path", non_client_modules(), ids=module_name_of)
def test_only_a_client_reads_the_working_directory(path: Path):
    assert working_directory_readers(path) == []


# What a client reaches through the service and must not call itself (14c,
# 14d): the sequences that take the corpus lock and commit, and the reads
# the service answers. Written by hand, so a module or a name added to the
# acting layer is a decision here too (#373). A project's bundle is the
# service's too since 14e: what builds, writes or reads its index, and the
# list of projects' writers. Finding the bundle from the working directory
# and reading the list stay with the client, which alone has a working
# directory (#508).
_BUNDLE_ACTORS = {
    "bundle_status",
    "index_bundle",
    "init_bundle",
    "load_bundle_index",
    "remember_in_bundle",
    "removable_documents",
    "reset_bundle",
}
_ACTING = {
    "kennis.operations": None,
    "kennis.holdings": None,
    "kennis.finding": None,
    "kennis.retrieval": {
        "chunk_range",
        "document_chunks",
        "index_for",
        "search_scope",
        "sweep",
    },
    "kennis.writing": None,
    "kennis.engine.locking": None,
    "kennis.engine.pack.installed": {"list_installed", "uninstall_pack"},
    "kennis.engine.pack.store": {"install_pack"},
    "kennis.engine.context": _BUNDLE_ACTORS,
    "kennis.engine.context.bundle": {"declare_packs", "init_bundle", "reset_bundle"},
    "kennis.engine.context.index": {"index_bundle", "load_bundle_index"},
    "kennis.engine.context.notes": {"remember_in_bundle"},
    "kennis.engine.context.packs": None,
    "kennis.engine.context.projects": {
        "add_project",
        "forget_project",
        "note_project",
        "record_project",
    },
}


def client_modules() -> list[Path]:
    return [
        path
        for path in sorted((SOURCE_ROOT / "kennis").rglob("*.py"))
        if is_client(path)
    ]


def acting_imports(path: Path) -> list[str]:
    """Every import in `path` of something a client must ask the service for."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _ACTING:
            forbidden = _ACTING[node.module]
            for alias in node.names:
                if forbidden is None or alias.name in forbidden:
                    found.append(f"{node.module}.{alias.name} at line {node.lineno}")
        elif isinstance(node, ast.Import):
            found.extend(
                f"{alias.name} at line {node.lineno}"
                for alias in node.names
                if alias.name in _ACTING and _ACTING[alias.name] is None
            )
    return found


def test_there_are_client_modules():
    assert len(client_modules()) > 20


@pytest.mark.parametrize("path", client_modules(), ids=module_name_of)
def test_a_client_asks_the_service_rather_than_acting(path: Path):
    assert acting_imports(path) == []


def test_client_is_not_taken_for_cli():
    assert not is_client(SOURCE_ROOT / "kennis" / "client" / "api.py")
    assert is_client(SOURCE_ROOT / "kennis" / "cli" / "group.py")
