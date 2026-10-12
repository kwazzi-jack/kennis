"""The guided setup, as a catalogue of questions rather than a conversation.

**The engine owns what is asked; a front end owns how.** That is concern
#108's rule, and the shape follows from it: this module knows that `openai`
needs a key and `fastembed` does not, because that is a property of the
backend, and a command line or a form that re-derived it would be a second
front end re-implementing the first.

Nothing here prompts, prints or reads a terminal. A caller walks
`questions_for`, collects answers however it likes, and hands them back to
`apply_answers`. A terminal asks one at a time and skips what does not
apply; a form shows them all at once and binds visibility to the same
`when` predicate. One description, two renderings.

The questions are **hand-ordered and model-derived**: which five to ask, and
in what order, is a judgement about what a new user needs, while the options,
the bounds and the descriptions come from the pydantic fields so they cannot
drift from what the settings actually accept.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from kennis.engine.corpus.converters import DATALAB_KEY_VARIABLE
from kennis.engine.errors import SettingsError
from kennis.engine.settings import (
    EMBEDDING_DEFAULTS,
    Settings,
    config_path,
    credential,
    credentials_path,
    load_settings,
)

type QuestionKind = Literal["choice", "text", "integer", "boolean", "secret"]


@dataclass(frozen=True, slots=True)
class Question:
    """One thing the setup needs to know.

    Facts only, per #81: the key it sets, what kind of value it takes, what
    is currently in effect, and the constraints. `description` is the
    pydantic field's own, which is schema metadata rather than composed
    prose - the same text `config_template` emits, for the same reason.

    `when` is a conjunction of `(key, value)` pairs over the answers given so
    far. A value rather than a callback, so a form can evaluate it to decide
    what to show without running kennis's code per keystroke.

    `current` is what is in force and `suggested` what to offer. They
    differ only for a model or a width asked under a backend not in force
    (#441), and a front end offers `suggested` and writes an answer only
    when it differs from `current`.
    """

    key: str
    kind: QuestionKind
    description: str
    current: str = ""
    suggested: str = ""
    options: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    when: tuple[tuple[str, str], ...] = ()

    @property
    def section(self) -> str:
        return self.key.partition(".")[0]

    @property
    def field(self) -> str:
        return self.key.partition(".")[2]


# The order a new user is walked through, and nothing else. Every key kennis
# has is in `config.toml` with its default; these are the ones where the
# right answer depends on the person rather than on kennis.
_ASKED: Final[tuple[tuple[str, QuestionKind, tuple[tuple[str, str], ...]], ...]] = (
    ("embedding.backend", "choice", ()),
    # The width under every backend that has a model, because it is the
    # model's: kept at fastembed's 384 under openai it recorded a false
    # width beside 1536-wide vectors (#441).
    ("embedding.model", "text", (("embedding.backend", "fastembed"),)),
    ("embedding.dimensions", "integer", (("embedding.backend", "fastembed"),)),
    ("embedding.base_url", "text", (("embedding.backend", "ollama"),)),
    ("embedding.model", "text", (("embedding.backend", "ollama"),)),
    ("embedding.dimensions", "integer", (("embedding.backend", "ollama"),)),
    ("embedding.model", "text", (("embedding.backend", "openai"),)),
    ("embedding.dimensions", "integer", (("embedding.backend", "openai"),)),
    ("embedding.api_key", "secret", (("embedding.backend", "openai"),)),
    ("conversion.backend", "choice", ()),
    # Before the key: the mode is a price, and nobody wants to retype a key
    # because a cheap question came after it.
    ("conversion.mode", "choice", (("conversion.backend", "datalab"),)),
    ("conversion.api_key", "secret", (("conversion.backend", "datalab"),)),
    ("retrieval.corpus_method", "choice", ()),
    ("retrieval.default_top_k", "integer", ()),
    ("chunking.size", "integer", ()),
    ("corpus.root", "text", ()),
)


def setup_questions() -> tuple[Question, ...]:
    """Every question the setup can ask, in the order it would ask them.

    The whole catalogue, conditions and all. `questions_for` filters it;
    this is what a form binds to and what a test enumerates.
    """
    settings = load_settings()
    return tuple(_question(key, kind, when, settings) for key, kind, when in _ASKED)


def questions_for(answers: Mapping[str, str]) -> list[Question]:
    """The questions that apply, given what has been answered so far.

    A question whose condition names a key that has not been answered yet is
    judged against the value currently in effect, so a setup run that skips
    straight to the end still asks the right things.
    """
    settled = dict(answers)
    applicable: list[Question] = []
    for question in setup_questions():
        if _applies(question, settled):
            applicable.append(question)
            settled.setdefault(question.key, question.current)
    return applicable


def validate_answer(question: Question, value: str) -> str | None:
    """Why `value` is not acceptable for `question`, or None if it is.

    An empty answer is always acceptable and always means "keep what is
    there", which is what makes the setup safe to re-run: pressing return
    throughout changes nothing.
    """
    if not value:
        return None
    if question.kind == "secret":
        return None
    if question.options and value not in question.options:
        return f"expected one of {', '.join(question.options)}"
    try:
        _coerce(question, value)
    except ValueError as error:
        return str(error)

    try:
        _validated({question.key: value})
    except SettingsError as error:
        return str(error)
    return None


def apply_answers(answers: Mapping[str, str]) -> Settings:
    """Write the answers and return the settings they produce.

    **Validated before anything is written.** A setup that wrote each answer
    as it arrived would leave a half-configured file behind when the fifth
    one was rejected, and the user would have to work out which half.

    Answers left empty are not written at all, so a key keeps whatever it
    had - including from an earlier run of this same command.
    """
    given = {key: value for key, value in answers.items() if value}
    settings = _validated(given)

    secrets = {key: value for key, value in given.items() if _is_secret(key)}
    _write_config({key: value for key, value in given.items() if key not in secrets})
    if secrets:
        _write_credentials(
            {
                (key.partition(".")[0], _key_variable(key, settings)): value
                for key, value in secrets.items()
            }
        )
    return settings


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    """Which variable a key is read from, and whether anything holds it.

    Never the value: a status is drawn on a page and written to a log, and a
    key that reached either would be a key sent somewhere it was not meant
    to go.
    """

    variable: str
    is_set: bool


def credential_status(key: str) -> CredentialStatus:
    """The variable `key`'s value is read from, and whether it is set.

    The variable is the one the reader of the key consults, under the
    settings in force.
    """
    variable = _key_variable(key, load_settings())
    return CredentialStatus(variable=variable, is_set=bool(credential(variable)))


def _key_variable(key: str, settings: Settings) -> str:
    """The variable the reader of `key` asks `credential` for.

    The one answer to that question, for the writer and for the status
    alike: two tables answering it separately filed the embedding key
    under `OPENAI_API_KEY` while embedding read `embedding.api_key_env`
    (#440). An unknown key raises rather than being filed under a name
    nobody reads.
    """
    if key == "embedding.api_key":
        return settings.embedding.api_key_env
    if key == "conversion.api_key":
        return DATALAB_KEY_VARIABLE
    raise KeyError(key)


# ---------------------------------------------------------------------------
# Deriving a question from the model
# ---------------------------------------------------------------------------


def _question(
    key: str,
    kind: QuestionKind,
    when: tuple[tuple[str, str], ...],
    settings: Settings,
) -> Question:
    if kind == "secret":
        backend = when[0][1] if when else ""
        return Question(
            key=key,
            kind=kind,
            description=(
                f"API key for {backend}. Stored in {credentials_path().name}, "
                f"readable only by you, and never written to the config file."
            ),
            when=when,
        )

    field = _field_of(key)
    lower, upper = _bounds_of(field)
    return Question(
        key=key,
        kind=kind,
        description=field.description or key,
        current=_current(key, settings),
        suggested=_suggested(key, when, settings),
        options=_options_of(field.annotation),
        minimum=lower,
        maximum=upper,
        when=when,
    )


def _field_of(key: str) -> FieldInfo:
    section, _, name = key.partition(".")
    annotation = Settings.model_fields[section].annotation
    if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
        raise SettingsError(f"'{section}' is not a settings section")
    return annotation.model_fields[name]


def _current(key: str, settings: Settings) -> str:
    section, _, name = key.partition(".")
    value = getattr(getattr(settings, section), name)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _suggested(key: str, when: tuple[tuple[str, str], ...], settings: Settings) -> str:
    """What a front end offers for `key`: the value in force, unless the
    question is asked for an embedding backend other than the one in force.

    Then the value in force belongs to the other backend, and that
    backend's own model and width are offered instead (#441). This is not
    `current`, because `current` is what an answer is compared with to
    decide whether to write it: accepting the offer has to write it.
    """
    backend = dict(when).get("embedding.backend")
    default = EMBEDDING_DEFAULTS.get(backend or "")
    if default is None or backend == settings.embedding.backend:
        return _current(key, settings)
    if key == "embedding.model":
        return default.model
    if key == "embedding.dimensions":
        return str(default.dimensions)
    return _current(key, settings)


def _options_of(annotation: object) -> tuple[str, ...]:
    if get_origin(annotation) is Literal:
        return tuple(str(value) for value in get_args(annotation))
    return ()


def _bounds_of(field: FieldInfo) -> tuple[int | None, int | None]:
    lower = upper = None
    for item in field.metadata:
        lower = getattr(item, "ge", None) if lower is None else lower
        upper = getattr(item, "le", None) if upper is None else upper
    return (
        int(lower) if isinstance(lower, int | float) else None,
        int(upper) if isinstance(upper, int | float) else None,
    )


def _applies(question: Question, settled: Mapping[str, str]) -> bool:
    """Whether every condition on `question` holds.

    A condition naming an unanswered key falls back to what is currently in
    effect rather than failing, so a partial set of answers still produces a
    sensible list.

    **An empty answer counts as unanswered**, which is what it means
    everywhere else here - `apply_answers` writes nothing for it. Reading it
    as an answer of `""` instead would mean that keeping `openai` on a re-run
    matched no condition, so neither the model nor the key was asked for and
    there was no way to change an API key through the setup.
    """
    if not question.when:
        return True
    settings = load_settings()
    for key, expected in question.when:
        actual = settled.get(key) or _current(key, settings)
        if actual != expected:
            return False
    return True


# ---------------------------------------------------------------------------
# Validating and writing
# ---------------------------------------------------------------------------


def _is_secret(key: str) -> bool:
    return key.endswith(".api_key")


def _coerce(question: Question, value: str) -> object:
    if question.kind == "integer":
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"'{value}' is not a whole number") from None
    if question.kind == "boolean":
        if value.lower() not in {"true", "false", "yes", "no"}:
            return _refuse_boolean(value)
        return value.lower() in {"true", "yes"}
    return value


def _refuse_boolean(value: str) -> bool:
    raise ValueError(f"'{value}' is not true or false")


def _validated(given: Mapping[str, str]) -> Settings:
    """The settings these answers produce, or the first reason they do not.

    Built through the model rather than by checking the strings, so the
    answer to "is this acceptable" is the same one `load_settings` would
    give and cannot drift from it.
    """
    sections: dict[str, dict[str, object]] = {}
    for key, value in given.items():
        if _is_secret(key):
            continue
        section, _, name = key.partition(".")
        field = _field_of(key)
        sections.setdefault(section, {})[name] = _as_typed(field, value)

    merged = load_settings().model_dump()
    for section, values in sections.items():
        merged[section] = {**merged.get(section, {}), **values}
    try:
        return Settings.model_validate(merged)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise SettingsError(
            f"{where}: {first['msg']}", resolution="kennis config init"
        ) from error


def _as_typed(field: FieldInfo, value: str) -> object:
    """A command-line string as the type the field declares.

    Guessing from the string's shape would make `"800"` an integer for one
    field and a string for another depending on what the user typed, which
    is how a config file ends up with a quoted number in it.
    """
    # Held as `object` on purpose. Comparing `field.annotation` directly
    # narrows its type after the first `is`, and mypy then reads the `float`
    # branch as unreachable - which it is not, because the annotation is
    # whatever the model declared.
    declared: object = field.annotation
    if declared is bool:
        return value.lower() in {"true", "yes", "1"}
    if declared is int:
        try:
            return int(value)
        except ValueError:
            return value
    if declared is float:
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _write_config(values: Mapping[str, str]) -> None:
    """Merge `values` into the config file, keeping everything else.

    Read, merge, write - rather than dumping the whole settings model, which
    would write every default as an active value and freeze it at the moment
    the setup was run. `config_template`'s comment about that is the reason.
    """
    if not values:
        # Nothing to merge, so nothing is written. Without this a setup where
        # every answer was left unchanged - the ordinary re-run, and the
        # ordinary first run for somebody happy with the defaults - created a
        # 0-byte `config.toml`, which `config show` then found and printed
        # verbatim. An empty file is worse than no file: with no file at all
        # `show` prints the defaults and says where they came from.
        return
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, object]] = {}
    if path.is_file():
        existing = {
            section: dict(values)
            for section, values in tomllib.loads(
                path.read_text(encoding="utf-8")
            ).items()
            if isinstance(values, dict)
        }

    for key, value in values.items():
        section, _, name = key.partition(".")
        existing.setdefault(section, {})[name] = _as_typed(_field_of(key), value)

    path.write_text(_as_toml_document(existing), encoding="utf-8", newline="\n")


def _write_credentials(secrets: Mapping[tuple[str, str], str]) -> None:
    """Write API keys, each as `(section, variable)`, readable only by
    their owner.

    `credential` searches every section for the variable and takes the
    first, so the section is for the person reading the file - and a key
    is kept in its own, because one filed under a new section would sit
    behind an older value of the same name rather than replace it.

    The mode is set **before** the content is written, so the key is never
    on disk world-readable even briefly.
    """
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, object]] = {}
    if path.is_file():
        existing = {
            section: dict(values)
            for section, values in tomllib.loads(
                path.read_text(encoding="utf-8")
            ).items()
            if isinstance(values, dict)
        }

    for (section, variable), value in secrets.items():
        existing.setdefault(section, {})[variable] = value

    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(_as_toml_document(existing), encoding="utf-8", newline="\n")


def _as_toml_document(sections: Mapping[str, Mapping[str, object]]) -> str:
    lines: list[str] = []
    for section in sorted(sections):
        if not sections[section]:
            continue
        lines.append(f"[{section}]")
        for name in sorted(sections[section]):
            lines.append(f"{name} = {_as_toml_value(sections[section][name])}")
        lines.append("")
    return "\n".join(lines)


def _as_toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


__all__ = [
    "CredentialStatus",
    "Question",
    "QuestionKind",
    "apply_answers",
    "credential_status",
    "questions_for",
    "setup_questions",
    "validate_answer",
]
