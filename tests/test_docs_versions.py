"""A docs page has a version (#489, unit V1).

A page is identified by its project, its version and its path, and is filed
at `docs/<project>/<version>/`. The version is read from the address or
given; an add that can find neither is refused rather than given a label
kennis invented. Each project has a current version, the one most recently
added unless the reader chooses another.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from kennis.engine.corpus.add import AddOptions, add_docs, docs_input_refused
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.ids import derive_id, natural_key_for_docs
from kennis.engine.corpus.schema import DocsFrontmatter
from kennis.engine.docs.versions import (
    UNVERSIONED,
    checked_version,
    current_version_file,
    project_versions,
    version_in_address,
)
from kennis.engine.errors import InputError
from kennis.engine.events import Outcome
from kennis.engine.shell import quoted_for_this_shell

SEARCHINDEX = (
    'Search.setIndex({"docnames": ["index", "guide/start"], "filenames": []});'
)


def a_page(title: str) -> str:
    return (
        '<html><body><div role="main">'
        f"<h1>{title}</h1><p>Body of {title}.</p>"
        "</div></body></html>"
    )


def sphinx_site(
    requested: list[str] | None = None, *, docnames: tuple[str, ...] = ()
) -> httpx.Client:
    """A two-page Sphinx site served under whatever folder it is asked about,
    so one fake stands for every version of it. `docnames` replaces its page
    list, for a site that has gained a page."""
    index = (
        SEARCHINDEX
        if not docnames
        else f'Search.setIndex({{"docnames": {json.dumps(list(docnames))}}});'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if requested is not None:
            requested.append(str(request.url))
        path = request.url.path
        if path.endswith("searchindex.js"):
            return httpx.Response(200, text=index)
        if path.endswith("documentation_options.js"):
            return httpx.Response(200, text="var O = {VERSION: '2.1.0'};")
        if path.endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        for name, title in (
            ("index.html", "Overview"),
            ("start.html", "Start"),
            ("faq.html", "Questions"),
        ):
            if path.endswith(name):
                return httpx.Response(
                    200, text=a_page(title), headers={"content-type": "text/html"}
                )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def docs(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="docs")


def added(
    docs: Collection, address: str, *, version: str | None = None
) -> list[Outcome]:
    report = add_docs(
        docs,
        [address],
        AddOptions(project="example", request_delay_seconds=0, version=version),
        client=sphinx_site(),
    )
    return [outcome.outcome for outcome in report.outcomes]


def pages_of(docs: Collection) -> list[DocsFrontmatter]:
    found = []
    for document in docs.contents().documents:
        assert isinstance(document.frontmatter, DocsFrontmatter)
        found.append(document.frontmatter)
    return found


def files_of(docs: Collection) -> list[str]:
    return sorted(
        path.relative_to(docs.path).as_posix() for path in docs.path.rglob("*.md")
    )


# ---------------------------------------------------------------------------
# The version in an address
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("address", "version"),
    [
        ("https://pydantic.dev/docs/validation/2.12/", "2.12"),
        ("https://pydantic.dev/docs/validation/2.12/concepts/models/", "2.12"),
        ("https://pydantic.dev/docs/validation/latest/get-started/", "latest"),
        ("https://stimela.readthedocs.io/en/latest/index.html", "latest"),
        ("https://example.org/en/v2.1.0/", "v2.1.0"),
        ("https://example.org/en/2.2.0rc1/guide.html", "2.2.0rc1"),
        ("https://example.org/en/stable/", "stable"),
        ("https://example.org/docs/", None),
        ("https://example.org/", None),
        # A page named like a number is a page, not a version.
        ("https://example.org/guide/2.html", None),
    ],
)
def test_the_version_is_read_from_the_address(address: str, version: str | None):
    assert version_in_address(address) == version


def test_the_last_version_in_an_address_is_the_one():
    assert version_in_address("https://example.org/v1/api/2.3/") == "2.3"


@pytest.mark.parametrize("name", ["2.12", "latest", "v2.1.0", "2.2.0rc1", "main_x"])
def test_a_version_that_can_be_a_folder_is_kept(name: str):
    assert checked_version(name) == name


@pytest.mark.parametrize("name", ["", "..", ".hidden", "2.12/x", "a\\b", "-x", "a b"])
def test_a_version_that_cannot_be_a_folder_is_refused(name: str):
    with pytest.raises(InputError):
        checked_version(name)


# ---------------------------------------------------------------------------
# Identity and folder
# ---------------------------------------------------------------------------


def test_a_page_is_filed_under_its_project_and_version(docs: Collection):
    added(docs, "https://example.org/en/latest/")

    assert files_of(docs) == ["example/latest/Overview.md", "example/latest/Start.md"]
    assert {page.docs.version for page in pages_of(docs)} == {"latest"}


def test_the_site_s_own_release_is_kept_apart_from_the_version(docs: Collection):
    """`latest` keeps one release string across many builds."""
    added(docs, "https://example.org/en/latest/")

    assert {page.docs.release for page in pages_of(docs)} == {"2.1.0"}


def test_the_identifier_is_derived_from_project_version_and_page(docs: Collection):
    added(docs, "https://example.org/en/latest/")

    [overview] = [page for page in pages_of(docs) if page.docs.page == "index"]
    key = natural_key_for_docs(project="example", version="latest", page="index")
    assert overview.id_from == key
    assert overview.id == derive_id(key)


def test_two_versions_of_a_site_are_two_sets_of_pages(docs: Collection):
    assert added(docs, "https://example.org/en/2.0/") == [Outcome.ADDED] * 2
    assert added(docs, "https://example.org/en/2.1/") == [Outcome.ADDED] * 2

    # The same title in two folders keeps its name in each.
    assert files_of(docs) == [
        "example/2.0/Overview.md",
        "example/2.0/Start.md",
        "example/2.1/Overview.md",
        "example/2.1/Start.md",
    ]
    assert len({page.id for page in pages_of(docs)}) == 4


def test_adding_a_version_again_changes_nothing(docs: Collection):
    added(docs, "https://example.org/en/2.0/")

    assert added(docs, "https://example.org/en/2.0/") == [Outcome.UNCHANGED] * 2


def test_a_named_version_wins_over_the_address(docs: Collection):
    added(docs, "https://example.org/en/latest/", version="2.14")

    assert files_of(docs)[0].startswith("example/2.14/")


def test_an_address_with_no_version_is_refused_before_any_request(docs: Collection):
    requested: list[str] = []

    with pytest.raises(InputError, match="--version"):
        add_docs(
            docs,
            ["https://example.org/docs/"],
            AddOptions(project="example", request_delay_seconds=0),
            client=sphinx_site(requested),
        )

    assert requested == []


def test_a_version_that_cannot_be_a_folder_is_refused_as_an_option():
    with pytest.raises(InputError):
        AddOptions(version="../up")


# ---------------------------------------------------------------------------
# The current version
# ---------------------------------------------------------------------------


def test_the_first_version_added_is_current(docs: Collection):
    added(docs, "https://example.org/en/2.0/")

    assert project_versions(docs.path)["example"].current == "2.0"
    assert (
        current_version_file(docs.path, "example").read_text(encoding="utf-8").strip()
        == "2.0"
    )


def test_a_version_added_later_becomes_current(docs: Collection):
    added(docs, "https://example.org/en/2.0/")
    added(docs, "https://example.org/en/2.1/")

    versions = project_versions(docs.path)["example"]
    assert versions.current == "2.1"
    assert versions.held == ("2.0", "2.1")


def test_adding_a_held_version_again_does_not_make_it_current(docs: Collection):
    added(docs, "https://example.org/en/2.0/")
    added(docs, "https://example.org/en/2.1/")
    added(docs, "https://example.org/en/2.0/")

    assert project_versions(docs.path)["example"].current == "2.1"


def test_a_page_new_to_a_held_version_does_not_make_it_current(docs: Collection):
    """Adding 2.0 again after the site gained a page writes into a folder
    that exists; only a version's first page makes it current."""
    added(docs, "https://example.org/en/2.0/")
    added(docs, "https://example.org/en/2.1/")

    add_docs(
        docs,
        ["https://example.org/en/2.0/"],
        AddOptions(project="example", request_delay_seconds=0),
        client=sphinx_site(docnames=("index", "guide/start", "faq")),
    )

    assert "example/2.0/Questions.md" in files_of(docs)
    assert project_versions(docs.path)["example"].current == "2.1"


def test_a_recorded_choice_wins_over_the_most_recent_fetch(docs: Collection):
    """The record is the reader's choice, which can be an older version."""
    added(docs, "https://example.org/en/2.0/")
    added(docs, "https://example.org/en/2.1/")
    current_version_file(docs.path, "example").write_text("2.0\n", encoding="utf-8")

    assert project_versions(docs.path)["example"].current == "2.0"


def test_without_a_record_the_most_recently_fetched_version_is_current(
    docs: Collection,
):
    added(docs, "https://example.org/en/2.1/")
    added(docs, "https://example.org/en/2.0/")
    current_version_file(docs.path, "example").unlink()

    assert project_versions(docs.path)["example"].current == "2.0"


def test_a_record_naming_a_version_not_held_is_not_believed(docs: Collection):
    added(docs, "https://example.org/en/2.0/")
    current_version_file(docs.path, "example").write_text("9.9\n", encoding="utf-8")

    assert project_versions(docs.path)["example"].current == "2.0"


def test_the_record_is_not_a_document(docs: Collection):
    added(docs, "https://example.org/en/2.0/")

    assert all(not path.name.startswith(".") for path in docs.path.rglob("*.md"))
    assert len(pages_of(docs)) == 2


# ---------------------------------------------------------------------------
# A local page, and a file at an address
# ---------------------------------------------------------------------------


def test_a_local_page_joins_the_project_s_current_version(
    docs: Collection, tmp_path: Path
):
    added(docs, "https://example.org/en/2.0/")
    added(docs, "https://example.org/en/2.1/")
    tutorial = tmp_path / "tutorial.md"
    tutorial.write_text("# A tutorial\n\nBy hand.\n", encoding="utf-8")

    add_docs(docs, [str(tutorial)], AddOptions(project="example"))

    assert "example/2.1/A tutorial.md" in files_of(docs)


def test_a_local_page_takes_a_named_version(docs: Collection, tmp_path: Path):
    tutorial = tmp_path / "tutorial.md"
    tutorial.write_text("# A tutorial\n", encoding="utf-8")

    add_docs(docs, [str(tutorial)], AddOptions(project="example", version="notes"))

    assert files_of(docs) == ["example/notes/A tutorial.md"]


def test_a_local_page_with_no_version_to_join_is_refused(
    docs: Collection, tmp_path: Path
):
    tutorial = tmp_path / "tutorial.md"
    tutorial.write_text("# A tutorial\n", encoding="utf-8")

    with pytest.raises(InputError, match="--version"):
        add_docs(docs, [str(tutorial)], AddOptions(project="example"))


def test_a_file_at_an_address_takes_the_version_in_it(docs: Collection):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="# Guide\n\nSteps.\n", headers={"content-type": "text/markdown"}
        )

    add_docs(
        docs,
        ["https://example.org/en/3.0/guide.md"],
        AddOptions(project="example"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert files_of(docs) == ["example/3.0/Guide.md"]


def test_a_page_answers_to_its_project_version_and_page(docs: Collection):
    added(docs, "https://example.org/en/2.0/")
    added(docs, "https://example.org/en/2.1/")

    found = docs.resolve("example/2.0/index")

    assert isinstance(found.frontmatter, DocsFrontmatter)
    assert found.frontmatter.docs.version == "2.0"


# ---------------------------------------------------------------------------
# Documentation that has no versions (Brian, 2026-10-27)
# ---------------------------------------------------------------------------


def test_unversioned_is_a_version_like_any_other(docs: Collection):
    """A site with one edition and no version in its address -
    `https://casacore.github.io/python-casacore/` - is filed under the
    reserved name the refusal offers."""
    added(docs, "https://example.org/en/latest/", version=UNVERSIONED)

    assert files_of(docs) == [
        "example/unversioned/Overview.md",
        "example/unversioned/Start.md",
    ]


def test_the_refusal_offers_unversioned_as_a_command_that_runs():
    refused = docs_input_refused(
        "https://casacore.github.io/python-casacore/", "unversioned"
    )

    assert "--version unversioned" in str(refused)
    assert refused.resolution == (
        "kennis corpus add -d https://casacore.github.io/python-casacore/ "
        "--version unversioned"
    )


def test_the_refusal_names_the_command_that_was_typed():
    refused = docs_input_refused(
        "https://example.org/a b/", "unversioned", command="kennis pack add"
    )

    assert refused.resolution == (
        f"kennis pack add -d {quoted_for_this_shell('https://example.org/a b/')} "
        "--version unversioned"
    )
