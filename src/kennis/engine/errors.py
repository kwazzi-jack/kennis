"""The engine's exceptions.

**Every error names the command that resolves it.** There is no state-derived
hint system deciding what advice a failure deserves; the error carries its own
answer, chosen where the failure is raised and by nothing else.

The resolution is recorded twice, on purpose. It is attached with `add_note`,
so it travels with the exception through a handler that knows nothing about
kennis and prints unaided at the bottom of a traceback; and it is kept as an
attribute, so a front end can render it in its own idiom - the command line as
a `hint:` line under the failure - without parsing `__notes__`.

These are *domain* exceptions. An engine module raising a front end's error
type is the inversion the engine/interface separation exists to forbid: the
command line is what turns `CorpusNotFound` into `Error: ...` and an exit
code, while the MCP server turns the same exception into a tool error.
"""

from __future__ import annotations


class _Unset:
    """Tells "the caller said nothing" apart from "the caller said `None`".

    `resolution=None` is a real answer - this failure has no command that
    fixes it - and it has to be distinguishable from an omitted argument,
    which means falling back to the subclass's default.
    """

    __slots__ = ()


_UNSET = _Unset()


class KennisError(Exception):
    """Something kennis could not do, and the command that would fix it.

    A subclass sets `default_resolution` to the command that resolves it in
    the usual case. A caller with better information passes `resolution`;
    a caller that knows nothing resolves this particular failure passes
    `resolution=None`, which is also the base class's own default - an error
    with no fix to name should say so by omission rather than by a
    placeholder.
    """

    default_message = "kennis could not complete the operation"
    default_resolution: str | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        resolution: str | _Unset | None = _UNSET,
    ) -> None:
        super().__init__(message if message is not None else self.default_message)
        self.resolution = (
            self.default_resolution if isinstance(resolution, _Unset) else resolution
        )
        if self.resolution is not None:
            self.add_note(f"run `{self.resolution}`")


class CorpusNotFound(KennisError):
    """No corpus exists where kennis was told to look."""

    default_message = "no corpus found"
    default_resolution = "kennis corpus init"


class CorpusBusy(KennisError):
    """Another kennis process holds the corpus lock.

    The lock is taken with a zero timeout, so a second caller is told the
    corpus is busy rather than left blocking on it.
    """

    default_message = "the corpus is in use by another kennis process"
    default_resolution = "kennis corpus status"


class GitUnavailable(KennisError):
    """The `git` binary is missing.

    kennis shells out to `git` rather than binding a library, and there is no
    fallback implementation, so this is a system requirement rather than a
    degraded mode.
    """

    default_message = "the git binary was not found on PATH"
    default_resolution = "sudo apt install git"


class SettingsError(KennisError):
    """A setting is missing, malformed, or outside its permitted range."""

    default_message = "a setting could not be read"
    default_resolution = "kennis config show"


class UnknownCollection(KennisError):
    """A collection name kennis does not have.

    There are three, fixed: `notes`, `literature` and `docs`. A fourth is not
    a configuration option - each of the three is a different processing layer
    over one ingestion pipeline, not a folder someone may add to.
    """

    default_message = "no such collection"
    default_resolution = "kennis corpus status"


class DocumentNotFound(KennisError):
    """No document answers to the handle given.

    Also raised for an *ambiguous* handle. Two documents sharing a citekey or
    a title make that key useless, and the honest answer is that it addresses
    nothing; resolving it to whichever was walked first would silently hand
    back the wrong paper.
    """

    default_message = "no such document"
    default_resolution = "kennis corpus list"


class DocumentInvalid(KennisError):
    """A document on disk does not validate against its collection's schema.

    A missing field, a key kennis does not understand, or an `owner` from a
    vocabulary it does not recognise. Refused with the document named rather
    than guessed at: kennis ships no migration, because the corpora are
    rebuildable and there is no compatibility obligation.
    """

    default_message = "a document could not be read"
    default_resolution = "kennis corpus status"
