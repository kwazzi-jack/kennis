# Python API

!!! warning "Not a stable interface"
    `kennis.engine` exports nothing from its `__init__`, and v0.1 has no
    curated public API. What is shown here is the surface a caller
    plausibly reaches for. Everything else under `kennis.engine` is
    internal and will change without a deprecation path, because
    [this project keeps none](https://github.com/kwazzi-jack/kennis).

    The command line is the supported interface. See
    [Commands](cli.md).

The docstrings below are essays about why a mechanism has the shape it does,
because that is what they are in the source. Parameter types come from the
annotations, which are complete - kennis is checked with mypy in strict mode
and has no bare `dict` and no `type: ignore`.

## Searching

::: kennis.engine.rag.search
    options:
      heading_level: 3
      members_order: source

## Settings

The `Settings` model itself is on the
[Configuration](configuration.md#the-model) page.

The  model itself is on the
[Configuration](configuration.md#the-model) page.

::: kennis.engine.settings
    options:
      heading_level: 3
      members: [config_path, credentials_path, load_settings]

## Events

An operation reports progress by emitting events. A front end subscribes;
nothing in the engine knows what a progress bar is.

::: kennis.engine.events
    options:
      heading_level: 3
      members_order: source
