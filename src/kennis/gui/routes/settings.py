"""Settings: this window's preferences, kennis's configuration and what
each change costs, and the backup.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
)

from kennis.context import existing_corpus
from kennis.engine.backup import check_backup
from kennis.engine.errors import (
    SettingsError,
)
from kennis.engine.settings import config_path, load_settings, unknown_settings
from kennis.engine.setup import apply_answers, validate_answer
from kennis.gui import words
from kennis.gui.configuration import (
    answers_in,
    changed_answers,
    needs_rebuild,
    offered,
    shown_indexes,
    shown_settings,
)
from kennis.gui.preferences import (
    COOKIE_SECONDS,
    PREFERENCES,
    chosen_in,
    preferences_of,
)
from kennis.gui.responses import (
    TEMPLATES,
    PostedForm,
    frame,
    from_htmx,
    refused_in_the_form,
)
from kennis.gui.routes.jobs import started
from kennis.operations import (
    back_up_corpus,
)
from kennis.render.backup import (
    BACKUP_CAUTION,
    BACKUP_CAUTION_LINK,
    BACKUP_CAUTION_PAGE,
    BACKUP_CONTENTS,
    NO_BACKUP_FOLDER,
    describe_archive,
    describe_folder,
    describe_verified,
)
from kennis.render.settings import describe_unknown_settings

router = APIRouter()


def _settings_page(
    request: Request,
    kennis: dict[str, object],
    backup: dict[str, object] | None = None,
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
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
            "window_tip": words.WINDOW_SETTINGS_TIP,
            "save_label": words.SAVE,
            **kennis,
            **(backup if backup is not None else _backup_section()),
            **frame(existing_corpus()),
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
        "kennis_settings_heading": words.KENNIS_SETTINGS_HEADING,
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
        "credential_set": words.CREDENTIAL_SET,
        "credential_unset": words.CREDENTIAL_UNSET,
        "converter_missing": words.CONVERTER_MISSING,
        "unknown_settings": _unknown_settings_said(),
    }


def _unknown_settings_said() -> str:
    """The file's settings kennis does not read, or nothing (#480).

    Read at drawing, so a save - which rewrites the file without them -
    takes the notice away in the same answer.
    """
    keys = unknown_settings()
    return describe_unknown_settings(keys, str(config_path())) if keys else ""


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
        "backup_caution": BACKUP_CAUTION,
        "backup_caution_link": BACKUP_CAUTION_LINK,
        "backup_caution_page": BACKUP_CAUTION_PAGE,
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
        "backup_now_tip": words.BACKUP_NOW_TIP,
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
    if from_htmx(request):
        return TEMPLATES.TemplateResponse(request, "settings-backup.html", section)
    return _settings_page(request, _kennis_section({}), section)


@router.get("/settings")
def serve_settings(request: Request) -> HTMLResponse:
    """The settings page: this window's preferences (12a) and
    kennis's own configuration (12b)."""
    return _settings_page(request, _kennis_section({}))


@router.get("/settings/kennis")
def redraw_kennis_settings(request: Request) -> HTMLResponse:
    """The configuration section for the values in the address.

    What a changed choice asks, so the rows that apply are the
    engine's answer for what the form holds rather than for what
    is saved. Nothing is written.
    """
    section = _kennis_section(answers_in(request.query_params))
    if from_htmx(request):
        return TEMPLATES.TemplateResponse(request, "settings-kennis.html", section)
    return _settings_page(request, section)


@router.post("/settings/kennis")
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
    if from_htmx(request):
        return TEMPLATES.TemplateResponse(request, "settings-kennis.html", section)
    return _settings_page(request, section)


@router.post("/settings")
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


@router.get("/settings/backup")
def serve_backup_section(request: Request) -> HTMLResponse:
    """The Backup section as it stands, for a finished job to redraw."""
    return _backup_answer(request, _backup_section())


@router.post("/settings/backup")
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
            _backup_section(about="folder", problem=words.not_a_backup_folder(given)),
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


@router.post("/settings/backup/test")
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


@router.post("/backup")
def start_backup(request: Request, form: PostedForm) -> Response:
    """Back up now: a job, so it is in the strip and refused while
    another runs. The password reaches the job as an argument only."""
    password = str(form.get("password") or "")
    confirmation = str(form.get("confirmation") or "")
    folder = _backup_folder()
    # Each is about this section's own fields, so each is said in it (#475).
    if folder is None:
        return refused_in_the_form(request, "#backup-problem", NO_BACKUP_FOLDER)
    if not password:
        return refused_in_the_form(request, "#backup-problem", words.PASSWORD_NEEDED)
    if password != confirmation:
        return refused_in_the_form(request, "#backup-problem", words.PASSWORDS_DIFFER)
    context = existing_corpus()
    return started(
        request,
        "backup",
        lambda events: back_up_corpus(context, folder, password, events=events),
    )
