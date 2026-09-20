"""The engine's exceptions, and the note that names the way out of one."""

from __future__ import annotations

import pytest

from kennis.engine.errors import (
    CorpusBusy,
    CorpusNotFound,
    GitUnavailable,
    KennisError,
    SettingsError,
)

SUBCLASSES = (CorpusNotFound, CorpusBusy, GitUnavailable, SettingsError)


def test_a_bare_error_has_no_resolution():
    error = KennisError("something went wrong")

    assert str(error) == "something went wrong"
    assert error.resolution is None
    assert not getattr(error, "__notes__", [])


def test_a_resolution_becomes_a_note_on_the_exception():
    """The note travels with the exception, so a handler that knows nothing
    about kennis still prints the command that fixes the problem."""
    error = KennisError("no corpus here", resolution="kennis corpus init")

    assert error.resolution == "kennis corpus init"
    assert error.__notes__ == ["run `kennis corpus init`"]


def test_the_resolution_is_readable_without_parsing_the_note():
    """A front end renders the resolution as its own line, so it must not
    have to scrape `__notes__` to find it."""
    error = CorpusNotFound()

    assert error.resolution is not None
    assert error.resolution not in str(error)


@pytest.mark.parametrize("subclass", SUBCLASSES, ids=lambda cls: cls.__name__)
def test_every_subclass_is_a_kennis_error(subclass: type[KennisError]):
    assert issubclass(subclass, KennisError)
    assert issubclass(subclass, Exception)


@pytest.mark.parametrize("subclass", SUBCLASSES, ids=lambda cls: cls.__name__)
def test_every_subclass_names_a_resolving_command_by_default(
    subclass: type[KennisError],
):
    error = subclass()

    assert error.resolution
    assert error.__notes__ == [f"run `{error.resolution}`"]


def test_a_caller_may_override_the_default_resolution():
    error = CorpusBusy(resolution="kennis corpus status")

    assert error.resolution == "kennis corpus status"
    assert error.__notes__ == ["run `kennis corpus status`"]


def test_a_caller_may_state_that_no_command_resolves_it():
    error = CorpusBusy(resolution=None)

    assert error.resolution is None
    assert not getattr(error, "__notes__", [])


def test_the_message_may_be_replaced_while_the_resolution_stands():
    error = CorpusNotFound("no corpus at /home/brian/knowledge")

    assert str(error) == "no corpus at /home/brian/knowledge"
    assert error.resolution == CorpusNotFound.default_resolution
