"""The words for each condition the engine can report.

Concern #285. A diagnostic used to arrive as a finished English sentence
built in `engine/`, and the command line printed it unchanged - so this
was the one event type for which `render/` did not exist. The engine now
names the condition and carries its facts as fields, and the sentence is
chosen here, where a second front end can choose differently.

`describe_diagnostic` is exhaustive over `DiagnosticDetail` by
construction: the `match` has an arm per member and no fall-through, so
a seventh condition added without a sentence is a type error rather than
a blank line in front of a user.
"""

from __future__ import annotations

from kennis.engine.events import (
    DiagnosticDetail,
    DocumentSkipped,
    DocumentUnsearchable,
    FrontmatterUnreadable,
    MetadataUnavailable,
    NoPagesDiscovered,
    TitleDotStripped,
)


def describe_diagnostic(detail: DiagnosticDetail) -> str:
    """One line for one condition, with no trailing stop.

    No trailing stop and no leading capital, because a front end decides
    where this sits: the command line puts `warning: ` in front of it,
    and a sentence that punctuates itself cannot be embedded in another.
    """
    match detail:
        case DocumentUnsearchable(problem=problem, path=path):
            # The problem text is the reader's own, quoted rather than
            # composed, and it already names the document. Where there
            # is none, the path is all there is to say.
            if problem:
                return f"{problem}: this document will not be searchable"
            return f"{path} could not be read"
        case FrontmatterUnreadable(path=path):
            return (
                f"{path} opens with a frontmatter block that could not be "
                "read; it is indexed without its metadata"
            )
        case TitleDotStripped(title=title):
            return (
                f"title '{title}' looked like a dotfile name; the leading "
                "dot was stripped from the filename so it stays visible to "
                "search"
            )
        case DocumentSkipped(problem=problem):
            return f"{problem} - it was left alone"
        case MetadataUnavailable(identifier=identifier):
            return (
                f"arXiv did not answer for {identifier}, so its metadata is "
                "missing and its citekey is derived from the title alone"
            )
        case NoPagesDiscovered(base_url=base_url, mode=mode, path_prefix=prefix):
            beneath = f" under '{prefix}'" if prefix else ""
            return (
                f"'{base_url}' produced no pages: {mode} discovery "
                f"found nothing{beneath}"
            )


__all__ = ["describe_diagnostic"]
