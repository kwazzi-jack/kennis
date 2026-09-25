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
import tomllib
from pathlib import Path

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

    **A file that sets nothing is treated as no file.** "Is there a file" was
    never the question a reader is asking; "are any settings set" is. A
    0-byte `config.toml` - which a setup where every answer was left
    unchanged used to write - otherwise made this command print nothing at
    all.

    The note comes *after* the body. It is sixty lines of TOML, so a leading
    note is off the top of the terminal before the command has finished
    printing, and a reader looks at the end.

    The body is styled rather than printed plain, because sixty lines in one
    colour is read by nobody. rich drops colour when stdout is not a
    terminal, so the redirect above still writes a file with no escape codes
    in it.
    """
    path = config_path()
    settings = _settings_in(path)
    display.toml(settings if settings else config_template())
    if settings:
        return
    display.note(
        f"no settings are set in {path}; these are the defaults"
        if path.is_file()
        else f"no configuration file at {path}; these are the defaults",
        stderr=True,
    )
    display.next_step("kennis config init", stderr=True)


def _settings_in(path: Path) -> str:
    """The file's text, or empty when it sets nothing.

    Parsed rather than measured: a file of nothing but comments is as empty
    as a file of nothing, and both are what `config init` can leave behind.
    """
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        # Unreadable is not empty. Showing it as it is lets the reader see
        # what is wrong with it, which printing the defaults would hide.
        return text
    return text if any(parsed.values()) else ""


@config_group.command(name="get")
@click.argument("key", required=False)
def get_command(key: str | None) -> None:
    """One setting's value, or every setting when no key is given."""
    settings = load_settings()
    if key is None:
        for name in Settings.model_fields:
            for field, value in _section_values(settings, name).items():
                display.setting_row(describe_setting(f"{name}.{field}", value))
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
    section = ""
    while True:
        remaining = [
            question
            for question in questions_for(answers)
            if question.key not in answers
        ]
        if not remaining:
            break
        question = remaining[0]
        # The heading when the section changes, and not otherwise. The
        # catalogue in `engine/setup.py` is already ordered by section, so
        # this groups the run without deciding anything about its order -
        # and a conditional question that changes which section comes next
        # still gets its own heading rather than appearing under the last
        # one printed.
        # A blank line before every question, and the heading after it when
        # the section changes. One rule rather than two: the questions are
        # separated whether or not a heading falls between them, and a
        # heading never ends up hugging the answer above it.
        display.info()
        if question.section != section:
            section = question.section
            display.heading(section.capitalize())
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

    Everything but the input line is printed through `display`, so the
    description and the accepted values meet the theme. `click.prompt` is
    left only the short line it has to echo and read on, because it writes
    with `click.echo` and nothing it prints can be styled.
    """
    _describe(question)
    while True:
        answered: str = click.prompt(
            f"{_QUESTION_INDENT}{question.key}",
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


# Questions sit under their section heading, and their own lines under them,
# the same two steps the report grammar uses for an operation and its details.
_QUESTION_INDENT = "  "


def _describe(question: Question) -> None:
    """What the question is, and what it will accept, above the input line.

    Wrapped to the terminal here because that is layout: a form would put the
    same description under the field and the options in a menu.
    """
    for line in textwrap.wrap(question.description, width=_width()):
        display.muted(f"{_QUESTION_INDENT}{line}")
    # On its own line rather than trailing the description, so that a long
    # description cannot push the list of accepted values across a line break
    # and split it mid-option.
    if question.options:
        display.info(f"{_QUESTION_INDENT}one of: {' | '.join(question.options)}")
    if question.minimum is not None and question.maximum is not None:
        display.info(f"{_QUESTION_INDENT}{question.minimum} to {question.maximum}")


def _width() -> int:
    """Wrapping width for a question's description.

    Capped as well as measured: a very wide terminal makes a paragraph that
    the eye cannot track back across, and a very narrow one still needs
    something to wrap to. The indent is taken off, so the wrapped text ends
    where an unindented line of the same width would.
    """
    columns = shutil.get_terminal_size(fallback=(80, 24)).columns
    return max(40, min(columns - 2, 88)) - len(_QUESTION_INDENT)


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
