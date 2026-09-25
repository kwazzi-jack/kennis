# Errors

kennis raises a domain exception rather than letting an internal failure
reach the terminal as a traceback. Every one of them derives from
`KennisError`, and every one carries the command that resolves it, attached
with `add_note` - that note is what becomes the `hint:` line.

The engine raises these. It never catches them to print: the front end
decides what an error looks like. See
[Three layers](../explanation/architecture.md).

::: kennis.engine.errors
    options:
      show_root_heading: false
      show_root_toc_entry: false
      members_order: source
      heading_level: 2
