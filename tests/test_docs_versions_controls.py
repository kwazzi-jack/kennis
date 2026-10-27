"""The reader's controls over held docs versions (#489, unit V4).

Refreshing a held version asks the site whether each page changed - by the
validators it sent last time where it sent any, by fetching and comparing
the text where it did not - and rewrites a changed page where it is, under
the same identifier. Removing a version removes every page of it in one
write, and the project's current version moves to what is left.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from kennis.context import Context
from kennis.engine.corpus.add import AddOptions, add_docs
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.schema import DocsFrontmatter
from kennis.engine.docs.versions import current_version_file, project_versions
from kennis.engine.errors import InputError
from kennis.engine.events import Outcome
from kennis.operations import remove_docs_version

BASE = "https://example.org/en/2.1/"

SEARCHINDEX = (
    'Search.setIndex({"docnames": ["index", "guide/start"], "filenames": []});'
)


def a_page(title: str, sentence: str) -> str:
    return (
        '<html><body><div role="main">'
        f"<h1>{title}</h1><p>{sentence}</p>"
        "</div></body></html>"
    )


@dataclass
class Served:
    html: str
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class Site:
    """A two-page Sphinx site whose pages can change between adds, and
    which records what it was asked."""

    pages: dict[str, Served] = field(default_factory=dict)
    asked: list[httpx.Request] = field(default_factory=list)
    failing: set[str] = field(default_factory=set)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.answer))

    def answer(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("searchindex.js"):
            return httpx.Response(200, text=SEARCHINDEX)
        if path.endswith("documentation_options.js"):
            return httpx.Response(200, text="var DOCUMENTATION_OPTIONS = {};")
        if path.endswith("robots.txt"):
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        self.asked.append(request)
        if path in self.failing:
            return httpx.Response(500)
        served = self.pages.get(path)
        if served is None:
            return httpx.Response(404)
        headers = {"content-type": "text/html"}
        if served.etag is not None:
            headers["etag"] = served.etag
            if request.headers.get("if-none-match") == served.etag:
                return httpx.Response(304, headers=headers)
        if served.last_modified is not None:
            headers["last-modified"] = served.last_modified
            if request.headers.get("if-modified-since") == served.last_modified:
                return httpx.Response(304, headers=headers)
        return httpx.Response(200, text=served.html, headers=headers)

    def pages_asked(self) -> list[httpx.Request]:
        return [request for request in self.asked if request.url.path.endswith(".html")]


INDEX = "/en/2.1/index.html"
START = "/en/2.1/guide/start.html"


MODIFIED = "Wed, 01 Oct 2026 10:00:00 GMT"


def a_site(*, etag: bool = True, last_modified: bool = False) -> Site:
    return Site(
        pages={
            INDEX: Served(
                a_page("Overview", "What the project is."),
                etag='"index-1"' if etag else None,
                last_modified=MODIFIED if last_modified else None,
            ),
            START: Served(
                a_page("Getting started", "Install it first."),
                etag='"start-1"' if etag else None,
                last_modified=MODIFIED if last_modified else None,
            ),
        }
    )


@pytest.fixture
def docs(tmp_path: Path) -> Collection:
    return Collection(root=tmp_path / "corpus", name="docs")


ADD = AddOptions(project="example", request_delay_seconds=0)
REFRESH = AddOptions(project="example", request_delay_seconds=0, refresh=True)


def held(docs: Collection) -> dict[str, tuple[DocsFrontmatter, str, Path]]:
    found: dict[str, tuple[DocsFrontmatter, str, Path]] = {}
    for document in docs.contents().documents:
        frontmatter = document.frontmatter
        assert isinstance(frontmatter, DocsFrontmatter)
        found[frontmatter.docs.page] = (frontmatter, document.body, document.md_path)
    return found


# ---------------------------------------------------------------------------
# What a fetch records
# ---------------------------------------------------------------------------


def test_a_fetched_page_records_the_validators_its_site_sent(docs: Collection):
    site = a_site(etag=True, last_modified=True)

    add_docs(docs, [BASE], ADD, client=site.client())

    page = held(docs)["index"][0].docs
    assert page.etag == '"index-1"'
    assert page.last_modified == "Wed, 01 Oct 2026 10:00:00 GMT"


def test_a_page_whose_site_sent_none_records_none(docs: Collection):
    add_docs(docs, [BASE], ADD, client=a_site(etag=False).client())

    page = held(docs)["index"][0].docs
    assert page.etag is None and page.last_modified is None


# ---------------------------------------------------------------------------
# Adding again without refreshing
# ---------------------------------------------------------------------------


def test_without_refresh_a_held_page_is_not_asked_for(docs: Collection):
    site = a_site()
    add_docs(docs, [BASE], ADD, client=site.client())
    site.asked.clear()

    report = add_docs(docs, [BASE], ADD, client=site.client())

    assert site.pages_asked() == []
    assert {item.outcome for item in report.outcomes} == {Outcome.UNCHANGED}


# ---------------------------------------------------------------------------
# Refreshing with validators
# ---------------------------------------------------------------------------


def test_a_refresh_asks_by_the_validators_it_holds(docs: Collection):
    site = a_site(etag=True, last_modified=True)
    add_docs(docs, [BASE], ADD, client=site.client())
    site.asked.clear()

    add_docs(docs, [BASE], REFRESH, client=site.client())

    asked = {request.url.path: request for request in site.pages_asked()}
    assert set(asked) == {INDEX, START}
    assert asked[INDEX].headers["if-none-match"] == '"index-1"'
    assert asked[INDEX].headers["if-modified-since"] == "Wed, 01 Oct 2026 10:00:00 GMT"


def test_a_page_the_site_says_is_not_modified_is_unchanged_and_untouched(
    docs: Collection,
):
    site = a_site()
    add_docs(docs, [BASE], ADD, client=site.client())
    before = {page: path.read_bytes() for page, (_, _, path) in held(docs).items()}

    report = add_docs(docs, [BASE], REFRESH, client=site.client())

    assert [item.outcome for item in report.outcomes] == [Outcome.UNCHANGED] * 2
    after = {page: path.read_bytes() for page, (_, _, path) in held(docs).items()}
    assert after == before


def test_a_changed_page_is_rewritten_where_it_is_under_the_same_identifier(
    docs: Collection,
):
    site = a_site()
    add_docs(docs, [BASE], ADD, client=site.client())
    frontmatter, _, path = held(docs)["guide/start"]
    site.pages[START] = Served(
        a_page("Getting started", "Install it with uv."), etag='"start-2"'
    )

    report = add_docs(docs, [BASE], REFRESH, client=site.client())

    by_page = {item.identifier: item.outcome for item in report.outcomes}
    assert by_page == {
        f"{BASE}index.html": Outcome.UNCHANGED,
        f"{BASE}guide/start.html": Outcome.CHANGED,
    }
    refreshed, body, refreshed_path = held(docs)["guide/start"]
    assert refreshed.id == frontmatter.id
    assert refreshed_path == path
    assert "Install it with uv." in body
    assert refreshed.docs.etag == '"start-2"'
    assert refreshed.source.at > frontmatter.source.at


def test_a_changed_page_reports_its_identifier(docs: Collection):
    site = a_site()
    add_docs(docs, [BASE], ADD, client=site.client())
    document_id = held(docs)["guide/start"][0].id
    site.pages[START] = Served(a_page("Getting started", "Changed."), etag='"s2"')

    report = add_docs(docs, [BASE], REFRESH, client=site.client())

    changed = [item for item in report.outcomes if item.outcome is Outcome.CHANGED]
    assert [item.document_id for item in changed] == [document_id]


# ---------------------------------------------------------------------------
# Refreshing without validators
# ---------------------------------------------------------------------------


def test_without_validators_the_text_is_compared(docs: Collection):
    site = a_site(etag=False)
    add_docs(docs, [BASE], ADD, client=site.client())
    before = {page: path.read_bytes() for page, (_, _, path) in held(docs).items()}
    site.asked.clear()

    report = add_docs(docs, [BASE], REFRESH, client=site.client())

    # Asked for in full, since nothing could be asked conditionally ...
    assert len(site.pages_asked()) == 2
    assert all("if-none-match" not in r.headers for r in site.pages_asked())
    # ... and the same text is not written again.
    assert [item.outcome for item in report.outcomes] == [Outcome.UNCHANGED] * 2
    after = {page: path.read_bytes() for page, (_, _, path) in held(docs).items()}
    assert after == before


def test_without_validators_a_changed_text_is_rewritten(docs: Collection):
    site = a_site(etag=False)
    add_docs(docs, [BASE], ADD, client=site.client())
    site.pages[INDEX] = Served(a_page("Overview", "What it is now."))

    report = add_docs(docs, [BASE], REFRESH, client=site.client())

    assert Outcome.CHANGED in {item.outcome for item in report.outcomes}
    assert "What it is now." in held(docs)["index"][1]


def test_a_refresh_that_cannot_fetch_a_page_leaves_it_as_it_was(docs: Collection):
    site = a_site()
    add_docs(docs, [BASE], ADD, client=site.client())
    path = held(docs)["index"][2]
    before = path.read_bytes()
    site.failing.add(INDEX)

    report = add_docs(docs, [BASE], REFRESH, client=site.client())

    failed = [item for item in report.outcomes if item.outcome is Outcome.FAILED]
    assert [item.identifier for item in failed] == [f"{BASE}index.html"]
    assert path.read_bytes() == before


def test_a_page_new_to_the_site_is_added_by_a_refresh(docs: Collection):
    site = a_site()
    site.pages.pop(START)
    add_docs(docs, [BASE], ADD, client=site.client())
    site.pages[START] = Served(a_page("Getting started", "New."), etag='"s"')

    report = add_docs(docs, [BASE], REFRESH, client=site.client())

    by_page = {item.identifier: item.outcome for item in report.outcomes}
    assert by_page[f"{BASE}guide/start.html"] is Outcome.ADDED


def test_a_refreshed_page_is_paced_like_a_new_one(
    docs: Collection, monkeypatch: pytest.MonkeyPatch
):
    """Each held page costs a request when refreshed, so it costs a wait."""
    site = a_site()
    paced = AddOptions(project="example", request_delay_seconds=0.5, refresh=True)
    add_docs(docs, [BASE], ADD, client=site.client())
    slept: list[float] = []
    monkeypatch.setattr(
        "kennis.engine.corpus.add.time.sleep", lambda seconds: slept.append(seconds)
    )

    add_docs(docs, [BASE], paced, client=site.client())

    # One wait, of what is left of the delay once the first request has
    # started (2026-10-27, requests to a site overlap).
    assert len(slept) == 1
    assert 0 < slept[0] <= 0.5


def test_a_refresh_keeps_a_page_in_its_version(docs: Collection):
    site = a_site()
    add_docs(docs, [BASE], ADD, client=site.client())
    site.pages[INDEX] = Served(a_page("Overview", "Moved on."), etag='"i2"')

    add_docs(docs, [BASE], REFRESH, client=site.client())

    frontmatter, _, path = held(docs)["index"]
    assert frontmatter.docs.version == "2.1"
    assert path.parent == docs.path / "example" / "2.1"


# ---------------------------------------------------------------------------
# Removing a version
# ---------------------------------------------------------------------------


def a_page_file(tmp_path: Path, version: str, name: str) -> Path:
    source = tmp_path / "sources" / version / f"{name}.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(f"# {name}\n\nRelease {version} of {name}.\n", encoding="utf-8")
    return source


def git_log(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    return result.stdout.splitlines()


def git_status(root: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    return result.stdout


@pytest.fixture
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Context:
    from click.testing import CliRunner

    from kennis.cli.__main__ import main
    from kennis.context import existing_corpus

    monkeypatch.setenv("KENNIS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("KENNIS_CORPUS_ROOT", str(tmp_path / "corpus"))
    monkeypatch.setenv("KENNIS_EMBEDDING_BACKEND", "none")
    run = CliRunner()
    assert run.invoke(main, ["corpus", "init"]).exit_code == 0
    for version in ("2.12", "2.14"):
        for name in ("models", "fields"):
            source = a_page_file(tmp_path, version, name)
            adding = ["corpus", "add", "-d", "--project", "pydantic", "--version"]
            result = run.invoke(main, [*adding, version, str(source)])
            assert result.exit_code == 0, result.output
    return existing_corpus()


def docs_of(context: Context) -> Path:
    return context.corpus_root / "docs"


def test_removing_a_version_removes_every_page_of_it_and_no_other(context: Context):
    removed = remove_docs_version(context, "pydantic", "2.12")

    assert removed.pages == 2
    assert not (docs_of(context) / "pydantic" / "2.12").exists()
    assert project_versions(docs_of(context))["pydantic"].held == ("2.14",)


def test_removing_the_current_version_makes_another_current(context: Context):
    assert project_versions(docs_of(context))["pydantic"].current == "2.14"

    removed = remove_docs_version(context, "pydantic", "2.14")

    assert removed.current == "2.12"
    assert project_versions(docs_of(context))["pydantic"].current == "2.12"
    # The record named the version that went, so it goes with it.
    assert not current_version_file(docs_of(context), "pydantic").exists()


def test_removing_another_version_keeps_the_current_one_recorded(context: Context):
    record = current_version_file(docs_of(context), "pydantic")
    before = record.read_text(encoding="utf-8")

    remove_docs_version(context, "pydantic", "2.12")

    assert record.read_text(encoding="utf-8") == before


def test_removing_the_last_version_removes_the_project(context: Context):
    remove_docs_version(context, "pydantic", "2.12")
    removed = remove_docs_version(context, "pydantic", "2.14")

    assert removed.current is None
    assert not (docs_of(context) / "pydantic").exists()


def test_removing_a_version_is_one_commit_and_leaves_nothing_behind(context: Context):
    before = git_log(context.corpus_root)

    remove_docs_version(context, "pydantic", "2.12")

    after = git_log(context.corpus_root)
    assert len(after) == len(before) + 1
    assert after[0].startswith("remove(docs):")
    assert "pydantic 2.12" in after[0]
    assert git_status(context.corpus_root) == ""


def test_a_version_not_held_is_refused_with_the_ones_that_are(context: Context):
    with pytest.raises(InputError) as raised:
        remove_docs_version(context, "pydantic", "9.9")

    assert "9.9" in str(raised.value)
    assert "2.12" in str(raised.value) and "2.14" in str(raised.value)
    assert project_versions(docs_of(context))["pydantic"].held == ("2.12", "2.14")


def test_a_project_not_held_is_refused(context: Context):
    with pytest.raises(InputError):
        remove_docs_version(context, "attrs", "2.12")


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def cli(*arguments: str) -> tuple[int, str]:
    from click.testing import CliRunner

    from kennis.cli.__main__ import main

    result = CliRunner().invoke(main, list(arguments))
    return result.exit_code, result.output


def test_corpus_version_lists_each_project_with_its_current_version(context: Context):
    code, output = cli("corpus", "version")

    assert code == 0, output
    line = next(line for line in output.splitlines() if "pydantic" in line)
    assert "2.12" in line and "2.14 (current)" in line


def test_corpus_version_makes_a_version_current(context: Context):
    code, output = cli("corpus", "version", "pydantic", "2.12")

    assert code == 0, output
    assert project_versions(docs_of(context))["pydantic"].current == "2.12"
    assert git_log(context.corpus_root)[0] == "version(docs): pydantic 2.12"


def test_corpus_version_refuses_a_version_not_held(context: Context):
    code, output = cli("corpus", "version", "pydantic", "9.9")

    assert code != 0
    assert "2.12" in output and "2.14" in output


def test_corpus_remove_removes_a_version_in_one_command(context: Context):
    code, output = cli(
        "corpus", "remove", "--project", "pydantic", "--version", "2.12", "-y"
    )

    assert code == 0, output
    assert project_versions(docs_of(context))["pydantic"].held == ("2.14",)
    assert "2 documents" in output


def test_corpus_remove_asks_first_and_says_how_many_pages_go(context: Context):
    from click.testing import CliRunner

    from kennis.cli.__main__ import main

    result = CliRunner().invoke(
        main,
        ["corpus", "remove", "--project", "pydantic", "--version", "2.12"],
        input="n\n",
    )

    assert "2 documents" in result.output
    assert project_versions(docs_of(context))["pydantic"].held == ("2.12", "2.14")


@pytest.mark.parametrize(
    ("arguments", "says"),
    [
        (["models", "--project", "pydantic", "--version", "2.12"], "not both"),
        (["--version", "2.12"], "--project"),
        (["--project", "pydantic"], "--version"),
        ([], "--project"),
    ],
)
def test_corpus_remove_refuses_an_unclear_request(
    context: Context, arguments: list[str], says: str
):
    code, output = cli("corpus", "remove", "-y", *arguments)

    assert code != 0
    assert says in output
    assert project_versions(docs_of(context))["pydantic"].held == ("2.12", "2.14")


def test_refresh_is_refused_outside_docs(context: Context, tmp_path: Path):
    source = tmp_path / "a-note.md"
    source.write_text("# A note\n\nText.\n", encoding="utf-8")

    code, output = cli("corpus", "add", "-n", "--refresh", str(source))

    assert code != 0
    assert "--refresh" in output and "docs" in output


def test_refresh_reaches_the_add_and_its_count_is_reported(
    context: Context, tmp_path: Path
):
    source = tmp_path / "sources" / "2.12" / "models.md"
    source.write_text("# models\n\nRelease 2.12, revised.\n", encoding="utf-8")
    adding = ["corpus", "add", "-d", "--project", "pydantic", "--version", "2.12"]

    code, output = cli(*adding, "--refresh", str(source))

    assert code == 0, output
    assert "1 updated" in output
    body = (docs_of(context) / "pydantic" / "2.12" / "models.md").read_text(
        encoding="utf-8"
    )
    assert "revised" in body
