"""This window's own preferences: what each is, and which one is in force.

**A preference is a cookie the server renders.** Each is written onto
`<html>` as `data-<name>` from the request, so the first byte is already
right - read from browser storage after paint, every page would draw in
the defaults and then repaint. The name is the cookie, the attribute and
the form field at once, so there is one spelling to keep in step.

**None of them is kennis's configuration.** The command line and the MCP
server never read them; kennis's own settings are written through
`engine/setup.py` and are milestone 12's other half.

The words are in `gui/words.py`; this module holds the values and the
defaults, and the default is always what the window did before there was
a choice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from starlette.requests import Request

from kennis.gui import words

type Section = Literal["appearance", "results"]

# A year: a preference is kept until it is changed, and a browser that
# outlives that asks again by showing the defaults.
COOKIE_SECONDS: Final = 31_536_000


@dataclass(frozen=True, slots=True)
class Preference:
    """One preference: its choices as (value, words), its default, and
    the section of the page it is shown in."""

    name: str
    label: str
    sentence: str
    choices: tuple[tuple[str, str], ...]
    default: str
    section: Section

    def offers(self, value: str) -> bool:
        return any(value == offered for offered, _ in self.choices)


def _preference(name: str, default: str, section: Section) -> Preference:
    label, sentence = words.PREFERENCE_WORDS[name]
    choices = words.THEME_CHOICES if name == "theme" else words.PREFERENCE_CHOICES[name]
    return Preference(
        name=name,
        label=label,
        sentence=sentence,
        choices=choices,
        default=default,
        section=section,
    )


# In the order the page shows them.
PREFERENCES: Final[dict[str, Preference]] = {
    preference.name: preference
    for preference in (
        _preference("theme", "system", "appearance"),
        _preference("face", "serif", "appearance"),
        _preference("size", "normal", "appearance"),
        _preference("spacing", "normal", "appearance"),
        _preference("strength", "bars", "results"),
        _preference("labels", "icons", "results"),
        _preference("scale", "viridis", "results"),
    )
}


def preference_of(request: Request, name: str) -> str:
    """The value in force: the cookie's, only when it is one offered.

    Anything can be in a cookie. `data-face="comic"` would match no rule
    and fall through to the default anyway, but relying on that is
    relying on the cascade to absorb bad input.
    """
    preference = PREFERENCES[name]
    asked = request.cookies.get(name, preference.default)
    return asked if preference.offers(asked) else preference.default


def preferences_of(request: Request) -> dict[str, str]:
    """Every preference in force, by name, for the root element."""
    return {name: preference_of(request, name) for name in PREFERENCES}


def chosen_in(form: Mapping[str, object]) -> dict[str, str]:
    """The preferences a submitted form names with a value offered.

    A value not offered is dropped rather than replaced with the default:
    saving the default would overwrite a choice the reader made earlier.
    """
    chosen: dict[str, str] = {}
    for name, preference in PREFERENCES.items():
        value = form.get(name)
        if isinstance(value, str) and preference.offers(value):
            chosen[name] = value
    return chosen


__all__ = [
    "COOKIE_SECONDS",
    "PREFERENCES",
    "Preference",
    "Section",
    "chosen_in",
    "preference_of",
    "preferences_of",
]
