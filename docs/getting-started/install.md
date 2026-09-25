# Install

kennis is not on PyPI yet, so install it from source. It needs Python 3.12 or
later, [uv](https://docs.astral.sh/uv/), and `git` on your PATH.

## Requirements

| what | why |
|---|---|
| Python 3.12+ | kennis uses PEP 695 type aliases |
| `uv` | the only supported way to run and install it |
| `git` | the corpus is a repository; checked once at `corpus init`, with no fallback |

## From source

```
git clone https://github.com/kwazzi-jack/kennis.git
cd kennis
uv sync
uv run kennis --help
```

To convert PDFs, DOCX, PPTX and XLSX you need the `mineru` extra, which is a
large download:

```
uv sync --extra mineru
```

!!! warning "A bare `uv sync` removes the extra"
    `uv sync` syncs the default set, which **uninstalls** anything the
    `mineru` extra brought in. Once you are using it, always say
    `uv sync --extra mineru`.

## As a tool on your PATH

To get a `kennis` command instead of prefixing everything with `uv run`:

```
uv tool install .                       # without PDF conversion
uv tool install "kennis[mineru] @ ."    # with it
```

`uv tool install` links only the requested package's executables, so `mineru`
itself does not land on your PATH. kennis finds it in the environment it was
installed into.

!!! note "`uv tool install` ignores the lockfile"
    It resolves fresh from `pyproject.toml`. A dependency can therefore land
    on a different version from the one `uv.lock` pins, which has produced
    real skew before. If something behaves differently between `uv run
    kennis` and `kennis`, compare the two environments' versions first.

To upgrade after pulling:

```
uv tool install --force "kennis[mineru] @ ."
```

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
| the corpus | `~/.local/share/kennis/corpus` | `corpus.root` |
| the log | `~/.local/state/kennis/log/kennis.log` | - |
| embedding models | `~/.cache/kennis/models` | - |

These are the XDG defaults; on macOS and Windows they are the platform
equivalents. `kennis config path` prints the real one.

Setting `KENNIS_CONFIG_DIR` is the clean way to try kennis without touching a
configuration you already have.

## Next

[Tutorial: your first corpus](tutorial.md).
