"""The `tag` tool: tags on a passage or a document, from an agent (#625).

It writes, as `remember` does, so the instructions name both and say to use
it when the person asks. A passage is named as `cite` takes it - a hit's
`document_id`, or a context hit's `path`, with its `chunk` - and never by a
link the agent composed. One request the service cannot find refuses the
batch, as `kennis tag` does, so nothing is half tagged.
"""

from __future__ import annotations

from typing import Final

from kennis.client import api
from kennis.context import existing_corpus
from kennis.engine.errors import KennisError
from kennis.engine.tags import split_tag_names
from kennis.mcp.tools.cite import CiteRequest, requested
from kennis.tagging import Tagged

# As many as one answer cites.
_MAX_REQUESTS: Final = 12


def tag(requests: list[CiteRequest], tags: list[str], remove: bool = False) -> str:
    """Tag passages or documents, or with `remove=True` take tags off them.

    Use it when the person asks to tag, bookmark or gather passages - for
    writing, or to search within later - never on your own initiative: a tag
    is kept in their corpus or their project, committed, and seen again.

    Name each passage as a search hit gives it: its `document_id`, or a
    context hit's `path`, with its `chunk`; leave out `chunk` to tag the
    whole document. A tag is one word, folded to lowercase; join words with
    a hyphen. If any passage cannot be found, nothing is tagged and each
    problem is said at its position.
    """
    if not requests:
        return "no requests"
    if len(requests) > _MAX_REQUESTS:
        return (
            f"{len(requests)} requests is more than one call tags. "
            f"Ask for at most {_MAX_REQUESTS}."
        )
    if not tags:
        return "no tags were named. Give at least one in `tags`."
    try:
        names = tuple(
            dict.fromkeys(name for each in tags for name in split_tag_names(each))
        )
    except KennisError as error:
        return f"{error}."
    for position, request in enumerate(requests, start=1):
        handles = [request.document_id, request.path]
        if sum(handle is not None for handle in handles) != 1:
            return (
                f"[{position}] names {sum(h is not None for h in handles)} handles. "
                "Give exactly one of `document_id` or `path`."
            )
    refused: list[str] = []
    asked = []
    for position, request in enumerate(requests, start=1):
        try:
            asked.append(requested(request))
        except KennisError as error:
            refused.append(_refusal(position, str(error), error.resolution))
    if refused:
        return _nothing_done(refused, remove=remove)
    call = api.untag if remove else api.tag
    return _report(
        call(existing_corpus().corpus_root, asked, names).result, remove=remove
    )


def _report(tagged: Tagged, *, remove: bool) -> str:
    if tagged.refused:
        return _nothing_done(
            [
                _refusal(refusal.position + 1, refusal.message, refusal.resolution)
                for refusal in tagged.refused
            ],
            remove=remove,
        )
    verb = "untagged" if remove else "tagged"
    unmoved = "was not tagged" if remove else "already tagged"
    blocks: list[str] = []
    for change in tagged.changes:
        title = change.title or change.handle
        lines = [f"[{change.position + 1}] {title}"]
        if change.changed:
            lines.append(f"{verb}: {', '.join(change.changed)}")
        if change.unchanged:
            lines.append(f"{unmoved}: {', '.join(change.unchanged)}")
        lines.append(f"link: {change.link}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _refusal(position: int, message: str, resolution: str | None) -> str:
    run = f" Run `{resolution}`." if resolution else ""
    return f"[{position}] {message}.{run}"


def _nothing_done(refused: list[str], *, remove: bool) -> str:
    what = "untagged" if remove else "tagged"
    return "\n".join([*refused, f"Nothing was {what}."])


__all__ = ["tag"]
