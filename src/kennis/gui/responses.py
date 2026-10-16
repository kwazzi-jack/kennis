"""What every route of the window answers with, and the shell around it.

The templates and the globals every page's shell draws from, the shapes a
refusal takes for htmx and for a plain form, the form a POST carries, and
the header a write answers with. Shared by `gui/routes/`, which import it
and nothing from one another but `jobs.started`.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Annotated, Final

from fastapi import Depends, Request, Response
from fastapi.datastructures import FormData
from fastapi.responses import (
    HTMLResponse,
)
from fastapi.templating import Jinja2Templates

from kennis.context import Context, existing_corpus
from kennis.engine.context.index import CONTEXT_COLLECTION
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.errors import (
    KennisError,
)
from kennis.gui import words
from kennis.gui.icons import icon
from kennis.gui.jobs import Job, Jobs
from kennis.gui.layout import SIZES, sizes_of, strip_state
from kennis.gui.pages import (
    ShownOutcome,
)
from kennis.gui.pane import Pane, pane_now
from kennis.gui.preferences import (
    preferences_of,
)
from kennis.holdings import (
    revision,
)
from kennis.retrieval import (
    EVERY_SCOPE,
)

_HERE: Final = Path(__file__).parent


TEMPLATES: Final = Jinja2Templates(directory=str(_HERE / "templates"))


# Globals rather than per-route context entries: the shell is on every
# page, and not every route builds its context through `frame`.
# The pane's state is a cookie rather than browser storage, so the
# server renders it and the first byte is already right. Read after
# paint from `localStorage`, a collapsed pane would show open and then
# collapse on every page load.
#
# A global **function** taking the request, not a constant and not
# `frame`: it varies per request, so a constant is wrong, and not
# every route builds its context through `frame`, so a value put
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
TEMPLATES.env.globals["preferences"] = preferences_of


# The open book, carried whole as a `data:` address rather than served:
# the locked page is answered without the token every static file needs,
# and the stopped page is drawn as the server exits, so neither could
# fetch it. `img-src data:` already admits it. The light version only,
# because `media` on an icon link is not honoured everywhere and the
# white pages read on a dark tab strip too.
TEMPLATES.env.globals["favicon"] = "data:image/svg+xml;base64," + base64.b64encode(
    (_HERE / "static" / "brand" / "favicon.svg").read_bytes()
).decode("ascii")


# The scopes a person may search, in the order they are offered. The
# bundle last because it is the one that is not always there.
SCOPES: Final = (*COLLECTION_NAMES, CONTEXT_COLLECTION)


def for_the_window(resolution: str | None) -> bool:
    """Whether a refusal's command is worth printing in the window.

    Not a command's `--help`: that is a terminal's answer to someone
    looking at a form, and the window has the dialogs it would lead to.
    A command with no window equivalent - a restore, a claim - stays.
    """
    return bool(resolution) and not str(resolution).rstrip().endswith("--help")


TEMPLATES.env.tests["for_the_window"] = for_the_window

TEMPLATES.env.globals.update(
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
        "problem_heading": words.PROBLEM_HEADING,
        "skip_to_content": words.SKIP_TO_CONTENT,
        "overridden_by": words.overridden_by,
        "index_now": words.index_now,
        "index_now_label": words.INDEX_NOW,
        "sync_corpus_label": words.SYNC_CORPUS_ACTION,
        "sync_context_label": words.SYNC_CONTEXT_ACTION,
        "copy_label": words.COPY_LABEL,
        "copied_label": words.COPIED_LABEL,
        "cancel_label": words.CANCEL,
        "more_from": words.more_from,
        "welcome_heading": words.WELCOME_HEADING,
        "welcome": words.WELCOME,
        "welcome_tip": words.WELCOME_TIP,
        "welcome_actions": words.WELCOME_ACTIONS,
        "folded_after": words.FOLDED_AFTER,
        "every_item": words.every_item,
        "progress_label": words.PROGRESS_LABEL,
        "note_text_label": words.NOTE_TEXT_LABEL,
        "title_label": words.TITLE_LABEL,
        "group_label": words.GROUP_LABEL,
        "target_label": words.TARGET_LABEL,
        "pack_path_label": words.PACK_PATH_LABEL,
        "index_which_label": words.INDEX_WHICH_LABEL,
        "problem_back": words.PROBLEM_BACK,
        "problem_corpus": words.PROBLEM_CORPUS,
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
        "no_context_tip": words.NO_CONTEXT_TIP,
        "recents_heading": words.RECENTS_HEADING,
        "results_heading": words.RESULTS_HEADING,
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
        "prefilled_note": words.PREFILLED_NOTE,
        "looking_up": words.LOOKING_UP,
        "field_labels": words.FIELD_LABELS,
        "field_tips": words.FIELD_TIPS,
        "browse": words.BROWSE,
        "upload_files": words.UPLOAD_FILES,
        "upload_folder": words.UPLOAD_FOLDER,
        "upload_hint": words.UPLOAD_HINT,
        "tip_about": words.tip_about,
        "index_waiting": words.index_waiting,
        "upload_pdf": words.UPLOAD_PDF,
        "upload_typed": words.UPLOAD_TYPED,
        "upload_typed_pdf": words.UPLOAD_TYPED_PDF,
        "upload_clear": words.UPLOAD_CLEAR,
        "upload_said": words.UPLOAD_SAID,
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


async def form_of(request: Request) -> FormData:
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
type PostedForm = Annotated[FormData, Depends(form_of)]


# The header a response to this window's own write carries: the commit the
# corpus is at once the write is done.
REVISION_HEADER: Final = "X-Kennis-Revision"


def written[Answer: Response](answer: Answer) -> Answer:
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


def frame(context: Context) -> dict[str, object]:
    """What every page carries regardless of what it shows.

    The revision is the page's own timestamp, in the only unit that
    matters here: a commit the corpus was at when this was drawn. The
    message travels with it so the script does not compose words.
    """
    return {
        "revision": revision(context) or "",
        "corpus_changed": words.CORPUS_CHANGED,
    }


def problem_page(request: Request, error: KennisError) -> HTMLResponse:
    """A domain failure as a page.

    Design section 20: the engine raises, and each front end turns it
    into what that front end has - an exit code, a tool error, or this.
    """
    return TEMPLATES.TemplateResponse(
        request,
        "problem.html",
        {"problem": str(error), "resolution": error.resolution},
        status_code=404,
    )


def from_htmx(request: Request) -> bool:
    """Whether htmx sent this, and so wants a fragment rather than a page."""
    return request.headers.get("hx-request") == "true"


def refused_a_post(
    request: Request, problem: str, *, resolution: str | None = None
) -> HTMLResponse:
    """A refusal in the panel for htmx, and as a page for a plain form.

    A plain form's browser replaces the page with whatever comes back,
    so a fragment there is a page with no window around it (#412).
    """
    if from_htmx(request):
        return refused(request, problem, resolution=resolution)
    return TEMPLATES.TemplateResponse(
        request, "problem.html", {"problem": problem, "resolution": resolution}
    )


def job_state(job: Job) -> str:
    if not job.done.is_set():
        return words.JOB_RUNNING
    return words.JOB_FAILED if job.failed else words.JOB_FINISHED


def _job_now(request: Request) -> Job | None:
    """The running job, for the strip on every page."""
    jobs: Jobs = request.app.state.jobs
    return jobs.running()


def _last_job(request: Request) -> tuple[str, str] | None:
    """The newest job that has ended, as an address and the strip's words."""
    jobs: Jobs = request.app.state.jobs
    for job in jobs.recent():
        if job.done.is_set():
            return f"/job/{job.id}", words.last_job(job.kind, job_state(job))
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
TEMPLATES.env.globals.update(
    {"job_now": _job_now, "last_job": _last_job, "strip_status": _strip_status}
)


def refused(
    request: Request, problem: str, *, resolution: str | None = None
) -> HTMLResponse:
    """A refusal inside the panel, not as a page.

    The form the person filled in is still on the page behind this, and
    replacing the page would lose what they typed. `CorpusBusy` is the
    case that makes it matter: something else is writing, nothing was
    changed, and the answer is to try again in a moment.
    """
    return TEMPLATES.TemplateResponse(
        request,
        "outcome.html",
        {
            "outcome": ShownOutcome(
                message=problem, role="role-warning", resolution=resolution
            )
        },
    )


def action_page(
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
        return TEMPLATES.TemplateResponse(request, "dialog.html", shown)
    return TEMPLATES.TemplateResponse(
        request, "action-page.html", {**shown, **frame(existing_corpus())}
    )
