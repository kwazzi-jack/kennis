"""The words for what changing a setting costs.

`describe_cost` is exhaustive over `SettingCost`: a fifth cost added
without a sentence is a type error, not a blank cell on the settings page.
`kennis config set` and the window both print `describe_costs`, so the
two say the same thing about the same change.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import assert_never

from kennis.engine.setting_costs import SettingCost


def describe_cost(cost: SettingCost) -> str:
    match cost:
        case "next_search":
            return "takes effect at the next search"
        case "next_add":
            return "takes effect at the next add"
        case "next_index":
            return "takes effect at the next index"
        case "next_command":
            return "takes effect at the next command"
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


__all__ = [
    "describe_cost",
    "describe_costs",
    "describe_overridden",
    "describe_unknown_settings",
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
