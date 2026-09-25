# Configuration

kennis reads its settings from one TOML file, and its credentials from
somewhere else entirely. This page lists every key; the reasoning behind the
split is in [Keep credentials out of the config](../how-to/credentials.md).

## Where the file lives

```
kennis config path
```

The platform configuration directory, which on Linux is
`~/.config/kennis/config.toml`. Setting `KENNIS_CONFIG_DIR` overrides it,
which is what makes a throwaway configuration possible without touching your
own.

## Precedence

A value is taken from the first source that offers it:

1. **The environment**, as `KENNIS_<SECTION>_<FIELD>` - so
   `KENNIS_EMBEDDING_BACKEND` or `KENNIS_EMBEDDING_API_KEY_ENV`.
2. **`config.toml`** in the configuration directory.
3. **The default** shown in the tables below.

!!! note "Exact names, not nested delimiters"
    pydantic-settings can split an environment variable on `_` to find a
    nested field. kennis does not use that. `KENNIS_EMBEDDING_API_KEY_ENV`
    would resolve to `embedding.api.key.env`, match nothing, and be dropped
    **in silence** - the field keeps its default and the person who set the
    variable has no way to find out why. kennis walks its own model instead
    and looks each name up exactly.

## Reading and changing settings

```
kennis config show                    # the whole file, as valid TOML
kennis config get                     # every setting and the value in effect
kennis config get embedding.model     # one value, unstyled, for scripts
kennis config set embedding.backend ollama
kennis config init                    # the guided setup
```

`kennis config show` writes the file to standard output and its warnings to
standard error, so `kennis config show > config.toml` produces a usable file
rather than one with a warning in the middle.

`kennis config get <key>` prints the bare value with no styling, so it can be
read by a script. `kennis config get` with no key prints the whole set,
highlighted.

## Every setting

--8<-- "reference/_settings-table.md"

## Settings kennis deliberately does not offer

A setting that nothing honours is worse than a missing one, because it is a
promise. Where the design defers a mechanism, its setting is absent rather
than present and ignored.

## The model

::: kennis.engine.settings.Settings
    options:
      heading_level: 3
      show_root_heading: false
