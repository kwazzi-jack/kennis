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

from kennis.engine.context.index import CONTEXT_COLLECTION
from kennis.render.hits import (
    ScoreStyle,
    best_lexical,
    rendered_hit,
    score_style_for,
)
from kennis.retrieval import search_scope

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


def search_docs(question: str, top_k: int = 5) -> str:
    """Search the docs collection - documentation sites, one per project.

    Reach for this for upstream usage, configuration and syntax. Call
    `list_corpus` first if you need to know which projects are held.

    Returns ranked hits with a `document_id` and `chunk` for `read_docs`.
    """
    return _searched("docs", question, top_k)


def search_context(question: str, top_k: int = 5) -> str:
    """Search this project's `.context/` bundle - its own conventions.

    Reach for this for decisions and conventions specific to the
    repository you are working in, before falling back to anything
    machine-global.

    **Returns file locations, not content.** A bundle lives in the
    user's own repository, so each hit's handle is a path: open it with
    your native file tools. There is no `read_context`.
    """
    return _searched(CONTEXT_COLLECTION, question, top_k)


def _searched(collection: str, question: str, top_k: int) -> str:
    """One scope, searched and rendered.

    The searching is `kennis.retrieval.search_scope`, shared with the
    graphical front end - it answers "where is the index and which
    mode can it run", which is not a question either front end owns.
    What is left here is the rendering, which is.

    Its exceptions carry the command that resolves them, and fastmcp
    turns them into a tool error the agent can read.
    """
    hits = search_scope(collection, question, top_k)
    if not hits:
        return _NOTHING
    # The degraded flag is dropped rather than printed. A command line
    # says "these are raw scores" above the report; here the detail line
    # shows the numbers and their absence of a band is self-evident, and
    # a sentence about calibration would cost tokens to say so twice.
    style, _ = score_style_for(hits, _STYLE)
    best = best_lexical(hits)
    # A context hit's body is left out: the handle is a path and the
    # agent opens the file, so a snippet would be a second copy of text
    # it is about to read in full.
    snippet = "none" if collection == CONTEXT_COLLECTION else "short"
    blocks: list[str] = []
    for rank, hit in enumerate(hits, start=1):
        shown = rendered_hit(hit, rank=rank, style=style, best=best, snippet=snippet)
        lines = [shown.headline, f"  {shown.detail}"]
        if shown.body is not None:
            lines.append(f"  {shown.body}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


__all__ = [
    "search_context",
    "search_docs",
    "search_literature",
    "search_notes",
]
