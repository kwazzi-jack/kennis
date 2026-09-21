"""What a documentation site is, as kennis addresses one.

A site is named by a project, and the project is both a frontmatter field and
a directory under the docs collection. That second role is why the name is
validated rather than taken as given: an unchecked name that becomes a path
component is a traversal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from kennis.engine.errors import InputError

# A project name becomes a directory, so it has to be a safe path component:
# lowercase alphanumerics plus `-` and `_`, and never leading punctuation,
# which rules out both `..` and `../evil`.
_PROJECT_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Host labels that name the service rather than the project, so the label
# before them is the one worth taking.
_SERVICE_LABELS: Final = frozenset({"readthedocs", "github", "gitlab", "netlify"})


@dataclass(frozen=True, slots=True)
class DocsSite:
    """One documentation site, and the scope of what is taken from it."""

    project: str
    base_url: str
    exclude: tuple[str, ...] = ()
    # "sphinx", "sitemap" or "crawl". None means probe for it.
    discovery: str | None = None
    # Crawl and sitemap scope. None means derive it from `base_url`.
    path_prefix: str | None = None

    def __post_init__(self) -> None:
        validate_project_name(self.project)


def validate_project_name(name: str) -> str:
    """`name` if it can be a directory, otherwise a refusal naming the rule."""
    if not _PROJECT_NAME.match(name):
        raise InputError(
            f"'{name}' is not a usable project name: it becomes a directory, so "
            "it must be lowercase letters, digits, '-' and '_', starting with a "
            "letter or a digit"
        )
    return name


def project_name_from_url(base_url: str) -> str:
    """A project name derived from the host of `base_url`.

    The first label of the host, except where that label names a hosting
    service rather than a project - `stimela.readthedocs.io` is stimela's,
    `docs.pytest.org` is pytest's. Lower-cased and stripped of anything the
    name rule does not allow, and refused rather than mangled if nothing is
    left, because a silently invented project name is a directory nobody
    asked for.
    """
    host = urlsplit(base_url).hostname or ""
    labels = [label for label in host.split(".") if label]
    if not labels:
        raise InputError(
            f"could not work out a project name from '{base_url}': name one with "
            "--project"
        )

    chosen = labels[0]
    if chosen in ("docs", "www") and len(labels) > 1:
        chosen = labels[1]
    elif len(labels) > 1 and labels[1] in _SERVICE_LABELS:
        chosen = labels[0]

    cleaned = re.sub(r"[^a-z0-9_-]", "-", chosen.lower()).strip("-_")
    if not cleaned or not _PROJECT_NAME.match(cleaned):
        raise InputError(
            f"could not work out a project name from '{base_url}': name one with "
            "--project"
        )
    return cleaned
