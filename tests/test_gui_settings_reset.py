"""A setting back to its default from the window (#666, #700).

On the settings page an emptied field is the empty value, refused beside
its field where empty means nothing, and only the reset button beside a
setting that differs from its default puts the default into the form
(Brian, 2026-11-24, replacing 2026-11-18's "emptied is the default"). The
setup walk keeps "empty means keep", and so does a key.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.settings import EMBEDDING_DEFAULTS, load_settings
from kennis.engine.setup import Question, apply_answers, every_question
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.gui.configuration import changed_answers, shown_settings
from test_gui_kennis_settings import (
    HTMX,
    TOKEN,
    form_of,
    row_of,
    section_of,
    sent_from,
)

# By hand: what each setting's default is, as the model states it.
EXPECTED_DEFAULTS = {
    "conversion.quality": "best",
    "conversion.threads": "0",
    "conversion.timeout_minutes": "240",
    "conversion.repair_ligatures": "true",
    "literature.request_delay": "3.0",
    "figures.trusted_hosts": "",
    "retrieval.default_collections": "context literature docs notes annotations",
}


@pytest.fixture(autouse=True)
def configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A configuration of the test's own, for every test here."""
    folder = tmp_path / "config"
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(folder))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    for variable in ("KENNIS_EMBEDDING_BACKEND", "OPENAI_API_KEY", "DATALAB_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    return folder


@pytest.fixture
def client() -> TestClient:
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def question_named(key: str, backend: str | None = None) -> Question:
    for question in every_question():
        if question.key != key:
            continue
        if backend is None or dict(question.when).get("embedding.backend") == backend:
            return question
    raise AssertionError(key)


def drawn(client: TestClient, tab: str) -> Tag:
    return section_of(client.get(f"/settings?tab={tab}").text)


def saved_from(client: TestClient, tab: str, **changes: str) -> str:
    answer = client.post(
        "/settings/kennis",
        data=sent_from(form_of(drawn(client, tab)), **changes),
        headers=HTMX,
    )
    assert answer.status_code == 200
    return answer.text


def reset_button_of(section: Tag, key: str) -> Tag | None:
    found = row_of(section, key).find("button", attrs={"name": "reset"})
    return found if isinstance(found, Tag) else None


# ---------------------------------------------------------------------------
# The engine's fact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("key", "default"), EXPECTED_DEFAULTS.items())
def test_a_question_carries_its_default(key: str, default: str) -> None:
    apply_answers({"conversion.quality": "fast", "literature.request_delay": "15"})

    assert question_named(key).default == default


@pytest.mark.parametrize("backend", sorted(EMBEDDING_DEFAULTS))
def test_a_model_s_default_is_the_same_under_every_backend(backend: str) -> None:
    """A default never follows another setting (Brian, 2026-11-25): what
    a backend usually serves is a suggestion, not the default."""
    assert question_named("embedding.model", backend).default == (
        "BAAI/bge-small-en-v1.5"
    )


# ---------------------------------------------------------------------------
# An emptied field
# ---------------------------------------------------------------------------


def test_an_emptied_number_is_refused_beside_its_field(client: TestClient) -> None:
    """Empty is not a number, and the default is the reset button's."""
    apply_answers({"literature.request_delay": "15"})

    answer = saved_from(client, "documents", **{"literature.request_delay": ""})

    assert load_settings().literature.request_delay == 15.0
    problem = row_of(section_of(answer), "literature.request_delay").find(
        class_="role-error"
    )
    assert isinstance(problem, Tag) and problem.get_text(strip=True)


@pytest.mark.parametrize("key", ["embedding.model", "embedding.api_key_env"])
def test_an_emptied_name_whose_default_is_not_empty_is_refused(
    client: TestClient, key: str
) -> None:
    """Empty means nothing for either, so it is refused rather than read
    as the default (#700)."""
    apply_answers({"embedding.backend": "openai"})
    before = getattr(load_settings().embedding, key.partition(".")[2])

    answer = saved_from(client, "searching", **{key: ""})

    assert getattr(load_settings().embedding, key.partition(".")[2]) == before
    problem = row_of(section_of(answer), key).find(class_="role-error")
    assert isinstance(problem, Tag) and problem.get_text(strip=True)


def test_an_emptied_field_whose_default_is_empty_clears_it(
    client: TestClient,
) -> None:
    """#666 itself: withdrawing a consent from the window."""
    apply_answers({"figures.trusted_hosts": "arxiv.org"})

    saved_from(client, "documents", **{"figures.trusted_hosts": ""})

    assert load_settings().figures.trusted_hosts == ""


def test_another_tab_s_settings_are_kept(client: TestClient) -> None:
    """A tab posts its own fields; an absent one is not an emptied one."""
    apply_answers({"literature.request_delay": "15"})

    saved_from(client, "searching")

    assert load_settings().literature.request_delay == 15.0


def test_an_empty_key_keeps_the_stored_key() -> None:
    changed = changed_answers(
        {"embedding.backend": "openai", "embedding.api_key": ""},
        empty_is_value=True,
    )

    assert "embedding.api_key" not in changed


def test_the_setup_walk_still_reads_empty_as_keep() -> None:
    apply_answers({"literature.request_delay": "15"})

    changed = changed_answers({"literature.request_delay": ""}, every=False)

    assert "literature.request_delay" not in changed


def test_an_emptied_field_stays_empty_and_offers_its_reset_on_a_redraw(
    client: TestClient,
) -> None:
    apply_answers({"literature.request_delay": "15"})
    form = form_of(drawn(client, "documents"))
    sent = sent_from(form, **{"literature.request_delay": ""})
    redraw = {
        str(control["name"]): sent[str(control["name"])]
        for control in form.select("[data-redraw]")
        if control.has_attr("name") and str(control["name"]) in sent
    }

    redrawn = section_of(
        client.get("/settings/kennis", params=redraw, headers=HTMX).text
    )
    field = row_of(redrawn, "literature.request_delay").find("input")

    assert isinstance(field, Tag)
    assert field.get("value", "") == ""
    # "(unset)", not "Default: 3.0": emptying no longer gives the default.
    assert field["placeholder"] == words.UNSET
    assert reset_button_of(redrawn, "literature.request_delay") is not None


# ---------------------------------------------------------------------------
# The reset button
# ---------------------------------------------------------------------------


def test_a_setting_off_its_default_has_a_reset_button(
    client: TestClient,
) -> None:
    apply_answers({"conversion.quality": "fast"})
    section = drawn(client, "documents")

    button = reset_button_of(section, "conversion.quality")

    assert button is not None
    assert button["value"] == "conversion.quality"
    assert button["hx-get"] == "/settings/kennis"
    assert button.has_attr("hidden"), "a script shows it; without one it does nothing"
    assert button["aria-label"] == words.reset_label(
        words.SETTING_NAMES["conversion.quality"],
        words.SETTING_CHOICES["conversion.quality"]["best"],
    )
    assert reset_button_of(section, "conversion.device") is None


def redrawn_resetting(client: TestClient, tab: str, key: str) -> Tag:
    form = form_of(drawn(client, tab))
    sent = sent_from(form)
    redraw = {
        str(control["name"]): sent[str(control["name"])]
        for control in form.select("[data-redraw]")
        if control.has_attr("name") and str(control["name"]) in sent
    }
    return section_of(
        client.get(
            "/settings/kennis", params={**redraw, "reset": key}, headers=HTMX
        ).text
    )


def test_a_reset_draws_the_default_and_writes_nothing(
    client: TestClient,
) -> None:
    apply_answers({"conversion.quality": "fast"})

    redrawn = redrawn_resetting(client, "documents", "conversion.quality")
    chosen = row_of(redrawn, "conversion.quality").find("option", selected=True)

    assert isinstance(chosen, Tag) and chosen["value"] == "best"
    assert load_settings().conversion.quality == "fast"


def test_a_reset_redraws_an_ordered_setting_s_chips(
    client: TestClient,
) -> None:
    apply_answers({"retrieval.default_collections": "notes"})

    redrawn = redrawn_resetting(client, "searching", "retrieval.default_collections")
    row = row_of(redrawn, "retrieval.default_collections")
    field = row.find("input", attrs={"type": "text"})
    ticked = [
        str(chip["data-value"])
        for chip in row.select(".order-chip")
        if not chip.has_attr("data-left-out")
    ]

    assert isinstance(field, Tag)
    assert field["value"] == EXPECTED_DEFAULTS["retrieval.default_collections"]
    assert ticked == EXPECTED_DEFAULTS["retrieval.default_collections"].split()


def test_a_reset_then_saved_writes_the_default(client: TestClient) -> None:
    apply_answers({"conversion.quality": "fast"})
    form = form_of(redrawn_resetting(client, "documents", "conversion.quality"))

    client.post("/settings/kennis", data=sent_from(form), headers=HTMX)

    assert load_settings().conversion.quality == "best"


def test_the_setup_walk_offers_no_reset() -> None:
    """Its save reads an empty field as keep; a reset button would promise
    what it does not do."""
    apply_answers({"conversion.quality": "fast", "literature.request_delay": "15"})

    rows = shown_settings({}, every=False)

    assert rows, "the walk drew nothing"
    assert all(row.reset_label == "" for row in rows)


# ---------------------------------------------------------------------------
# What is saved, marked on each field, so Save can be disabled until a
# field differs from it (Brian, 2026-11-24)
# ---------------------------------------------------------------------------


def saved_mark_of(section: Tag, key: str) -> str | None:
    field = row_of(section, key).select_one(f'[name="{key}"]:not([type="hidden"])')
    assert isinstance(field, Tag), f"no field for {key}"
    mark = field.get("data-saved")
    return None if mark is None else str(mark)


def test_each_field_is_marked_with_the_value_saved(client: TestClient) -> None:
    apply_answers({"conversion.quality": "fast", "literature.request_delay": "15"})
    documents = drawn(client, "documents")

    # By hand: the values in force, as the field writes them.
    assert saved_mark_of(documents, "conversion.quality") == "fast"
    assert saved_mark_of(documents, "literature.request_delay") == "15.0"
    assert saved_mark_of(documents, "conversion.timeout_minutes") == "240"
    assert saved_mark_of(documents, "conversion.repair_ligatures") == "true"
    assert saved_mark_of(documents, "figures.trusted_hosts") == ""


def test_a_redraw_keeps_the_saved_mark_not_the_answer(client: TestClient) -> None:
    """A redraw draws what was typed; the mark is still what is saved, or
    Save would be disabled over an unsaved change."""
    redrawn = section_of(
        client.get(
            "/settings/kennis",
            params={"tab": "documents", "conversion.quality": "fast"},
            headers=HTMX,
        ).text
    )

    chosen = row_of(redrawn, "conversion.quality").find("option", selected=True)
    assert isinstance(chosen, Tag) and chosen["value"] == "fast"
    assert saved_mark_of(redrawn, "conversion.quality") == "best"


def test_a_key_is_marked_as_nothing_saved(client: TestClient) -> None:
    """A key's field is always drawn empty, so anything typed is a change."""
    apply_answers({"embedding.backend": "openai"})

    assert saved_mark_of(drawn(client, "searching"), "embedding.api_key") == ""


def test_the_settings_page_loads_the_script_that_disables_save(
    client: TestClient,
) -> None:
    from bs4 import BeautifulSoup

    page = BeautifulSoup(client.get("/settings?tab=documents").text, "html.parser")

    assert page.select('script[src="/static/unsaved.js"]')
    assert client.get("/static/unsaved.js").status_code == 200
    save = page.select_one(".kennis-settings .save-bar button[type=submit]")
    assert isinstance(save, Tag)
    assert not save.has_attr("disabled"), "without a script Save must still work"


def test_an_empty_field_says_unset_on_the_settings_page(client: TestClient) -> None:
    field = row_of(drawn(client, "documents"), "figures.trusted_hosts").find("input")

    assert isinstance(field, Tag)
    assert field.get("value", "") == ""
    assert field["placeholder"] == words.UNSET


def test_the_setup_walk_draws_no_unset_where_empty_means_keep() -> None:
    rows = shown_settings({}, every=False)

    assert all(row.placeholder == "" for row in rows)
