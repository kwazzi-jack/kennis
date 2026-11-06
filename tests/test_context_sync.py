"""`kennis context sync`: a project's bundle holds a copy of the context of
every pack it declares (Brian, 2026-11-06, #624, reversing #513).

The rules each test here holds the sync to:

- a declared pack's file is copied in, owned by the pack, and a new
  release replaces a copy nobody edited;
- a file whose owner is the user is never touched, and a pack's copy
  somebody typed in is never overwritten or removed;
- a pack the project stops declaring leaves its copies where they are
  until the person asks a sync to remove them;
- a copy of a pack the project declares and this machine lacks is never
  removed, because whoever has the pack relies on it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kennis.engine.context.bundle import declare_packs, init_bundle
from kennis.engine.context.notes import remember_in_bundle
from kennis.engine.context.sync import plan_sync, sync_bundle
from kennis.engine.errors import DocumentInvalid
from kennis.engine.events import Outcome, Recorder
from kennis.engine.frontmatter import join_frontmatter, split_frontmatter
from kennis.engine.pack.content import content_digest
from kennis.engine.pack.store import install_pack
from kennis.engine.pack.update import update_pack


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    return root


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return init_bundle(project).path


def installed(
    corpus: Path,
    tmp_path: Path,
    identifier: str = "alpha",
    *,
    files: dict[str, str] | None = None,
    version: str = "1.0.0",
) -> None:
    """A pack shipping `files` (address -> text) as its context, built and
    installed as a provider would."""
    root = tmp_path / f"provider-{identifier}"
    content = root / "content"
    for address, text in (files or {"one.md": "One.\n"}).items():
        (content / address).parent.mkdir(parents=True, exist_ok=True)
        (content / address).write_text(text, encoding="utf-8")
    path = root / f"{identifier}.ken.yml"
    path.write_text(
        "kennis:\n  schema_version: 1\n"
        f'pack:\n  id: {identifier}\n  name: n\n  version: "{version}"\n'
        "context:\n  - source: content/\n",
        encoding="utf-8",
    )
    update_pack(path)
    install_pack(corpus, path)


def released_again(corpus: Path, tmp_path: Path, files: dict[str, str]) -> None:
    """The pack alpha at a new version with `files` replacing its context."""
    content = tmp_path / "provider-alpha" / "content"
    for old in content.rglob("*.md"):
        old.unlink()
    installed(corpus, tmp_path, files=files, version="1.1.0")


def header_of(path: Path) -> dict[str, object]:
    frontmatter, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    return frontmatter


def body_of(path: Path) -> str:
    _, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return body


def typed_into(path: Path, words: str) -> None:
    header, body = path.read_text(encoding="utf-8").split("---\n", 2)[1:]
    path.write_text(f"---\n{header}---\n{body}{words}", encoding="utf-8")


# ---------------------------------------------------------------------------
# Copying in


def test_a_declared_pack_s_file_is_copied_in_and_owned_by_the_pack(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"one.md": "---\ntitle: The one\n---\nOne.\n"})
    declare_packs(bundle, ["alpha"])

    result = sync_bundle(bundle, corpus)

    copy = bundle / "one.md"
    assert result.written == ("one.md",)
    assert body_of(copy) == "One.\n"
    header = header_of(copy)
    assert header["owner"] == "pack:alpha"
    assert header["title"] == "The one"
    source = header["source"]
    assert isinstance(source, dict)
    assert source["via"] == "pack" and source["address"] == "one.md"


def test_a_pack_the_project_does_not_declare_is_not_copied(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)

    result = sync_bundle(bundle, corpus)

    assert not (bundle / "one.md").exists()
    assert result.written == ()


def test_a_second_sync_changes_nothing(corpus: Path, bundle: Path, tmp_path: Path):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    before = (bundle / "one.md").read_bytes()

    again = sync_bundle(bundle, corpus)

    assert (again.written, again.updated) == ((), ())
    assert again.unchanged == 1
    assert (bundle / "one.md").read_bytes() == before


def test_a_new_release_replaces_a_copy_nobody_edited(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    released_again(corpus, tmp_path, {"one.md": "One, revised.\n"})

    result = sync_bundle(bundle, corpus)

    assert result.updated == ("one.md",)
    assert body_of(bundle / "one.md") == "One, revised.\n"


def test_a_copy_moved_in_the_bundle_is_updated_where_it_is(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    moved = bundle / "kept" / "one.md"
    moved.parent.mkdir()
    (bundle / "one.md").rename(moved)
    released_again(corpus, tmp_path, {"one.md": "One, revised.\n"})

    result = sync_bundle(bundle, corpus)

    assert not (bundle / "one.md").exists()
    assert body_of(moved) == "One, revised.\n"
    assert result.moved == (("one.md", "kept/one.md"),)


def test_a_pack_may_not_write_where_a_bundle_reserves(
    corpus: Path, bundle: Path, tmp_path: Path
):
    from kennis.engine.errors import PackInvalid

    installed(corpus, tmp_path, files={"LANDING.md": "Mine.\n"})
    declare_packs(bundle, ["alpha"])
    landing = (bundle / "LANDING.md").read_bytes()

    with pytest.raises(PackInvalid):
        sync_bundle(bundle, corpus)

    assert (bundle / "LANDING.md").read_bytes() == landing


def test_two_declared_packs_shipping_one_address_give_it_to_the_first_installed(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path, "alpha", files={"one.md": "Alpha's.\n"})
    installed(corpus, tmp_path, "beta", files={"one.md": "Beta's.\n"})
    declare_packs(bundle, ["beta", "alpha"])

    result = sync_bundle(bundle, corpus)

    assert body_of(bundle / "one.md") == "Alpha's.\n"
    assert result.deferred == (("one.md", "beta"),)


# ---------------------------------------------------------------------------
# What is never touched


def test_a_file_the_user_owns_is_never_touched(
    corpus: Path, bundle: Path, tmp_path: Path
):
    """Owning a pack's file is deliberate: the person says so in its
    header, and from then on no release reaches it."""
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    copy = bundle / "one.md"
    header, body = split_frontmatter(copy.read_text(encoding="utf-8"))
    copy.write_text(join_frontmatter({**header, "owner": "user"}, body), "utf-8")
    assert header_of(copy)["owner"] == "user"
    before = copy.read_bytes()
    released_again(corpus, tmp_path, {"one.md": "One, revised.\n"})

    result = sync_bundle(bundle, corpus)

    assert copy.read_bytes() == before
    assert result.yours == ("one.md",)
    assert result.updated == ()


def test_a_pack_s_copy_somebody_typed_in_is_not_overwritten(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    copy = bundle / "one.md"
    typed_into(copy, "And mine.\n")
    released_again(corpus, tmp_path, {"one.md": "One, revised.\n"})

    result = sync_bundle(bundle, corpus)

    assert body_of(copy) == "One.\nAnd mine.\n"
    assert result.edited == ("one.md",)
    assert header_of(copy)["owner"] == "pack:alpha"


def test_a_note_the_person_remembered_is_never_touched(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])
    remembered = remember_in_bundle(
        bundle, "Our gains drift.", title=None, group=None
    ).path
    before = remembered.read_bytes()

    sync_bundle(bundle, corpus, remove_undeclared=True)

    assert remembered.read_bytes() == before


def test_an_unrecognised_owner_is_refused_before_anything_is_written(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])
    (bundle / "odd.md").write_text("---\nowner: somebody\n---\nOdd.\n", "utf-8")

    with pytest.raises(DocumentInvalid) as raised:
        sync_bundle(bundle, corpus)

    assert "odd.md" in str(raised.value)
    assert not (bundle / "one.md").exists()


# ---------------------------------------------------------------------------
# A pack the project stops declaring


def test_dropping_a_pack_keeps_its_copies_and_says_so(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    declare_packs(bundle, [])

    result = sync_bundle(bundle, corpus)

    assert (bundle / "one.md").is_file()
    assert result.undeclared == ("one.md",)
    assert result.removed == ()


def test_a_sync_asked_to_removes_the_copies_of_a_dropped_pack(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"decisions/one.md": "One.\n"})
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    declare_packs(bundle, [])

    result = sync_bundle(bundle, corpus, remove_undeclared=True)

    assert not (bundle / "decisions").exists()
    assert result.removed == ("decisions/one.md",)
    assert result.undeclared == ()


def test_an_edited_copy_of_a_dropped_pack_is_kept_even_when_asked(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    typed_into(bundle / "one.md", "And mine.\n")
    declare_packs(bundle, [])

    result = sync_bundle(bundle, corpus, remove_undeclared=True)

    assert (bundle / "one.md").is_file()
    assert result.edited == ("one.md",)


def test_a_copy_of_a_declared_pack_this_machine_lacks_is_never_removed(
    corpus: Path, bundle: Path
):
    """The project's declaration is committed; a collaborator who has the
    pack relies on its copies, which this machine cannot rebuild."""
    body = "Gamma's.\n"
    (bundle / "g.md").write_text(
        "---\ntitle: g\nowner: pack:gamma\nsource:\n  via: pack\n  pack: gamma\n"
        f"  address: g.md\n  sha256: {content_digest(body.encode())}\n---\n{body}",
        encoding="utf-8",
    )
    declare_packs(bundle, ["gamma"])

    result = sync_bundle(bundle, corpus, remove_undeclared=True)

    assert (bundle / "g.md").is_file()
    assert result.removed == ()
    assert result.missing == ("gamma",)


def test_a_removal_leaves_a_directory_holding_something_else(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"decisions/one.md": "One.\n"})
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    (bundle / "decisions" / "notes.txt").write_text("mine", encoding="utf-8")
    declare_packs(bundle, [])

    sync_bundle(bundle, corpus, remove_undeclared=True)

    assert (bundle / "decisions" / "notes.txt").exists()


# ---------------------------------------------------------------------------
# A plan, for the window's dialog


def test_a_plan_writes_nothing_and_says_what_a_sync_would_do(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"one.md": "One.\n", "two.md": "Two.\n"})
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    (bundle / "two.md").unlink()
    released_again(corpus, tmp_path, {"one.md": "One, revised.\n", "two.md": "Two.\n"})
    before = sorted(path.read_bytes() for path in bundle.rglob("*.md"))

    plan = plan_sync(bundle, corpus)

    assert sorted(path.read_bytes() for path in bundle.rglob("*.md")) == before
    assert plan.written == ("two.md",)
    assert plan.updated == ("one.md",)
    assert plan == sync_bundle(bundle, corpus)


# ---------------------------------------------------------------------------
# The declaration


def test_the_declared_packs_are_split_by_whether_they_are_installed(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha", "gamma"])

    result = sync_bundle(bundle, corpus)

    assert result.declared == ("alpha",)
    assert result.missing == ("gamma",)
    assert result.available == ()


def test_a_project_declaring_nothing_is_offered_the_installed_packs(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path, "beta")
    installed(corpus, tmp_path, "alpha")

    result = sync_bundle(bundle, corpus)

    assert result.available == ("alpha", "beta")


# ---------------------------------------------------------------------------
# Reporting


def test_every_change_reaches_the_event_stream(
    corpus: Path, bundle: Path, tmp_path: Path
):
    installed(corpus, tmp_path, files={"one.md": "One.\n", "two.md": "Two.\n"})
    declare_packs(bundle, ["alpha"])
    sync_bundle(bundle, corpus)
    typed_into(bundle / "two.md", "Mine.\n")
    released_again(
        corpus, tmp_path, {"one.md": "One, revised.\n", "two.md": "Two, revised.\n"}
    )
    events = Recorder()

    sync_bundle(bundle, corpus, events=events)

    assert events.outcomes() == {
        "one.md": Outcome.CHANGED,
        "two.md": Outcome.SKIPPED,
    }


def test_the_sync_makes_no_commit(corpus: Path, bundle: Path, tmp_path: Path):
    """kennis does not write to the person's repository's history."""
    project = bundle.parent
    subprocess.run(
        ["git", "init", "-q"],
        cwd=project,
        check=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    installed(corpus, tmp_path)
    declare_packs(bundle, ["alpha"])

    sync_bundle(bundle, corpus)

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    assert log.stdout.strip() == ""
