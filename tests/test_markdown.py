"""Normalising a converter's output so that what is stored is markdown.

MinerU stores tables as raw HTML. On a 17-page MNRAS paper that was 15% of
the stored characters - 14252 characters of tag, 2722 `<td>` and 260 `<tr>`.
BM25 tokenises what is stored, so the index fills with `td` and `tr`, the
dense leg embeds them, and chunking splits a table mid-row with no header
carried over. Concern #154.
"""

from __future__ import annotations

from kennis.engine.corpus.markdown import normalise_markdown

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def test_an_html_table_becomes_a_pipe_table():
    html = (
        "<table><tr><td>Cores</td><td>Time</td></tr>"
        "<tr><td>4</td><td>9s</td></tr></table>"
    )

    assert normalise_markdown(html) == ("| Cores | Time |\n| --- | --- |\n| 4 | 9s |")


def test_the_first_row_gets_a_separator_beneath_it():
    """A pipe table without the `---` line is not a table. It renders as a
    run of text with pipes in it, which is worse than the HTML was."""
    html = "<table><tr><td>a</td></tr><tr><td>b</td></tr></table>"

    assert "| --- |" in normalise_markdown(html)


def test_a_header_cell_is_treated_as_a_cell():
    html = (
        "<table><tr><th>Name</th><th>Value</th></tr>"
        "<tr><td>x</td><td>1</td></tr></table>"
    )

    assert normalise_markdown(html) == "| Name | Value |\n| --- | --- |\n| x | 1 |"


def test_a_pipe_inside_a_cell_is_escaped():
    """An unescaped pipe would end the cell early and shift every column
    after it."""
    html = "<table><tr><td>a|b</td><td>c</td></tr></table>"

    assert normalise_markdown(html) == "| a\\|b | c |\n| --- | --- |"


def test_a_newline_inside_a_cell_becomes_a_space():
    """A pipe row is one line by construction."""
    html = "<table><tr><td>two\nlines</td><td>c</td></tr></table>"

    assert normalise_markdown(html) == "| two lines | c |\n| --- | --- |"


def test_a_ragged_table_is_padded_to_its_widest_row():
    """MinerU's rows are not guaranteed to be the same length, and a short
    row would otherwise put a cell under the wrong heading."""
    html = "<table><tr><td>a</td><td>b</td><td>c</td></tr><tr><td>d</td></tr></table>"

    assert normalise_markdown(html) == (
        "| a | b | c |\n| --- | --- | --- |\n| d |  |  |"
    )


def test_an_empty_table_is_removed_rather_than_left_as_tags():
    assert normalise_markdown("before<table></table>after") == "beforeafter"


def test_text_around_a_table_is_kept():
    html = "Results follow.\n\n<table><tr><td>a</td></tr></table>\n\nAs shown."

    normalised = normalise_markdown(html)

    assert normalised.startswith("Results follow.")
    assert normalised.endswith("As shown.")
    assert "<table>" not in normalised


def test_two_tables_are_both_converted():
    html = "<table><tr><td>a</td></tr></table>x<table><tr><td>b</td></tr></table>"

    normalised = normalise_markdown(html)

    assert normalised.count("| --- |") == 2
    assert "<table>" not in normalised


# ---------------------------------------------------------------------------
# Superscripts and subscripts
# ---------------------------------------------------------------------------
#
# Both converters emit these, so this is a shared convention rather than a
# MinerU defect - but `sup` and `sub` are still tokens the index would carry.


def test_a_superscript_becomes_a_caret():
    assert normalise_markdown("x<sup>2</sup>") == "x^2"


def test_a_subscript_becomes_an_underscore():
    assert normalise_markdown("G<sub>pq</sub>") == "G_pq"


def test_an_unknown_tag_is_left_alone():
    """Only the tags that were measured are handled. Stripping every tag
    would silently change text kennis has not looked at."""
    assert normalise_markdown("<mark>kept</mark>") == "<mark>kept</mark>"


# ---------------------------------------------------------------------------
# What must not be touched
# ---------------------------------------------------------------------------


def test_a_fenced_code_block_is_left_alone():
    text = "```html\n<table><tr><td>a</td></tr></table>\n```"

    assert normalise_markdown(text) == text


def test_inline_code_is_left_alone():
    text = "use `<sup>` for exponents"

    assert normalise_markdown(text) == text


def test_mathematics_is_left_alone():
    text = "$a<sup>2</sup>b$"

    assert normalise_markdown(text) == text


def test_text_with_no_html_is_returned_unchanged():
    text = "# A heading\n\nA paragraph with no tags at all.\n"

    assert normalise_markdown(text) == text


def test_a_table_containing_mathematics_is_still_converted():
    """Found by running the command, not by the suite. A real MinerU table
    had `$F _ { \\mathrm { m e d } }$` in a cell. Protecting maths by
    splitting the text put the `<table>` and its `</table>` into different
    fragments, so the table regex matched neither and 1270 `<td>` reached the
    corpus. Maths belongs inside cells; a table never belongs inside maths.
    """
    html = (
        "<table><tr><td>Name</td><td>$F_{med}$ (mJy)</td></tr>"
        "<tr><td>BfS 0</td><td>1.2</td></tr></table>"
    )

    normalised = normalise_markdown(html)

    assert "<td>" not in normalised
    assert "$F_{med}$" in normalised
    assert normalised.startswith("| Name | $F_{med}$ (mJy) |")


def test_a_table_inside_a_fenced_block_is_still_left_alone():
    """The protection that matters for tables is code, not maths."""
    text = "```\n<table><tr><td>a</td></tr></table>\n```"

    assert normalise_markdown(text) == text
