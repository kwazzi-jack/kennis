"""Searching: the page, the results htmx swaps in, and the history of what
was asked.
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)

from kennis.context import existing_corpus
from kennis.engine.errors import (
    KennisError,
)
from kennis.gui import history, words
from kennis.gui.pages import (
    shown_groups_of,
    shown_key,
    shown_orders,
    shown_recents,
    shown_skips,
)
from kennis.gui.responses import SCOPES, TEMPLATES, frame, from_htmx
from kennis.retrieval import (
    EVERY_SCOPE,
    SCOPE_NAMES,
    sweep,
)

router = APIRouter()


def _prefetched(request: Request) -> bool:
    """Whether the browser fetched this on its own, ahead of the reader.

    A search is a GET, so a browser may fetch one before it is asked -
    a link to a recent search, hovered. That is not a search the reader
    made, and the history is a record of what the reader looked for.
    Chromium says `Sec-Purpose: prefetch`, Firefox `X-Moz: prefetch`, and
    older engines `Purpose: prefetch`.
    """
    headers = request.headers
    return any(
        "prefetch" in headers.get(name, "")
        for name in ("sec-purpose", "purpose", "x-moz")
    )


def _hits_context(
    question: str, scope: str, mode: str, order: str = "", *, record: bool = True
) -> dict[str, object]:
    """What a search page and its partial both need.

    A failure becomes fields rather than an exception: a search box
    whose scope has no index should say so above the box the person is
    still typing in, not replace the page with an error.

    **Every scope by default**, through the same sweep the command
    line runs. Searching one collection at a time and defaulting to
    notes meant a reader looking for a paper from a cold start was
    answered nothing at all until they knew to change a dropdown.
    Concern #314 is what made one sweep possible.
    """
    context: dict[str, object] = {
        **frame(existing_corpus()),
        # What was asked. What the form offers - the scopes, the hint
        # for each, the modes - is a template global, because the form
        # is the bar's and is on every page.
        "question": question,
        "scope": scope,
        "mode": mode,
        # Only this page's form searches as you type: live search swaps
        # into `#hits`, which no other page has.
        "searching_here": True,
        "groups": [],
        "summary": None,
        "order": order,
        "skips": [],
        "keywords_only": None,
        "key": None,
        "orders": [],
        "order_label": words.ORDER_LABEL,
        "order_limit": words.ORDER_LIMIT,
        "nothing": words.NOTHING_FOUND,
        "problem": None,
        "resolution": None,
    }
    if not question:
        return context
    if scope not in SCOPES and scope != EVERY_SCOPE:
        context["problem"] = words.unknown_scope(scope, SCOPES)
        return context
    # Checked against what the window offers rather than by letting
    # `retrieval.as_mode` raise: its resolution is `kennis config get
    # retrieval.corpus_method`, which is the wrong remedy for someone
    # who edited an address. The same shape `preference_of` uses.
    if mode not in {value for value, _ in words.MODE_CHOICES}:
        context["problem"] = words.unknown_mode(mode)
        return context
    if order not in {value for value, _ in words.ORDER_CHOICES}:
        context["problem"] = words.unknown_order(order)
        return context
    asked = SCOPE_NAMES if scope == EVERY_SCOPE else (scope,)
    try:
        found = sweep(
            question,
            scopes=asked,
            named=scope != EVERY_SCOPE,
            # Empty is "no mode given", which lets each scope use its
            # own setting. Not the same as "hybrid": a bundle index is
            # lexical by design.
            mode=mode or None,
        )
        context["groups"] = shown_groups_of(found, question, order)
        found_count = sum(len(hits) for hits in found.groups.values())
        # Any scope that filled its quota had more to give, so the
        # total is a floor. `default_top_k` is 3 per scope, which is
        # why this is the usual case rather than the exception.
        wanted = existing_corpus().settings.retrieval.default_top_k
        capped = any(len(hits) >= wanted for hits in found.groups.values())
        if found_count:
            context["summary"] = words.results_for(
                found_count, capped=capped, question=question
            )
        key = shown_key(found)
        context["key"] = key
        # Only when both measures scored: with one, the results are
        # already in that measure's own order and a choice would change
        # nothing.
        if key is not None and len(key.lines) > 1:
            context["orders"] = shown_orders(
                question=question, scope=scope, mode=mode, order=order
            )
        context["skips"] = shown_skips(found)
        # The command line has printed this since milestone 1 and the
        # page never did. A control offering "Meaning only" that
        # quietly returns lexical results is a control that lies, so
        # the mode selector is what made the omission matter.
        # Concern #381.
        #
        # One quiet notice for every collection it applies to, with the
        # step that would change it: three bold sentences, one per
        # collection, took the top of every page before a single result.
        if found.degraded:
            context["keywords_only"] = shown_keywords_only(found.degraded)
        # Here rather than in either route, because both run a search
        # and a reload, a Back and a keystroke must all record the
        # same way. A refused search is not recorded: it found
        # nothing because it could not run, which is not something to
        # offer the reader again.
        if record:
            history.record(
                question,
                scope=scope,
                mode=mode,
                hits=found_count,
                capped=capped,
            )
    except KennisError as error:
        context["problem"] = str(error)
        context["resolution"] = error.resolution
    return context


def shown_keywords_only(degraded: Sequence[str]) -> dict[str, str]:
    """The keywords-only notice, and what would give the search meaning.

    With no meaning model configured, building again changes nothing, so
    the way forward is Settings; with one, it is an index.
    """
    if existing_corpus().settings.embedding.backend == "none":
        label, href = words.KEYWORDS_ONLY_CHOOSE, "/settings#setting-embedding.backend"
    else:
        label, href = words.KEYWORDS_ONLY_INDEX, "/index"
    return {"sentence": words.keywords_only(degraded), "label": label, "href": href}


@router.get("/")
def serve_search(
    request: Request,
    q: str = "",
    scope: str = EVERY_SCOPE,
    mode: str = words.MODE_DEFAULT,
    order: str = "",
) -> HTMLResponse:
    context = _hits_context(q, scope, mode, order, record=not _prefetched(request))
    # Only with no query. With one, the results have that space -
    # a page showing both would put what was looked for before
    # beside what was just found, which is two answers to one
    # question.
    context["recents"] = [] if q.strip() else shown_recents(history.recent())
    context["recents_heading"] = words.RECENTS_HEADING
    context["recents_clear"] = words.RECENTS_CLEAR
    return TEMPLATES.TemplateResponse(request, "search.html", context)


@router.post("/history/clear")
def clear_history(request: Request) -> Response:
    # A POST, because a GET that writes is one a prefetcher will
    # follow and this one destroys. The reader's own words are
    # in here and there has to be a way to remove them.
    history.clear()
    if not from_htmx(request):
        return RedirectResponse("/", status_code=303)
    context = _hits_context("", EVERY_SCOPE, words.MODE_DEFAULT)
    context["recents"] = []
    context["recents_heading"] = words.RECENTS_HEADING
    context["recents_clear"] = words.RECENTS_CLEAR
    return TEMPLATES.TemplateResponse(request, "recents.html", context)


@router.get("/hits")
def serve_hits(
    request: Request,
    q: str = "",
    scope: str = EVERY_SCOPE,
    mode: str = words.MODE_DEFAULT,
    order: str = "",
) -> HTMLResponse:
    # The partial htmx swaps in. The same context as the page, so
    # a first load and a keystroke cannot disagree about what a
    # result looks like.
    answer = TEMPLATES.TemplateResponse(
        request,
        "hits.html",
        _hits_context(q, scope, mode, order, record=not _prefetched(request)),
    )
    # **The address the reader should end up at, not the one that
    # was fetched.** `hx-push-url="true"` pushes the request URL,
    # which is this route - so Back and reload rendered the bare
    # fragment with no page around it. Found by walking the
    # interface, not by the suite. Concern #340.
    # The mode only when there was one, for the same reason a
    # recent search's link omits it: an address carrying `mode=`
    # says the reader chose the default rather than not having
    # chosen.
    chosen = f"&mode={quote(mode)}" if mode else ""
    answer.headers["HX-Push-Url"] = f"/?q={quote(q)}&scope={quote(scope)}{chosen}"
    return answer
