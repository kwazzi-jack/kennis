"""A string holding a colon is written in double quotes (#523, Brian,
2026-10-21).

YAML reads `from: copy:0yldj2vkpy` as one string, because a colon starts a
mapping only when a space or the end follows it. Quoting is so that no
reader of a document - a person, another tool - needs to know that rule.
Existing documents keep the bare form until kennis rewrites them; both
read the same.
"""

from __future__ import annotations

import yaml

from kennis.engine.frontmatter import join_frontmatter, split_frontmatter


def block_of(frontmatter: dict[str, object]) -> str:
    return join_frontmatter(frontmatter, "Body.\n").split("---\n")[1]


def test_a_source_with_a_colon_is_written_in_double_quotes():
    block = block_of({"source": {"from": "copy:0yldj2vkpy", "via": "copy"}})

    assert '  from: "copy:0yldj2vkpy"\n' in block
    assert "  via: copy\n" in block


def test_every_kind_of_source_is_quoted_alike():
    for value in ("pack:alpha/notes/a.md", "url:https://example.org/a", "inline:"):
        assert f'from: "{value}"' in block_of({"source": {"from": value}})


def test_a_string_without_a_colon_stays_bare():
    assert "title: Rivers\n" in block_of({"title": "Rivers"})


def test_what_is_written_reads_back_as_it_was():
    frontmatter = {
        "id": "0yldj2vkpy",
        "title": 'A "quoted": title',
        "source": {"from": "copy:0yldj2vkpy"},
        "tags": ["a:b", "plain"],
    }

    read, body = split_frontmatter(join_frontmatter(frontmatter, "Body.\n"))

    assert read == frontmatter
    assert body == "Body.\n"


def test_the_bare_form_an_older_kennis_wrote_reads_the_same():
    assert yaml.safe_load("from: copy:0yldj2vkpy") == {"from": "copy:0yldj2vkpy"}
