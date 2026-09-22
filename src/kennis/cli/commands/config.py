"""`kennis config`: where settings live, what they are, and the guided setup.

`init` is the one that matters. It asks the engine what to ask, prompts for
each answer, and hands them back - so the same setup is reachable from a
form later without a GUI importing anything under `cli/`. Concern #108.

The knowledge that `openai` needs a key and `fastembed` does not is **not**
here. It is a property of the backend and lives in `engine/setup.py`, which
is what makes a second front end a rendering rather than a reimplementation.
"""

from __future__ import annotations

import shutil
import textwrap

import click

from kennis.cli import display
from kennis.cli.group import KennisGroup
from kennis.engine.errors import SettingsError
from kennis.engine.settings import (
    Settings,
    config_path,
    config_template,
    credentials_path,
    load_settings,
)
from kennis.engine.setup import Question, apply_answers, questions_for, validate_answer
from kennis.render.words import count_of, describe_setting


@click.group(name="config", cls=KennisGroup)
def config_group() -> None:
    """Settings, credentials, and the guided setup."""


@config_group.command(name="path")
def path_command() -> None:
    """Where the configuration file lives."""
    display.path(config_path())


@config_group.command(name="show")
def show_command() -> None:
    """Print the configuration, as valid TOML.

    **The warning goes to stderr**, so `kennis config show > config.toml`
    produces a usable file rather than one with a warning in the middle. That
    is the same rule that keeps `serve` off stdout.
    """
    path = config_path()
    if not path.is_file():
        display.note(
            f"no configuration file at {path}; these are the defaults",
            stderr=True,
        )
        display.next_step("kennis config init", stderr=True)
        display.plain(config_template())
        return
    display.plain(path.read_text(encoding="utf-8"))


@config_group.command(name="get")
@click.argument("key", required=False)
def get_command(key: str | None) -> None:
    """One setting's value, or every setting when no key is given."""
    settings = load_settings()
    if key is None:
        for name in Settings.model_fields:
            for field, value in _section_values(settings, name).items():
                display.detail(" ", describe_setting(f"{name}.{field}", value))
        return
    display.plain(str(_value_of(settings, key)))


@config_group.command(name="set")
@click.argument("key")
@click.argument("value")
def set_command(key: str, value: str) -> None:
    """Change one setting.

    Validated through the same path the setup uses, so a value this accepts
    is one `load_settings` will accept on the next command rather than one
    that fails somewhere else later.
    """
    _value_of(load_settings(), key)
    apply_answers({key: value})
    display.operation("Set", f"{key} = {value}")


@config_group.command(name="init")
@click.option(
    "--defaults",
    is_flag=True,
    help="Write the configuration file without asking anything.",
)
def init_command(defaults: bool) -> None:
    """Set kennis up, asking only what depends on you.

    Re-runnable: every question offers what is currently in effect, so
    pressing return throughout changes nothing.
    """
    if defaults:
        _write_template()
        return

    display.using(f"configuration at {config_path()}")
    display.guidance("press return to keep the value shown in brackets")

    answers: dict[str, str] = {}
    while True:
        remaining = [
            question
            for question in questions_for(answers)
            if question.key not in answers
        ]
        if not remaining:
            break
        question = remaining[0]
        answers[question.key] = _ask(question)

    apply_answers(answers)
    # The count is of what was *written*, not of what was asked. An unchanged
    # answer writes nothing, so counting questions would report five settings
    # configured for a file that sets none.
    changed = {key: value for key, value in answers.items() if value}
    if changed:
        display.operation("Configured", count_of(len(changed), "setting"))
    else:
        # "Configured 0 settings" reads as a failure to someone who
        # deliberately kept everything. Not "every default" either: on a
        # re-run what is kept is the previous answers, which are not defaults.
        display.operation("Changed", "nothing")
    for key, value in sorted(changed.items()):
        display.detail("~", describe_setting(key, _hidden_if_secret(key, value)))
    if any(key.endswith(".api_key") for key in changed):
        display.detail(" ", f"credentials written to {credentials_path()}")
    display.next_step("kennis corpus init", note="to create the corpus")


def _ask(question: Question) -> str:
    """One question, until the answer is acceptable.

    The loop is here and not in the engine: re-asking is an interaction, and
    a form would handle a rejected value by marking the field rather than by
    asking again.
    """
    while True:
        answered: str = click.prompt(
            _prompt_for(question),
            default=question.current,
            show_default=bool(question.current),
            hide_input=question.kind == "secret",
            type=str,
        )
        value = answered.strip()
        if value == question.current:
            # Unchanged is the same as unanswered: nothing is written for it,
            # so a later kennis that improves the default still reaches them.
            return ""
        problem = validate_answer(question, value)
        if problem is None:
            return value
        display.note(problem)


def _prompt_for(question: Question) -> str:
    """The question as a person reads it.

    Assembled here because it is layout - the description and the values it
    accepts above the field, wrapped to the terminal. A form would put the
    description under the field and the options in a menu.
    """
    width = _width()
    lines = [textwrap.fill(question.description, width=width)]
    # On its own line rather than trailing the description, so that a long
    # description cannot push the list of accepted values across a line break
    # and split it mid-option.
    if question.options:
        lines.append(f"[{' | '.join(question.options)}]")
    if question.minimum is not None and question.maximum is not None:
        lines.append(f"[{question.minimum}-{question.maximum}]")
    return "\n" + "\n".join([*lines, question.key])


def _width() -> int:
    """Wrapping width for a question.

    Capped as well as measured: a very wide terminal makes a paragraph that
    the eye cannot track back across, and a very narrow one still needs
    something to wrap to.
    """
    columns = shutil.get_terminal_size(fallback=(80, 24)).columns
    return max(40, min(columns - 2, 88))


def _hidden_if_secret(key: str, value: str) -> str:
    """A key's value, or the fact that there is one.

    An API key echoed back into the terminal ends up in scrollback, in a
    screenshot, and in whatever the terminal logs.
    """
    return "(set)" if key.endswith(".api_key") else value


def _write_template() -> None:
    path = config_path()
    if path.is_file():
        display.note(f"{path} already exists and was left alone")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config_template(), encoding="utf-8")
    display.operation("Wrote", str(path))


def _section_values(settings: Settings, section: str) -> dict[str, object]:
    held = getattr(settings, section, None)
    if held is None:
        return {}
    return {name: getattr(held, name) for name in type(held).model_fields}


def _value_of(settings: Settings, key: str) -> object:
    section, _, field = key.partition(".")
    if section not in Settings.model_fields:
        raise SettingsError(
            f"no settings section '{section}'; expected one of "
            f"{', '.join(Settings.model_fields)}",
            resolution="kennis config show",
        )
    values = _section_values(settings, section)
    if field not in values:
        raise SettingsError(
            f"no setting '{key}'; {section} has {', '.join(sorted(values))}",
            resolution="kennis config show",
        )
    return values[field]


__all__ = ["config_group"]
