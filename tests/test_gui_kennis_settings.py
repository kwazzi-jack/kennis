"""Milestone 12b: kennis's own configuration on the settings page.

Written through `engine/setup.py::apply_answers`, the writer `kennis
config set` uses, so the window imports no front end and a value saved
here is one every front end reads. Each row says what a change costs; a
change that needs a rebuild offers to rebuild now, later, or to undo; a
key is shown only as its variable and whether it is set.
"""

from __future__ import annotations

import tomllib
from html import unescape
from pathlib import Path

import pytest
from bs4 import BeautifulSoup, Tag
from click.testing import CliRunner
from fastapi.testclient import TestClient

from kennis.cli.__main__ import main
from kennis.engine.setting_costs import costs_of
from kennis.engine.settings import config_path, load_settings
from kennis.gui import words
from kennis.gui.app import build_app
from kennis.render.settings import describe_cost, describe_costs

TOKEN = "a-test-token"
HTMX = {"HX-Request": "true"}

# Written by hand: the rows the default configuration shows, in order.
# `corpus.root` is absent on purpose: changing it under an open window
# moves the corpus from under every page and every running job.
EXPECTED_ROWS = [
    "embedding.backend",
    "embedding.model",
    "embedding.dimensions",
    "retrieval.corpus_method",
    "retrieval.default_top_k",
    "chunking.size",
    "conversion.backend",
]
# And the heading each row sits under, as the plan lays the page out.
EXPECTED_GROUPS = {
    "Searching and indexing": EXPECTED_ROWS[:6],
    "Converting documents": EXPECTED_ROWS[6:],
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_LOG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.delenv("KENNIS_EMBEDDING_BACKEND", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DATALAB_API_KEY", raising=False)
    assert CliRunner().invoke(main, ["corpus", "init"]).exit_code == 0
    opened = TestClient(build_app(TOKEN), follow_redirects=False)
    assert opened.get("/", params={"token": TOKEN}).status_code == 200
    return opened


def section_of(text: str) -> Tag:
    found = BeautifulSoup(text, "html.parser").find(attrs={"data-section": "kennis"})
    assert isinstance(found, Tag), text[:500]
    return found


def rows_of(section: Tag) -> list[str]:
    return [str(row["data-key"]) for row in section.select(".setting[data-key]")]


def row_of(section: Tag, key: str) -> Tag:
    found = section.find(attrs={"data-key": key})
    assert isinstance(found, Tag), key
    return found


def form_of(section: Tag) -> Tag:
    form = section.find("form", class_="kennis-settings")
    assert isinstance(form, Tag)
    return form


def saved() -> dict[str, dict[str, object]]:
    path = config_path()
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


# ---------------------------------------------------------------------------
# The rows
# ---------------------------------------------------------------------------


def test_the_section_is_kenniss_and_says_so(client: TestClient):
    section = section_of(client.get("/settings").text)

    assert words.KENNIS_SETTINGS_NOTE in section.get_text(" ", strip=True)


def test_the_rows_are_the_questions_that_apply(client: TestClient):
    assert rows_of(section_of(client.get("/settings").text)) == EXPECTED_ROWS


def test_the_rows_sit_under_their_headings(client: TestClient):
    section = section_of(client.get("/settings").text)
    grouped = {
        str(group.find("h3").get_text(strip=True)): rows_of(group)
        for group in section.select(".setting-group")
    }

    assert grouped == EXPECTED_GROUPS


def test_the_corpus_root_is_not_offered(client: TestClient):
    assert "corpus.root" not in client.get("/settings").text


@pytest.mark.parametrize("key", EXPECTED_ROWS)
def test_each_row_says_what_a_change_costs(client: TestClient, key: str):
    row = row_of(section_of(client.get("/settings").text), key)
    current = load_settings()
    section_name, _, field = key.partition(".")
    value = str(getattr(getattr(current, section_name), field))
    cost = row.find(class_="cost")

    assert isinstance(cost, Tag), key
    assert cost.get_text(" ", strip=True) == describe_costs(costs_of(key, value))


def test_a_row_shows_the_value_in_force(client: TestClient):
    section = section_of(client.get("/settings").text)
    size = row_of(section, "chunking.size").find(
        "input", attrs={"name": "chunking.size"}
    )
    backend = row_of(section, "embedding.backend").find(
        "option", attrs={"selected": True}
    )

    assert isinstance(size, Tag) and size["value"] == "1500"
    assert isinstance(backend, Tag) and backend["value"] == "fastembed"


def test_choosing_a_backend_redraws_with_its_questions(client: TestClient):
    """The engine's `when` decides, with the form's values, not the saved
    ones - one rule, as `config init` walks it."""
    section = section_of(client.get("/settings").text)
    choice = row_of(section, "embedding.backend").find("select")
    assert isinstance(choice, Tag)
    assert choice["hx-get"] == "/settings/kennis"
    assert choice["hx-trigger"] == "change"

    redrawn = section_of(
        client.get(
            "/settings/kennis", params={"embedding.backend": "openai"}, headers=HTMX
        ).text
    )

    assert "embedding.api_key" in rows_of(redrawn)
    # Asked under every backend since #441: the width belongs to the model.
    assert "embedding.dimensions" in rows_of(redrawn)
    cost = row_of(redrawn, "embedding.backend").find(class_="cost")
    assert isinstance(cost, Tag)
    assert describe_cost("leaves_machine") in cost.get_text()
    # Sending a document away is never a default, so it is drawn apart.
    assert "role-warning" in cost.get("class", [])


def test_choosing_a_backend_offers_its_own_model_and_saving_writes_it(
    client: TestClient,
):
    """The model in force is the previous backend's, and a name means
    something only to its backend: kept, it failed only at the next index.
    Saving the redrawn form as drawn has to write the new pairing, which is
    why the offered value is not the value in force. Concern #441."""
    form = redrawn_from(
        client,
        form_of(section_of(client.get("/settings").text)),
        **{"embedding.backend": "openai"},
    )
    model = row_of(form, "embedding.model").find("input")
    assert isinstance(model, Tag) and model["value"] == "text-embedding-3-small"

    client.post("/settings/kennis", data=sent_from(form), headers=HTMX)

    embedding = load_settings().embedding
    assert (embedding.backend, embedding.model, embedding.dimensions) == (
        "openai",
        "text-embedding-3-small",
        1536,
    )


def test_a_model_follows_the_backend_there_and_back(client: TestClient):
    """The page's own offer is not something the person typed: a redraw
    through ollama and back to openai offers openai's model again, rather
    than keeping ollama's because the field now holds it."""
    form = form_of(section_of(client.get("/settings").text))
    for backend in ("ollama", "openai"):
        form = redrawn_from(client, form, **{"embedding.backend": backend})

    model = row_of(form, "embedding.model").find("input")
    assert isinstance(model, Tag) and model["value"] == "text-embedding-3-small"


def test_a_model_the_person_typed_survives_a_redraw(client: TestClient):
    form = redrawn_from(
        client,
        form_of(section_of(client.get("/settings").text)),
        **{"embedding.model": "BAAI/bge-base-en-v1.5", "chunking.size": "777"},
    )
    form = redrawn_from(client, form, **{"retrieval.corpus_method": "bm25"})

    model = row_of(form, "embedding.model").find("input")
    assert isinstance(model, Tag) and model["value"] == "BAAI/bge-base-en-v1.5"


def test_a_local_backend_is_not_drawn_as_a_warning(client: TestClient):
    cost = row_of(section_of(client.get("/settings").text), "embedding.backend").find(
        class_="cost"
    )

    assert isinstance(cost, Tag)
    assert "role-warning" not in cost.get("class", [])


def test_a_redraw_keeps_what_was_typed(client: TestClient):
    redrawn = section_of(
        client.get(
            "/settings/kennis",
            params={"embedding.backend": "fastembed", "chunking.size": "777"},
            headers=HTMX,
        ).text
    )
    size = row_of(redrawn, "chunking.size").find("input")

    assert isinstance(size, Tag) and size["value"] == "777"


# ---------------------------------------------------------------------------
# Credentials and the converter
# ---------------------------------------------------------------------------


def test_a_key_is_its_variable_and_whether_it_is_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DATALAB_API_KEY", "dl-secret-value")
    page = client.get(
        "/settings/kennis", params={"conversion.backend": "datalab"}, headers=HTMX
    ).text
    row = row_of(section_of(page), "conversion.api_key")
    field = row.find("input", attrs={"name": "conversion.api_key"})

    assert "dl-secret-value" not in page
    assert "DATALAB_API_KEY" in row.get_text()
    assert words.CREDENTIAL_SET in row.get_text()
    assert isinstance(field, Tag)
    assert field["type"] == "password"
    assert not field.get("value")


def test_an_unset_key_says_so(client: TestClient):
    page = client.get(
        "/settings/kennis", params={"conversion.backend": "datalab"}, headers=HTMX
    ).text

    text = row_of(section_of(page), "conversion.api_key").get_text()

    assert words.CREDENTIAL_UNSET in text
    assert words.CREDENTIAL_SET not in text


def test_a_typed_key_never_travels_in_an_address(client: TestClient):
    """A redraw is a GET, so whatever it includes lands in the address,
    the history and the log. The key's field must not be among them."""
    section = section_of(
        client.get(
            "/settings/kennis", params={"conversion.backend": "datalab"}, headers=HTMX
        ).text
    )
    choice = row_of(section, "conversion.backend").find("select")
    assert isinstance(choice, Tag)
    included = section.select(
        str(choice["hx-include"]).replace(".kennis-settings ", "")
    )
    key = row_of(section, "conversion.api_key").find("input")

    assert included, "the redraw includes nothing"
    assert key not in included


def test_every_offered_choice_and_setting_has_words():
    from kennis.engine.setting_costs import COSTLESS
    from kennis.engine.setup import setup_questions

    for question in setup_questions():
        if question.key in COSTLESS:
            continue
        assert question.key in words.SETTING_NAMES, question.key
        for option in question.options:
            assert option in words.SETTING_CHOICES.get(question.key, {}), (
                question.key,
                option,
            )


def test_the_converter_says_whether_mineru_is_here(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from kennis.engine.corpus import converters

    monkeypatch.setattr(converters.MineruConverter, "is_available", lambda self: False)
    row = row_of(section_of(client.get("/settings").text), "conversion.backend")
    hint = converters.MineruConverter().install_hint()

    assert words.CONVERTER_NAMES["mineru"] in row.get_text()
    assert words.CONVERTER_MISSING in row.get_text()
    assert row.find("code", string=hint) is not None


def test_an_installed_converter_raises_no_warning(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from kennis.engine.corpus import converters

    monkeypatch.setattr(converters.MineruConverter, "is_available", lambda self: True)
    row = row_of(section_of(client.get("/settings").text), "conversion.backend")

    assert words.CONVERTER_MISSING not in row.get_text()


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------


def sent_from(form: Tag, **changes: str) -> dict[str, str]:
    """What a browser sends from the drawn form, with some fields changed."""
    sent: dict[str, str] = {}
    for control in form.find_all(["input", "select"]):
        name = control.get("name")
        if not isinstance(name, str):
            continue
        if control.name == "select":
            chosen = control.find("option", attrs={"selected": True})
            sent[name] = str(chosen["value"]) if isinstance(chosen, Tag) else ""
        else:
            value = control.get("value")
            sent[name] = value if isinstance(value, str) else ""
    sent.update(changes)
    return sent


def redrawn_from(client: TestClient, form: Tag, **changes: str) -> Tag:
    """The section a choice redraws, asked as the page asks it: htmx
    includes every `[data-redraw]` field in the form, not only the one that
    changed. A test sending the backend alone passed while the page kept
    the previous backend's model (#441)."""
    select = form.find("select", attrs={"hx-get": True})
    assert isinstance(select, Tag)
    assert select["hx-include"] == ".kennis-settings [data-redraw]"
    sent = {
        name: value
        for name, value in sent_from(form).items()
        if isinstance(found := form.find(attrs={"name": name}), Tag)
        and found.has_attr("data-redraw")
    }
    sent.update(changes)
    answer = client.get(str(select["hx-get"]), params=sent, headers=HTMX)
    return form_of(section_of(answer.text))


def test_saving_as_drawn_writes_through_the_engine(client: TestClient):
    form = form_of(section_of(client.get("/settings").text))
    assert form["hx-post"] == form["action"] == "/settings/kennis"

    answer = client.post(
        "/settings/kennis",
        data=sent_from(form, **{"retrieval.default_top_k": "7"}),
        headers=HTMX,
    )

    assert answer.status_code == 200
    assert load_settings().retrieval.default_top_k == 7
    assert words.KENNIS_SAVED in answer.text


def test_an_unchanged_value_is_not_written(client: TestClient):
    """Saving the form as drawn writes nothing: every field holds the value
    in force, and writing it would pin a default into the file."""
    form = form_of(section_of(client.get("/settings").text))

    client.post("/settings/kennis", data=sent_from(form), headers=HTMX)

    assert saved() == {}


def test_a_refused_value_is_named_beside_its_field_and_nothing_is_written(
    client: TestClient,
):
    form = form_of(section_of(client.get("/settings").text))

    answer = client.post(
        "/settings/kennis",
        data=sent_from(form, **{"chunking.size": "0", "retrieval.default_top_k": "9"}),
        headers=HTMX,
    )
    row = row_of(section_of(answer.text), "chunking.size")
    problem = row.find(class_="role-error")

    assert isinstance(problem, Tag)
    assert problem.get_text(strip=True)
    assert load_settings().retrieval.default_top_k == 3  # not half-written
    assert saved() == {}


def test_a_key_is_written_to_the_credentials_and_never_shown(client: TestClient):
    form = form_of(
        section_of(
            client.get(
                "/settings/kennis",
                params={"conversion.backend": "datalab"},
                headers=HTMX,
            ).text
        )
    )

    answer = client.post(
        "/settings/kennis",
        data=sent_from(
            form,
            **{"conversion.backend": "datalab", "conversion.api_key": "dl-new-key"},
        ),
        headers=HTMX,
    )

    assert "dl-new-key" not in answer.text
    assert "dl-new-key" not in config_path().read_text(encoding="utf-8")
    assert (
        words.CREDENTIAL_SET
        in row_of(section_of(answer.text), "conversion.api_key").get_text()
    )


def test_without_a_script_saving_answers_with_the_page(client: TestClient):
    form = form_of(section_of(client.get("/settings").text))

    answer = client.post(
        "/settings/kennis", data=sent_from(form, **{"retrieval.default_top_k": "5"})
    )

    assert answer.status_code == 200
    assert 'class="shell"' in answer.text
    assert load_settings().retrieval.default_top_k == 5


# ---------------------------------------------------------------------------
# A change that needs a rebuild
# ---------------------------------------------------------------------------


def index_notes(tmp: Path) -> None:
    source = tmp / "a.md"
    source.write_text("# A\n\nCalibration converged.\n", encoding="utf-8")
    assert CliRunner().invoke(main, ["corpus", "add", "-n", str(source)]).exit_code == 0
    assert CliRunner().invoke(main, ["corpus", "index"]).exit_code == 0


def test_a_rebuild_is_offered_now_later_or_undone(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    index_notes(tmp_path)
    monkeypatch.delenv("KENNIS_EMBEDDING_BACKEND")
    form = form_of(section_of(client.get("/settings").text))

    answer = client.post(
        "/settings/kennis",
        data=sent_from(form, **{"chunking.size": "900"}),
        headers=HTMX,
    )
    panel = BeautifulSoup(answer.text, "html.parser").find(class_="rebuild")

    assert isinstance(panel, Tag), answer.text
    rebuild = panel.find("form", attrs={"hx-post": "/index"})
    undo = panel.find("form", class_="undo")
    later = panel.find(attrs={"data-later": True})
    assert isinstance(rebuild, Tag) and isinstance(undo, Tag) and later is not None
    # Undo carries the value that was in force, and posts it back.
    assert undo.find("input", attrs={"name": "chunking.size", "value": "1500"})
    # Until then, each index is named by what it was built with.
    assert "notes" in panel.get_text()
    assert words.LEXICAL_ONLY_INDEX in unescape(panel.get_text())


def test_undo_restores_the_value_that_was_in_force(client: TestClient):
    form = form_of(section_of(client.get("/settings").text))
    answer = client.post(
        "/settings/kennis",
        data=sent_from(form, **{"chunking.size": "900"}),
        headers=HTMX,
    )
    undo = BeautifulSoup(answer.text, "html.parser").find("form", class_="undo")
    assert isinstance(undo, Tag)

    client.post(
        str(undo["hx-post"]),
        data=sent_from(undo),
        headers=HTMX,
    )

    assert load_settings().chunking.size == 1500


def test_a_change_that_needs_no_rebuild_offers_none(client: TestClient):
    form = form_of(section_of(client.get("/settings").text))

    answer = client.post(
        "/settings/kennis",
        data=sent_from(form, **{"retrieval.default_top_k": "4"}),
        headers=HTMX,
    )

    assert BeautifulSoup(answer.text, "html.parser").find(class_="rebuild") is None


def test_a_key_the_page_does_not_offer_is_not_written(
    client: TestClient, tmp_path: Path
):
    """An edited form or address cannot reach a setting the page left out."""
    form = form_of(section_of(client.get("/settings").text))
    elsewhere = str(tmp_path / "elsewhere")

    client.post(
        "/settings/kennis",
        data=sent_from(form, **{"corpus.root": elsewhere}),
        headers=HTMX,
    )

    assert str(load_settings().corpus.root) != elsewhere
    assert saved() == {}
