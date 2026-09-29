"""What was searched for, so the search page can offer it again.

**The first thing kennis stores about its user.** Everything else the
interface shows is recomputed from the corpus on request; this is a
record of the person rather than of their documents, which is why
where it lives and how it is removed are the parts that matter.

Not in the corpus. That is a git repository staged with
`git add --all .` and converged by a pack sync, so a file put there
would be committed and carried wherever the corpus goes. Not in the
bundle either, and worse: that repository is the user's and kennis
does not commit to it. It goes in the state directory, beside the
log, which is per-machine and travels nowhere.

Private to `gui/`, and deliberately. The rule is that shared
orchestration lives beside `context.py` because every front end asks
and none owns the answer - here one front end asks and does own it.
`kennis search` writing a file would make a read command mutate the
disk, and the MCP server's searches are an agent's rather than a
person's, so mixing them in would answer "what did I look for" with
somebody else's questions. If a second front end ever wants this it
moves, which is the #292 and #314 pattern.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from platformdirs import user_state_dir

from kennis.engine.atomic import replace_file

_STATE_DIR_VARIABLE: Final = "KENNIS_STATE_DIR"
_HISTORY_FILE: Final = "searches.json"

# How many are kept. Enough that yesterday's work is still there,
# few enough that the page stays a page.
KEPT: Final = 20

# Within this, a query that extends the last one is the same search
# still being typed; beyond it, it is a new search that happens to
# start with the same words. Not a tuned number and it does not need
# to be: typing is seconds and a separate sitting is hours, so
# anything from about a minute to about a quarter of an hour behaves
# identically on both cases. Named so it can be argued with.
COLLAPSE_WINDOW_SECONDS: Final = 300.0


@dataclass(frozen=True, slots=True)
class Search:
    """One search, as much of it as is kept.

    The count and never the results. A record of which documents
    matched which query is a far more revealing file than a record of
    the queries, and nothing the page does needs it.
    """

    query: str
    scope: str
    hits: int
    # Whether a scope returned everything it was asked for, so `hits`
    # is a floor rather than a total. `default_top_k` is per scope, so
    # this is true of most searches.
    capped: bool
    at: float


def state_dir() -> Path:
    """Where kennis keeps state that is neither log nor configuration.

    `KENNIS_STATE_DIR` overrides the platform default, through the
    same mechanism a user gets rather than a back door only tests
    know about - the pattern `log_dir` and `config_dir` already use.

    On Linux the default is `~/.local/state/kennis`, the parent of
    `user_log_dir`, so this sits beside the log rather than inside it.
    """
    override = os.environ.get(_STATE_DIR_VARIABLE)
    if override:
        return Path(override).expanduser()
    return Path(user_state_dir("kennis"))


def history_path() -> Path:
    return state_dir() / _HISTORY_FILE


def recent() -> list[Search]:
    """The searches, newest first, or none when there are none.

    **Never raises.** It is a file on disk that an older version
    wrote and that anything can damage, and a search page returning
    500 because of it would put the whole corpus out of reach of the
    interface for the sake of a convenience.
    """
    try:
        written = json.loads(history_path().read_text(encoding="utf-8"))
        return [
            Search(
                query=str(entry["query"]),
                scope=str(entry["scope"]),
                hits=int(entry["hits"]),
                capped=bool(entry["capped"]),
                at=float(entry["at"]),
            )
            for entry in written
        ]
    except (OSError, ValueError, TypeError, KeyError):
        return []


def overwrite(searches: Sequence[Search]) -> None:
    """Replace the file with exactly these, newest first."""
    replace_file(
        history_path(),
        json.dumps(
            [
                {
                    "query": search.query,
                    "scope": search.scope,
                    "hits": search.hits,
                    "capped": search.capped,
                    "at": search.at,
                }
                for search in searches
            ],
            indent=2,
        ),
    )


def clear() -> None:
    overwrite([])


def record(query: str, *, scope: str, hits: int, capped: bool) -> None:
    """Note that this search happened, collapsing it into the last
    one where the two are the same search still being typed.

    The box fires every 400ms, so "calibration" arrives as "cali",
    "calibratio", "calibration". Recording each would fill the list
    with prefixes of one word, and changing the scope re-runs the
    search, so it would fill with repeats of one query too.

    A read-modify-write, and two windows racing can lose an entry.
    Deliberately not locked: one lost recent search costs nothing and
    a lock on a keystroke path costs more than it is worth.
    """
    cleaned = query.strip()
    if not cleaned:
        return
    entry = Search(query=cleaned, scope=scope, hits=hits, capped=capped, at=time.time())
    held = recent()
    # Two removals, and they are different rules.
    #
    # **An exact repeat moves to the top** rather than taking a
    # second slot, wherever it sits and however old it is. Without
    # this the list fills with the few queries a person actually
    # runs - searching "calibration" on four days put it in four of
    # twenty slots, which one run of the interface could not show
    # and two could.
    kept = [previous for previous in held if previous.query != cleaned]
    # **And the query still being typed replaces the last one**,
    # which is about the 400ms box rather than about repetition, so
    # it looks only at the most recent entry and only inside the
    # window.
    if kept and held and kept[0] is held[0] and _same_search(entry, held[0]):
        kept = kept[1:]
    overwrite([entry, *kept][:KEPT])


def _same_search(entry: Search, previous: Search) -> bool:
    """Whether this is the previous search still being typed.

    Either direction of the prefix relation, because backspacing from
    "calibration" to "cal" is the same interaction seen from the
    other end and the entry should keep whichever query the reader
    stopped on.

    Regardless of scope. Changing the scope re-runs the search, so
    two entries differing only in scope are the reader adjusting one
    search rather than making two.
    """
    if entry.at - previous.at > COLLAPSE_WINDOW_SECONDS:
        return False
    return entry.query.startswith(previous.query) or previous.query.startswith(
        entry.query
    )


__all__ = [
    "COLLAPSE_WINDOW_SECONDS",
    "KEPT",
    "Search",
    "clear",
    "history_path",
    "overwrite",
    "recent",
    "record",
    "state_dir",
]
