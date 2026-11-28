"""The words for what changing a setting costs.

`describe_cost` is exhaustive over `SettingCost`: a fifth cost added
without a sentence is a type error, not a blank cell on the settings page.
`kennis config set` and the window both print `describe_costs`, so the
two say the same thing about the same change.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, assert_never

from kennis.engine.setting_costs import SettingCost

if TYPE_CHECKING:
    from kennis.engine.rag.limits import ChunkFit
    from kennis.engine.setup import Question, QuestionKind

# One fact about a setting, as `kennis config info` lists it: a label and
# its value.
type SettingFact = tuple[str, str]


def describe_cost(cost: SettingCost) -> str:
    match cost:
        case "next_search":
            return "takes effect at the next search"
        case "next_add":
            return "takes effect at the next add"
        case "next_index":
            return "takes effect at the next index"
        case "next_cite":
            return "takes effect at the next citation"
        case "next_command":
            return "takes effect at the next command"
        case "next_document":
            return "takes effect at the next document opened"
        case "next_start":
            return "takes effect the next time kennis starts"
        case "rebuild":
            return "takes effect in each index only once it is rebuilt"
        case "leaves_machine":
            return "sends document text to a third party"
        case _:
            assert_never(cost)


def describe_costs(costs: Sequence[SettingCost]) -> str:
    return "; ".join(describe_cost(cost) for cost in costs)


def describe_kind(kind: QuestionKind) -> str:
    """What a setting's value is, as the settings page's field takes it."""
    match kind:
        case "choice":
            return "one of the values"
        case "text":
            return "text"
        case "integer":
            return "whole number"
        case "number":
            return "number"
        case "boolean":
            return "true or false"
        case "secret":
            return "secret, kept out of the config file"
        case _:
            assert_never(kind)


def setting_facts(
    questions: Sequence[Question], *, secret_is_set: bool = False
) -> list[SettingFact]:
    """What `kennis config info` says about one setting.

    `questions` are every question for one key - a key asked under each
    backend is several - and say the same thing but their condition. A
    secret's value is never given, only whether one is held.
    """
    first = questions[0]
    facts: list[SettingFact] = [("type", describe_kind(first.kind))]
    if first.options:
        facts.append(("values", " | ".join(first.options)))
    elif first.minimum is not None and first.maximum is not None:
        facts.append(("values", f"{first.minimum} to {first.maximum}"))
    elif first.minimum is not None:
        facts.append(("values", f"at least {first.minimum}"))
    if first.kind == "secret":
        facts.append(("current", "(set)" if secret_is_set else "(unset)"))
    else:
        facts.append(("default", first.default or "(unset)"))
        facts.append(("current", first.current or "(unset)"))
    applies = _describe_conditions([question.when for question in questions])
    if applies:
        facts.append(("applies", applies))
    return facts


def _describe_conditions(conditions: Sequence[tuple[tuple[str, str], ...]]) -> str:
    """When a setting is used: `when embedding.backend is fastembed, ollama
    or openai`. Empty for one used always."""
    if not any(conditions):
        return ""
    keys = {pair[0] for condition in conditions for pair in condition}
    if len(keys) == 1 and all(len(condition) == 1 for condition in conditions):
        values = [condition[0][1] for condition in conditions]
        return f"when {keys.pop()} is {_listed(values)}"
    return "when " + " or ".join(
        " and ".join(f"{key} is {value}" for key, value in condition)
        for condition in conditions
    )


def _listed(values: Sequence[str]) -> str:
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])} or {values[-1]}"


__all__ = [
    "SettingFact",
    "describe_cost",
    "describe_costs",
    "describe_kind",
    "describe_overridden",
    "describe_unknown_settings",
    "setting_facts",
]


def describe_overridden(variable: str) -> str:
    """A value just written that the environment goes on overriding.

    Said after `config set`, which wrote the file and printed "Set" while
    `config get` went on showing the variable's value.
    """
    return (
        f"{variable} is set and overrides the file, so this takes effect only "
        f"once it is unset"
    )


def describe_unknown_settings(keys: Sequence[str], path: str) -> str:
    """Names in the configuration file that kennis does not read (#480).

    A misspelling, or a setting a later kennis removed. Every write renders
    the whole file from the settings kennis has, so the next one drops them.
    """
    named = ", ".join(keys)
    return (
        f"{path} sets {named}, which kennis does not read, so it has no "
        f"effect; the next change to the configuration removes it"
        if len(keys) == 1
        else f"{path} sets {named}, which kennis does not read, so they have "
        f"no effect; the next change to the configuration removes them"
    )


def describe_fit(fit: ChunkFit, *, model: str) -> str:
    """Whether a chunk of the configured size fits `model`, with the numbers.

    Every count of tokens is an estimate from measured ratios (#577), and the
    sentence says so, because a person choosing a size reads it as a promise
    otherwise.
    """
    bound = (
        f"a chunk is at most {fit.ceiling} characters: an estimated "
        f"{fit.prose_tokens} tokens of prose, and up to about "
        f"{fit.densest_tokens} for a dense table of that length"
    )
    match fit.verdict:
        case "fits":
            return f"{bound}; {model} reads {fit.model_tokens}, so every chunk fits"
        case "dense-may-not-fit":
            return (
                f"{bound}; {model} reads {fit.model_tokens}: prose fits, but a "
                "dense table or equation near that length does not, and a "
                "meaning search sees only its beginning"
            )
        case "may-not-fit":
            return (
                f"{bound}; {model} reads {fit.model_tokens}, so even a chunk of "
                "prose is longer than that, and a meaning search sees only its "
                "beginning; a smaller chunking.size fits it"
            )
        case "unknown":
            return (
                f"{bound}; kennis does not know how many tokens {model} reads, "
                "so it cannot say whether a chunk fits"
            )
        case _:
            assert_never(fit.verdict)
