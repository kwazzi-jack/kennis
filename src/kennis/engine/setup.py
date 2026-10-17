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
from pathlib import Path
from typing import Final, Literal, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from kennis.engine.atomic import replace_file
from kennis.engine.corpus.converters import DATALAB_KEY_VARIABLE
from kennis.engine.errors import SettingsError
from kennis.engine.settings import (
    CREDENTIALS_KEPT,
    EMBEDDING_DEFAULTS,
    Settings,
    config_document,
    config_path,
    credential,
    credentials_path,
    load_settings,
    repair_of,
    section_models,
    toml_value,
)

type QuestionKind = Literal["choice", "text", "integer", "number", "boolean", "secret"]


@dataclass(frozen=True, slots=True)
class Question:
    """One thing the setup needs to know.

    Facts only, per #81: the key it sets, what kind of value it takes, what
    is currently in effect, and the constraints. `description` is the
    pydantic field's own, which is schema metadata rather than composed
    prose - the same text `config_document` emits, for the same reason.

    `when` is a conjunction of `(key, value)` pairs over the answers given so
    far. A value rather than a callback, so a form can evaluate it to decide
    what to show without running kennis's code per keystroke.

    `current` is what is in force and `suggested` what to offer. They
    differ only for the model asked under a backend not in force (#441). A
    front end offers `suggested`, and compares an answer with `current` to
    say what changed; every setting is written either way (#445).
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
    ("embedding.model", "text", (("embedding.backend", "fastembed"),)),
    ("embedding.base_url", "text", (("embedding.backend", "ollama"),)),
    ("embedding.model", "text", (("embedding.backend", "ollama"),)),
    ("embedding.model", "text", (("embedding.backend", "openai"),)),
    ("embedding.api_key", "secret", (("embedding.backend", "openai"),)),
    ("conversion.backend", "choice", ()),
    # Before the key: the mode is a price, and nobody wants to retype a key
    # because a cheap question came after it.
    ("conversion.mode", "choice", (("conversion.backend", "datalab"),)),
    ("conversion.api_key", "secret", (("conversion.backend", "datalab"),)),
    ("retrieval.corpus_method", "choice", ()),
    ("retrieval.default_top_k", "integer", ()),
    ("chunking.size", "integer", ()),
    # Whose address Unpaywall is asked with: a paper known only by its DOI
    # is otherwise one the reader must fetch by hand (#475).
    ("literature.unpaywall_email", "text", ()),
    ("corpus.root", "text", ()),
)

# Every other setting, for a front end that offers them all: the settings
# page (Brian, 2026-10-17). The walk is what a new user is asked; this is
# what anyone may change. Each kind comes from the field's annotation, and
# a condition is kept only where a setting means nothing otherwise.
_EMBEDDING_BACKENDS: Final = ("fastembed", "ollama", "openai")
_ALSO_OFFERED: Final[tuple[tuple[str, tuple[tuple[str, str], ...]], ...]] = (
    *(
        (key, (("embedding.backend", backend),))
        for key in ("embedding.normalise", "embedding.batch_size")
        for backend in _EMBEDDING_BACKENDS
    ),
    ("embedding.api_key_env", (("embedding.backend", "openai"),)),
    ("chunking.overlap", ()),
    ("retrieval.context_method", ()),
    ("corpus.keep_original", ()),
    ("corpus.default_group", ()),
    ("conversion.repair_ligatures", (("conversion.backend", "mineru"),)),
    ("conversion.batch_size", ()),
    ("literature.request_delay", ()),
    ("logging.level", ()),
    ("logging.max_bytes", ()),
    ("logging.backup_count", ()),
)
# What a front end offering every setting leaves out. `corpus.root` moves
# the corpus from under whatever is open; `backup.folder` is chosen where
# the backup is made, beside the chooser and the test.
_NOT_OFFERED: Final = frozenset({"corpus.root", "backup.folder"})
# Where each key sits among its section's fields. A secret is no field of
# the model, so it sits after the field it belongs with.
_SECRET_AFTER: Final[dict[str, str]] = {
    "embedding.api_key": "api_key_env",
    "conversion.api_key": "mode",
}


def setup_questions() -> tuple[Question, ...]:
    """Every question the setup can ask, in the order it would ask them.

    The whole catalogue, conditions and all. `questions_for` filters it;
    this is what a form binds to and what a test enumerates.
    """
    settings = load_settings()
    return tuple(_question(key, kind, when, settings) for key, kind, when in _ASKED)


def every_question() -> tuple[Question, ...]:
    """Every setting a front end may offer, in the configuration file's order.

    The walk's questions, conditions and secrets included, and every other
    setting beside them, less `_NOT_OFFERED`. In the model's order rather
    than the walk's, so a setting sits beside its neighbours; a key asked
    under several conditions keeps the walk's order among them.
    """
    settings = load_settings()
    entries = [
        (key, kind, when) for key, kind, when in _ASKED if key not in _NOT_OFFERED
    ] + [(key, _kind_of(key), when) for key, when in _ALSO_OFFERED]
    entries.sort(key=lambda entry: _position_of(entry[0]))
    return tuple(_question(key, kind, when, settings) for key, kind, when in entries)


def questions_for(answers: Mapping[str, str], *, every: bool = False) -> list[Question]:
    """The questions that apply, given what has been answered so far.

    `every` widens the walk to `every_question`.

    A question whose condition names a key that has not been answered yet is
    judged against the value currently in effect, so a setup run that skips
    straight to the end still asks the right things.
    """
    settled = dict(answers)
    applicable: list[Question] = []
    for question in every_question() if every else setup_questions():
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
    # The key first: a configuration naming a backend whose key failed to
    # save is the half-written state this function promises not to leave.
    if secrets:
        _write_credentials(
            {
                (key.partition(".")[0], _key_variable(key, settings)): value
                for key, value in secrets.items()
            }
        )
    _write_config({key: value for key, value in given.items() if key not in secrets})
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
                f"{CREDENTIALS_KEPT}, and never written to the config file."
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
    """What a front end offers for `key`: the value in force, unless it is
    the model asked for an embedding backend other than the one in force.

    Then the model in force belongs to the other backend, and this
    backend's own model is offered instead (#441). Not `current`, because
    `current` is what an answer is compared with to say what changed.
    """
    backend = dict(when).get("embedding.backend")
    model = EMBEDDING_DEFAULTS.get(backend or "")
    if key == "embedding.model" and model and backend != settings.embedding.backend:
        return model
    return _current(key, settings)


# By identity, so `bool` is never taken for the `int` it subclasses.
_KIND_OF_TYPE: Final[dict[object, QuestionKind]] = {
    bool: "boolean",
    int: "integer",
    float: "number",
}


def _kind_of(key: str) -> QuestionKind:
    annotation = _field_of(key).annotation
    if get_origin(annotation) is Literal:
        return "choice"
    return _KIND_OF_TYPE.get(annotation, "text")


def _position_of(key: str) -> tuple[int, float]:
    section, _, name = key.partition(".")
    sections = list(Settings.model_fields)
    annotation = Settings.model_fields[section].annotation
    fields = list(getattr(annotation, "model_fields", {}))
    if name in fields:
        return sections.index(section), float(fields.index(name))
    return sections.index(section), fields.index(_SECRET_AFTER[key]) + 0.5


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
    if question.kind == "number":
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"'{value}' is not a number") from None
    if question.kind == "boolean":
        if value.lower() not in {"true", "false", "yes", "no"}:
            return _refuse_boolean(value)
        return value.lower() in {"true", "yes"}
    return value


def _refuse_boolean(value: str) -> bool:
    raise ValueError(f"'{value}' is not true or false")


def _validated(given: Mapping[str, str]) -> Settings:
    """The settings these answers produce, or the first reason they do not.

    Built through the models rather than by checking the strings, so the
    answer to "is this acceptable" is the same one `load_settings` would
    give and cannot drift from it.

    **Against the file, not the environment**, as `_write_config` writes
    it. Settled through `load_settings`, a bad value in the file - or one
    exported for this shell - refused every `config set`, including the
    one that would have replaced it. An answer replaces the file's value
    for its own key, so the repair a refusal names always goes through.
    """
    held = _held()
    for key, value in given.items():
        if _is_secret(key):
            continue
        section, _, name = key.partition(".")
        field = _field_of(key)
        held.setdefault(section, {})[name] = _as_typed(key, field, value)

    sections: dict[str, BaseModel] = {}
    for section, model in section_models().items():
        try:
            sections[section] = model.model_validate(held.get(section, {}))
        except ValidationError as error:
            first = error.errors()[0]
            key = ".".join(str(part) for part in (section, *first["loc"][:1]))
            path = config_path()
            where = key if key in given else f"{key} in {path}"
            raise SettingsError(
                f"{where}: {first['msg']}", resolution=repair_of(key, path)
            ) from error
    return Settings.model_construct().model_copy(update=sections)


def _held() -> dict[str, dict[str, object]]:
    """What `config.toml` holds, section by section, unchecked."""
    path = config_path()
    if not path.is_file():
        return {}
    return {
        section: dict(entries)
        for section, entries in _toml_of(path).items()
        if isinstance(entries, dict)
    }


_TRUE: Final = frozenset({"true", "yes", "on", "1"})
_FALSE: Final = frozenset({"false", "no", "off", "0"})


def _as_typed(key: str, field: FieldInfo, value: str) -> object:
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
        # Refused rather than read as false: `ture` was stored as `false`,
        # said "Set" and quietly turned a feature off.
        answer = value.strip().lower()
        if answer in _TRUE:
            return True
        if answer in _FALSE:
            return False
        raise SettingsError(
            f"'{value}' is not true or false",
            resolution=f"kennis config set {key} true",
        )
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
    """Write the whole file: every section's defaults, then what the file
    holds, then `values`.

    Every setting is written, including one at its default, so the file
    says what is in use and can be synced (Brian, 2026-10-12). **The
    environment is not a source**: a variable exported for one shell would
    otherwise outlive it, so each section is read through its own model,
    which does not consult the environment as `Settings` does. A key the
    model no longer has is dropped; kennis keeps no compatibility before
    v1.0.0.
    """
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    held = _held()

    for key, value in values.items():
        section, _, name = key.partition(".")
        held.setdefault(section, {})[name] = _as_typed(key, _field_of(key), value)

    complete = {
        section: model.model_validate(held.get(section, {})).model_dump()
        for section, model in section_models().items()
    }
    replace_file(path, config_document(complete))


def _write_credentials(secrets: Mapping[tuple[str, str], str]) -> None:
    """Write API keys, each as `(section, variable)`, readable only by
    their owner where the platform has file modes.

    `credential` searches every section for the variable and takes the
    first, so the section is for the person reading the file - and a key
    is kept in its own, because one filed under a new section would sit
    behind an older value of the same name rather than replace it.

    The file is never on disk world-readable, even briefly: see below.
    """
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, object]] = {}
    if path.is_file():
        existing = {
            section: dict(values)
            for section, values in _toml_of(path).items()
            if isinstance(values, dict)
        }

    for (section, variable), value in secrets.items():
        existing.setdefault(section, {})[variable] = value

    # Written whole and swapped in: `mkstemp` makes the temporary file 0600
    # before a byte is written, and the rename carries that mode over an
    # existing file too. A Ctrl-C part-way leaves the old file, not half of
    # a new one.
    replace_file(path, _as_toml_document(existing))
    # Said as well as relied on; a no-op where the platform has no mode.
    path.chmod(0o600)


def _toml_of(path: Path) -> dict[str, object]:
    """A TOML file kennis keeps, or a refusal naming it: a truncated file
    raised a bare `TOMLDecodeError` out of a save, with a traceback."""
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise SettingsError(
            f"{path} is not valid TOML ({error})",
            resolution=f"fix or remove {path}",
        ) from error


def _as_toml_document(sections: Mapping[str, Mapping[str, object]]) -> str:
    lines: list[str] = []
    for section in sorted(sections):
        if not sections[section]:
            continue
        lines.append(f"[{section}]")
        for name in sorted(sections[section]):
            lines.append(f"{name} = {toml_value(sections[section][name])}")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "CredentialStatus",
    "Question",
    "QuestionKind",
    "apply_answers",
    "credential_status",
    "every_question",
    "questions_for",
    "setup_questions",
    "validate_answer",
]
