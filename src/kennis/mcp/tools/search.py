"""The `search` tool: every scope, or the ones the agent names.

**The hit text is not composed here.** `render/hits.py::rendered_hit` is
what turns a result into words, and the command line calls the same
function - design section 20's one deliberate exception to every front
end rendering for itself. It is worth the exception because the
byte-identical property is what makes `kennis search` output a faithful
proxy for what an agent sees: a person debugging retrieval at the
terminal is looking at the thing the model looked at.

**One tool with the collections as an argument** (Brian, 2026-11-10,
#643). It was four, one per scope, on the reasoning that a tool's name
is what an agent selects on. One tool can answer "where is this said"
without the agent choosing first, and what each collection is for is in
this docstring and in the server's instructions.

**A scope the agent named is a promise, and one swept into is not** -
the command line's own rule, because this is the same sweep. A named
collection with no index is an error: answering "no hits" for an index
that was never built tells the caller something false. With none named,
a scope with no index is skipped and the answer says so.
"""

from __future__ import annotations

from pathlib import Path

from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.context.bundle import find_bundle
from kennis.engine.context.groups import CONTEXT_COLLECTION
from kennis.engine.context.projects import present_bundles, project_named
from kennis.engine.errors import InputError
from kennis.render.hits import (
    Hit,
    basis_phrase,
    best_lexical,
    rendered_hit,
    score_style_for,
)
from kennis.render.words import ScoreStyle, describe_skipped, group_title
from kennis.scopes import MAX_TOP_K, SCOPE_NAMES

# What the tool answers with when no scope holds anything for this
# question. A sentence rather than an empty string: an agent handed ""
# cannot tell a miss from a broken tool.
_NOTHING = "no matching passages"


def search(
    question: str,
    collections: list[str] | None = None,
    top_k: int = 5,
    version: list[str] | None = None,
    projects: str | list[str] = "",
    tags: list[str] | None = None,
) -> str:
    """Search what kennis holds, in every collection or the ones named.

    `collections` is any of:

    - `notes` - the user's own material, machine-global: their
      conventions, their decisions, what they asked kennis to remember.
    - `literature` - papers. Reach for it to ground *why* a method works
      rather than answering from general knowledge, and cite what comes
      back.
    - `docs` - documentation sites: upstream usage, configuration and
      syntax.
    - `context` - this project's `.context/` bundle: decisions and
      conventions specific to the repository you are working in.

    Omit it to search all four. Name the ones you want when you know
    where the answer is: a named collection that has no index is an
    error, while an unnamed one is skipped and the answer says so.

    The answer is grouped by collection, each group ranked on its own.
    Relevance in one group is not comparable with another's. Each hit
    carries a relevance band, a snippet, and a `document_id` and `chunk`
    to pass to `read`. Search locates; read expands. `top_k` is how many
    hits each collection gives.

    **A `context` hit is a file location, not content**: its handle is a
    path in the user's own repository, so open it with your native file
    tools rather than `read`.

    `version` applies to `docs`: each project's current version is
    searched unless it names others - `"2.12"` for every project holding
    2.12, `"pydantic=2.12"` for one project's, `"all"` for every version
    held. `list_corpus` says which are held.

    `projects` applies to `context`: `"all"` for every project on this
    machine, or a list of project names. Outside any project every
    project is searched.

    `tags` keeps only what carries every one of them.
    """
    scopes = _scopes(collections)
    # The MCP server runs where its agent works, so its directory is the
    # project's (#508); the service is sent the bundle, never asked to
    # look for one.
    bundle = find_bundle(Path.cwd())
    # No corpus, no service: refused with `kennis corpus init`, which
    # fastmcp gives the agent as the tool's error (14e). So is a named
    # scope with no index, with the command that builds one.
    found = api.sweep(
        existing_corpus().corpus_root,
        question,
        scopes=scopes,
        named=collections is not None,
        # An agent may pass anything. Zero would return nothing and read
        # as a miss; a thousand would return an index as one payload.
        top_k=max(1, min(top_k, MAX_TOP_K)),
        filters=None,
        mode=None,
        versions=tuple(version or ()),
        bundle=bundle,
        others=_other_projects(projects, here=bundle),
        tags=tuple(tags or ()),
    )
    # The degraded flag is dropped rather than printed. A command line
    # says "these are raw scores" above the report; here the detail line
    # shows the numbers and their absence of a band is self-evident, and
    # a sentence about calibration would cost tokens to say so twice.
    everything = [hit for hits in found.groups.values() for hit in hits]
    style, _ = score_style_for(everything, existing_corpus().settings.retrieval.scores)
    blocks = [
        _group(name, hits, style) for name, hits in found.groups.items() if hits
    ] or [_NOTHING]
    # One line a scope, each with its own command: the command line
    # collapses several onto `kennis corpus index`, which is a decision
    # about how its report reads and is its own.
    blocks.extend(
        f"{describe_skipped([skipped.name])}. Run `{skipped.resolution}`."
        for skipped in found.skipped
    )
    return "\n\n".join(blocks)


def _scopes(collections: list[str] | None) -> tuple[str, ...]:
    """The scopes to search; an unknown name is refused with the ones there
    are. In any order: the sweep answers in the order a report lists them."""
    if collections is None:
        return SCOPE_NAMES
    unknown = [name for name in collections if name not in SCOPE_NAMES]
    if unknown or not collections:
        raise InputError(
            f"collections must name one or more of {', '.join(SCOPE_NAMES)}"
            + (f", not {', '.join(unknown)}" if unknown else "")
        )
    return tuple(collections)


def _group(name: str, hits: list[Hit], style: ScoreStyle) -> str:
    """One collection's hits under its heading.

    The heading carries what the group's relevance bands are bands of,
    in the words `kennis search` prints there: a band is never shown
    without its scale, and each group's is its own.
    """
    best = best_lexical(hits)
    lines = [f"{group_title(name)} {basis_phrase(hits, style)}".rstrip()]
    for rank, hit in enumerate(hits, start=1):
        # A bundle hit's body is left out: the handle is a path and the
        # agent opens the file, so a snippet would be a second copy of
        # text it is about to read in full.
        snippet = "none" if hit.collection == CONTEXT_COLLECTION else "short"
        shown = rendered_hit(hit, rank=rank, style=style, best=best, snippet=snippet)
        lines.extend([shown.headline, f"  {shown.detail}"])
        if shown.body is not None:
            lines.append(f"  {shown.body}")
    return "\n".join(lines)


def _other_projects(projects: str | list[str], *, here: Path | None) -> list[Path]:
    """The bundles a context search reads besides this project's.

    Every known project when asked for `"all"`, or when the agent works
    outside any project, where "this project" names nothing; the named
    ones otherwise, refused by name when unknown.
    """
    if projects == "all" or (here is None and not projects):
        return list(present_bundles())
    if isinstance(projects, str):
        return [project_named(projects).bundle] if projects else []
    return [project_named(name).bundle for name in projects]


__all__ = ["search"]
