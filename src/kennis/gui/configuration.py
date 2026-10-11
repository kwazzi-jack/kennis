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

from kennis.engine.corpus.converters import MineruConverter
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.rag.index import read_binding
from kennis.engine.setting_costs import COSTLESS, costs_of
from kennis.engine.setup import (
    CredentialStatus,
    Question,
    QuestionKind,
    credential_status,
    questions_for,
)
from kennis.gui import words
from kennis.render.settings import describe_costs

type Answers = Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ShownSetting:
    """One row: everything the template needs, decided here."""

    key: str
    # The heading the row sits under: `words.KENNIS_GROUPS`'s first column.
    group: str
    name: str
    sentence: str
    kind: QuestionKind
    # What the control holds: the answer given, else the value in force.
    # Always empty for a key, which is never drawn back into a page.
    value: str
    choices: tuple[tuple[str, str], ...]
    minimum: int | None
    maximum: int | None
    cost: str
    # Drawn as a warning: sending a document away is never a default
    # (rules.md 4.5), so choosing it should not read like the rest.
    leaves_machine: bool
    problem: str
    credential: CredentialStatus | None
    # The command that installs the chosen converter, when it is missing.
    install_hint: str


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
    return [
        _shown(question, answers, found.get(question.key, ""))
        for question in offered(answers)
    ]


def changed_answers(answers: Answers) -> dict[str, str]:
    """The answers that differ from what is in force.

    An unchanged value is not written, because writing it would pin a
    default into the file and a later change of default would not reach it.
    An empty answer means keep, as it does in `config init`.
    """
    changed: dict[str, str] = {}
    for question in offered(answers):
        value = answers.get(question.key, "")
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


def _shown(question: Question, answers: Answers, problem: str) -> ShownSetting:
    secret = question.kind == "secret"
    value = "" if secret else answers.get(question.key) or question.current
    labels = words.SETTING_CHOICES.get(question.key, {})
    costs = costs_of(question.key, value)
    return ShownSetting(
        key=question.key,
        group="converting" if question.section == "conversion" else "searching",
        name=words.SETTING_NAMES[question.key],
        sentence=question.description,
        kind=question.kind,
        value=value,
        choices=tuple((option, labels[option]) for option in question.options),
        minimum=question.minimum,
        maximum=question.maximum,
        cost=describe_costs(costs),
        leaves_machine="leaves_machine" in costs,
        problem=problem,
        credential=credential_status(question.key) if secret else None,
        install_hint=_missing_converter(question.key, value),
    )


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
