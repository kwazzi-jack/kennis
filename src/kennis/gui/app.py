"""The application: one guard, one page, one stylesheet.

**The guard is middleware, not a decorator.** Every request passes it,
including one for a static asset and one for a route that does not
exist. A per-route check is a check a route added in a later unit can
forget, and the route most likely to be forgotten is the one nobody
writes by hand.

**Why there is a guard at all.** The server listens on the loopback
interface, and loopback is not private on a shared machine: any other
process, and any other user account on the same host, can reach
127.0.0.1. A corpus is personal knowledge and cluster login nodes have
other users on them. Concern #309.

The token is minted per launch and never stored. It arrives once as a
query parameter, because that is what can be put in a URL handed to a
browser, and is then held in a cookie so it is not on every subsequent
request line and not in the address bar to be copied into a chat
window by accident.
"""

from __future__ import annotations

import secrets
import shlex
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Final, assert_never
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request, Response
from fastapi.datastructures import FormData
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from kennis.context import Context, existing_corpus, resolve_context
from kennis.engine.backup import SET_FOLDER_COMMAND, BackupReport, check_backup
from kennis.engine.context.bundle import find_bundle
from kennis.engine.context.index import CONTEXT_COLLECTION
from kennis.engine.context.status import bundle_freshness
from kennis.engine.context.sync import BundleSync
from kennis.engine.corpus.add import AddOptions, AddReport
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.layout import relative_to_corpus
from kennis.engine.corpus.preview import check_lines, preview_paper, preview_site
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.corpus.sync import CorpusSync
from kennis.engine.errors import (
    ContextNotFound,
    CorpusBusy,
    KennisError,
    SettingsError,
    UnknownCollection,
)
from kennis.engine.events import EventSink
from kennis.engine.history.outofband import OutOfBandChange
from kennis.engine.history.repository import Repository
from kennis.engine.pack.store import PackInstall
from kennis.engine.rag.models import Chunk
from kennis.engine.settings import load_settings
from kennis.engine.setup import apply_answers, validate_answer
from kennis.gui import history, words
from kennis.gui.adding import (
    FIRST_BLOCKS,
    FIXED_COLLECTIONS,
    add_fields,
    add_kind,
    add_tabs,
    chooser_target,
    destination_of,
    filled,
    listing_of,
    shown_checks,
    shown_paper_preview,
    shown_site_preview,
)
from kennis.gui.configuration import (
    answers_in,
    changed_answers,
    needs_rebuild,
    offered,
    shown_indexes,
    shown_settings,
)
from kennis.gui.icons import icon
from kennis.gui.jobs import AlreadyRunning, Job, Jobs
from kennis.gui.layout import SIZES, sizes_of, strip_state
from kennis.gui.pages import (
    ShownDocument,
    ShownJob,
    ShownOutcome,
    palette_entries,
    shown_add,
    shown_backup,
    shown_bundle_document,
    shown_bundle_sync,
    shown_corpus_sync,
    shown_document,
    shown_groups,
    shown_groups_of,
    shown_index,
    shown_install,
    shown_key,
    shown_matches,
    shown_orders,
    shown_recents,
    shown_rows,
    shown_skips,
    shown_tree,
)
from kennis.gui.pane import Pane, bundle_folders, pane_now
from kennis.gui.preferences import (
    COOKIE_SECONDS,
    PREFERENCES,
    chosen_in,
    preferences_of,
)
from kennis.gui.stream import as_stream, sent_event
from kennis.gui.theme import stylesheet
from kennis.holdings import (
    document_marks,
    freshness_of,
    holdings,
    installed_packs,
    revision,
)
from kennis.operations import (
    GroupBlock,
    IndexBuild,
    add_documents,
    add_in_groups,
    back_up_corpus,
    build_indexes,
    install_a_pack,
    move_a_document,
    synchronise_bundle,
    synchronise_corpus,
)
from kennis.render.backup import (
    BACKUP_CONTENTS,
    NO_BACKUP_FOLDER,
    describe_archive,
    describe_folder,
    describe_verified,
)
from kennis.render.html import MarkedRange
from kennis.render.packs import describe_holdings
from kennis.render.words import describe_change, describe_lexical_fallback
from kennis.retrieval import (
    EVERY_SCOPE,
    SCOPE_NAMES,
    chunk_range,
    document_chunks,
    sweep,
)
from kennis.writing import write_context_note, write_note

_HERE: Final = Path(__file__).parent
_TEMPLATES: Final = Jinja2Templates(directory=str(_HERE / "templates"))
# Globals rather than per-route context entries: the shell is on every
# page, and not every route builds its context through `_frame`.
# The pane's state is a cookie rather than browser storage, so the
# server renders it and the first byte is already right. Read after
# paint from `localStorage`, a collapsed pane would show open and then
# collapse on every page load.
#
# A global **function** taking the request, not a constant and not
# `_frame`: it varies per request, so a constant is wrong, and not
# every route builds its context through `_frame`, so a value put
# there is undefined on the pages that do not.
_PANE_COOKIE: Final = "pane"
_CLOSED: Final = "closed"
_OPEN: Final = "open"


_INSPECTOR_COOKIE: Final = "inspector"


def _pane_state(request: Request) -> str:
    """`closed` only for exactly that value. Anything can be in a
    cookie, and the default is the state that shows what is there."""
    return _CLOSED if request.cookies.get(_PANE_COOKIE) == _CLOSED else _OPEN


def _inspector_state(request: Request) -> str:
    """The document inspector's, by the pane's rule."""
    return _CLOSED if request.cookies.get(_INSPECTOR_COOKIE) == _CLOSED else _OPEN


# Every preference of this window, rendered onto `<html>` from its
# cookie (`gui/preferences.py`), for the reason the pane's is.
_TEMPLATES.env.globals["preferences"] = preferences_of
# The scopes a person may search, in the order they are offered. The
# bundle last because it is the one that is not always there.
SCOPES: Final = (*COLLECTION_NAMES, CONTEXT_COLLECTION)

_TEMPLATES.env.globals.update(
    {
        "pane_state": _pane_state,
        "inspector_state": _inspector_state,
        "sizes": sizes_of,
        "size_bounds": SIZES,
        "strip_state": strip_state,
        "resize_labels": words.RESIZE_LABELS,
        "strip_show": words.STRIP_SHOW,
        "strip_hide": words.STRIP_HIDE,
        "pane_now": pane_now,
        "pane_show": words.PANE_SHOW,
        "pane_hide": words.PANE_HIDE,
        "pane_states": words.PANE_STATES,
        "icon": icon,
        "actions": words.ACTIONS,
        "palette_title": words.PALETTE_TITLE,
        "settings_heading": words.SETTINGS_HEADING,
        "packs_heading": words.PACKS_HEADING,
        "documents_held": words.documents_held,
        "index_every": words.INDEX_EVERY,
        "remember_targets": words.REMEMBER_TARGETS,
        # Every job's outcome redraws these where the page has them (#457).
        "shell_redraws": (
            ("strip-status", "/strip/status"),
            ("pane-documents", "/pane/documents"),
            *((f"pane-row-{name}", f"/pane/row/{name}") for name in COLLECTION_NAMES),
        ),
        "palette_shortcut": words.PALETTE_SHORTCUT,
        "close_label": words.CLOSE,
        "collection_icons": words.COLLECTION_ICONS,
        "corpus_heading": words.CORPUS_HEADING,
        "context_heading": words.CONTEXT_HEADING,
        "kennis_heading": words.KENNIS_HEADING,
        "corpus_unreadable": words.CORPUS_UNREADABLE,
        "no_context": words.NO_CONTEXT,
        "recents_heading": words.RECENTS_HEADING,
        # The words a hit and the key carry. Globals because `hits.html`
        # is drawn by two routes, the page and the fragment.
        "show_passage": words.SHOW_PASSAGE,
        "hide_passage": words.HIDE_PASSAGE,
        "open_at_passage": words.OPEN_AT_PASSAGE,
        "key_summary": words.KEY_SUMMARY,
        "key_low": words.KEY_LOW,
        "key_high": words.KEY_HIGH,
        "key_order": words.KEY_ORDER,
        "key_models": words.key_models,
        "corpus_changed": words.CORPUS_CHANGED,
        "quit_label": words.QUIT,
        "quit_title": words.QUIT_TITLE,
        "activity_heading": words.ACTIVITY_HEADING,
        # The search form is the bar's, on every page, so what it
        # offers is invariant and global; only the search page passes
        # what was asked.
        "everywhere": EVERY_SCOPE,
        "everywhere_label": words.EVERYWHERE_LABEL,
        "scopes": SCOPES,
        "scope_hints": {
            name: words.search_hint_for(name) for name in (EVERY_SCOPE, *SCOPES)
        },
        "scope_label": words.SCOPE_LABEL,
        "mode_choices": words.MODE_CHOICES,
        "mode_label": words.MODE_LABEL,
        "mode_default": words.MODE_DEFAULT,
        "search_action": words.SEARCH_ACTION,
        "search_key_title": words.SEARCH_KEY_TITLE,
        "searching": words.SEARCHING,
        # The Add dialog's words, global because its fragments - a
        # preview, a block, a chooser - are drawn by routes of their own.
        "add_tabs_label": words.ADD_TABS_LABEL,
        "required": words.REQUIRED,
        "optional": words.OPTIONAL,
        "empty_prefix": words.EMPTY_PREFIX,
        "field_labels": words.FIELD_LABELS,
        "browse": words.BROWSE,
        "another_group": words.ANOTHER_GROUP,
        "block_heading": words.BLOCK_HEADING,
        "check_site": words.CHECK_SITE,
        "line_held": words.LINE_HELD,
        "chooser_heading": words.CHOOSER_HEADING,
        "chooser_up": words.CHOOSER_UP,
        "chooser_cancel": words.CHOOSER_CANCEL,
        "choose_folder": words.CHOOSE_FOLDER,
        "skip_label": words.SKIP,
        "skipped": words.SKIPPED,
        "open_candidate": words.open_candidate,
    }
)

# Sent with every answer: no page kennis serves tells another site where
# its reader came from (11e).
_REFERRER_POLICY: Final = "no-referrer"

# The name the cookie is held under, before its port. Prefixed because it
# is kennis's and a browser may be holding cookies for other things served
# from loopback on another port - a notebook, someone else's dev server -
# and an unprefixed `token` is exactly the collision that produces.
COOKIE_NAME: Final = "kennis_gui_token"

_UNAUTHORISED: Final = "this interface needs the token it was started with"
_CROSS_ORIGIN: Final = "this interface accepts changes only from its own pages"

# The methods that change nothing, and so need not come from kennis's own
# pages. Every write is a POST (11e).
_SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})


def cookie_name(request: Request) -> str:
    """The token cookie's name for the address this request was sent to.

    **Per port, because a cookie is not.** A browser sends a cookie set by
    `127.0.0.1:A` to `127.0.0.1:B` as well, so a second `kennis gui` - one
    per project is the ordinary case (#407) - overwrote the first one's
    token, and every request from the first tab was refused. The port is
    the one the browser addressed, read from `Host`, which over `ssh -L` is
    the forwarded port rather than the server's own.
    """
    port = request.url.port
    return COOKIE_NAME if port is None else f"{COOKIE_NAME}_{port}"


def from_elsewhere(request: Request) -> bool:
    """Whether a request that writes was sent by a page kennis did not serve.

    **`samesite=strict` is not enough on loopback.** A site is a scheme and
    a host, with no port, so a page served from `127.0.0.1` on any other
    port - a notebook, another account's server on a shared machine - is the
    same site, and the browser sends the token cookie with its POSTs. The
    browser states where a request came from in `Origin`, which every
    current browser sends with a POST, and in `Sec-Fetch-Site`; either one
    naming somewhere other than this address refuses the write. A request
    carrying neither came from no browser, and a client outside a browser
    with the token is the person.
    """
    if request.method in _SAFE_METHODS:
        return False
    origin = request.headers.get("origin")
    if origin is not None and origin != "null":
        here = f"{request.url.scheme}://{request.headers.get('host', '')}"
        return origin != here
    # **`Origin: null` is what kennis's own plain forms send.** Every
    # answer carries `Referrer-Policy: no-referrer`, and under it a
    # browser withholds the origin of a form's POST as well as its
    # referrer - so the check refused every form posted without a script,
    # which a test in a real browser found and the suite could not.
    # `Sec-Fetch-Site` is not withheld, and says the same thing.
    fetched = request.headers.get("sec-fetch-site")
    if fetched is not None:
        return fetched not in {"same-origin", "none"}
    # A browser that hid where the request came from and said nothing else.
    return origin == "null"


def new_token() -> str:
    """A token for one launch.

    `secrets` rather than `random`: this is what stands between a
    personal corpus and every other account on a shared machine.
    """
    return secrets.token_urlsafe(32)


async def _form_of(request: Request) -> FormData:
    """A request's form, read on the event loop for a route that is not.

    **Every route is a plain `def`**, which FastAPI runs on a worker thread.
    Nearly all of them touch the disk or start git: a search, a commit, the
    pane's counts on every page (600 ms at a thousand documents), testing a
    backup's every member. In an `async` route each of those stopped the
    whole server, a running job's progress stream included. Reading a form
    is the one thing that has to be awaited, so it is this dependency.
    """
    return await request.form()


# A route's form, as a parameter: `form: PostedForm`.
type PostedForm = Annotated[FormData, Depends(_form_of)]


def _keep_running() -> None:
    """The default `on_quit`, for an application nobody launched."""


def build_app(token: str, on_quit: Callable[[], None] = _keep_running) -> FastAPI:
    """The application, guarded by `token`.

    Taken as an argument rather than read from a global, for the reason
    concern #87 gives about the engine: a value two callers can set
    differently in one process is a value a test can set at all.

    `on_quit` is how a POST to `/quit` reaches whoever is running the
    server. The application cannot stop the server itself - uvicorn owns
    it - so it says it has been asked to and the launcher does the rest.
    """
    app = FastAPI(title="kennis", docs_url=None, redoc_url=None)
    # On the application rather than in a module-level variable, so a
    # test builds its own and two applications in one process do not
    # share a job list.
    app.state.jobs = Jobs()

    @app.middleware("http")
    async def require_token(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        cookie = cookie_name(request)
        supplied = request.query_params.get("token") or request.cookies.get(cookie)
        if not secrets.compare_digest(supplied or "", token):
            # 401 and not a redirect. A refusal that redirects is a
            # refusal a client follows, and then the test that proves
            # the guard works reports 200 for a request that was
            # turned away.
            refusal = JSONResponse({"detail": _UNAUTHORISED}, status_code=401)
            refusal.headers["Referrer-Policy"] = _REFERRER_POLICY
            return refusal
        if from_elsewhere(request):
            refusal = JSONResponse({"detail": _CROSS_ORIGIN}, status_code=403)
            refusal.headers["Referrer-Policy"] = _REFERRER_POLICY
            return refusal
        answer = await call_next(request)
        # On every answer, so a link followed out of kennis - a candidate's
        # registry page, a citation in a converted paper - does not tell
        # the remote site where the reader was. The browser's default
        # already withholds the path across sites; this states the rule
        # rather than relying on the default (11e).
        answer.headers["Referrer-Policy"] = _REFERRER_POLICY
        if request.query_params.get("token"):
            answer.set_cookie(
                cookie,
                token,
                httponly=True,
                samesite="strict",
                # No `secure`: the interface is served over plain HTTP
                # on loopback, and a secure cookie would never be sent
                # back, so the guard would refuse every request after
                # the first.
            )
        return answer

    @app.exception_handler(KennisError)
    def drawn_as_a_problem(request: Request, error: Exception) -> HTMLResponse:
        """A domain failure no route turned into something of its own.

        Design section 20: the engine raises, and each front end turns it
        into what that front end has. A route that reads the settings is
        nearly every route, so a `config.toml` holding one value out of range
        answered every page with a bare "Internal Server Error" - the
        sentence saying which value, and the command that shows it, were
        both in the error and neither reached the reader.
        """
        if not isinstance(error, KennisError):
            raise error
        if _from_htmx(request):
            return _refused(request, str(error), resolution=error.resolution)
        return _TEMPLATES.TemplateResponse(
            request,
            "problem.html",
            {"problem": str(error), "resolution": error.resolution},
            status_code=500,
        )

    # Mounted, not routed one file at a time. The guard above is
    # application middleware, so it runs for a mounted app too - which
    # is the case a per-route decorator would have missed, and the one
    # nobody would have thought to check.
    app.mount(
        "/static/vendor",
        StaticFiles(directory=str(_HERE / "static" / "vendor")),
        name="vendor",
    )

    @app.get("/static/kennis.css")
    def serve_stylesheet() -> PlainTextResponse:
        return PlainTextResponse(stylesheet(), media_type="text/css")

    @app.post("/quit")
    def quit_interface(request: Request) -> HTMLResponse:
        """Answer, then ask the launcher to stop.

        **Refused while a job runs.** The worker is a daemon thread, and
        ending the process ends it wherever it is - inside the corpus
        lock, or between writing a document and committing it.

        **The stop is a background task**, which Starlette runs only
        once the response has been sent. uvicorn would deliver the page
        either way - its shutdown waits for requests already in flight,
        and an injection that asked first was not caught for that
        reason - so this states the order rather than relying on a
        server's grace. What uvicorn will not do is answer the *next*
        request, so the page carries its stylesheet inline: a `<link>`
        would be fetched from a server that has gone.
        """
        if app.state.jobs.running() is not None:
            return _TEMPLATES.TemplateResponse(
                request,
                "problem.html",
                {"problem": words.QUIT_WHILE_RUNNING, "resolution": None},
                status_code=409,
            )
        return _TEMPLATES.TemplateResponse(
            request,
            "stopped.html",
            {"stopped": words.STOPPED, "stylesheet": stylesheet()},
            background=BackgroundTask(on_quit),
        )

    @app.get("/static/{name}.js")
    def serve_script(name: str) -> PlainTextResponse:
        # The interface's own scripts, as opposed to the vendored ones
        # under `/static/vendor`. `name` is matched against what is
        # actually there rather than joined into a path, so no request
        # can walk out of this directory.
        available = {path.stem: path for path in (_HERE / "static").glob("*.js")}
        found = available.get(name)
        if found is None:
            return PlainTextResponse("", status_code=404)
        return PlainTextResponse(
            found.read_text(encoding="utf-8"), media_type="text/javascript"
        )

    @app.get("/")
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
        return _TEMPLATES.TemplateResponse(request, "search.html", context)

    @app.post("/history/clear")
    def clear_history(request: Request) -> Response:
        # A POST, because a GET that writes is one a prefetcher will
        # follow and this one destroys. The reader's own words are
        # in here and there has to be a way to remove them.
        history.clear()
        if not _from_htmx(request):
            return RedirectResponse("/", status_code=303)
        context = _hits_context("", EVERY_SCOPE, words.MODE_DEFAULT)
        context["recents"] = []
        context["recents_heading"] = words.RECENTS_HEADING
        context["recents_clear"] = words.RECENTS_CLEAR
        return _TEMPLATES.TemplateResponse(request, "recents.html", context)

    @app.get("/hits")
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
        answer = _TEMPLATES.TemplateResponse(
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

    @app.get("/corpus")
    def serve_corpus(request: Request) -> HTMLResponse:
        context = existing_corpus()
        held = holdings(context)
        return _TEMPLATES.TemplateResponse(
            request,
            "corpus.html",
            {
                "rows": shown_rows(held),
                "empty": not any(holding.documents for holding in held),
                "packs": describe_holdings(installed_packs(context)),
                "nothing_held": words.NOTHING_HELD,
                "no_packs": words.NO_PACKS,
                **_frame(context),
            },
        )

    @app.get("/collection/{collection}")
    def serve_collection(request: Request, collection: str) -> HTMLResponse:
        context = existing_corpus()
        if collection not in COLLECTION_NAMES:
            return _problem(
                request, UnknownCollection(words.unknown_scope(collection, SCOPES))
            )
        groups, unreadable = shown_groups(context, collection)
        held = next(h for h in holdings(context) if h.collection == collection)
        return _TEMPLATES.TemplateResponse(
            request,
            "collection.html",
            {
                "collection": collection,
                "groups": groups,
                "summary": words.describe_count(held),
                "unreadable": words.unreadable_note(unreadable),
                **_frame(context),
            },
        )

    @app.get("/tree/{collection}")
    def serve_tree(request: Request, collection: str) -> HTMLResponse:
        """One collection's documents, or the bundle's, for the pane.

        Fetched when the reader opens it, never drawn with the page:
        every document costs about 0.7 ms to list, which on every page
        load would be most of a second at a thousand documents.
        """
        if collection == CONTEXT_COLLECTION:
            bundle = find_bundle()
            folders = [] if bundle is None else bundle_folders(bundle)
            return _TEMPLATES.TemplateResponse(
                request, "tree-context.html", {"folders": folders}
            )
        if collection not in COLLECTION_NAMES:
            return _refused(request, words.unknown_scope(collection, SCOPES))
        return _tree(request, collection)

    @app.post("/move")
    def move_from_the_tree(request: Request, form: PostedForm) -> Response:
        """Refile one document into the group typed in its menu.

        htmx gets the collection's branch redrawn, so the reader sees the
        document where it now is; a plain form returns to the collection's
        page. A refusal - a group that leaves the collection, a docs page,
        a busy corpus - is drawn at the head of the same branch.
        """
        collection = str(form.get("collection") or "")
        if collection not in COLLECTION_NAMES:
            return _refused_a_post(request, words.unknown_scope(collection, SCOPES))
        handle = str(form.get("document") or "")
        group = str(form.get("group") or "").strip()
        context = existing_corpus()
        held = Collection(root=context.corpus_root, name=collection)
        restored: list[OutOfBandChange] = []
        try:
            move_a_document(
                context, held, held.resolve(handle), group=group, restored=restored
            )
        except KennisError as error:
            if _from_htmx(request):
                return _tree(request, collection, problem=str(error))
            return _refused_a_post(request, str(error), resolution=error.resolution)
        if _from_htmx(request):
            notes = tuple(describe_change(change) for change in restored)
            return _written(_tree(request, collection, notes=notes))
        return RedirectResponse(f"/collection/{collection}", status_code=303)

    @app.get("/remember")
    def serve_remember_form(request: Request) -> HTMLResponse:
        return _action(
            request, "/remember", "forms/remember.html", _remember_context(None)
        )

    @app.get("/add")
    def serve_add_form(
        request: Request,
        kind: str = "",
        collection: str = "",
        group: str = "",
        project: str = "",
    ) -> HTMLResponse:
        # The place is filled in when the dialog is opened from the tree's
        # Add here; choosing the row was the reader choosing it (#431).
        given = {"collection": collection, "group": group, "project": project}
        return _action(request, "/add", "forms/add.html", _add_context(kind, given))

    @app.get("/add/block")
    def serve_add_block(request: Request, index: int = 1) -> HTMLResponse:
        """One more group, and the button that asks for the one after."""
        return _TEMPLATES.TemplateResponse(
            request,
            "forms/add-blocks.html",
            {"index": max(1, min(index, 999)), "collections": COLLECTION_NAMES},
        )

    # Plain `def`, not `async`: a preview may ask arXiv or probe a site,
    # and a blocking request inside an `async` route would stall every
    # other request until it answered. FastAPI runs these on a thread.
    @app.get("/add/preview/paper")
    def preview_a_paper(
        request: Request, identifiers: str = "", citekey: str = "", title: str = ""
    ) -> HTMLResponse:
        first = next(iter(_lines(identifiers)), "")
        papers = Collection(root=existing_corpus().corpus_root, name="literature")
        preview = preview_paper(
            papers, first, citekey=citekey.strip() or None, title=title.strip() or None
        )
        return _TEMPLATES.TemplateResponse(
            request, "forms/add-preview.html", {"lines": shown_paper_preview(preview)}
        )

    @app.get("/add/preview/site")
    def preview_a_site(
        request: Request, identifiers: str = "", project: str = "", probe: str = ""
    ) -> HTMLResponse:
        first = next(iter(_lines(identifiers)), "")
        probed = bool(probe) and bool(first)
        preview = preview_site(first, project=project.strip() or None, probe=probed)
        return _TEMPLATES.TemplateResponse(
            request,
            "forms/add-preview.html",
            {"lines": shown_site_preview(preview, probed=probed)},
        )

    @app.get("/add/check")
    def check_a_block(request: Request, index: int = 1) -> HTMLResponse:
        """Each line of one group, as its own tab would recognise it."""
        asked = request.query_params
        destination = asked.get(f"collection-{index}", "notes")
        if destination not in COLLECTION_NAMES:
            destination = "notes"
        target = Collection(root=existing_corpus().corpus_root, name=destination)
        checks = check_lines(target, _lines(asked.get(f"lines-{index}", "")))
        return _TEMPLATES.TemplateResponse(
            request, "forms/add-check.html", {"checks": shown_checks(checks)}
        )

    @app.get("/skip")
    def serve_skip(request: Request) -> HTMLResponse:
        """What Skip beside a refusal's repairs amounts to: nothing.

        No engine change and nothing written - the item was already
        refused and the rest of the add went on. A GET, because it
        changes nothing, and a page without a script so the button is
        never dead.
        """
        if _from_htmx(request):
            return _TEMPLATES.TemplateResponse(request, "skipped.html", {})
        return _TEMPLATES.TemplateResponse(
            request, "skipped-page.html", _frame(existing_corpus())
        )

    @app.get("/browse")
    def serve_chooser(
        request: Request, target: str = "", path: str = "", folders: str = ""
    ) -> HTMLResponse:
        """One folder of this computer, for a field to take a path from.

        Read-only and names only, under the same token as every route.
        Without a script it is a page of paths to copy, because nothing
        else can put one into a form.
        """
        chosen = chooser_target(target)
        if chosen is None:
            return HTMLResponse(words.NOT_A_FIELD, status_code=400)
        wants_folders = bool(folders)
        context = {
            "target": chosen,
            "folders": wants_folders,
            "listing": listing_of(path, target=chosen, folders=wants_folders),
        }
        if _from_htmx(request):
            return _TEMPLATES.TemplateResponse(request, "chooser.html", context)
        return _TEMPLATES.TemplateResponse(
            request,
            "chooser-page.html",
            {**context, "page": True, **_frame(existing_corpus())},
        )

    @app.get("/index")
    def serve_index_form(request: Request, collection: str = "") -> HTMLResponse:
        # A collection in the address is checked, as the palette's
        # "Index notes" asks; anything else leaves every collection.
        return _action(
            request,
            "/index",
            "forms/index.html",
            {
                "collections": COLLECTION_NAMES,
                "chosen": collection if collection in COLLECTION_NAMES else "",
                "index_preamble": words.INDEX_PREAMBLE,
                "index_action": words.INDEX_ACTION,
            },
        )

    @app.get("/palette")
    def serve_palette(request: Request) -> HTMLResponse:
        """Every action and place, as one list to type into (11g)."""
        return _action(
            request,
            "/palette",
            "forms/palette.html",
            {
                "entries": palette_entries(),
                "palette_prompt": words.PALETTE_PROMPT,
                "palette_empty": words.PALETTE_EMPTY,
                "palette_keys": words.PALETTE_KEYS,
            },
        )

    @app.get("/settings")
    def serve_settings(request: Request) -> HTMLResponse:
        """The settings page: this window's preferences (12a) and
        kennis's own configuration (12b)."""
        return _settings_page(request, _kennis_section({}))

    @app.get("/settings/kennis")
    def redraw_kennis_settings(request: Request) -> HTMLResponse:
        """The configuration section for the values in the address.

        What a changed choice asks, so the rows that apply are the
        engine's answer for what the form holds rather than for what
        is saved. Nothing is written.
        """
        section = _kennis_section(answers_in(request.query_params))
        if _from_htmx(request):
            return _TEMPLATES.TemplateResponse(request, "settings-kennis.html", section)
        return _settings_page(request, section)

    @app.post("/settings/kennis")
    def save_kennis_settings(request: Request, form: PostedForm) -> HTMLResponse:
        """Check every changed answer, and write them together or not at all.

        Each refusal is drawn beside its field, which is why the answers
        are checked one at a time before `apply_answers` checks them as a
        set: the page should say which value, not only that one was wrong.
        """
        answers = answers_in(form)
        problems = {
            question.key: problem
            for question in offered(answers)
            if (problem := validate_answer(question, answers.get(question.key, "")))
        }
        changed = {} if problems else changed_answers(answers)
        previous: dict[str, str] = {}
        if not problems:
            previous = {
                question.key: question.current
                for question in offered({})
                if question.key in changed and question.kind != "secret"
            }
            # Written even when nothing changed: saving is choosing what the
            # page shows, and the file holds every setting (Brian,
            # 2026-10-12).
            try:
                apply_answers(changed)
            except SettingsError as error:
                problems = {"": str(error)}
        if problems:
            section = _kennis_section(
                answers,
                problems=problems,
                outcome=problems.get("", words.KENNIS_NOT_SAVED),
                outcome_is_problem=True,
            )
        elif changed:
            section = _kennis_section(
                {},
                outcome=words.KENNIS_SAVED,
                rebuild=needs_rebuild(changed),
                previous=previous,
            )
        else:
            section = _kennis_section({}, outcome=words.KENNIS_UNCHANGED)
        if _from_htmx(request):
            return _TEMPLATES.TemplateResponse(request, "settings-kennis.html", section)
        return _settings_page(request, section)

    @app.post("/settings")
    def save_settings(request: Request, form: PostedForm) -> Response:
        """Where the form posts without a script; with one, `prefs.js`
        has already written each cookie as it was chosen."""
        answer = RedirectResponse("/settings", status_code=303)
        for name, value in chosen_in(form).items():
            answer.set_cookie(
                name,
                value,
                max_age=COOKIE_SECONDS,
                path="/",
                samesite="strict",
            )
        return answer

    @app.get("/settings/backup")
    def serve_backup_section(request: Request) -> HTMLResponse:
        """The Backup section as it stands, for a finished job to redraw."""
        return _backup_answer(request, _backup_section())

    @app.post("/settings/backup")
    def save_backup_folder(request: Request, form: PostedForm) -> HTMLResponse:
        """The folder, written through `apply_answers` like any setting.

        Refused when it is not a folder, because the chooser lists files
        too and a file would only be found out at the next backup.
        """
        given = str(form.get("backup.folder") or "").strip()
        if not given:
            return _backup_answer(
                request, _backup_section(about="folder", outcome=words.KENNIS_UNCHANGED)
            )
        folder = Path(given).expanduser()
        if not folder.is_dir():
            return _backup_answer(
                request,
                _backup_section(
                    about="folder", problem=words.not_a_backup_folder(given)
                ),
            )
        try:
            apply_answers({"backup.folder": str(folder)})
        except SettingsError as error:
            return _backup_answer(
                request, _backup_section(about="folder", problem=str(error))
            )
        return _backup_answer(
            request, _backup_section(about="folder", outcome=words.KENNIS_SAVED)
        )

    @app.post("/settings/backup/test")
    def test_backup(request: Request, form: PostedForm) -> HTMLResponse:
        """Every member decrypted against its checksum, with this password."""
        password = str(form.get("password") or "")
        folder = _backup_folder()
        if folder is None:
            return _backup_answer(
                request, _backup_section(about="test", problem=NO_BACKUP_FOLDER)
            )
        if not password:
            return _backup_answer(
                request, _backup_section(about="test", problem=words.PASSWORD_NEEDED)
            )
        verified = check_backup(folder, password).verified
        if verified is None:
            return _backup_answer(
                request,
                _backup_section(
                    about="test", problem=describe_archive(check_backup(folder))
                ),
            )
        if verified:
            return _backup_answer(
                request, _backup_section(about="test", outcome=describe_verified(True))
            )
        return _backup_answer(
            request, _backup_section(about="test", problem=describe_verified(False))
        )

    @app.post("/backup")
    def start_backup(request: Request, form: PostedForm) -> Response:
        """Back up now: a job, so it is in the strip and refused while
        another runs. The password reaches the job as an argument only."""
        password = str(form.get("password") or "")
        confirmation = str(form.get("confirmation") or "")
        folder = _backup_folder()
        if folder is None:
            return _refused_a_post(
                request, NO_BACKUP_FOLDER, resolution=SET_FOLDER_COMMAND
            )
        if not password:
            return _refused_a_post(request, words.PASSWORD_NEEDED)
        if password != confirmation:
            return _refused_a_post(request, words.PASSWORDS_DIFFER)
        context = existing_corpus()
        return _started(
            request,
            "backup",
            lambda events: back_up_corpus(context, folder, password, events=events),
        )

    @app.get("/sync")
    def serve_sync_form(request: Request) -> HTMLResponse:
        return _action(
            request,
            "/sync",
            "forms/sync.html",
            {
                "sync_preamble": words.SYNC_PREAMBLE,
                "sync_corpus_action": words.SYNC_CORPUS_ACTION,
                "sync_context_action": words.SYNC_CONTEXT_ACTION,
            },
        )

    @app.get("/pack")
    def serve_pack_form(request: Request) -> HTMLResponse:
        return _action(
            request,
            "/pack",
            "forms/pack.html",
            {"pack_preamble": words.PACK_PREAMBLE, "pack_action": words.PACK_ACTION},
        )

    @app.post("/remember")
    def accept_remembered(request: Request, form: PostedForm) -> HTMLResponse:
        """Write a note, and answer with the outcome alone.

        **POST, not GET.** A GET that writes is a GET something will
        follow - a prefetcher, a link checker, a restored history
        entry - and each of those would write a note nobody asked
        for.

        Cross-site protection is the guard's: the token cookie's
        `samesite=strict` keeps it from other sites, and `from_elsewhere`
        refuses a POST from another page on loopback, which the browser
        counts as the same site.
        """
        text_given = str(form.get("text") or "")
        title = str(form.get("title") or "") or None
        group = str(form.get("group") or "") or None
        to_context = str(form.get("target") or "notes") == "context"
        outcome = _remembered(
            text_given, title=title, group=group, to_context=to_context
        )
        if not _from_htmx(request):
            return _action(
                request, "/remember", "forms/remember.html", _remember_context(outcome)
            )
        return _written(
            _TEMPLATES.TemplateResponse(request, "outcome.html", {"outcome": outcome})
        )

    @app.get("/strip/status")
    def serve_strip_status(request: Request) -> HTMLResponse:
        """The strip's status line alone, for a finished job (#457)."""
        return _TEMPLATES.TemplateResponse(request, "strip-status.html", {})

    @app.get("/pane/documents")
    def serve_pane_documents(request: Request) -> HTMLResponse:
        """The pane's document count alone, for a finished job (#457)."""
        return _TEMPLATES.TemplateResponse(
            request, "pane-documents.html", {"pane": pane_now()}
        )

    @app.get("/pane/row/{collection}")
    def serve_pane_row(request: Request, collection: str) -> HTMLResponse:
        """One collection's row in the pane, for a finished job (#457)."""
        rows = {row.collection: row for row in pane_now().collections}
        if collection not in rows:
            return HTMLResponse("", status_code=404)
        return _TEMPLATES.TemplateResponse(
            request, "pane-row.html", {"row": rows[collection]}
        )

    @app.get("/revision")
    def serve_revision() -> JSONResponse:
        # Answered on demand, never pushed. One `git rev-parse`, which
        # is cheap enough to ask when a window regains focus and far
        # too expensive to poll. Concern #311.
        return JSONResponse({"revision": revision(existing_corpus())})

    @app.get("/document/{collection}/{document_id}")
    def serve_document(
        request: Request,
        collection: str,
        document_id: str,
        images: str = "",
        chunk: str = "",
        q: str = "",
    ) -> HTMLResponse:
        load_remote = images == "on"
        context = existing_corpus()
        marked, withheld = _marked(context, collection, document_id, chunk)
        try:
            document = shown_document(
                context.corpus_root,
                collection,
                document_id,
                load_remote_images=load_remote,
                marked=marked,
                marks=document_marks(context, collection),
                question=q,
            )
        except KennisError as error:
            return _problem(request, error)
        freshness = (
            freshness_of(context, Repository(context.corpus_root), collection)
            if q
            else None
        )
        return _TEMPLATES.TemplateResponse(
            request,
            "document.html",
            _document_context(
                document,
                question=q,
                load_remote=load_remote,
                withheld=withheld,
                placeable=None if freshness is None else freshness.state == "in step",
                chunks=lambda: document_chunks(
                    context, collection, document.document_id
                ),
            ),
        )

    def _started(
        request: Request,
        kind: str,
        work: Callable[[EventSink], JobReport],
        *,
        restored: list[OutOfBandChange] | None = None,
    ) -> Response:
        """Hand the work to a thread and answer with the panel watching it.

        A second operation is refused rather than queued, and says so:
        the corpus lock would refuse it anyway with `timeout=0`, so the
        limit is honest, and dropping a click in silence is not.
        """
        try:
            job = app.state.jobs.start(kind, work, restored=restored)
        except AlreadyRunning as busy:
            if not _from_htmx(request):
                return RedirectResponse(f"/job/{busy.running}", status_code=303)
            return _TEMPLATES.TemplateResponse(
                request,
                "job.html",
                {
                    "job_id": busy.running,
                    "kind": kind,
                    "problem": words.BUSY_WITH_ANOTHER,
                },
            )
        if not _from_htmx(request):
            # 303: the answer to a POST that tells the browser to GET,
            # so a reload shows the job rather than starting it again
            # (#412).
            return RedirectResponse(f"/job/{job.id}", status_code=303)
        return _TEMPLATES.TemplateResponse(
            request, "job.html", {"job_id": job.id, "kind": job.kind}
        )

    @app.get("/bundle/{relative_path:path}")
    def serve_bundle_document(
        request: Request,
        relative_path: str,
        images: str = "",
        chunk: str = "",
        q: str = "",
    ) -> HTMLResponse:
        """One note out of this project's bundle.

        A separate route from `/document/...` because it reads a
        separate store: the bundle is in the user's repository and is
        not a collection of the corpus. Linking a context hit into
        the corpus route is what answered a quarter of all searches
        with "unknown collection". Concern #332.
        """
        bundle = find_bundle()
        if bundle is None:
            return _problem(request, ContextNotFound())
        marked, withheld = _marked_in_bundle(bundle, relative_path, chunk)
        load_remote = images == "on"
        try:
            document = shown_bundle_document(
                bundle,
                relative_path,
                load_remote_images=load_remote,
                marked=marked,
                question=q,
            )
        except KennisError as error:
            return _problem(request, error)
        freshness = bundle_freshness(bundle) if q else None
        return _TEMPLATES.TemplateResponse(
            request,
            "document.html",
            _document_context(
                document,
                question=q,
                load_remote=load_remote,
                withheld=withheld,
                placeable=None if freshness is None else freshness.state == "in step",
                chunks=lambda: document_chunks(
                    resolve_context(), CONTEXT_COLLECTION, relative_path
                ),
            ),
        )

    @app.post("/add")
    def start_add(request: Request, form: PostedForm) -> Response:
        """Start an add and answer with somewhere to watch it.

        Answers at once rather than when the work is done: one PDF is
        twenty seconds of MinerU and a documentation crawl is minutes,
        and a POST that returns at the end is a browser that appears to
        have hung.
        """
        context = existing_corpus()
        options = _add_options(context, form)
        if isinstance(options, str):
            return _refused_a_post(request, options)
        if form.get("kind") == "group":
            blocks = _group_blocks(form)
            if isinstance(blocks, str):
                return _refused_a_post(request, blocks)
            if not blocks:
                return _refused_a_post(request, words.NOTHING_TO_ADD)
            restored: list[OutOfBandChange] = []
            return _started(
                request,
                "add",
                lambda events: add_in_groups(
                    context, blocks, options, events=events, restored=restored
                ),
                restored=restored,
            )
        identifiers = _lines(str(form.get("identifiers") or ""))
        destination = str(form.get("collection") or "")
        if not identifiers:
            return _refused_a_post(request, words.NOTHING_TO_ADD)
        if not destination:
            return _refused_a_post(request, words.CHOOSE_A_COLLECTION)
        if destination not in COLLECTION_NAMES:
            return _refused_a_post(request, words.unknown_collection(destination))
        put_back: list[OutOfBandChange] = []
        return _started(
            request,
            "add",
            lambda events: add_documents(
                context,
                destination,
                identifiers,
                options,
                events=events,
                restored=put_back,
            ),
            restored=put_back,
        )

    @app.post("/index")
    def start_index(request: Request, form: PostedForm) -> Response:
        chosen = str(form.get("collection") or "")
        collection = chosen if chosen in COLLECTION_NAMES else None
        context = existing_corpus()
        restored: list[OutOfBandChange] = []
        return _started(
            request,
            "index",
            lambda events: build_indexes(
                context, collection, events=events, restored=restored
            ),
            restored=restored,
        )

    @app.post("/sync")
    def start_corpus_sync(request: Request) -> Response:
        context = existing_corpus()
        restored: list[OutOfBandChange] = []
        return _started(
            request,
            "sync",
            lambda events: synchronise_corpus(
                context, events=events, restored=restored
            ),
            restored=restored,
        )

    @app.post("/context-sync")
    def start_bundle_sync(request: Request) -> Response:
        context = existing_corpus()
        bundle = find_bundle()
        if bundle is None:
            # `ContextNotFound` carries the command that makes one,
            # which is the whole point of the errors carrying their
            # own resolution: the advice was chosen where the problem
            # is known.
            refusal = ContextNotFound()
            return _refused_a_post(request, str(refusal), resolution=refusal.resolution)
        return _started(
            request,
            "context-sync",
            lambda events: synchronise_bundle(bundle, context, events=events),
        )

    @app.post("/pack")
    def start_pack_install(request: Request, form: PostedForm) -> Response:
        given = str(form.get("path") or "").strip()
        path = Path(given).expanduser()
        if not given or not path.is_file():
            return _refused_a_post(request, words.no_such_pack(given))
        context = existing_corpus()
        return _started(
            request, "pack", lambda events: install_a_pack(context, path, events=events)
        )

    @app.get("/job/{job_id}")
    def serve_job(request: Request, job_id: str) -> HTMLResponse:
        """One job: its panel for htmx, the panel inside the shell otherwise.

        The page is where a scriptless POST is sent (#412), where the
        strip's last-job link and the Activity page lead, and a reload
        of it watches the same job rather than starting another.
        """
        job = app.state.jobs.get(job_id)
        if job is None:
            return _refused_a_post(request, words.NO_SUCH_JOB)
        shown = {"job_id": job.id, "kind": job.kind}
        if _from_htmx(request):
            return _TEMPLATES.TemplateResponse(request, "job.html", shown)
        return _TEMPLATES.TemplateResponse(
            request,
            "job-page.html",
            {**shown, "title": words.JOB_KINDS.get(job.kind, job.kind)},
        )

    @app.get("/activity")
    def serve_activity(request: Request) -> HTMLResponse:
        """What has run since kennis started, newest first.

        The registry keeps a job for an hour; this lists what it has,
        and says so when that is nothing.
        """
        return _TEMPLATES.TemplateResponse(
            request,
            "activity.html",
            {
                "rows": [_activity_row(job) for job in app.state.jobs.recent()],
                "nothing_run": words.NOTHING_RUN,
            },
        )

    @app.get("/job/{job_id}/events")
    def serve_job_events(job_id: str) -> StreamingResponse:
        """This job's events, pushed until the operation ends.

        A sync generator on purpose: Starlette runs one in a thread, so
        the blocking `queue.get` inside it never touches the event
        loop, and the alternative is bridging a thread-safe queue into
        asyncio for no gain.
        """
        jobs: Jobs = app.state.jobs
        job = jobs.get(job_id)
        if job is None:
            return StreamingResponse(
                iter([sent_event({"kind": "closed", "text": words.NO_SUCH_JOB})]),
                media_type="text/event-stream",
            )
        return StreamingResponse(
            as_stream(iter(jobs.stream(job)), {"kind": "closed"}),
            media_type="text/event-stream",
            # Without this a proxy or a browser may hold the response
            # until it is complete, which is the one thing a progress
            # stream must not allow.
            headers={"cache-control": "no-store", "x-accel-buffering": "no"},
        )

    @app.get("/job/{job_id}/outcome")
    def serve_job_outcome(request: Request, job_id: str) -> HTMLResponse:
        """What the job amounted to, fetched once its stream has closed.

        Rendered here rather than assembled by the script, so every
        word on the page was chosen in Python - including the repair
        forms, which are built from 9e's typed refusals.
        """
        job = app.state.jobs.get(job_id)
        if job is None:
            return _refused(request, words.NO_SUCH_JOB)
        if not job.done.is_set():
            return _refused(request, words.STILL_RUNNING)
        if job.crash is not None:
            answer = _refused(request, words.job_crashed(job.crash))
        elif job.error is not None:
            answer = _refused(
                request,
                words.CORPUS_BUSY_RETRY
                if isinstance(job.error, CorpusBusy)
                else str(job.error),
                resolution=job.error.resolution,
            )
        else:
            shown = _shown_result(job)
            # What the operation put back before it ran, said where it
            # says what it did: the command line has always said it, and
            # a document reappearing in silence is a surprise of its own.
            put_back = tuple(describe_change(change) for change in job.restored)
            answer = _TEMPLATES.TemplateResponse(
                request,
                "job-outcome.html",
                {"shown": replace(shown, notes=(*put_back, *shown.notes))},
            )
        # Only a job that commits moves the page's revision: a bundle sync,
        # a pack install and a backup write no corpus history, so a terminal
        # that wrote meanwhile is still news. One that does commit takes the
        # corpus as it stands when the outcome is fetched, which a terminal
        # writing in that same moment would share - a window of the length of
        # one request, against a banner that was wrong after every add.
        return _written(answer) if job.kind in _COMMITTING_JOBS else answer

    return app


def _remember_context(outcome: ShownOutcome | None) -> dict[str, object]:
    """What the writing page needs, with or without an answer yet."""
    return {
        "outcome": outcome,
        "preamble": words.REMEMBER_PREAMBLE,
        "placeholder": words.REMEMBER_PLACEHOLDER,
        "title_hint": words.TITLE_HINT,
        "group_hint": words.GROUP_HINT,
        "action": words.REMEMBER_ACTION,
        **_frame(existing_corpus()),
    }


def _remembered(
    text: str, *, title: str | None, group: str | None, to_context: bool
) -> ShownOutcome:
    """Write, and turn whatever happened into something to show.

    Every domain failure becomes an outcome rather than a page: the
    text the person typed is still in the box, and replacing the page
    would lose it. `CorpusBusy` is the case that makes this matter -
    a `corpus index` running in a terminal refuses this write, and it
    is worth retrying rather than worth an error page.
    """
    if not text.strip():
        return ShownOutcome(message=words.NOTHING_TO_REMEMBER, role="role-warning")
    try:
        if to_context:
            note, bundle_name = write_context_note(text, title=title, group=group)
            return words.describe_written_to_bundle(note, bundle_name)
        restored: list[OutOfBandChange] = []
        report = write_note(text, title=title, group=group, restored=restored)
        written = words.describe_written(
            report, relative_to_corpus(report.path, existing_corpus().corpus_root)
        )
        return replace(
            written, notes=tuple(describe_change(change) for change in restored)
        )
    except CorpusBusy:
        return ShownOutcome(message=words.CORPUS_BUSY, role="role-warning")
    except KennisError as error:
        return ShownOutcome(
            message=str(error), role="role-error", resolution=error.resolution
        )


def _document_context(
    document: ShownDocument,
    *,
    question: str,
    load_remote: bool,
    withheld: bool,
    placeable: bool | None,
    chunks: Callable[[], list[Chunk]],
) -> dict[str, object]:
    """What a document page needs, from either store.

    `placeable` is whether the index is in step with the document: None
    when there is no index or nothing was searched, and then there are
    no matches to list. A changed document lists none and says why, by
    the rule that withholds the mark, because its chunks address text
    that has moved. `chunks` is called only when they will be read.
    """
    matches = (
        shown_matches(
            chunks(),
            question=question,
            collection=document.collection,
            document_id=document.document_id,
        )
        if question and placeable
        else ()
    )
    return {
        "document": document,
        "load_remote_images": load_remote,
        "blocked_note": words.IMAGES_BLOCKED,
        "blocked_action": words.LOAD_IMAGES,
        "mark_withheld": words.MARK_WITHHELD if withheld else None,
        "question": question,
        "search_crumb": words.search_crumb(question) if question else None,
        "matches": matches,
        "matches_withheld": bool(question) and placeable is False,
        "matches_heading": words.matches_heading(question) if question else None,
        "matches_withheld_note": words.MATCHES_WITHHELD,
        "inspector_label": words.INSPECTOR_LABEL,
        "crumbs_label": words.CRUMBS_LABEL,
        "inspector_show": words.INSPECTOR_SHOW,
        "inspector_hide": words.INSPECTOR_HIDE,
        "details_heading": words.DETAILS_HEADING,
        "outline_heading": words.OUTLINE_HEADING,
        "no_headings": words.NO_HEADINGS,
        "no_matches": words.NO_MATCHES,
    }


def _marked(
    context: Context, collection: str, document_id: str, chunk: str
) -> tuple[MarkedRange | None, bool]:
    """The passage to mark, and whether one was withheld.

    Two `None`s that mean different things, which is why the second
    value exists. *No chunk was asked for* - the reader opened the
    document from a listing - should say nothing. *A chunk was asked
    for and cannot be placed* has to say so, because the reader
    followed a link to a passage and would otherwise be left looking
    for it.

    **The offsets belong to the index, so a stale index withholds
    them.** They address the document as it was when it was indexed,
    and once it has changed they point at text that has moved. A mark
    on the wrong paragraph is worse than no mark: it is a confident
    claim, and the reader has no way to tell it is wrong.
    `unverifiable` withholds too - "kennis cannot check" is not
    "kennis checked and it is fine".
    """
    if not chunk:
        return None, False
    try:
        index = int(chunk)
    except ValueError:
        # Arrived in a query string, so it can be anything. Not an
        # error page: the document is there and is what was asked for.
        return None, False

    freshness = freshness_of(context, Repository(context.corpus_root), collection)
    if freshness is None:
        # No index at all, so there is nothing to place the passage
        # against and nothing was withheld. `chunk_range` would answer
        # None a moment later; asking first keeps it off the disk.
        return None, False
    if freshness.state != "in step":
        return None, True

    found = chunk_range(context, collection, document_id, index)
    if found is None:
        return None, False
    start, end = found
    return MarkedRange(start=start, end=end, anchor=f"chunk-{index}"), False


def _marked_in_bundle(
    bundle: Path, relative_path: str, chunk: str
) -> tuple[MarkedRange | None, bool]:
    """`_marked`, for the scope that is not in the corpus.

    The same three decisions and the same order, over a different
    index and a different freshness: `bundle_freshness` answers the
    question `freshness_of` answers for a collection, and cannot be
    the same function because a bundle has no git history to compare
    against. Written out rather than abstracted over the two, because
    the two only look alike - the shared part is three lines and the
    differing part is every value in them.
    """
    if not chunk:
        return None, False
    try:
        index = int(chunk)
    except ValueError:
        return None, False

    freshness = bundle_freshness(bundle)
    if freshness is None:
        return None, False
    if freshness.state != "in step":
        return None, True

    found = chunk_range(resolve_context(), CONTEXT_COLLECTION, relative_path, index)
    if found is None:
        return None, False
    start, end = found
    return MarkedRange(start=start, end=end, anchor=f"chunk-{index}"), False


def _settings_page(
    request: Request,
    kennis: dict[str, object],
    backup: dict[str, object] | None = None,
) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(
        request,
        "settings.html",
        {
            "chosen": preferences_of(request),
            "sections": (
                ("appearance", words.APPEARANCE_HEADING),
                ("results", words.RESULTS_HEADING),
            ),
            "preference_list": list(PREFERENCES.values()),
            "window_heading": words.WINDOW_SETTINGS_HEADING,
            "window_note": words.WINDOW_SETTINGS_NOTE,
            "save_label": words.SAVE,
            **kennis,
            **(backup if backup is not None else _backup_section()),
            **_frame(existing_corpus()),
        },
    )


def _kennis_section(
    answers: Mapping[str, str],
    *,
    problems: Mapping[str, str] | None = None,
    outcome: str = "",
    outcome_is_problem: bool = False,
    rebuild: bool = False,
    previous: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """What the configuration section draws, for a page or for htmx."""
    return {
        "kennis_settings": shown_settings(answers, problems),
        "kennis_heading": words.KENNIS_SETTINGS_HEADING,
        "kennis_note": words.KENNIS_SETTINGS_NOTE,
        "kennis_save": words.KENNIS_SAVE,
        "kennis_groups": words.KENNIS_GROUPS,
        "outcome": outcome,
        "outcome_is_problem": outcome_is_problem,
        "rebuild": rebuild,
        "indexes": shown_indexes(existing_corpus().corpus_root) if rebuild else [],
        "previous": dict(previous or {}),
        "rebuild_heading": words.REBUILD_HEADING,
        "rebuild_note": words.REBUILD_NOTE,
        "rebuild_none": words.REBUILD_NONE,
        "rebuild_now": words.REBUILD_NOW,
        "rebuild_later": words.REBUILD_LATER,
        "undo_label": words.UNDO,
        "credential_keep": words.CREDENTIAL_KEEP,
        "credential_set": words.CREDENTIAL_SET,
        "credential_unset": words.CREDENTIAL_UNSET,
        "converter_missing": words.CONVERTER_MISSING,
    }


def _backup_folder() -> Path | None:
    configured = load_settings().backup.folder
    return Path(configured).expanduser() if configured else None


def _backup_section(
    *, outcome: str = "", problem: str = "", about: str = ""
) -> dict[str, object]:
    """What the Backup section draws: 13a's check, in 13a's words.

    `about` names the form an outcome answers, `folder` or `test`, so it
    is drawn under the control that produced it rather than at the head
    of the section.
    """
    folder = _backup_folder()
    checked = check_backup(folder) if folder is not None else None
    archive = checked.archive if checked is not None else None
    return {
        "backup_heading": words.BACKUP_HEADING,
        "backup_contents": BACKUP_CONTENTS,
        "backup_outcome": outcome,
        "backup_problem": problem,
        "backup_about": about,
        "backup_folder_label": words.BACKUP_FOLDER_LABEL,
        "backup_folder": str(folder) if folder is not None else "",
        "backup_save_folder": words.BACKUP_SAVE_FOLDER,
        "backup_folder_state": (
            describe_folder(checked) if checked is not None else NO_BACKUP_FOLDER
        ),
        "backup_archive_state": describe_archive(checked)
        if checked is not None
        else "",
        "backup_now_label": words.BACKUP_NOW,
        "backup_now_note": words.BACKUP_NOW_NOTE,
        "backup_password": words.BACKUP_PASSWORD,
        "backup_confirmation": words.BACKUP_CONFIRMATION,
        "backup_test_label": words.BACKUP_TEST,
        "backup_test_note": words.BACKUP_TEST_NOTE,
        "restore_label": words.BACKUP_RESTORE_LABEL,
        "backup_restore_note": words.BACKUP_RESTORE_NOTE,
        "restore_command": (
            f"kennis backup restore {shlex.quote(str(archive))}"
            if archive is not None
            else "kennis backup restore <file>"
        ),
    }


def _backup_answer(request: Request, section: dict[str, object]) -> HTMLResponse:
    if _from_htmx(request):
        return _TEMPLATES.TemplateResponse(request, "settings-backup.html", section)
    return _settings_page(request, _kennis_section({}), section)


# The jobs whose work ends in a corpus commit, by `_started`'s kind.
_COMMITTING_JOBS: Final = frozenset({"add", "index", "sync"})

# The header a response to this window's own write carries: the commit the
# corpus is at once the write is done.
REVISION_HEADER: Final = "X-Kennis-Revision"


def _written[Answer: Response](answer: Answer) -> Answer:
    """`answer`, saying which commit this window's own write left.

    The banner that says something *else* changed the corpus compares the
    revision on focus with the one the page last knew. Fixed at page load,
    it took the window's own add, note or move for someone else's, because
    none of those reloads the page. `revision.js` moves the page's revision
    to this header's value, on the responses to writes and to nothing else -
    a search answering it would hide a terminal's write behind a keystroke.
    """
    answer.headers[REVISION_HEADER] = revision(existing_corpus()) or ""
    return answer


def _frame(context: Context) -> dict[str, object]:
    """What every page carries regardless of what it shows.

    The revision is the page's own timestamp, in the only unit that
    matters here: a commit the corpus was at when this was drawn. The
    message travels with it so the script does not compose words.
    """
    return {
        "revision": revision(context) or "",
        "corpus_changed": words.CORPUS_CHANGED,
    }


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
        **_frame(existing_corpus()),
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
        "fallbacks": [],
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
        context["fallbacks"] = [
            describe_lexical_fallback(name) for name in found.degraded
        ]
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


def _problem(request: Request, error: KennisError) -> HTMLResponse:
    """A domain failure as a page.

    Design section 20: the engine raises, and each front end turns it
    into what that front end has - an exit code, a tool error, or this.
    """
    return _TEMPLATES.TemplateResponse(
        request,
        "problem.html",
        {"problem": str(error), "resolution": error.resolution},
        status_code=404,
    )


__all__ = ["COOKIE_NAME", "build_app", "cookie_name", "from_elsewhere", "new_token"]


def _lines(given: str) -> list[str]:
    """One identifier per line, blank lines ignored.

    A textarea rather than a single field because a batch is the
    ordinary case - a folder of papers arrives as a list - and because
    a space-separated field cannot hold a path with a space in it.
    """
    return [line.strip() for line in given.splitlines() if line.strip()]


def _add_context(
    asked: str, given: Mapping[str, str] | None = None
) -> dict[str, object]:
    """One tab of the Add dialog, with any place it was opened on filled in."""
    kind = add_kind(asked)
    return {
        "kind": kind,
        "tabs": add_tabs(kind),
        "preamble": words.ADD_PREAMBLES[kind],
        "fields": filled(
            add_fields(
                kind, default_group=existing_corpus().settings.corpus.default_group
            ),
            given or {},
        ),
        "fixed_collection": FIXED_COLLECTIONS.get(kind),
        "collections": COLLECTION_NAMES,
        "first_blocks": FIRST_BLOCKS,
        "add_action": words.ADD_ACTIONS[kind],
        "adds_to": words.ADDS_TO,
        "cancel": words.CANCEL,
        "destination": destination_of(kind, given or {}),
    }


def _group_blocks(form: FormData) -> list[GroupBlock] | str:
    """The Several by group tab's blocks that have lines, or why not.

    A block with no lines is skipped - two are drawn whether or not both
    are wanted - and a block with lines and no name is refused, because
    the name is the point of the tab.
    """
    numbers = sorted(
        int(key.removeprefix("lines-"))
        for key in form
        if key.startswith("lines-") and key.removeprefix("lines-").isdigit()
    )
    blocks: list[GroupBlock] = []
    for number in numbers:
        identifiers = _lines(str(form.get(f"lines-{number}") or ""))
        if not identifiers:
            continue
        name = str(form.get(f"group-{number}") or "").strip()
        if not name:
            return words.GROUP_NEEDS_A_NAME
        destination = str(form.get(f"collection-{number}") or "")
        if not destination:
            return words.CHOOSE_A_COLLECTION
        if destination not in COLLECTION_NAMES:
            return words.unknown_collection(destination)
        blocks.append(
            GroupBlock(
                collection=destination, group=name, identifiers=tuple(identifiers)
            )
        )
    return blocks


def _count(form: FormData, name: str, default: int) -> int | str:
    """A whole-number field, its default when empty, or why not."""
    given = str(form.get(name) or "").strip()
    if not given:
        return default
    if not given.isdigit() or int(given) < 1:
        return words.not_a_count(words.FIELD_LABELS[name], given)
    return int(given)


def _add_options(context: Context, form: FormData) -> AddOptions | str:
    """The engine's options, from the form and the settings behind it,
    or the sentence refusing a field that cannot be one.

    The settings supply what the form does not ask: a default group, a
    conversion batch size and the politeness delay are configuration
    rather than per-add decisions, and putting them on the page would
    invite changing them per add.
    """
    defaults = AddOptions()
    max_pages = _count(form, "max_pages", defaults.max_pages)
    if isinstance(max_pages, str):
        return max_pages
    max_depth = _count(form, "max_depth", defaults.max_depth)
    if isinstance(max_depth, str):
        return max_depth
    identifier = str(form.get("identifier") or "") or None
    return AddOptions(
        max_pages=max_pages,
        max_depth=max_depth,
        title=str(form.get("title") or "") or None,
        group=str(form.get("group") or "")
        or context.settings.corpus.default_group
        or None,
        keep_original=context.settings.corpus.keep_original,
        identifier=identifier,
        citekey=str(form.get("citekey") or "") or None,
        project=str(form.get("project") or "") or None,
        batch_size=context.settings.conversion.batch_size,
        request_delay_seconds=context.settings.literature.request_delay,
        extra_file_types=(),
    )


# What a job started from this window returns. `_started` takes only work
# returning one of these, so mypy refuses a job whose report has no page, and
# `_shown_result` matches them exhaustively, so mypy refuses a report added
# here without one - the rule `render/refusals.py` keeps for refusals.
JobReport = (
    AddReport | IndexBuild | CorpusSync | BundleSync | PackInstall | BackupReport
)


def _shown_result(job: Job) -> ShownJob:
    """One finished job as the shape a page lays out.

    The `match` is on the report's type rather than on `job.kind`,
    because the type is what decides which renderer is correct and a
    string that disagreed with it would be a wrong page rather than an
    error.
    """
    report = job.result
    if not isinstance(report, JobReport):
        # A job started without `_started` - nothing in the window does.
        return ShownJob(headline=words.NOTHING_TO_SHOW, role="role-muted")
    match report:
        case AddReport():
            return shown_add(report)
        case IndexBuild():
            return shown_index(report)
        case CorpusSync():
            return shown_corpus_sync(report)
        case BundleSync():
            return shown_bundle_sync(report)
        case PackInstall():
            return shown_install(report)
        case BackupReport():
            return shown_backup(report)
        case _:
            assert_never(report)


def _tree(
    request: Request,
    collection: str,
    *,
    problem: str | None = None,
    notes: tuple[str, ...] = (),
) -> HTMLResponse:
    """One collection's branch of the pane, with a refusal at its head, or
    what a move from it put back."""
    return _TEMPLATES.TemplateResponse(
        request,
        "tree.html",
        {
            "tree": shown_tree(existing_corpus(), collection),
            "problem": problem,
            "notes": notes,
            "attention_only": words.ATTENTION_ONLY,
            "menu_open": words.MENU_OPEN,
            "menu_move": words.MENU_MOVE,
            "menu_add_here": words.MENU_ADD_HERE,
            "menu_index": words.MENU_INDEX,
            "move_group_label": words.MOVE_GROUP_LABEL,
            "move_group_empty": words.MOVE_GROUP_EMPTY,
            "menu_for": words.menu_for,
        },
    )


def _from_htmx(request: Request) -> bool:
    """Whether htmx sent this, and so wants a fragment rather than a page."""
    return request.headers.get("hx-request") == "true"


def _refused_a_post(
    request: Request, problem: str, *, resolution: str | None = None
) -> HTMLResponse:
    """A refusal in the panel for htmx, and as a page for a plain form.

    A plain form's browser replaces the page with whatever comes back,
    so a fragment there is a page with no window around it (#412).
    """
    if _from_htmx(request):
        return _refused(request, problem, resolution=resolution)
    return _TEMPLATES.TemplateResponse(
        request, "problem.html", {"problem": problem, "resolution": resolution}
    )


@dataclass(frozen=True, slots=True)
class ActivityRow:
    """One job as the Activity page lists it."""

    job_id: str
    kind: str
    state: str
    started: str


def _job_state(job: Job) -> str:
    if not job.done.is_set():
        return words.JOB_RUNNING
    return words.JOB_FAILED if job.failed else words.JOB_FINISHED


def _activity_row(job: Job) -> ActivityRow:
    return ActivityRow(
        job_id=job.id,
        kind=words.JOB_KINDS.get(job.kind, job.kind),
        state=_job_state(job),
        started=time.strftime("%H:%M", time.localtime(job.started_wall)),
    )


def _job_now(request: Request) -> Job | None:
    """The running job, for the strip on every page."""
    jobs: Jobs = request.app.state.jobs
    return jobs.running()


def _last_job(request: Request) -> tuple[str, str] | None:
    """The newest job that has ended, as an address and the strip's words."""
    jobs: Jobs = request.app.state.jobs
    for job in jobs.recent():
        if job.done.is_set():
            return f"/job/{job.id}", words.last_job(job.kind, _job_state(job))
    return None


def _strip_status(pane: Pane) -> list[tuple[str, str]]:
    """Where the corpus stands, from the pane the page already drew.

    Plan 11b's four, as `(text, role)`: the commit, what is searchable,
    what needs indexing, and the last change. The second and third are
    one collection count and one document count, because a person deciding
    whether to index asks how much, and a collection that is behind may be
    behind by one note. A role is empty for ordinary muted text.
    """
    states = [row.state for row in pane.collections]
    items = [
        (
            words.searchable_summary(
                searchable=sum(state in ("current", "behind") for state in states),
                total=len(states),
                behind=states.count("behind"),
            ),
            "",
        )
    ]
    if pane.waiting:
        items.append((words.documents_waiting(pane.waiting), "warning"))
    change = pane.last_change
    if change is not None:
        items.insert(0, (words.corpus_at(change.commit[:7]), ""))
        items.append(
            (
                words.last_change(
                    change.operation,
                    change.scope,
                    change.summary,
                    time.time() - change.when.timestamp(),
                ),
                "",
            )
        )
    return items


# The strip, on every page: the running job if there is one, otherwise
# where the corpus stands and what ran last (#405). Functions taking the
# request, registered here because they are defined above.
_TEMPLATES.env.globals.update(
    {"job_now": _job_now, "last_job": _last_job, "strip_status": _strip_status}
)


def _refused(
    request: Request, problem: str, *, resolution: str | None = None
) -> HTMLResponse:
    """A refusal inside the panel, not as a page.

    The form the person filled in is still on the page behind this, and
    replacing the page would lose what they typed. `CorpusBusy` is the
    case that makes it matter: something else is writing, nothing was
    changed, and the answer is to try again in a moment.
    """
    return _TEMPLATES.TemplateResponse(
        request,
        "outcome.html",
        {
            "outcome": ShownOutcome(
                message=problem, role="role-warning", resolution=resolution
            )
        },
    )


def _action(
    request: Request, path: str, form_template: str, context: dict[str, object]
) -> HTMLResponse:
    """An action's form: a dialog when htmx asks, a page otherwise.

    **One route per action.** The bar's link, and any later entrance,
    is an ordinary link to `path`. htmx fetches it into `#dialog`; a
    reader without a script follows it and gets the same form inside
    the whole window. Both render `form_template`, so the form is
    written once.
    """
    shown = {
        "title": words.ACTION_TITLES[path],
        "form_template": form_template,
        **context,
    }
    if request.headers.get("hx-request") == "true":
        return _TEMPLATES.TemplateResponse(request, "dialog.html", shown)
    return _TEMPLATES.TemplateResponse(
        request, "action-page.html", {**shown, **_frame(existing_corpus())}
    )
