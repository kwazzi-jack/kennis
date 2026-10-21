"""A project declares the packs that apply to it (14g, #512, #513).

The declaration is in the bundle's manifest, which is committed with the
project, so a collaborator's clone declares the same packs. A project that
declares none gets no pack content. What the declaration controls - which
packs a project's search reads - is g3's; this is the declaration itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kennis.cli.__main__ import main
from kennis.engine.context.bundle import (
    MANIFEST_FILENAME,
    declare_packs,
    declared_packs,
    init_bundle,
)
from kennis.engine.errors import InputError


@pytest.fixture(autouse=True)
def no_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """And a corpus, whose service acts on a bundle (14e)."""
    monkeypatch.delenv("KENNIS_CONTEXT_DIR", raising=False)
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    initialised = CliRunner().invoke(main, ["corpus", "init"])
    assert initialised.exit_code == 0, initialised.output


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "pipelines"
    (root / ".git").mkdir(parents=True)
    monkeypatch.chdir(root)
    return root


def manifest_of(bundle: Path) -> dict[str, object]:
    document = json.loads((bundle / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


# ---------------------------------------------------------------------------
# The declaration


def test_a_new_bundle_declares_no_packs(project: Path):
    bundle = init_bundle(project).path

    assert declared_packs(bundle) == ()


def test_declared_packs_are_read_back_sorted_and_once(project: Path):
    bundle = init_bundle(project).path

    declare_packs(bundle, ["stimela", "casa", "stimela"])

    assert declared_packs(bundle) == ("casa", "stimela")
    # Written so too: the manifest is committed, and an order that varied
    # with how the ids were typed would be a diff in someone's review.
    assert manifest_of(bundle)["packs"] == ["casa", "stimela"]


def test_a_declaration_keeps_the_rest_of_the_manifest(project: Path):
    bundle = init_bundle(project).path
    before = manifest_of(bundle)

    declare_packs(bundle, ["stimela"])

    after = manifest_of(bundle)
    assert after["packs"] == ["stimela"]
    assert {key: after[key] for key in before} == before


def test_declaring_nothing_clears_the_declaration(project: Path):
    bundle = init_bundle(project).path
    declare_packs(bundle, ["stimela"])

    declare_packs(bundle, [])

    assert declared_packs(bundle) == ()


def test_a_name_that_is_no_pack_id_is_refused(project: Path):
    bundle = init_bundle(project).path

    with pytest.raises(InputError) as raised:
        declare_packs(bundle, ["Not A Pack"])

    assert "Not A Pack" in str(raised.value)
    assert declared_packs(bundle) == ()


# ---------------------------------------------------------------------------
# The commands


def test_init_declares_the_packs_it_is_given(project: Path):
    result = CliRunner().invoke(
        main, ["context", "init", "--pack", "stimela", "--pack", "casa"]
    )

    assert result.exit_code == 0, result.output
    assert declared_packs(project / ".context") == ("casa", "stimela")


def test_context_packs_sets_the_declaration(project: Path):
    init_bundle(project)

    result = CliRunner().invoke(main, ["context", "packs", "stimela"])

    assert result.exit_code == 0, result.output
    assert declared_packs(project / ".context") == ("stimela",)
    assert "stimela" in result.output


def test_context_packs_adds_to_the_declaration_rather_than_replacing_it(
    project: Path,
):
    """A command printed for one pack - after `pack add`, or by a sync -
    must not drop the packs a project already uses."""
    bundle = init_bundle(project).path
    declare_packs(bundle, ["casa"])

    result = CliRunner().invoke(main, ["context", "packs", "stimela"])

    assert result.exit_code == 0, result.output
    assert declared_packs(bundle) == ("casa", "stimela")


def test_context_packs_drop_removes_one(project: Path):
    bundle = init_bundle(project).path
    declare_packs(bundle, ["casa", "stimela"])

    result = CliRunner().invoke(main, ["context", "packs", "--drop", "casa"])

    assert result.exit_code == 0, result.output
    assert declared_packs(bundle) == ("stimela",)


def test_context_packs_alone_says_what_is_declared(project: Path):
    bundle = init_bundle(project).path
    declare_packs(bundle, ["stimela"])

    result = CliRunner().invoke(main, ["context", "packs"])

    assert result.exit_code == 0, result.output
    assert "stimela" in result.output
    assert declared_packs(bundle) == ("stimela",)


def test_context_packs_alone_with_none_declared_says_how_to_declare(project: Path):
    init_bundle(project)

    result = CliRunner().invoke(main, ["context", "packs"])

    assert result.exit_code == 0, result.output
    assert "no packs" in result.output
    assert "kennis context packs --help" in result.output


def test_context_packs_none_clears_the_declaration(project: Path):
    bundle = init_bundle(project).path
    declare_packs(bundle, ["stimela"])

    result = CliRunner().invoke(main, ["context", "packs", "--none"])

    assert result.exit_code == 0, result.output
    assert declared_packs(bundle) == ()


def test_context_packs_refuses_names_and_none_together(project: Path):
    bundle = init_bundle(project).path
    declare_packs(bundle, ["stimela"])

    result = CliRunner().invoke(main, ["context", "packs", "casa", "--none"])

    assert result.exit_code != 0
    assert declared_packs(bundle) == ("stimela",)


def test_context_packs_outside_a_project_names_init(tmp_path: Path):
    result = CliRunner().invoke(main, ["context", "packs", "stimela"])

    assert result.exit_code != 0
    assert "kennis context init" in result.output
