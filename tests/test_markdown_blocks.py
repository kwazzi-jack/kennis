"""Splitting a markdown body into prose, fences and code.

The property that matters is that nothing is lost: the terminal shows the
characters the corpus holds, and an agent reading the same document sees the
same bytes. Concern #214.
"""

from __future__ import annotations

import time

import pytest

from kennis.render.markdown import (
    Block,
    detected_language,
    split_blocks,
)


def kinds(text: str) -> list[str]:
    return [block.kind for block in split_blocks(text)]


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Just prose.\n",
        "```\ncode\n```\n",
        "```python\nprint(1)\n```\n",
        "Before.\n\n```yaml\na: 1\n```\n\nAfter.\n",
        # Unterminated: a fence opened and never closed, which a truncated
        # document really does produce.
        "Before.\n\n```\ncode without an end\n",
        # A tilde fence, which commonmark allows and which a document
        # containing backticks has to use.
        "~~~\ncode\n~~~\n",
        # Four backticks, which is how a block containing ``` is written.
        "````\n```\ninner\n```\n````\n",
        # Indented, which commonmark allows up to three spaces.
        "  ```py\n  print(1)\n  ```\n",
        # No trailing newline at all.
        "```\ncode\n```",
        # A line that is only backticks in the middle of prose.
        "Some ``` prose with a fence marker inline.\n",
    ],
)
def test_the_blocks_reassemble_into_exactly_what_was_given(text: str):
    """Character for character. A renderer that drops a newline turns a
    document into a different document."""
    assert "".join(block.text for block in split_blocks(text)) == text


def test_prose_alone_is_one_block():
    assert kinds("Just prose.\nMore prose.\n") == ["prose"]


def test_a_fenced_block_is_three_blocks():
    """The fences are their own blocks rather than being consumed, so they
    can be styled where they stand."""
    assert kinds("```\ncode\n```\n") == ["fence", "code", "fence"]


def test_a_fence_carries_the_language_it_named():
    blocks = split_blocks("```python\nprint(1)\n```\n")

    assert blocks[0].language == "python"
    assert blocks[1].language == "python"
    assert blocks[1].text == "print(1)\n"


def test_a_fence_that_names_nothing_has_no_language():
    """262 of 262 blocks in a real corpus. Guessing one produced MySQL,
    GDScript and Tera Term macro for YAML, so the absence is recorded rather
    than filled in. Concern #214."""
    blocks = split_blocks("```\na: 1\n```\n")

    assert blocks[1].kind == "code"
    assert blocks[1].language == ""


def test_an_unterminated_fence_still_ends_the_document():
    """A truncated document is a document. Everything after the opening
    fence is code, and nothing is lost."""
    blocks = split_blocks("```\nno end here\n")

    assert [block.kind for block in blocks] == ["fence", "code"]


def test_a_closing_fence_must_match_the_one_that_opened():
    """A ``` inside a ```` block is content, not a terminator - which is the
    whole reason four-backtick fences exist."""
    blocks = split_blocks("````\n```\ninner\n```\n````\n")

    assert [block.kind for block in blocks] == ["fence", "code", "fence"]
    assert blocks[1].text == "```\ninner\n```\n"


def test_a_fence_marker_inside_a_line_is_not_a_fence():
    """A fence is a line of its own. `Some ``` prose` is prose."""
    assert kinds("Some ``` prose with a marker.\n") == ["prose"]


def test_a_tilde_fence_is_not_closed_by_a_backtick_one():
    blocks = split_blocks("~~~\n```\ninner\n```\n~~~\n")

    assert [block.kind for block in blocks] == ["fence", "code", "fence"]


def test_an_empty_code_block_has_no_code_block_between_its_fences():
    """Two fences with nothing between them. An empty `code` block would
    render an empty line the document does not contain."""
    assert kinds("```\n```\n") == ["fence", "fence"]


def test_a_block_knows_its_own_text():
    block = Block(kind="prose", text="hello\n")

    assert block.text == "hello\n"
    assert block.language == ""


class TestDetectedLanguage:
    """What a block can be *proved* to be, which is not what it might be.

    The distinction that matters: `guess_lexer` scores a block against every
    lexer and returns the best, so it always answers. `detected_language`
    parses, so it answers only when the text is a document of that kind.
    """

    def test_nested_yaml_is_detected(self):
        assert detected_language("recipe:\n  steps:\n    a:\n      cab: c\n") == "yaml"

    def test_a_yaml_sequence_of_mappings_is_detected(self):
        assert detected_language("- cab: x\n- cab: y\n") == "yaml"

    def test_prose_with_colons_is_not_yaml(self):
        """Two sentences with colons parse as a two-key mapping. Requiring a
        nested value is what separates a document from a paragraph, and on
        the real corpus it cost nothing: 95 of 137 either way."""
        assert detected_language("Note: this matters.\nAlso: it does.\n") == ""

    def test_a_flat_mapping_is_not_enough(self):
        assert detected_language("DEFAULT: ratt-parrot\nOTHER: x\n") == ""

    def test_a_bullet_list_is_not_yaml(self):
        assert detected_language("- one\n- two\n") == ""

    def test_python_is_not_yaml(self):
        assert detected_language("def solve(matrix):\n    return matrix.T\n") == ""

    def test_shell_is_not_yaml(self):
        assert detected_language("cd /tmp\nls -la\nmake install\n") == ""

    def test_a_table_is_not_yaml(self):
        assert detected_language("| a | b |\n|---|---|\n| 1 | 2 |\n") == ""

    def test_toml_is_not_yaml(self):
        assert detected_language("[tool.ruff]\nline-length = 88\n") == ""

    def test_a_traceback_is_not_yaml(self):
        assert (
            detected_language(
                'Traceback (most recent call last):\n  File "x.py", line 1\n'
            )
            == ""
        )

    def test_json_is_detected_as_json_not_yaml(self):
        """JSON is a subset of YAML, so the YAML test would accept it and
        pygments would then lex it with the wrong lexer. JSON is tried
        first because it is the narrower claim."""
        assert detected_language('{"a": {"b": 1}}\n') == "json"

    def test_a_json_array_is_detected(self):
        assert detected_language('[{"a": 1}, {"b": 2}]\n') == "json"

    def test_a_bare_json_scalar_is_not_json(self):
        """`json.loads("5")` succeeds. A number is not a document."""
        assert detected_language("5\n") == ""

    def test_malformed_yaml_is_not_detected(self):
        assert detected_language("key: [unclosed\n  other: x\n") == ""

    def test_empty_text_is_not_detected(self):
        assert detected_language("") == ""
        assert detected_language("\n\n") == ""

    def test_an_alias_bomb_is_not_expanded(self):
        """`compose` builds a node graph and constructs no values, so the
        classic alias-expansion payload costs what its 289 bytes cost. A
        converted third-party document can contain anything."""
        bomb = (
            'a: &a ["x","x","x","x","x","x","x","x","x"]\n'
            "b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a]\n"
            "c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b]\n"
            "d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c]\n"
            "e: &e [*d,*d,*d,*d,*d,*d,*d,*d,*d]\n"
            "f: &f [*e,*e,*e,*e,*e,*e,*e,*e,*e]\n"
            "g: &g [*f,*f,*f,*f,*f,*f,*f,*f,*f]\n"
            "h: &h [*g,*g,*g,*g,*g,*g,*g,*g,*g]\n"
        )
        started = time.monotonic()

        assert detected_language(bomb) == "yaml"
        assert time.monotonic() - started < 1.0

    def test_a_declared_language_is_never_overridden(self):
        """Detection answers for blocks that named nothing. A fence that
        said `text` meant it."""
        blocks = split_blocks("```text\nrecipe:\n  steps:\n    a: 1\n```\n")
        code = next(block for block in blocks if block.kind == "code")

        assert code.language == "text"
