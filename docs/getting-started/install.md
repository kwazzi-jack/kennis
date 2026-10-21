# Install

kennis is published on PyPI as `kennis`. It needs Python 3.12 to 3.14 and
`git` on your PATH; [uv](https://docs.astral.sh/uv/) is the recommended way
to install it.

## Requirements

| what | why |
|---|---|
| Python 3.12 to 3.14 | kennis uses PEP 695 type aliases; MinerU does not yet support 3.15 |
| `uv` | recommended; `pip` and `pipx` also install the published package |
| `git` | the corpus is a repository; checked once at `corpus init`, with no fallback |

## From PyPI

```
uv tool install kennis                # kennis, the window and PDF conversion
uv tool install "kennis[mcp]"         # and the MCP server for agents
```

`uv tool install` gives kennis an environment of its own and puts the
`kennis` command on your PATH. `pipx install kennis` does the same, and
`pip install kennis` installs it into whatever environment is active.

kennis converts PDFs, DOCX, PPTX and XLSX locally with MinerU, which is part
of the install. It is the large part: MinerU brings PyTorch, and on Linux the
CUDA libraries with it, a download of several gigabytes. On a machine with no
NVIDIA GPU, PyTorch's CPU build is a few hundred megabytes instead:

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

To upgrade:

```
uv tool upgrade kennis
```

Before you add anything, read
[where your data goes](../privacy.md): what kennis stores, where, and
which actions send anything off the machine.

## From source

For working on kennis itself, or running an unreleased version:

```
git clone https://github.com/kwazzi-jack/kennis.git
cd kennis
uv sync
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

To upgrade after pulling, run the same two commands again. A kennis service
started from the earlier installation is replaced by the next command that
finds it idle, because its installed code differs from the client's. An
agent's MCP server is a process of the earlier installation too, so restart
the agent's session.

## Check it

```
kennis --version
kennis config path
```

## Where kennis puts things

| what | where | override |
|---|---|---|
| configuration | `~/.config/kennis/config.toml` | `KENNIS_CONFIG_DIR` |
| credentials | `~/.config/kennis/credentials.toml` | `KENNIS_CONFIG_DIR` |
| the corpus | `~/.local/share/kennis` | `corpus.root` |
| recent searches | `~/.local/state/kennis` | `KENNIS_STATE_DIR` |
| the log | `~/.local/state/kennis/log/kennis.log` | `KENNIS_LOG_DIR` |
| embedding models | `~/.cache/kennis/models` | - |

These are the XDG defaults; on macOS and Windows they are the platform
equivalents. `kennis config path` prints the real one.

Setting `KENNIS_CONFIG_DIR` is the clean way to try kennis without touching a
configuration you already have.

## Next

[Tutorial: your first corpus](tutorial.md).
