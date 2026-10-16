"""kennis's configuration as rows on the settings page (12b).

The questions are the engine's: `setup_questions` is the catalogue
`config init` walks, `questions_for` decides which apply, and
`validate_answer` and `apply_answers` check and write. This module only
lays each one out - its name, its value, what changing it costs, and for a
key the variable it is read from - so the window cannot offer a setting
the command line would refuse, or phrase a cost the command line does not.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kennis.engine.corpus.converters import MineruConverter
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.rag.index import read_binding
from kennis.engine.setting_costs import COSTLESS, costs_of
from kennis.engine.settings import (
    CREDENTIALS_KEPT,
    credentials_path,
    overriding_variable,
)
from kennis.engine.setup import (
    CredentialStatus,
    Question,
    QuestionKind,
    credential_status,
    questions_for,
    setup_questions,
)
from kennis.gui import words
from kennis.render.settings import describe_cost, describe_costs

type Answers = Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ShownSetting:
    """One row: everything the template needs, decided here."""

    key: str
    # The heading the row sits under: `words.KENNIS_GROUPS`'s first column.
    group: str
    name: str
    # Everything said about the row that need not take a line: what it is
    # for, what changing it costs short of sending anything away, and its
    # key. Drawn as an info tip beside the name.
    tip: str
    kind: QuestionKind
    # What the control holds: the answer given, else the value in force.
    # Always empty for a key, which is never drawn back into a page.
    value: str
    choices: tuple[tuple[str, str], ...]
    minimum: int | None
    maximum: int | None
    # Drawn as a warning: sending a document away is never a default
    # (rules.md 4.5), so choosing it should not read like the rest. The
    # one cost said on the row itself rather than in its tip, because it
    # is a privacy risk; empty when the choice keeps everything here.
    leaves_machine: str
    problem: str
    credential: CredentialStatus | None
    # The command that installs the chosen converter, when it is missing.
    install_hint: str
    # The environment variable that decides this value, when one does:
    # the control is then shown and not offered, because saving it would
    # write a value the environment goes on overriding.
    overridden_by: str = ""


@dataclass(frozen=True, slots=True)
class ShownIndex:
    collection: str
    built_with: str


def offered(answers: Answers) -> list[Question]:
    """The questions that apply to these answers, less what is not offered."""
    return [
        question for question in questions_for(answers) if question.key not in COSTLESS
    ]


def answers_in(form: Mapping[str, object]) -> dict[str, str]:
    """A submitted form's text fields, trimmed.

    Not filtered by key: what is written is decided once, by `offered` in
    `changed_answers`, so a key the page leaves out cannot be written
    whatever a form or an edited address carries. A second filter here
    could not be tested, because the first would always hide its absence.
    """
    return {key: value.strip() for key, value in form.items() if isinstance(value, str)}


def shown_settings(
    answers: Answers, problems: Mapping[str, str] | None = None
) -> list[ShownSetting]:
    found = problems or {}
    offers = _offers()
    return [
        _shown(
            question,
            _typed(question, answers, offers.get(question.key, set())),
            found.get(question.key, ""),
        )
        for question in offered(answers)
    ]


def _offers() -> dict[str, set[str]]:
    """Every value the page may have offered for each key, under any backend.

    The value in force and each other backend's own model and width.
    """
    offers: dict[str, set[str]] = {}
    for question in setup_questions():
        offers.setdefault(question.key, set()).add(question.suggested)
    return offers


def _typed(question: Question, answers: Answers, offers: set[str]) -> str:
    """What the person typed into `question`'s field, or `""`.

    A redraw sends every field back, so a field still holding one of the
    page's own offers carries no answer: it follows the backend. Read as an
    answer, choosing OpenAI kept fastembed's model, and choosing ollama and
    then OpenAI kept ollama's (#441). Anything else was typed, and a redraw
    keeps it.
    """
    value = answers.get(question.key, "")
    return "" if value in offers else value


def changed_answers(answers: Answers) -> dict[str, str]:
    """The answers that differ from what is in force.

    An unchanged value is not written, because writing it would pin a
    default into the file and a later change of default would not reach it.
    An empty answer means keep, as it does in `config init`.
    """
    changed: dict[str, str] = {}
    for question in offered(answers):
        value = answers.get(question.key, "")
        # The environment decides it, so writing the file would say
        # "Saved." and change nothing the reader can see.
        if question.kind != "secret" and overriding_variable(question.key):
            continue
        if value and value != question.current:
            changed[question.key] = value
    return changed


def needs_rebuild(changed: Answers) -> bool:
    return any("rebuild" in costs_of(key, value) for key, value in changed.items())


def shown_indexes(corpus_root: Path) -> list[ShownIndex]:
    """Each collection's index and what it was built with."""
    root = index_root(corpus_root)
    shown: list[ShownIndex] = []
    for collection in COLLECTION_NAMES:
        binding = read_binding(root, collection)
        if binding is None:
            continue
        model = binding.model
        shown.append(
            ShownIndex(
                collection=collection,
                built_with=words.built_with(
                    model.model if model else None,
                    model.kind if model else None,
                    binding.chunking.size,
                ),
            )
        )
    return shown


# The heading a section's settings sit under; any other is searching's.
_GROUP_OF_SECTION: Final[dict[str, str]] = {
    "conversion": "converting",
    "literature": "adding",
}


def _shown(question: Question, typed: str, problem: str) -> ShownSetting:
    secret = question.kind == "secret"
    value = "" if secret else typed or question.suggested
    labels = words.SETTING_CHOICES.get(question.key, {})
    costs = costs_of(question.key, value)
    return ShownSetting(
        key=question.key,
        group=_GROUP_OF_SECTION.get(question.section, "searching"),
        name=words.SETTING_NAMES[question.key],
        tip=words.setting_tip(
            _sentence(question),
            describe_costs([cost for cost in costs if cost != "leaves_machine"]),
            question.key,
        ),
        kind=question.kind,
        value=value,
        choices=tuple((option, labels[option]) for option in question.options),
        minimum=question.minimum,
        maximum=question.maximum,
        leaves_machine=(
            describe_cost("leaves_machine") if "leaves_machine" in costs else ""
        ),
        problem=problem,
        credential=credential_status(question.key) if secret else None,
        install_hint=_missing_converter(question.key, value),
        overridden_by="" if secret else overriding_variable(question.key) or "",
    )


def _sentence(question: Question) -> str:
    """What a setting is for, in the window's words when it has them.

    The engine's description is written for `config init` and the config
    file; a key the window has no words for falls back to it.
    """
    if question.kind == "secret":
        backend = question.when[0][1] if question.when else ""
        kept = words.credential_tip(backend, credentials_path().name, CREDENTIALS_KEPT)
        return f"{kept} {words.CREDENTIAL_KEEP}"
    return words.SETTING_TIPS.get(question.key, question.description)


def _missing_converter(key: str, value: str) -> str:
    """The install command for MinerU when it is chosen and absent.

    Datalab has nothing to install - its key is the requirement, and the
    key's own row says whether it is set.
    """
    if key != "conversion.backend" or value != "mineru":
        return ""
    converter = MineruConverter()
    return "" if converter.is_available() else converter.install_hint()


__all__ = [
    "ShownIndex",
    "ShownSetting",
    "answers_in",
    "changed_answers",
    "needs_rebuild",
    "offered",
    "shown_indexes",
    "shown_settings",
]
