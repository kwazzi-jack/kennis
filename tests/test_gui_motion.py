"""Things arrive rather than appear, briefly, and not at all for a reader
who has asked for less motion.

Brian, 2026-10-12: "modern and crisp and efficient". Each entry is CSS
alone - `@starting-style` and a cross-document view transition - so no
script handles an event for it, and `sketches/2026-10-12-motion.md`
says why each place moves.
"""

from __future__ import annotations

import re

from kennis.gui.theme import stylesheet

# Written by hand: the elements that arrive with an entry, and the
# longest any motion may take, in seconds.
EXPECTED_ENTRIES = [".dialog[open]", ".dialog[open]::backdrop", ".menu-items", ".hit"]
LONGEST = 0.25


def code() -> str:
    return re.sub(r"/\*.*?\*/", "", stylesheet(), flags=re.S)


def starting_styles(css: str) -> dict[str, str]:
    """Each selector inside an `@starting-style` block, with its body."""
    found: dict[str, str] = {}
    for block in re.findall(r"@starting-style\s*\{((?:[^{}]|\{[^{}]*\})*)\}", css):
        for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", block):
            for selector in head.split(","):
                found[selector.strip()] = body
    return found


def test_each_entry_starts_invisible_and_is_transitioned():
    css = code()
    starts = starting_styles(css)

    for selector in EXPECTED_ENTRIES:
        assert selector in starts, selector
        assert "opacity: 0" in starts[selector] or "transparent" in starts[selector]


def test_a_new_job_in_the_strip_fades_in():
    assert ".strip .job" in starting_styles(code())


def test_moving_between_pages_crossfades_and_holds_the_shell_still():
    css = code()

    assert re.search(r"@view-transition\s*\{\s*navigation: auto;\s*\}", css)
    for element, name in ((".bar", "bar"), (".pane", "pane"), (".strip", "strip")):
        rule = re.search("^" + re.escape(element) + r" \{([^}]*)\}", css, re.M)
        assert rule and f"view-transition-name: {name}" in rule.group(1), element


def test_no_motion_is_longer_than_a_quarter_second():
    """Crisp: a longer motion is one the reader waits for. The passage's
    growth is the one exception, since its distance is a whole passage."""
    css = code()
    for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if ".passage" in head or "prefers-reduced-motion" in head:
            continue
        for value in re.findall(r"(?:transition|animation)[^:]*:([^;]*)", body):
            for seconds in re.findall(r"\b(\d*\.?\d+)s\b", value):
                if "turning" in value:
                    continue
                assert float(seconds) <= LONGEST, (head.strip(), value)


def test_reduced_motion_turns_off_the_page_transition_too():
    """`*` selects no view transition pseudo-element, so the rule that
    shortens every other motion does not reach this one."""
    css = code()
    reduced = re.findall(
        r"@media \(prefers-reduced-motion: reduce\)\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
        css,
    )

    assert any(
        re.search(r"@view-transition\s*\{\s*navigation: none;\s*\}", block)
        for block in reduced
    )
    assert any("transition-duration: 0.01ms" in block for block in reduced)


def test_a_button_presses_down():
    rule = re.search(r"button:active,\s*a\.button:active\s*\{([^}]*)\}", code())

    assert rule and "translate: 0 1px" in rule.group(1)
