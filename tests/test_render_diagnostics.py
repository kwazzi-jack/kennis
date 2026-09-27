"""Every diagnostic condition, and the words a front end gives it.

Concern #285. The engine used to build these sentences itself and the
command line printed them unchanged, so `render/` was bypassed for the
one event type that is pure prose. The engine now names the condition
and carries its fields; the words live here, which is what lets a second
front end - the MCP server, v0.4 - hand a client the code and the fields
instead of a paragraph.
"""

from __future__ import annotations

import pytest

from kennis.engine.events import (
    DiagnosticDetail,
    DocumentSkipped,
    DocumentUnsearchable,
    FrontmatterUnreadable,
    MetadataUnavailable,
    NoPagesDiscovered,
    TitleDotStripped,
)
from kennis.render.diagnostics import describe_diagnostic

# One of every condition, so the exhaustiveness test below cannot pass by
# forgetting one.
# A PEP 695 alias is a `TypeAliasType`; the union it stands for is
# `__value__`, and its members are that union's `__args__`.
DECLARED = set(DiagnosticDetail.__value__.__args__)

EVERY_CONDITION: tuple[DiagnosticDetail, ...] = (
    DocumentUnsearchable(problem="notes/a.md: bad yaml", path="notes/a.md"),
    DocumentUnsearchable(problem=None, path="notes/a.md"),
    FrontmatterUnreadable(path="conventions/naming.md"),
    TitleDotStripped(title=".hidden"),
    DocumentSkipped(problem="notes/a.md: bad yaml"),
    MetadataUnavailable(identifier="1101.1764"),
    NoPagesDiscovered(base_url="https://x.example", mode="sphinx", path_prefix=None),
)


@pytest.mark.parametrize("detail", EVERY_CONDITION, ids=lambda d: d.code)
def test_every_condition_has_words(detail: DiagnosticDetail):
    said = describe_diagnostic(detail)

    assert said
    assert said == said.strip()
    assert not said.endswith(".")


def test_every_condition_type_is_covered():
    """The guard behind the parametrisation above: a condition added to
    the union and not to `EVERY_CONDITION` is not being rendered by any
    test, and the list would go stale in silence."""
    covered = {type(detail) for detail in EVERY_CONDITION}
    declared = DECLARED

    assert covered == declared


def test_an_unreadable_document_names_the_problem_and_the_consequence():
    said = describe_diagnostic(
        DocumentUnsearchable(problem="notes/a.md: bad yaml", path="notes/a.md")
    )

    assert "notes/a.md: bad yaml" in said
    assert "searchable" in said


def test_an_unreadable_document_with_no_problem_names_the_path():
    """`problem` is absent when the reader could not say what was wrong,
    and a sentence built around an empty string says nothing."""
    said = describe_diagnostic(DocumentUnsearchable(problem=None, path="notes/a.md"))

    assert "notes/a.md" in said


def test_missing_metadata_names_the_identifier_and_what_was_lost():
    said = describe_diagnostic(MetadataUnavailable(identifier="1101.1764"))

    assert "1101.1764" in said
    assert "citekey" in said


def test_no_pages_names_the_prefix_only_when_there_is_one():
    """The prefix is the surprising half - it is derived from the URL, so
    a link below the documentation root narrows the crawl silently - and
    naming an absent one would be noise."""
    with_prefix = describe_diagnostic(
        NoPagesDiscovered(
            base_url="https://x.example", mode="sphinx", path_prefix="guide/"
        )
    )
    without = describe_diagnostic(
        NoPagesDiscovered(base_url="https://x.example", mode="sphinx", path_prefix=None)
    )

    assert "guide/" in with_prefix
    assert "under" not in without


def test_a_stripped_title_names_the_title():
    said = describe_diagnostic(TitleDotStripped(title=".hidden"))

    assert ".hidden" in said


def test_a_skipped_document_says_it_was_left_alone():
    said = describe_diagnostic(DocumentSkipped(problem="notes/a.md: bad yaml"))

    assert "notes/a.md: bad yaml" in said
    assert "left alone" in said


def test_unreadable_frontmatter_names_the_file():
    said = describe_diagnostic(FrontmatterUnreadable(path="conventions/naming.md"))

    assert "conventions/naming.md" in said


def test_each_code_is_distinct_and_stable():
    """The code is what crosses a wire. Two conditions sharing one, or a
    code that is not a lowercase slug, would both be found only by
    whoever consumed it."""
    codes = [type(detail).code for detail in EVERY_CONDITION]

    assert len(set(codes)) == len(DECLARED)
    for code in codes:
        assert code == code.lower()
        assert " " not in code
