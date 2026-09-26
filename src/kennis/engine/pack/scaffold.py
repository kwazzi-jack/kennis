"""Writing a new `.ken.yml`. Design sections 3 and 18.

**A template, not a dump.** `yaml.dump` of a `Pack` would produce a valid
file with no comments, its keys in whatever order the dumper chose, and no
section headings. A pack file is edited by hand for the rest of its life,
so the scaffold is text with the identity interpolated - and it is parsed
before it is written, so the scaffold can never be a file kennis refuses.

**The header line is the point.** Section 18: one comment at the top gives
an author with no kennis installed completion and inline errors from
`redhat.vscode-yaml`, which reads the raw GitHub URL directly. The path is
versioned, so schema 2 is a new file and this line never changes meaning.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

from kennis.engine.errors import PackInvalid
from kennis.engine.events import EventSink, ItemFinished, OperationFinished, Outcome
from kennis.engine.pack.schema import SCHEMA_VERSION, load_pack

# Raw GitHub serves `text/plain`, which the extension accepts. A fact about
# where kennis is published rather than about packs, which is why it is one
# constant and not spread through the template.
SCHEMA_URL: Final = (
    "https://raw.githubusercontent.com/kwazzi-jack/kennis/main/schema/"
    f"ken-{SCHEMA_VERSION}.json"
)

DEFAULT_VERSION: Final = "0.1.0"

OPERATION: Final = "pack-init"

_TEMPLATE: Final = """# yaml-language-server: $schema={url}

kennis:
  schema_version: {schema_version}

pack:
  id: {identifier}
  name: "{name}"
  version: "{version}"
{description}
# What this pack ships. Every section is optional, and a path is relative to
# this file. Run `kennis pack update` after adding one, then
# `kennis pack validate` to check it.
#
# corpus:
#   literature:          # fetched over the network; needs a real identifier
#     - citekey: smirnovRevisitingRIMEI2011
#       title: "Revisiting the radio interferometer measurement equation I"
#       arxiv_id: "1101.1764"
#   docs:                # crawled from base_url
#     - project: stimela
#       base_url: "https://stimela.readthedocs.io/en/latest/"
#   notes:               # markdown copied into the corpus
#     - source: notes/
#       group: stimela
#
# context:               # markdown copied into a project's .context/
#   - source: content/
"""


def scaffold_pack(
    path: Path,
    *,
    identifier: str,
    name: str,
    version: str = DEFAULT_VERSION,
    description: str | None = None,
    events: EventSink | None = None,
) -> Path:
    """Write a new pack file at `path` and return it.

    Raises `PackInvalid` when `path` exists, or when the identity given
    would not validate.

    **Refuses rather than converges**, unlike `context init`. A bundle is a
    directory of many files and restoring a missing one is the command's
    job; a pack file is one file holding hand-written declarations, and it
    lives in the provider's repository rather than in anything kennis has
    history for. Rewriting it would delete work with nothing to restore
    from.
    """
    started = time.monotonic()
    if path.exists():
        # `resolution=None` rather than the class default. `PackInvalid`
        # normally points at `kennis pack validate`, and validating the file
        # you just failed to overwrite answers a question nobody asked. There
        # is no command for this one: choose another path, or delete that
        # file deliberately. Found by running the command, not by a test.
        raise PackInvalid(
            f"{path} already exists, and a pack file holds declarations "
            "kennis did not write. Give another path, or delete that file "
            "first",
            resolution=None,
        )
    text = _TEMPLATE.format(
        url=SCHEMA_URL,
        schema_version=SCHEMA_VERSION,
        identifier=identifier,
        name=name,
        version=version,
        description=_description_line(description),
    )
    # Before writing, not after: an id that is not a slug leaves no file
    # behind, so a failed `init` is not a half-made pack the author has to
    # delete before trying again.
    load_pack(text)
    path.write_text(text, encoding="utf-8")
    if events is not None:
        events.emit(
            ItemFinished(operation=OPERATION, item=str(path), outcome=Outcome.ADDED)
        )
        events.emit(
            OperationFinished(
                operation=OPERATION,
                elapsed_seconds=time.monotonic() - started,
                counts={Outcome.ADDED: 1},
            )
        )
    return path


def _description_line(description: str | None) -> str:
    """The description as a block, or the comment saying it is worth adding.

    Omitted rather than written empty, because `description: ""` would pass
    the length cap and reach an MCP server's instructions as nothing at all.
    """
    if description is None:
        return (
            "  # description: a sentence or two. It reaches a model, not "
            "only a reader.\n"
        )
    return f'  description: "{description}"\n'


__all__ = ["DEFAULT_VERSION", "OPERATION", "SCHEMA_URL", "scaffold_pack"]
