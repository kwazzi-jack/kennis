"""Every button in the window by one rule (#670; sketch
`2026-11-13-button-review`).

Brian, 2026-11-13: the save button was hard to find, and "this goes for all
buttons". A button with words is never borderless and muted, a button is
never drawn as underlined text, and the one action a form exists for is
filled and carries an icon. Read from the templates' source, because a
template draws a button in more states than a test would render; the table
of each template's main action is written by hand, so a button changing
kind fails here rather than agreeing with itself (#373).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).parent.parent / "src/kennis/gui/templates"

# Kinds of control with their own drawing, which the rule leaves alone.
STRUCTURAL = frozenset(
    {"item", "segment", "action", "tip-button", "bookmark-tab", "entry"}
)


@dataclass(frozen=True)
class Drawn:
    template: str
    line: int
    tag: str
    classes: frozenset[str]
    attributes: str
    label: str
    has_icon: bool

    def __str__(self) -> str:
        classes = sorted(self.classes)
        return (
            f"{self.template}:{self.line} <{self.tag} class={classes}> {self.label!r}"
        )


def _drawn() -> list[Drawn]:
    found: list[Drawn] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        # Template comments say what a button is for and are not buttons.
        source = re.sub(
            r"\{#.*?#\}",
            lambda match: "\n" * match.group().count("\n"),
            source,
            flags=re.S,
        )
        for match in re.finditer(
            r"<(button|a)\b([^>]*)>(.*?)</\1>", source, flags=re.S
        ):
            tag, attributes, inner = match.groups()
            classes = re.search(r'class="([^"]*)"', attributes)
            names = frozenset((classes.group(1) if classes else "").split())
            # Only what is drawn as a button or a menu entry: an `<a>` is a
            # link otherwise.
            if tag == "a" and not names & {"button", "item"}:
                continue
            words_only = re.sub(r"\{\{\s*icon\([^}]*\}\}", "", inner)
            words_only = re.sub(r"<[^>]+>", "", words_only)
            found.append(
                Drawn(
                    template=str(path.relative_to(TEMPLATES)),
                    line=source[: match.start()].count("\n") + 1,
                    tag=tag,
                    classes=names,
                    attributes=attributes,
                    label=" ".join(words_only.split()),
                    has_icon="icon(" in inner,
                )
            )
    return found


DRAWN = _drawn()


def kind_of(button: Drawn) -> str:
    if button.classes & STRUCTURAL or "visually-hidden" in button.classes:
        return "structural"
    if "danger" in button.classes:
        return "danger"
    if "primary" in button.classes:
        return "primary"
    if "ghost" in button.classes:
        return "icon alone"
    return "secondary"


# The one action each template's form or offer exists for, by the words
# its label is drawn from - written by hand.
EXPECTED_PRIMARY: dict[str, list[str]] = {
    "base.html": ["{{ corpus_changed_reload }}"],
    "chooser.html": ["{{ choose_folder }}"],
    "forms/add.html": ["{{ add_action }}"],
    "forms/clear-history.html": ["{{ clear_history_action }}"],
    "forms/delete-project.html": ["{{ delete_project_action }}"],
    "forms/forget-project.html": ["{{ forget_project_action }}"],
    "forms/index.html": ["{{ index_action }}"],
    "forms/new-project.html": ["{{ new_project_action }}"],
    "forms/pack.html": ["{{ pack_action }}"],
    "forms/project-packs.html": ["{{ project_packs_action }}"],
    "forms/remember.html": ["{{ action }}"],
    "forms/remove-document.html": ["{{ remove_document_action }}"],
    "forms/remove-version.html": ["{{ remove_version_action }}"],
    "forms/reset-project.html": ["{{ reset_project_action }}"],
    "forms/return.html": ["{{ return_action }}"],
    "forms/supply.html": ["{{ supply_action }}"],
    "forms/sync-project.html": ["{{ sync_project_action }}"],
    "forms/sync.html": ["{{ sync_corpus_action }}"],
    "forms/tag.html": ["{{ tag_action }}"],
    "forms/uninstall-pack.html": ["{{ uninstall_pack_action }}"],
    "job-outcome.html": ["{{ index_now_label }}", "{{ sync_corpus_label }}"],
    "outcome.html": ["{{ index_now_label }}"],
    "returned.html": ["{{ index_now }}"],
    "settings-backup.html": ["{{ backup_now_label }}"],
    "settings-kennis.html": ["{{ rebuild_now }}", "{{ kennis_save }}"],
    "settings.html": ["{{ save_label }}"],
}


def test_the_scan_finds_the_window_s_buttons() -> None:
    """A fixture assumption is an assertion (#362): a scan that matched
    nothing would pass every test below."""
    assert len(DRAWN) > 100
    assert any(button.label == "{{ add_action }}" for button in DRAWN)


@pytest.mark.parametrize(
    "button", [b for b in DRAWN if kind_of(b) == "icon alone"], ids=str
)
def test_a_borderless_button_has_no_words_and_says_what_it_does(button: Drawn) -> None:
    """A ghost has no border and muted text until hovered, which is what
    made an action hard to find. Kept for a control that is an icon alone,
    which a screen reader learns from its label."""
    assert not button.label, f"{button}: words on a borderless button"
    assert button.has_icon, button
    assert "aria-label=" in button.attributes, button


def test_no_button_is_drawn_as_underlined_text() -> None:
    """Brian's standing rule: a button with an icon, never link text.

    Every `<a>` and `<button>` in the source, not `DRAWN`: the scan keeps an
    `<a>` only when it is drawn as a button, so `a.later` - the defect this
    exists for - would never reach it."""
    # Whole class names: `\b` takes a hyphen as a boundary, and `skip-link`
    # is the page's link to its own content, not an action.
    drawn_as_text = [
        f"{path.name}: {match.group()}"
        for path in sorted(TEMPLATES.rglob("*.html"))
        for match in re.finditer(
            r'<(?:a|button)\b[^>]*class="([^"]*)"', path.read_text(encoding="utf-8")
        )
        if set(match.group(1).split()) & {"link", "later"}
    ]
    assert drawn_as_text == []


def test_no_link_offered_as_an_action_is_bare_text() -> None:
    """`a.later` was a link drawn as muted text beside two buttons. Every
    `<a>` that stands in a row of actions is drawn as a button."""
    for path in sorted(TEMPLATES.rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<a\b[^>]*\bdata-later\b[^>]*>", source):
            assert 'class="button' in match.group(), f"{path.name}: {match.group()}"


@pytest.mark.parametrize(
    "button", [b for b in DRAWN if kind_of(b) in ("primary", "danger")], ids=str
)
def test_a_main_or_removing_action_carries_an_icon(button: Drawn) -> None:
    assert button.has_icon, button


@pytest.mark.parametrize("button", [b for b in DRAWN if "item" in b.classes], ids=str)
def test_a_menu_item_carries_an_icon(button: Drawn) -> None:
    assert button.has_icon, button


def test_each_template_s_main_action_is_the_one_written_here() -> None:
    drawn: dict[str, list[str]] = {}
    for button in DRAWN:
        if kind_of(button) == "primary" or (
            kind_of(button) == "danger" and "primary" in button.classes
        ):
            drawn.setdefault(button.template, []).append(button.label)

    assert drawn == EXPECTED_PRIMARY


def test_a_form_has_at_most_one_main_action() -> None:
    for path in sorted(TEMPLATES.rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        for form in re.findall(r"<form\b.*?</form>", source, flags=re.S):
            primaries = re.findall(r'<(?:button|a)\b[^>]*class="[^"]*\bprimary\b', form)
            assert len(primaries) <= 1, f"{path.name}: {form[:120]}"
