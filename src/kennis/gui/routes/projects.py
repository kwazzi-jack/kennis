"""A project's controls in the window: what the pane's Context section and
each project's menu do (2026-11-04).

Each control does one thing, as its command does: list or start a project,
choose the packs it uses, sync their context into it, index it, reset it,
forget it, delete its context.
A dialog asks first where something goes. What reads or writes the bundle's
index runs as a task in that bundle's lane, so it waits for an index build
or a sync of the same bundle; choosing packs and listing a project each
write one small file and answer at once, as Forget does.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from kennis.context import existing_corpus
from kennis.engine.context.bundle import (
    BUNDLE_DIRNAME,
    declare_packs,
    declared_packs,
    init_bundle,
    is_bundle_dir,
)
from kennis.engine.context.deleting import delete_project, what_deleting_removes
from kennis.engine.context.projects import (
    Project,
    add_project,
    forget_project,
    project_named,
)
from kennis.engine.context.reset import reset_bundle
from kennis.engine.context.sync import plan_sync
from kennis.engine.errors import ContextNotFound, KennisError
from kennis.engine.typed import without_quotes
from kennis.gui import words
from kennis.gui.responses import (
    PostedForm,
    action_page,
    problem_page,
    refused_a_post,
    refused_in_the_form,
)
from kennis.gui.routes.jobs import started
from kennis.holdings import installed_packs
from kennis.operations import (
    index_a_bundle,
    synchronise_bundle,
    what_a_reset_removes,
)
from kennis.render.packs import describe_edited_copies, describe_not_installed
from kennis.render.words import count_of
from kennis.service.jobs import context_lane

router = APIRouter()


def _present(name: str) -> Project:
    """The project called `name`, refused when its bundle is not there: only
    Forget acts on a project whose folder has gone."""
    project = project_named(name)
    if not project.present:
        raise ContextNotFound(
            f"{name}'s bundle is not at {project.bundle}",
            resolution=f"kennis context forget {name}",
        )
    return project


# ---------------------------------------------------------------------------
# A new project


@router.get("/projects/new")
def ask_for_a_new_project(request: Request) -> HTMLResponse:
    return action_page(
        request,
        "/projects/new",
        "forms/new-project.html",
        {
            "new_project_preamble": words.NEW_PROJECT_PREAMBLE,
            "new_project_folder": words.NEW_PROJECT_FOLDER,
            "new_project_action": words.NEW_PROJECT_ACTION,
        },
    )


@router.post("/projects/new")
def add_a_new_project(request: Request, form: PostedForm) -> Response:
    """List the folder's project, making its bundle first where it has none.

    The folder is used as chosen, not walked up to its repository's root as
    `kennis context init` walks: the person picked it in the dialog.
    """
    given = without_quotes(str(form.get("folder") or ""))
    folder = Path(given).expanduser()
    if not given or not folder.is_dir():
        return refused_in_the_form(
            request, "#new-project-problem", words.no_such_folder(given)
        )
    try:
        if is_bundle_dir(folder / BUNDLE_DIRNAME) or is_bundle_dir(folder):
            add_project(folder)
        else:
            init_bundle(folder)
    except KennisError as error:
        return refused_a_post(request, str(error), resolution=error.resolution)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# The packs it uses


@router.get("/projects/packs")
def ask_which_packs(request: Request, project: str = "") -> HTMLResponse:
    """One checkbox per installed pack, and one per pack the project
    declares that this machine has not installed - checked and said so, so
    saving keeps a declaration a collaborator relies on."""
    try:
        known = _present(project)
    except KennisError as error:
        return problem_page(request, error)
    declared = set(declared_packs(known.bundle))
    installed = {
        one.state.pack_id: (
            one.declaration.pack.name if one.declaration else one.state.pack_id
        )
        for one in installed_packs(existing_corpus())
    }
    choices = [
        (pack_id, name, pack_id in declared, True)
        for pack_id, name in sorted(installed.items())
    ] + [
        (pack_id, pack_id, True, False)
        for pack_id in sorted(declared - installed.keys())
    ]
    return action_page(
        request,
        "/projects/packs",
        "forms/project-packs.html",
        {
            "project": project,
            "choices": choices,
            "project_packs_preamble": words.project_packs_preamble(project),
            "not_installed_here": words.NOT_INSTALLED_HERE,
            "no_packs": words.NO_PACKS,
            "project_packs_action": words.PROJECT_PACKS_ACTION,
        },
    )


@router.post("/projects/packs")
def declare_which_packs(request: Request, form: PostedForm) -> Response:
    """Make the checked packs exactly what the project declares."""
    try:
        known = _present(str(form.get("project") or ""))
        declare_packs(known.bundle, [str(one) for one in form.getlist("pack")])
    except KennisError as error:
        return refused_a_post(request, str(error), resolution=error.resolution)
    # Declaring copies nothing (#624): the sync dialog says what a sync
    # would now write or leave, and the person runs it.
    return RedirectResponse(
        f"/projects/sync?project={quote(known.name)}", status_code=303
    )


# ---------------------------------------------------------------------------
# A sync of the packs it uses


@router.get("/projects/sync")
def ask_to_sync_a_project(request: Request, project: str = "") -> HTMLResponse:
    """What a sync would do, from the sync's own plan, and the form that
    runs it; the copies of packs no longer declared go only when ticked."""
    try:
        known = _present(project)
        plan = plan_sync(known.bundle, existing_corpus().corpus_root)
    except KennisError as error:
        return problem_page(request, error)
    return action_page(
        request,
        "/projects/sync",
        "forms/sync-project.html",
        {
            "project": project,
            "plan": plan,
            "syncing": words.syncing_project(project, str(known.bundle)),
            "sync_labels": words.SYNC_LABELS,
            "edited_copies": describe_edited_copies(),
            "missing": describe_not_installed(plan.missing) if plan.missing else "",
            "nothing_to_do": not (plan.written or plan.updated or plan.undeclared),
            "nothing_to_sync": words.NOTHING_TO_SYNC,
            "undeclared": words.undeclared_copies(len(plan.undeclared)),
            "remove_undeclared": words.REMOVE_UNDECLARED,
            "sync_project_action": words.SYNC_PROJECT_ACTION,
        },
    )


@router.post("/projects/sync")
def sync_a_project(request: Request, form: PostedForm) -> Response:
    """Run the sync as a task in the bundle's lane, as `kennis context
    sync` runs it."""
    try:
        bundle = _present(str(form.get("project") or "")).bundle
    except KennisError as error:
        return problem_page(request, error)
    context = existing_corpus()
    removing = form.get("remove_undeclared") == "on"
    return started(
        request,
        "context-sync",
        lambda events: synchronise_bundle(
            bundle, context, remove_undeclared=removing, events=events
        ),
        lane=context_lane(str(bundle)),
    )


# ---------------------------------------------------------------------------
# Its index, and a reset


@router.post("/projects/index")
def index_a_project(request: Request, form: PostedForm) -> Response:
    try:
        bundle = _present(str(form.get("project") or "")).bundle
    except KennisError as error:
        return problem_page(request, error)
    context = existing_corpus()
    return started(
        request,
        "context-index",
        lambda events: index_a_bundle(context, bundle, events=events),
        lane=context_lane(str(bundle)),
    )


@router.get("/projects/reset")
def ask_to_reset_a_project(request: Request, project: str = "") -> HTMLResponse:
    """What a reset removes, asked of the reset's own rule, as `kennis
    context reset` asks it; nothing to remove offers no button."""
    try:
        known = _present(project)
    except KennisError as error:
        return problem_page(request, error)
    preview = what_a_reset_removes(known.bundle)
    return action_page(
        request,
        "/projects/reset",
        "forms/reset-project.html",
        {
            "project": project,
            "owned": preview.owned,
            "has_index": preview.has_index,
            "resetting": words.resetting_project(project, str(known.bundle)),
            "reset_index_item": words.RESET_INDEX_ITEM,
            "nothing_to_reset": words.NOTHING_TO_RESET,
            "reset_project_action": words.RESET_PROJECT_ACTION,
        },
    )


@router.post("/projects/reset")
def reset_a_project(request: Request, form: PostedForm) -> Response:
    try:
        bundle = _present(str(form.get("project") or "")).bundle
    except KennisError as error:
        return problem_page(request, error)
    return started(
        request,
        "context",
        lambda events: reset_bundle(bundle),
        lane=context_lane(str(bundle)),
    )


# ---------------------------------------------------------------------------
# Forgetting, and deleting its context


@router.get("/projects/forget")
def ask_to_forget_a_project(request: Request, project: str = "") -> HTMLResponse:
    """What forgetting the project does - kennis's list loses it, its
    folder keeps its files - and the form that does it."""
    try:
        known = project_named(project)
    except KennisError as error:
        return problem_page(request, error)
    return action_page(
        request,
        "/projects/forget",
        "forms/forget-project.html",
        {
            "project": project,
            "forgetting": words.forgetting_project(
                project, str(known.bundle), present=known.present
            ),
            "forget_project_action": words.FORGET_PROJECT_ACTION,
        },
    )


@router.post("/projects/forget")
def forget_a_project(request: Request, form: PostedForm) -> Response:
    """Take the project off kennis's list, as `kennis context forget` does,
    and answer with the window drawn whole, so the pane no longer lists it.
    Its files are not touched: the bundle is the person's own repository's."""
    try:
        forget_project(str(form.get("project") or ""))
    except KennisError as error:
        return refused_a_post(request, str(error), resolution=error.resolution)
    return RedirectResponse("/", status_code=303)


@router.get("/projects/delete")
def ask_to_delete_a_project(request: Request, project: str = "") -> HTMLResponse:
    """What deleting the project's context removes - the folder, how many
    files, and that kennis cannot undo it - and the form that does it.
    Asked of the delete's own refusals, so a folder it would refuse is
    refused here rather than offered."""
    try:
        preview = what_deleting_removes(project)
    except KennisError as error:
        return problem_page(request, error)
    return action_page(
        request,
        "/projects/delete",
        "forms/delete-project.html",
        {
            "project": project,
            "deleting": words.deleting_project(
                project,
                str(preview.project.bundle),
                count_of(preview.files, "file"),
            ),
            "delete_project_action": words.DELETE_PROJECT_ACTION,
        },
    )


@router.post("/projects/delete")
def delete_a_project(request: Request, form: PostedForm) -> Response:
    """Delete the project's `.context/` folder and unlist it, as `kennis
    context delete` does: a task in the bundle's own lane, so it waits for
    an index build or a sync of that bundle rather than removing it from
    under one."""
    name = str(form.get("project") or "")
    try:
        bundle = what_deleting_removes(name).project.bundle
    except KennisError as error:
        return problem_page(request, error)
    return started(
        request,
        "context-delete",
        lambda events: delete_project(name),
        lane=context_lane(str(bundle)),
    )


__all__ = ["router"]
