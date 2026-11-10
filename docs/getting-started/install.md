# Install

kennis is published on PyPI as `kennis`. This page installs it, checks that
it runs, and says where it keeps things; the
[tutorial](tutorial.md) then builds a first corpus.

## Requirements

| what | why |
|---|---|
| Python 3.12 to 3.14 | kennis uses PEP 695 type aliases; MinerU does not yet support 3.15 |
| [uv](https://docs.astral.sh/uv/) | recommended; `pipx` and `pip` also install the published package |
| `git` | the corpus is a repository; checked once at `corpus init`, with no fallback |

kennis is developed and used on Linux, and macOS runs its tests. **Windows is
not yet working properly**: the tests run there, but expect far more bugs
than on Linux.

## Install kennis

```
uv tool install kennis                # the command line, the window and PDF conversion
uv tool install "kennis[mcp]"         # and the MCP server for agents
```

`uv tool install` gives kennis an environment of its own and puts the
`kennis` command on your PATH. `pipx install kennis` does the same, and
`pip install kennis` installs it into whatever environment is active.

Install the `mcp` extra if you mean to connect an AI agent; without it,
`kennis serve` refuses and names the command above.

### On a machine with no NVIDIA GPU

kennis converts PDFs, DOCX, PPTX and XLSX locally with MinerU, which is part
of the install. It is the large part: MinerU brings PyTorch, and on Linux the
CUDA libraries with it, a download of several gigabytes. PyTorch's CPU build
is a few hundred megabytes instead:

```
uv tool install kennis \
  --index https://download.pytorch.org/whl/cpu \
  --index-strategy unsafe-best-match
```

The second flag is needed because PyTorch's index also carries old copies of
ordinary packages such as `packaging`, and uv otherwise takes every version
of a package from the first index that lists it. With it, uv chooses the
best version from both indexes, which is safe only because both are run by
parties you already trust with the install.

## Check it

```
kennis --version
kennis config path
```

The second prints where your configuration file is, which does not exist
until `kennis config init` writes it in the tutorial's first step.

## Where kennis puts things

| what | where | override |
|---|---|---|
| configuration | `~/.config/kennis/config.toml` | `KENNIS_CONFIG_DIR` |
| credentials | `~/.config/kennis/credentials.toml` | `KENNIS_CONFIG_DIR` |
| the corpus | `~/.local/share/kennis` | `corpus.root` |
| recent searches, the service's record | `~/.local/state/kennis` | `KENNIS_STATE_DIR` |
| the log | `~/.local/state/kennis/log/kennis.log` | `KENNIS_LOG_DIR` |
| embedding models | `~/.cache/kennis/models` | - |

These are the XDG defaults; on macOS and Windows they are the platform
equivalents, and `kennis config path` prints the real one. Every setting can
also be given as an environment variable, such as `KENNIS_EMBEDDING_BACKEND`.

Setting `KENNIS_CONFIG_DIR` and `KENNIS_CORPUS_ROOT` is the clean way to try
kennis without touching a configuration or corpus you already have.

Before you add anything, read [where your data goes](../privacy.md): what
kennis stores, where, and which actions send anything off the machine.

## Upgrade

```
uv tool upgrade kennis
```

A kennis service started by the earlier installation is replaced by the next
command that finds it idle, because its code differs from the new client's.
An agent's MCP server is a process of the earlier installation too, so
restart the agent's session.

## Next

[Tutorial: your first corpus](tutorial.md).

## From source

For working on kennis itself, or running an unreleased version.
[CONTRIBUTING.md](https://github.com/kwazzi-jack/kennis/blob/main/CONTRIBUTING.md)
says how changes are made.

```
git clone https://github.com/kwazzi-jack/kennis.git
cd kennis
uv sync --extra mcp
uv run kennis --help
```

!!! warning "A bare `uv sync` removes extras"
    `uv sync` syncs the default set, which **uninstalls** the `mcp` extra if
    you had it. Once you are using it, always say `uv sync --extra mcp`.

### A source checkout as a tool on your PATH

To get a `kennis` command from a checkout instead of prefixing everything
with `uv run`:

```
uv tool install .                     # kennis, the window and PDF conversion
uv tool install "kennis[mcp] @ ."     # and the MCP server for agents
```

`uv tool install` links only the requested package's executables, so `mineru`
itself does not land on your PATH. kennis finds it in the environment it was
installed into.

!!! note "`uv tool install` ignores the lockfile"
    It resolves fresh from `pyproject.toml`, so a dependency can land on a
    newer major version than the one `uv.lock` pins and the suite was run
    against. To install the locked versions, export them as constraints
    first:

    ```
    uv export --frozen --no-hashes --extra mcp --no-emit-project --no-dev > constraints.txt
    uv tool install --reinstall --constraints constraints.txt "kennis[mcp] @ ."
    ```

To upgrade after pulling, run the same two commands again.
