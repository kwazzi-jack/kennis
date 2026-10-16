"""Publishing to PyPI, and the notice that says where data goes.

Two kinds of agreement no other test sees. The workflows must agree with the
trusted publishers registered on PyPI and TestPyPI, which match a workflow by
its file name and environment; a renamed file or environment fails at upload
time, after a release has been announced. And `docs/privacy.md` must name
every host kennis's own code addresses, so that a new outside service cannot
arrive without the notice saying so.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
PRIVACY_NOTICE = PROJECT_ROOT / "docs" / "privacy.md"

type Workflow = dict[str, object]

# What each publisher on PyPI was registered with, written by hand: deriving
# it from the workflow files would make this test agree with whatever they
# say. Changing either side means changing the registration on the index.
PUBLISHERS: dict[str, tuple[str, str]] = {
    "rehearse.yml": ("testpypi", "https://test.pypi.org/legacy/"),
    "release.yml": ("pypi", ""),
}

# Hosts that appear in a URL in the source and that kennis never contacts.
NEVER_CONTACTED: dict[str, str] = {
    "github.com": "named inside kennis's User-Agent string, never requested",
    "www.sitemaps.org": "an XML namespace in a sitemap, compared, not fetched",
    "www.w3.org": "the Atom XML namespace, compared, not fetched",
    "localhost": "the default address of a local ollama, on this machine",
    "stimela.readthedocs.io": "an example inside a comment pack init writes",
}


def load_workflow(name: str) -> Workflow:
    loaded = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def jobs_of(workflow: Workflow) -> dict[str, dict[str, object]]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def run_scripts(job: dict[str, object]) -> list[str]:
    steps = job.get("steps", [])
    assert isinstance(steps, list)
    return [step["run"] for step in steps if "run" in step]


@pytest.mark.parametrize("name", sorted(PUBLISHERS))
def test_only_the_publishing_job_can_mint_an_upload_token(name: str):
    """`id-token: write` is the whole credential. A workflow-level grant
    would hand it to the build job too, which runs the project's own build
    backend on whatever the ref contains."""
    workflow = load_workflow(name)
    assert "id-token" not in (workflow.get("permissions") or {})
    holders = [
        job_name
        for job_name, job in jobs_of(workflow).items()
        if (job.get("permissions") or {}).get("id-token") == "write"
    ]
    assert len(holders) == 1, holders
    publisher = jobs_of(workflow)[holders[0]]
    environment, publish_url = PUBLISHERS[name]
    declared = publisher.get("environment")
    # GitHub accepts the environment as a bare name or as a mapping with one.
    name_of = declared.get("name") if isinstance(declared, dict) else declared
    assert name_of == environment
    (upload,) = [script for script in run_scripts(publisher) if "uv publish" in script]
    if publish_url:
        assert publish_url in upload
    else:
        assert "--publish-url" not in upload


def test_a_release_refuses_a_tag_that_is_not_the_projects_version():
    """The shape of #175: a tag on a commit whose `pyproject.toml` says
    something else. PyPI would accept the upload under the file's version
    and the tag would name a release that does not exist."""
    workflow = load_workflow("release.yml")
    scripts = [
        script for job in jobs_of(workflow).values() for script in run_scripts(job)
    ]
    assert any(
        "uv version --short" in script and "GITHUB_REF_NAME" in script
        for script in scripts
    )


def matrix_pairs(job: dict[str, object]) -> set[tuple[str, str]]:
    """The (os, python) pairs a job's matrix runs, with `include` added.
    A job without a matrix runs nowhere this can name, so it is empty."""
    strategy = job.get("strategy")
    if not isinstance(strategy, dict):
        return set()
    matrix = strategy["matrix"]
    assert isinstance(matrix, dict)
    pairs = {
        (str(os_name), str(python))
        for os_name in matrix.get("os", [])
        for python in matrix.get("python", [])
    }
    pairs |= {
        (str(entry["os"]), str(entry["python"])) for entry in matrix.get("include", [])
    }
    return pairs


def test_the_rehearsal_installs_on_every_pair_the_tests_run_on():
    """The tests install from the lock; a person's install resolves afresh,
    and what it finds depends on the platform and the Python - a dependency
    with no wheel for 3.14 or for Windows. So the rehearsal installs the
    uploaded wheel wherever the suite passes, and nowhere else."""
    tested = matrix_pairs(jobs_of(load_workflow("tests.yml"))["test"])
    rehearsed = matrix_pairs(jobs_of(load_workflow("rehearse.yml"))["install"])
    assert len(tested) >= 6, "the test matrix is smaller than this test assumes"
    assert rehearsed == tested


def hosts_named_in_source() -> dict[str, list[str]]:
    """Every host in a URL inside a string literal under `src/kennis`,
    docstrings excluded, because a docstring describes rather than calls.
    A host reached through a library's own default - the OpenAI API, the
    Hugging Face hub - is not in a literal, and the notice names those by
    hand."""
    found: dict[str, list[str]] = {}
    for path in sorted((PROJECT_ROOT / "src" / "kennis").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node,
                ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                for match in re.finditer(r"https?://([A-Za-z0-9.-]+)", node.value):
                    found.setdefault(match.group(1), []).append(
                        str(path.relative_to(PROJECT_ROOT))
                    )
    return found


def test_the_notice_names_every_host_kennis_addresses():
    notice = PRIVACY_NOTICE.read_text(encoding="utf-8")
    hosts = hosts_named_in_source()
    assert "api.unpaywall.org" in hosts, "the scan no longer finds a known host"
    missing = {
        host: paths
        for host, paths in hosts.items()
        if host not in NEVER_CONTACTED and f"`{host}`" not in notice
    }
    assert not missing, f"docs/privacy.md does not name {missing}"


def test_an_exemption_is_still_needed():
    """An exemption whose host has left the source would silently admit it
    again the day it returns as a real request."""
    hosts = hosts_named_in_source()
    assert set(NEVER_CONTACTED) <= set(hosts), set(NEVER_CONTACTED) - set(hosts)
