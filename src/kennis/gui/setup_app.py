"""The setup wizard, served by `kennis gui` before any corpus exists (#682).

**Not the corpus service.** That service refuses a folder holding no
corpus, by design: one with nothing to own would hold a lock and a port
for thirty minutes. So `kennis gui`, finding nothing set up, serves this
small application itself, in the foreground, on loopback with a token of
its own and the window's guard; its last step starts the corpus service
and sends the browser there, and this server stops.

Four steps, each a page at `/?step=<name>`: the settings (the walk `config
init` asks, `corpus.root` included), the corpus, an agent, and the way in.
A form answers 303 to the next step, or draws its step again marked where
it was refused.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Final
from urllib.parse import urlencode

import uvicorn
from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from kennis import setting_up
from kennis.engine.errors import SettingsError
from kennis.gui import words
from kennis.gui.app import guard, new_token, serve_assets
from kennis.gui.configuration import (
    answers_in,
    changed_answers,
    offered,
    shown_settings,
)
from kennis.gui.responses import TEMPLATES

_STEPS: Final = tuple(name for name, _ in words.SETUP_STEPS)
_HOST: Final = "127.0.0.1"
# A request that answers the last step starts the service, which can take
# a few seconds the first time; the wizard's own server is given that
# long to send the answer before it stops.
_SERVER_POLL_SECONDS: Final = 0.05

type StartService = Callable[[Path], str]
type Finished = Callable[[], None]


def _service_address(root: Path) -> str:
    """Start the corpus service for `root` if none runs, and the address a
    browser opens it at, with its token."""
    from kennis.client.process import ensure_service

    record = ensure_service(root)
    return f"{record.address}?" + urlencode({"token": record.token})


def _nothing() -> None:
    """The default `on_done`, for an application nobody serves."""


def _corpus_root() -> Path:
    from kennis.context import resolve_context

    # Resolved per request: `corpus.root` is one of the settings this
    # wizard writes.
    return resolve_context().corpus_root


def _is_corpus(root: Path) -> bool:
    return (root / ".git").is_dir()


def build_setup_app(
    token: str,
    *,
    start_service: StartService = _service_address,
    on_done: Finished = _nothing,
) -> FastAPI:
    """The wizard, guarded by `token`.

    `start_service` starts the corpus service and answers its address;
    `on_done` is told when the browser has been sent there, so whoever
    runs this server can stop it.
    """
    app = FastAPI(title="kennis setup", docs_url=None, redoc_url=None)
    guard(app, token)
    serve_assets(app)

    def page(
        request: Request,
        step: str,
        extra: Mapping[str, object],
        status_code: int = 200,
    ) -> HTMLResponse:
        context: dict[str, object] = {
            "title": words.SETUP_TITLE,
            "steps": words.SETUP_STEPS,
            "step": step,
            "next_label": words.SETUP_NEXT,
        }
        context.update(extra)
        return TEMPLATES.TemplateResponse(
            request, "setup.html", context, status_code=status_code
        )

    def settings_section(
        answers: Mapping[str, str],
        problems: Mapping[str, str] | None = None,
        outcome: str = "",
    ) -> dict[str, object]:
        shown = shown_settings(answers, problems, every=False)
        groups = {setting.group for setting in shown}
        return {
            "settings": shown,
            "setting_groups": [
                (group, heading)
                for group, heading in words.KENNIS_GROUPS
                if group in groups
            ],
            "settings_note": words.SETUP_SETTINGS_NOTE,
            "save_label": words.SETUP_SAVE,
            "order_hint": words.ORDER_HINT,
            "credential_set": words.CREDENTIAL_SET,
            "credential_unset": words.CREDENTIAL_UNSET,
            "converter_missing": words.CONVERTER_MISSING,
            "outcome": outcome,
        }

    def step_context(step: str, change: bool) -> dict[str, object]:
        from kennis.engine.settings import config_path

        if step == "settings":
            path = config_path()
            if path.is_file() and not change:
                return {
                    "kept_at": words.setup_settings_kept(str(path)),
                    "change_label": words.SETUP_CHANGE,
                }
            return settings_section({})
        if step == "corpus":
            root = _corpus_root()
            return {
                "corpus_note": words.SETUP_CORPUS_NOTE,
                "corpus_kept": (
                    words.setup_corpus_kept(str(root)) if _is_corpus(root) else ""
                ),
                "corpus_at": words.setup_corpus_at(str(root)),
                "create_label": words.SETUP_CREATE,
            }
        if step == "agent":
            return agent_context()
        return {
            "packs": words.SETUP_PACKS,
            "context": words.SETUP_CONTEXT,
            "open_label": words.SETUP_OPEN,
        }

    def agent_context(outcome: str = "", paste: str = "") -> dict[str, object]:
        if not setting_up.mcp_installed():
            return {
                "agent_note": words.SETUP_AGENT_NOTE,
                "needs_mcp": words.setup_needs_mcp(setting_up.MCP_INSTALL),
            }
        offered_agents = [
            (value, label)
            for value, label in words.SETUP_AGENT_CHOICES.items()
            if value != "claude-code" or setting_up.claude_on_path()
        ]
        return {
            "agent_note": words.SETUP_AGENT_NOTE,
            "agents": offered_agents,
            "connect_label": words.SETUP_CONNECT,
            "outcome": outcome,
            "paste": paste,
        }

    @app.get("/")
    def wizard(request: Request, step: str = "settings", change: str = "") -> Response:
        chosen = step if step in _STEPS else "settings"
        return page(request, chosen, step_context(chosen, change == "yes"))

    @app.get("/setup/settings")
    def redraw_settings(request: Request) -> HTMLResponse:
        """The settings section for the choices in the address, as the
        settings page redraws its own."""
        answers = {key: value for key, value in request.query_params.items()}
        return TEMPLATES.TemplateResponse(
            request, "setup-settings.html", settings_section(answers)
        )

    @app.post("/setup/settings")
    async def save_settings(request: Request) -> Response:
        from kennis.engine.setup import apply_answers, validate_answer

        answers = answers_in(dict(await request.form()))
        problems = {
            question.key: problem
            for question in offered(answers, every=False)
            if (problem := validate_answer(question, answers.get(question.key, "")))
        }
        if not problems:
            try:
                # Written even when nothing changed: the file then exists,
                # holding every setting, which is what setting up means.
                apply_answers(changed_answers(answers, every=False))
            except SettingsError as error:
                problems = {"": str(error)}
        if problems:
            return page(
                request,
                "settings",
                settings_section(
                    answers, problems, problems.get("", words.KENNIS_NOT_SAVED)
                ),
            )
        return RedirectResponse("/?step=corpus", status_code=303)

    @app.post("/setup/corpus")
    def create_corpus() -> Response:
        from kennis.engine.history.repository import initialise_corpus

        root = _corpus_root()
        if not _is_corpus(root):
            initialise_corpus(root)
        return RedirectResponse("/?step=agent", status_code=303)

    @app.post("/setup/agent")
    def connect_agent(
        request: Request, agent: Annotated[str, Form()] = "none"
    ) -> Response:
        if agent == "claude-code" and setting_up.claude_on_path():
            kennis = setting_up.this_kennis()
            if setting_up.claude_serves_kennis():
                said = agent_context(outcome=words.SETUP_ALREADY_CONNECTED)
            else:
                answered = setting_up.add_to_claude_code(kennis)
                if answered.returncode == 0:
                    said = agent_context(outcome=words.SETUP_CONNECTED)
                else:
                    reason = answered.stderr.strip() or f"exit {answered.returncode}"
                    said = agent_context(
                        outcome=words.setup_not_connected(reason),
                        paste=setting_up.server_block(kennis),
                    )
            return page(request, "agent", said)
        if agent == "other":
            return page(
                request,
                "agent",
                agent_context(
                    outcome=words.SETUP_PASTE,
                    paste=setting_up.server_block(setting_up.this_kennis()),
                ),
            )
        return RedirectResponse("/?step=done", status_code=303)

    @app.post("/setup/open")
    def open_kennis() -> Response:
        root = _corpus_root()
        if not _is_corpus(root):
            return RedirectResponse("/?step=corpus", status_code=303)
        address = start_service(root)
        on_done()
        return RedirectResponse(address, status_code=303)

    return app


def serve_setup(
    *,
    open_browser: bool,
    announce: Callable[[str], None] = lambda address: None,
) -> bool:
    """Serve the wizard on loopback until its last step sends the browser to
    the window, or until interrupted. Whether it finished.

    `announce` is given the wizard's address before the browser is asked,
    since `webbrowser.open` can fail silently and the address is then the
    only way in.
    """
    from kennis.gui.browser import open_quietly
    from kennis.service.serve import port_of

    finished = threading.Event()
    token = new_token()
    server = uvicorn.Server(
        uvicorn.Config(
            build_setup_app(token, on_done=finished.set),
            host=_HOST,
            port=0,
            log_level="warning",
            # The access log would carry the token in a query string.
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True, name="kennis-setup")
    thread.start()
    try:
        address = f"http://{_HOST}:{port_of(server)}/?" + urlencode({"token": token})
        announce(address)
        if open_browser:
            open_quietly(address)
        while not finished.wait(_SERVER_POLL_SECONDS):
            if not thread.is_alive():
                return False
        return True
    finally:
        # uvicorn finishes the answer in flight - the redirect to the
        # window - before it stops.
        server.should_exit = True
        thread.join(timeout=10)


__all__ = ["build_setup_app", "serve_setup"]
