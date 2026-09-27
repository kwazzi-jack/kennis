"""What the server tells a model about itself.

Design section 11. Half of this is written and half is generated: the
written half explains kennis - the collections, that ids are surrogates,
what `search_context` returns - and the generated half names what *this*
installation holds, from the packs that are actually installed.

Three things that buys, and they are the reason the block is generated
rather than written. It adapts to the machine instead of claiming
knowledge that is not there. The holdings are the same bytes `kennis
pack list` prints, so what a user reads and what a model reads cannot
drift. And the injection surface is a pair of length-capped plain-text
fields inside a pack's identity block, rather than free-form prose
spliced into a system prompt.

**It costs tokens on every session.** Changing its shape is a deliberate
decision, not something folded into an unrelated change.
"""

from __future__ import annotations

from collections.abc import Sequence

from kennis.engine.pack.installed import InstalledPack
from kennis.render.packs import describe_holdings

_ABOUT = """\
kennis holds durable knowledge for this machine and this project, and
serves it over search and read. It knows nothing about any subject on its
own: what it holds arrives as packs, and the list below is what this
installation actually has.

## The four collections

- `notes` - machine-global, entirely the user's own. Their conventions,
  their decisions, anything they asked kennis to remember. Prefer it when
  a question is about this user rather than about upstream behaviour.
- `literature` - papers, with their bibliographic metadata.
- `docs` - documentation sites, one project per site.
- `context` - the current project's `.context/` bundle, committed with
  the repository. Project-specific conventions and decisions.

## Search locates; read expands

A `search_*` tool returns ranked hits, each with a score, a source and a
bounded snippet. It is a coordinate, not an answer. When a snippet is
on-topic but cut off, follow up with the matching `read_*` tool.

`search_context` is the exception: it returns file locations in the
user's own repository, which you open with your native file tools.

Call `list_corpus` when you need to know what a collection *contains*
rather than what matches a query - which docs projects exist before
filtering a search by one, or whether a paper is held at all.

## Handles

A `document_id` is an opaque surrogate, not a title, a citekey or a path.
Copy it from a hit or from `list_corpus`; never construct or guess one.\
"""

_NOTHING_HELD = """\


## What this kennis holds

This installation holds no packs, so the collections above may be empty.
Search them before concluding anything about what is or is not here, and
say plainly when a search returns nothing rather than answering from
general knowledge.\
"""


def instructions_for(packs: Sequence[InstalledPack]) -> str:
    """The block this server is started with.

    `packs` is what is installed now, read at startup. A pack added
    later is not reflected until the server restarts, which is the same
    bargain every MCP client makes with its server's tool list.
    """
    holdings = describe_holdings(packs)
    if not holdings:
        return _ABOUT + _NOTHING_HELD
    named = "\n".join(f"  {line}" for line in holdings)
    return f"{_ABOUT}\n\n## What this kennis holds\n\n{named}"


__all__ = ["instructions_for"]
