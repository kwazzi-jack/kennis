"""The report grammar: where a line sits, what it says, and when it is silent.

Colour is not asserted here. rich decides on it from `isatty`, which is false
under pytest, so what these tests see is the plain text - which is also what a
user piping a command to a file sees, and therefore worth pinning exactly. The
role table is tested in `test_theme.py`; the join between the two is the part
this milestone leaves unchecked.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from kennis.cli import display


@pytest.fixture(autouse=True)
def default_verbosity() -> Iterator[None]:
    display.set_verbosity()
    yield
    display.set_verbosity()


def capture(action: Callable[[], None]) -> str:
    """Whatever `action` prints to the report console, as plain text."""
    with display.console.capture() as captured:
        action()
    return captured.get()


def capture_errors(action: Callable[[], None]) -> str:
    with display.error_console.capture() as captured:
        action()
    return captured.get()


# ---------------------------------------------------------------------------
# Operation lines
# ---------------------------------------------------------------------------


def test_an_operation_puts_its_verb_at_the_margin():
    assert capture(lambda: display.operation("Initialized", "bundle at .kennis")) == (
        "Initialized bundle at .kennis\n"
    )


def test_an_operation_with_no_payload_is_the_verb_alone():
    assert capture(lambda: display.operation("Indexed")) == "Indexed\n"


@pytest.mark.parametrize(
    ("seconds", "rendered"),
    [
        (0.0, "0ms"),
        (0.007, "7ms"),
        (0.0405, "40ms"),
        (0.9994, "999ms"),
        (1.0, "1.0s"),
        (4.72, "4.7s"),
        (59.9, "59.9s"),
        (60.0, "1m00s"),
        (145.0, "2m25s"),
        (3725.0, "62m05s"),
    ],
)
def test_elapsed_time_is_printed_at_a_precision_a_reader_can_act_on(
    seconds: float, rendered: str
):
    """Milliseconds below a second: `in 0.0s` on work that took 40ms reads as
    a rounding artefact. Past a minute the seconds still matter but tenths do
    not."""
    line = capture(lambda: display.operation("Built", "index", elapsed=seconds))

    assert line == f"Built index in {rendered}\n"


def test_the_environment_banner_is_not_an_operation():
    assert capture(lambda: display.using("corpus at ~/knowledge")) == (
        "Using corpus at ~/knowledge\n"
    )


# ---------------------------------------------------------------------------
# Details
# ---------------------------------------------------------------------------


def test_a_detail_is_indented_one_step_under_its_operation():
    assert capture(lambda: display.detail("+", "literature/welman2024")) == (
        "  + literature/welman2024\n"
    )


@pytest.mark.parametrize("marker", ["+", "-", "~", "="])
def test_every_marker_sits_in_the_same_column(marker: str):
    assert capture(lambda: display.detail(marker, "a")) == f"  {marker} a\n"


def test_details_are_capped_so_a_large_batch_stays_readable():
    """The count is already on the operation line above, so the elision loses
    nothing but names."""
    items = [f"doc{number}" for number in range(14)]

    lines = capture(lambda: display.details("+", items)).splitlines()

    assert len(lines) == display.DETAIL_LIMIT + 1
    assert lines[-1] == "    ... and 4 more"


def test_a_batch_at_the_limit_is_not_elided():
    items = [f"doc{number}" for number in range(display.DETAIL_LIMIT)]

    lines = capture(lambda: display.details("+", items)).splitlines()

    assert len(lines) == display.DETAIL_LIMIT


def test_details_without_a_limit_prints_all_of_them():
    items = [f"doc{number}" for number in range(14)]

    lines = capture(lambda: display.details("+", items, limit=None)).splitlines()

    assert len(lines) == 14


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_a_warning_breaks_the_left_edge():
    """A problem must not scan as one more step that went fine."""
    assert capture(lambda: display.note("index is stale")) == (
        "warning: index is stale\n"
    )


def test_an_error_breaks_the_left_edge():
    assert capture(lambda: display.failure("could not read the corpus")) == (
        "error: could not read the corpus\n"
    )


def test_a_hint_is_subordinate_to_the_line_it_follows():
    assert capture(lambda: display.hint("run `kennis corpus init`")) == (
        "  hint: run `kennis corpus init`\n"
    )


def test_a_diagnostic_can_be_sent_to_stderr():
    """For a command whose stdout is a payload rather than a report."""
    assert capture_errors(lambda: display.note("stale", stderr=True)) == (
        "warning: stale\n"
    )


def test_the_next_step_is_phrased_once_and_everywhere_the_same():
    assert capture(lambda: display.next_step("kennis corpus index")) == (
        "  hint: run `kennis corpus index`\n"
    )


def test_the_next_step_takes_a_preamble_and_a_trailer():
    line = capture(
        lambda: display.next_step(
            "kennis corpus index", before="the index is stale;", note="to rebuild it"
        )
    )

    assert line == (
        "  hint: the index is stale; run `kennis corpus index` to rebuild it\n"
    )


def test_a_composite_command_suppresses_the_advice_its_parts_would_give():
    """`corpus sync` closes by telling you to run `corpus index`; inside
    `kennis setup` that is advice to do what the next phase does anyway."""

    def inside_a_composite() -> None:
        with display.following_steps(False):
            display.next_step("kennis corpus index")

    assert capture(inside_a_composite) == ""


def test_the_advice_returns_once_the_composite_ends():
    def around_a_composite() -> None:
        with display.following_steps(False):
            display.next_step("kennis corpus index")
        display.next_step("kennis corpus index")

    assert capture(around_a_composite).count("hint:") == 1


# ---------------------------------------------------------------------------
# Severities
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line_function",
    [display.info, display.success, display.warning, display.error, display.muted],
    ids=lambda function: function.__name__,
)
def test_a_lead_word_is_followed_by_the_rest_of_the_sentence(
    line_function: Callable[..., None],
):
    rendered = capture(lambda: line_function("3 documents", lead="Added"))

    assert rendered == "Added 3 documents\n"


def test_a_lead_word_with_no_sentence_stands_alone():
    assert capture(lambda: display.success(lead="Done")) == "Done\n"


def test_a_line_can_be_indented_under_the_operation_it_belongs_to():
    assert capture(lambda: display.muted("no changes", indent="  ")) == (
        "  no changes\n"
    )


# ---------------------------------------------------------------------------
# Verbosity
# ---------------------------------------------------------------------------


def test_quiet_suppresses_the_report():
    display.set_verbosity(quiet=True)

    assert capture(lambda: display.operation("Indexed", "19 documents")) == ""
    assert capture(lambda: display.detail("+", "a")) == ""
    assert capture(lambda: display.note("stale")) == ""
    assert capture(lambda: display.using("corpus at ~/knowledge")) == ""


def test_quiet_does_not_suppress_a_failure():
    """--quiet suppresses reports rather than problems."""
    display.set_verbosity(quiet=True)

    assert capture(lambda: display.failure("could not read the corpus")) == (
        "error: could not read the corpus\n"
    )


def test_a_progress_bar_is_not_drawn_when_it_would_land_in_a_file():
    """stdout is not a terminal under pytest, which is the same condition as
    a redirected command."""
    assert display.progress_wanted() is False


def test_progress_can_be_turned_off_on_its_own():
    display.set_verbosity(progress=False)

    assert display.progress_wanted() is False


def test_a_suppressed_progress_bar_still_yields_something_to_call():
    """So a caller never has to branch on whether a bar is being drawn."""
    with display.progress_bar("Indexing", total=3) as advance:
        advance()
        advance(2, 3)


# ---------------------------------------------------------------------------
# Fragments
# ---------------------------------------------------------------------------


def test_a_command_is_delimited_by_backticks():
    """The delimiter is what the highlighter reads to decide the style, so a
    call site that picks its own is choosing a colour without knowing it."""
    assert display.command("kennis corpus init") == "`kennis corpus init`"


def test_a_value_is_quoted_so_it_never_reads_as_a_command():
    assert display.value("welman2024") == "'welman2024'"


def test_a_path_is_printed_whole():
    assert capture(lambda: display.path("/home/brian/knowledge")) == (
        "/home/brian/knowledge\n"
    )


def test_plain_text_reaches_stdout_exactly_as_given():
    assert capture(lambda: display.plain("[not a style tag]")) == (
        "[not a style tag]\n"
    )


def test_interpolated_text_is_data_rather_than_markup():
    """A title containing a literal `[` must not be swallowed as a style tag."""
    assert capture(lambda: display.info("read [1] and [2]")) == "read [1] and [2]\n"


# ---------------------------------------------------------------------------
# Aborts
# ---------------------------------------------------------------------------


def test_an_abort_reports_through_the_themed_stderr_console():
    error = display.CliError("no corpus at ~/knowledge")

    assert capture_errors(error.show) == "Error: no corpus at ~/knowledge\n"


def test_a_cancellation_is_not_called_an_error():
    """Nothing went wrong, and calling it an error sends the reader looking
    for a cause."""
    cancelled = display.Cancelled("stopped before anything was written")

    assert capture_errors(cancelled.show) == (
        "Cancelled: stopped before anything was written\n"
    )


def test_a_cancellation_exits_with_the_shell_convention_for_sigint():
    assert display.Cancelled("stopped").exit_code == 130


def test_every_abort_kennis_writes_itself_is_one_type():
    """`PlainMessage` is what the help formatter checks, so a new abort type
    cannot silently get rich-click's bordered panel back."""
    assert issubclass(display.CliError, display.PlainMessage)
    assert issubclass(display.Cancelled, display.PlainMessage)
