"""kennis's configuration as rows on the settings page (12b).

The questions are the engine's: `every_question` is every setting a front
end may offer - `config init` walks a shorter catalogue, and the page took
that walk for the whole until 2026-10-17 - `questions_for` decides which
apply, and
`validate_answer` and `apply_answers` check and write. This module only
lays each one out - its name, its value, what changing it costs, and for a
key the variable it is read from - so the window cannot offer a setting
the command line would refuse, or phrase a cost the command line does not.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from kennis.engine.corpus.converters import MineruConverter
from kennis.engine.corpus.layout import index_root
from kennis.engine.corpus.schema import COLLECTION_NAMES
from kennis.engine.rag.index import read_binding
from kennis.engine.rag.limits import chunk_fit
from kennis.engine.setting_costs import COSTLESS, costs_of
from kennis.engine.settings import (
    CREDENTIALS_KEPT,
    credentials_path,
    default_scopes,
    overriding_variable,
)
from kennis.engine.setup import (
    CredentialStatus,
    Question,
    QuestionKind,
    credential_status,
    every_question,
    questions_for,
)
from kennis.gui import words
from kennis.render.settings import describe_cost, describe_costs, describe_fit
from kennis.scopes import SCOPE_NAMES

type Answers = Mapping[str, str]


# Which headings of the configuration each tab of the settings page
# holds (#670). `window` and `backup` are tabs too and hold none of it.
TAB_GROUPS: Final[dict[str, tuple[str, ...]]] = {
    "searching": ("searching",),
    "documents": ("converting", "adding", "citing", "reading"),
    "system": ("terminal", "logging", "service"),
}

# The settings whose value is an ordered list of names, and the names
# there are: drawn as chips to drag as well as a field.
_ORDERED: Final[dict[str, tuple[str, ...]]] = {
    "retrieval.default_collections": SCOPE_NAMES,
}


@dataclass(frozen=True, slots=True)
class ShownChip:
    """One value an ordered setting may hold, and whether it holds it."""

    name: str
    icon: str
    included: bool
    include_label: str
    earlier_label: str
    later_label: str


def _chips(key: str, value: str) -> tuple[ShownChip, ...]:
    """Every name the setting may list: the listed ones in their order,
    then the rest. A name the value holds and the setting does not know is
    left to the field and its refusal."""
    known = _ORDERED.get(key, ())
    listed = [name for name in dict.fromkeys(default_scopes(value)) if name in known]
    return tuple(
        ShownChip(
            name=name,
            icon=words.COLLECTION_ICONS.get(name, "folder"),
            included=name in listed,
            include_label=words.chip_included(name),
            earlier_label=words.chip_earlier(name),
            later_label=words.chip_later(name),
        )
        for name in (*listed, *(name for name in known if name not in listed))
    )


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
    # Whether a chunk of this size fits the model chosen above it (#577),
    # on the chunk size's row alone; drawn as a warning unless it fits.
    fit: str = ""
    fit_warns: bool = False
    # A field whose change redraws the section, as a choice's does: the
    # chunk size, so its fit is said for the size typed.
    redraws: bool = False
    # For a setting that is an ordered list: every name it may hold, as
    # chips a script lets the reader drag. Empty for every other setting.
    order: tuple[ShownChip, ...] = ()
    # Whether a reset button is drawn beside it - only when the value
    # differs from the default and the reader may change it - with its
    # label. The one way back to the default on the page (#700).
    default: str = ""
    reset_label: str = ""
    # What an empty field says: `(unset)` on the settings page, where empty
    # is a value; nothing in the walk, where it keeps.
    placeholder: str = ""
    # The value saved, whatever the field now holds: `unsaved.js` disables
    # Save while no field differs from it (Brian, 2026-11-24). Empty for a
    # key, whose field is always drawn empty.
    saved: str = ""


@dataclass(frozen=True, slots=True)
class ShownIndex:
    collection: str
    built_with: str


def offered(answers: Answers, *, every: bool = True) -> list[Question]:
    """The questions that apply to these answers.

    What is not offered - `corpus.root`, `backup.folder` - the engine's
    `every_question` leaves out, once. With `every` false, the walk
    `config init` asks instead, `corpus.root` included: the setup wizard's,
    before any corpus exists to be moved (#682).
    """
    return questions_for(answers, every=every)


def answers_in(form: Mapping[str, object]) -> dict[str, str]:
    """A submitted form's text fields, trimmed.

    Not filtered by key: what is written is decided once, by `offered` in
    `changed_answers`, so a key the page leaves out cannot be written
    whatever a form or an edited address carries. A second filter here
    could not be tested, because the first would always hide its absence.
    """
    return {key: value.strip() for key, value in form.items() if isinstance(value, str)}


def shown_settings(
    answers: Answers,
    problems: Mapping[str, str] | None = None,
    *,
    every: bool = True,
) -> list[ShownSetting]:
    found = problems or {}
    offers = _offers()
    questions = offered(answers, every=every)
    # A field sent back empty stays empty, on a redraw and on a refused
    # save: refilled with the value in force, it would undo what the reader
    # did (#666). Only a field that can be emptied; a key is never drawn.
    emptied = {
        question.key
        for question in questions
        if question.kind in _EMPTIABLE and answers.get(question.key) == ""
    }
    values = {
        question.key: _typed(question, answers, offers.get(question.key, set()))
        or question.suggested
        for question in questions
    }
    shown = [
        _with_fit(
            _shown(
                question,
                _typed(question, answers, offers.get(question.key, set())),
                found.get(question.key, ""),
                emptied=question.key in emptied,
            ),
            values,
        )
        for question in questions
    ]
    if every:
        return shown
    # The setup walk reads an empty field as keep, so it offers no reset
    # and says no "(unset)": either would promise what its save does not do.
    return [replace(setting, placeholder="", reset_label="") for setting in shown]


def _with_fit(setting: ShownSetting, values: Mapping[str, str]) -> ShownSetting:
    """The chunk size's row with what its size means for the model chosen."""
    if setting.key != "chunking.size":
        return setting
    redrawn = replace(setting, redraws=True)
    try:
        size = int(values.get("chunking.size", ""))
    except ValueError:
        return redrawn
    model = values.get("embedding.model", "")
    fit = chunk_fit(size, values.get("embedding.backend", "none"), model)
    if fit is None:
        return redrawn
    return replace(
        redrawn,
        fit=describe_fit(fit, model=model),
        fit_warns=fit.verdict != "fits",
    )


def _offers() -> dict[str, set[str]]:
    """Every value the page may have offered for each key, under any backend.

    The value in force and each other backend's own model and width.
    """
    offers: dict[str, set[str]] = {}
    for question in every_question():
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


def changed_answers(
    answers: Answers, *, every: bool = True, empty_is_value: bool = False
) -> dict[str, str]:
    """The answers that differ from what is in force.

    An empty answer means keep, as it does in `config init` - unless
    `empty_is_value`, which the settings page asks for: there every field
    is drawn holding its value, so one sent back empty was emptied, and is
    the empty value; the default is the reset button's alone (Brian,
    2026-11-24, #700). Only a field sent: a tab posts its own, and the
    others' absence still means keep. Never a key, whose field is always
    drawn empty.
    """
    changed: dict[str, str] = {}
    for question in offered(answers, every=every):
        value = answers.get(question.key, "")
        # The environment decides it, so writing the file would say
        # "Saved." and change nothing the reader can see.
        if question.kind != "secret" and overriding_variable(question.key):
            continue
        if (
            empty_is_value
            and not value
            and question.key in answers
            and question.kind != "secret"
        ):
            if question.current:
                changed[question.key] = ""
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


# The heading a setting sits under where its section's is not the one.
_GROUP_OF_KEY: Final[dict[str, str]] = {"literature.citation_style": "citing"}

# The heading a section's settings sit under; any other is searching's.
_GROUP_OF_SECTION: Final[dict[str, str]] = {
    "conversion": "converting",
    "corpus": "adding",
    "literature": "adding",
    "logging": "logging",
    "service": "service",
    "figures": "reading",
    "terminal": "terminal",
}


def _group_of(key: str) -> str:
    """The heading a setting sits under."""
    section = key.partition(".")[0]
    return _GROUP_OF_KEY.get(key, _GROUP_OF_SECTION.get(section, "searching"))


def setting_address(key: str) -> str:
    """Where a setting's field is: its tab's address, at its row (#670).
    What a link elsewhere in the window sends the reader to, so the tab a
    setting is on is decided in one place."""
    group = _group_of(key)
    tab = next(name for name, groups in TAB_GROUPS.items() if group in groups)
    return f"/settings?tab={tab}#setting-{key}"


# The kinds whose field a reader can empty: a choice always holds one of
# its options, a box sends `false` beneath it, and a key is never drawn.
_EMPTIABLE: Final = frozenset({"text", "integer", "number"})


def _shown(
    question: Question, typed: str, problem: str, *, emptied: bool = False
) -> ShownSetting:
    secret = question.kind == "secret"
    value = "" if secret or emptied else typed or question.suggested
    # What the row will be saved as: an emptied field is empty (#700).
    effective = "" if emptied else value
    labels = words.SETTING_CHOICES.get(question.key, {})
    # A key with no cost recorded is one only the setup wizard offers -
    # `corpus.root`, before there is a corpus to move (#682) - so there is
    # no cost to state rather than an unknown one.
    costs = () if question.key in COSTLESS else costs_of(question.key, value)
    return ShownSetting(
        key=question.key,
        group=_group_of(question.key),
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
        order=_chips(question.key, value),
        default=question.default,
        saved="" if secret else question.current,
        placeholder=words.UNSET if question.kind in _EMPTIABLE else "",
        reset_label=(
            words.reset_label(
                words.SETTING_NAMES[question.key],
                _choice_label(question, question.default),
            )
            if not secret
            and not overriding_variable(question.key)
            and effective != question.default
            else ""
        ),
    )


def _choice_label(question: Question, value: str) -> str:
    """A value as the row names it: a choice by its label, else as is."""
    return words.SETTING_CHOICES.get(question.key, {}).get(value, value)


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
