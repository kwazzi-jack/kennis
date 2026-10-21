"""The four `search_*` tools, one per scope.

**The hit text is not composed here.** `render/hits.py::rendered_hit` is
what turns a result into words, and the command line calls the same
function - design section 20's one deliberate exception to every front
end rendering for itself. It is worth the exception because the
byte-identical property is what makes `kennis search` output a faithful
proxy for what an agent sees: a person debugging retrieval at the
terminal is looking at the thing the model looked at.

**Four functions rather than one with a `collection` argument.** The
tool name is what an agent selects on, and a docstring per collection is
what tells it which to reach for - a single `search(collection=...)`
would put that choice inside a parameter description where it is read
last, if at all.

**A named scope with no index is an error here**, where the command line
skips it. The command line sweeps every scope and reports what it
searched; a tool is asked about exactly one, and answering "no hits" for
an index that was never built tells the caller something false.
"""

from __future__ import annotations

from pathlib import Path

from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.context.bundle import find_bundle
from kennis.engine.context.groups import CONTEXT_COLLECTION
from kennis.engine.context.projects import present_bundles, project_named
from kennis.render.hits import best_lexical, rendered_hit, score_style_for
from kennis.render.words import ScoreStyle

# What a tool answers with when a scope holds nothing for this question.
# A sentence rather than an empty string: an agent handed "" cannot tell
# a miss from a broken tool.
_NOTHING = "no matching passages"

# Bands are what a reader wants and what an agent can act on; raw fused
# scores are a function of rank and say nothing an ordered list does not.
# Degrades to `raw` by itself when the model has no calibrated scale.
_STYLE: ScoreStyle = "human"


def search_notes(question: str, top_k: int = 5) -> str:
    """Search notes - the user's own material, machine-global.

    Reach for this when a question is about *this user*: their
    conventions, their decisions, something they asked kennis to
    remember. Not upstream documentation and not published papers.

    Returns ranked hits, each with a relevance band, a `document_id` and
    `chunk` to pass to `read_notes`, and a snippet. Search locates; read
    expands.
    """
    return _searched("notes", question, top_k)


def search_literature(question: str, top_k: int = 5) -> str:
    """Search the literature collection - papers, with their metadata.

    Reach for this to ground an explanation of *why* a method works, or
    to justify a choice, rather than answering from general knowledge.
    Cite what comes back.

    Returns ranked hits with a `document_id` and `chunk` for
    `read_literature`, which expands a hit that is on-topic but cut off.
    """
    return _searched("literature", question, top_k)


def search_docs(question: str, top_k: int = 5, version: list[str] | None = None) -> str:
    """Search the docs collection - documentation sites, one folder per
    project and version.

    Reach for this for upstream usage, configuration and syntax. Call
    `list_corpus` first if you need to know which projects and versions
    are held.

    Each project's current version is searched unless `version` names
    others: `"2.12"` for every project holding 2.12, `"pydantic=2.12"`
    for one project's, `"all"` for every version held. Each hit names
    its version; a passage equal in several versions is shown once,
    naming each.

    Returns ranked hits with a `document_id` and `chunk` for `read_docs`.
    """
    return _searched("docs", question, top_k, versions=tuple(version or ()))


def search_context(
    question: str, top_k: int = 5, projects: str | list[str] = ""
) -> str:
    """Search this project's `.context/` bundle - its own conventions.

    Reach for this for decisions and conventions specific to the
    repository you are working in, before falling back to anything
    machine-global.

    **Returns file locations, not content.** A bundle lives in the
    user's own repository, so each hit's handle is a path: open it with
    your native file tools. There is no `read_context`. Advice from a
    pack the project uses comes after, with a `pack=` handle and the
    passage itself.

    `projects` widens the search: `"all"` for every project on this
    machine, or a list of project names. Each other project's hits name
    its folder in full. Outside any project every project is searched.
    """
    return _searched(CONTEXT_COLLECTION, question, top_k, projects=projects)


def _searched(
    collection: str,
    question: str,
    top_k: int,
    *,
    versions: tuple[str, ...] = (),
    projects: str | list[str] = "",
) -> str:
    """One scope, searched and rendered.

    The searching is the service's `search_scope`, which the window and
    the command line reach too - it answers "where is the index and
    which mode can it run", which is not a question any front end owns.
    What is left here is the rendering, which is.

    Its exceptions carry the command that resolves them, and fastmcp
    turns them into a tool error the agent can read.
    """
    # The MCP server runs where its agent works, so its directory is the
    # project's (#508); the service is sent the bundle, never asked to
    # look for one.
    bundle = find_bundle(Path.cwd())
    others = _other_projects(projects, here=bundle)
    # No corpus, no service: refused with `kennis corpus init`, which
    # fastmcp gives the agent as the tool's error (14e).
    hits = api.search_scope(
        existing_corpus().corpus_root,
        collection,
        question,
        top_k=top_k,
        versions=versions,
        bundle=bundle,
        others=others,
    )
    if not hits:
        return _NOTHING
    # The degraded flag is dropped rather than printed. A command line
    # says "these are raw scores" above the report; here the detail line
    # shows the numbers and their absence of a band is self-evident, and
    # a sentence about calibration would cost tokens to say so twice.
    style, _ = score_style_for(hits, _STYLE)
    best = best_lexical(hits)
    blocks: list[str] = []
    for rank, hit in enumerate(hits, start=1):
        # A bundle hit's body is left out: the handle is a path and the
        # agent opens the file, so a snippet would be a second copy of
        # text it is about to read in full. A pack's file is in kennis's
        # store, which the agent has no path to, so it gets the passage.
        snippet = "none" if hit.collection == CONTEXT_COLLECTION else "short"
        shown = rendered_hit(hit, rank=rank, style=style, best=best, snippet=snippet)
        lines = [shown.headline, f"  {shown.detail}"]
        if shown.body is not None:
            lines.append(f"  {shown.body}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


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


__all__ = [
    "search_context",
    "search_docs",
    "search_literature",
    "search_notes",
]
