"""Every value the service and its clients exchange survives the wire (14a).

The set of values is **discovered**, not listed: the walk starts at the
parameters and returns of every public function in the four shared modules -
`operations.py`, `writing.py`, `retrieval.py`, `holdings.py`, which are what
the service will expose - and at the `Event` and `Refusal` unions, and
follows every dataclass field and union member. A field added to any of them
is then on the wire's test the moment it exists (#373).

Each class reached gets samples generated from its field types - every enum
value, every `Literal`, every union member, `None` and not `None` - and each
sample must come back equal after `dump`, `json.dumps`, `json.loads` and
`load`. What generation cannot invent (a pydantic model, a field a
constructor validates) is supplied by hand below, and a class with neither
fails the test with the name of what is missing.

Two hand-written statements keep the walk honest: `EXPECTED_REACHED`, the
classes the plan says cross, so a walk that silently stops early fails; and
`PROCESS_LOCAL`, what must never cross, each with its reason.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime
import enum
import inspect
import json
import types
import typing
from collections.abc import Iterable, Mapping, Sequence, Set
from pathlib import PurePath
from typing import Annotated, Literal, TypeAliasType, get_args, get_origin

import pytest
from pydantic import BaseModel

import kennis.holdings
import kennis.operations
import kennis.retrieval
import kennis.writing
from kennis.context import Context
from kennis.engine import errors
from kennis.engine.corpus.collection import Collection
from kennis.engine.corpus.schema import (
    DocsFrontmatter,
    DocumentFrontmatter,
    LiteratureFrontmatter,
    NoteFrontmatter,
)
from kennis.engine.events import Event, EventSink
from kennis.engine.history.repository import Repository
from kennis.engine.pack.schema import Pack
from kennis.engine.rag.index import LoadedIndex
from kennis.engine.rag.models import Chunk, Filter, SearchResult
from kennis.engine.refusals import Refusal, SameContent, SamePaper
from kennis.engine.settings import Settings
from kennis.protocol.wire import WireError, dump, load, load_error, wire_name


def type_checking_names(module: types.ModuleType) -> dict[str, object]:
    """The names a module imports under `if TYPE_CHECKING:`, imported.

    A module a client loads names its heavy types for the type checker
    alone (#535), so a signature resolves only as a type checker resolves
    it: with those imports in its namespace. Production never evaluates
    these signatures; this test reads them to find what crosses.
    """
    source = inspect.getsource(module)
    names: dict[str, object] = {}
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
        ):
            exec(
                compile(ast.Module(body=node.body, type_ignores=[]), "<guard>", "exec"),
                names,
            )
    names.pop("__builtins__", None)
    return names


SHARED_MODULES = (
    kennis.operations,
    kennis.writing,
    kennis.retrieval,
    kennis.holdings,
)

# What holds a process's resources, and so is named rather than sent.
PROCESS_LOCAL: dict[object, str] = {
    Context: "the service has its own; a request is about the corpus it owns",
    Collection: "a request names a collection; the service opens it",
    Repository: "git runs where the corpus is",
    LoadedIndex: "holds the index's arrays, which are what the service is for",
    Settings: "read by the service from the configuration file",
    EventSink: "events cross one at a time, as a stream",
    kennis.holdings.CorpusState: "a stamp compared inside one process",
}

# The third statement, by hand: classes the plan says cross the wire. The
# walk must reach every one; it may reach more.
EXPECTED_REACHED = frozenset(
    {
        "engine.backup.BackupReport",
        "engine.context.notes.BundleNote",
        "engine.context.sync.BundleSync",
        "engine.corpus.add.AddOptions",
        "engine.corpus.add.AddOutcome",
        "engine.corpus.add.AddReport",
        "engine.corpus.collection.CollectionContents",
        "engine.corpus.document.Document",
        "engine.corpus.sync.CorpusSync",
        "engine.events.Diagnostic",
        "engine.events.ItemFinished",
        "engine.events.ItemStarted",
        "engine.events.OperationFinished",
        "engine.events.Progress",
        "engine.history.freshness.Freshness",
        "engine.history.history.HistoryEntry",
        "engine.history.history.RestoredDocument",
        "engine.history.outofband.OutOfBandChange",
        "engine.pack.installed.InstalledPack",
        "engine.pack.store.PackInstall",
        "engine.refusals.Quoted",
        "engine.refusals.SameContent",
        "engine.refusals.SamePaper",
        "engine.remember.RememberReport",
        "holdings.DocumentMarks",
        "holdings.Holding",
        "operations.IndexBuild",
        "operations.RemovedVersion",
        "operations.ReturnedCorpus",
        "render.hits.Hit",
        "retrieval.Sweep",
        "retrieval.VersionChoice",
    }
)

SOURCE = {"from": "path:/sources/one.md", "via": "verbatim", "format": "markdown"}
FRONTMATTERS = [
    NoteFrontmatter.model_validate(
        {"id": "doc0000001", "title": "One", "owner": "user", "source": SOURCE}
    ),
    LiteratureFrontmatter.model_validate(
        {
            "id": "doc0000002",
            "title": "A paper",
            "owner": "pack:demo",
            "source": {**SOURCE, "from": "arxiv:1101.1764", "via": "mineru"},
            "id_from": "arxiv:1101.1764",
            "bib": {"citekey": "smith2011", "year": "2011"},
        }
    ),
    DocsFrontmatter.model_validate(
        {
            "id": "22k3nnp36k",
            "title": "Tool",
            "owner": "user",
            "source": {**SOURCE, "via": "html", "format": "html"},
            "docs": {"project": "tool", "page": "index", "version": "1.0"},
        }
    ),
]
CHUNK = Chunk(
    id="doc0000001:0",
    collection="notes",
    document_id="doc0000001",
    chunk_index=0,
    text="Calibration solves for gains.",
    source_path="notes/calibration.md",
    char_start=0,
    char_end=29,
    section="Gains",
    metadata={"group": "topics", "versions": ["1.0", "2.0"]},
)

# Models are pydantic's to write and read; one sample each, by hand.
MODEL_SAMPLES: dict[type, list[object]] = {
    DocumentFrontmatter: list(FRONTMATTERS),
    Chunk: [CHUNK],
    SearchResult: [
        SearchResult(chunk=CHUNK, score=1 / 61),
        SearchResult(chunk=CHUNK, score=0.5, dense_rank=2, dense_score=0.71),
    ],
    Filter: [Filter(field="group", op="glob", value="topics/*")],
    Pack: [
        Pack.model_validate(
            {
                "kennis": {"schema_version": 1},
                "pack": {"id": "demo", "name": "A demo", "version": "0.1.0"},
            }
        )
    ],
}

# Fields whose constructor checks more than the type says.
FIELD_SAMPLES: dict[tuple[str, str], list[object]] = {
    ("engine.corpus.add.AddOptions", "owner"): ["user", "pack:demo"],
    ("engine.corpus.add.AddOptions", "group"): [None, "topics/radio"],
    ("engine.corpus.add.AddOptions", "project"): [None, "tool"],
    ("engine.corpus.add.AddOptions", "version"): [None, "1.0"],
    ("engine.remember.RememberOptions", "group"): [None, "topics"],
}


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def unwrapped(hint: object) -> object:
    while True:
        if isinstance(hint, TypeAliasType):
            hint = hint.__value__
        elif isinstance(alias := get_origin(hint), TypeAliasType):
            hint = alias.__value__
        elif get_origin(hint) is Annotated:
            hint = get_args(hint)[0]
        else:
            return hint


def reached() -> dict[type, str]:
    """Every dataclass and model reachable from the roots, with how."""
    found: dict[type, str] = {}

    def visit(hint: object, via: str) -> None:
        hint = unwrapped(hint)
        if hint in PROCESS_LOCAL:
            return
        origin = get_origin(hint)
        if origin is Literal:
            return
        if origin is not None:
            for argument in get_args(hint):
                if argument is not Ellipsis:
                    visit(argument, via)
            return
        if not isinstance(hint, type) or hint in found:
            return
        if issubclass(hint, BaseModel):
            found[hint] = via
            return
        if dataclasses.is_dataclass(hint):
            found[hint] = via
            hints = typing.get_type_hints(hint)
            for field in dataclasses.fields(hint):
                visit(hints[field.name], f"{hint.__name__}.{field.name}")

    for module in SHARED_MODULES:
        for name, function in vars(module).items():
            if name.startswith("_") or not inspect.isfunction(function):
                continue
            if function.__module__ != module.__name__:
                continue
            namespace = {**vars(module), **type_checking_names(module)}
            for parameter, hint in typing.get_type_hints(
                function, globalns=namespace
            ).items():
                visit(hint, f"{module.__name__}.{name}:{parameter}")
    visit(Event, "Event")
    visit(Refusal, "Refusal")
    return found


REACHED = reached()


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------


def variants(hint: object, owner: str = "", field: str = "") -> list[object]:
    """Values of `hint`, enough to exercise every branch the wire takes."""
    if (owner, field) in FIELD_SAMPLES:
        return FIELD_SAMPLES[(owner, field)]
    hint = unwrapped(hint)
    origin = get_origin(hint)
    arguments = get_args(hint)
    if origin is Literal:
        return list(arguments)
    if origin in (typing.Union, types.UnionType):
        return [value for member in arguments for value in variants(member)[:2]]
    if origin is tuple:
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return [(), tuple(variants(arguments[0])[:2])]
        return [tuple(variants(one)[0] for one in arguments)]
    if isinstance(origin, type) and issubclass(origin, Mapping):
        keys, values = variants(arguments[0]), variants(arguments[1])
        return [{}, dict(zip(keys, values * len(keys), strict=False))]
    if origin in (list, Sequence, Iterable):
        items = variants(arguments[0])[:2]
        return [[], items] if origin is list else [(), tuple(items)]
    if origin in (set, frozenset, Set):
        return [frozenset(), frozenset(variants(arguments[0])[:2])]
    if hint is type(None):
        return [None]
    if hint is bool:
        return [True, False]
    if hint is int:
        return [3]
    if hint is float:
        return [0.25]
    if hint is str:
        return ["text with spaces"]
    if hint in (typing.Any, object):
        return ["anything"]
    if isinstance(hint, type):
        if issubclass(hint, enum.Enum):
            return list(hint)
        if issubclass(hint, PurePath):
            return [hint("/a corpus/notes/one.md")]
        if hint is datetime.datetime:
            return [datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.UTC)]
        if hint is datetime.date:
            return [datetime.date(2026, 1, 2)]
        if issubclass(hint, errors.KennisError):
            return [hint("a message", resolution="kennis corpus status")]
        if issubclass(hint, BaseModel):
            if hint not in MODEL_SAMPLES:
                pytest.fail(f"{wire_name(hint)} needs a sample in MODEL_SAMPLES")
            return MODEL_SAMPLES[hint]
        if dataclasses.is_dataclass(hint):
            return samples(hint)[:1]
    pytest.fail(f"no sample for {hint!r} ({owner}.{field})")


def samples(kind: type) -> list[object]:
    """Instances of a dataclass: one with each field's first value, then one
    per further value of each field, the others held at their first."""
    if issubclass(kind, BaseModel):
        return list(variants(kind))
    hints = typing.get_type_hints(kind)
    choices = {
        field.name: variants(hints[field.name], wire_name(kind), field.name)
        for field in dataclasses.fields(kind)
    }
    base = {name: values[0] for name, values in choices.items()}
    arguments = [base] + [
        {**base, name: value}
        for name, values in choices.items()
        for value in values[1:]
    ]
    built: list[object] = []
    for one in arguments:
        try:
            built.append(kind(**one))
        except Exception as error:
            pytest.fail(
                f"{wire_name(kind)}({one}) refused its sample ({error}); "
                "give the field a value in FIELD_SAMPLES"
            )
    return built


def through_the_wire(value: object, hint: object) -> object:
    text = json.dumps(dump(value), allow_nan=False)
    return load(json.loads(text), hint)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_the_walk_reaches_every_class_the_plan_says_crosses():
    names = {wire_name(kind) for kind in REACHED}

    assert sorted(EXPECTED_REACHED - names) == []


def test_every_event_and_refusal_is_reached():
    for union in (Event, Refusal):
        for member in get_args(unwrapped(union)):
            assert member in REACHED, wire_name(member)


@pytest.mark.parametrize(
    "kind", sorted(REACHED, key=wire_name), ids=lambda kind: wire_name(kind)
)
def test_every_value_comes_back_equal(kind: type):
    for value in samples(kind):
        assert through_the_wire(value, kind) == value


def test_two_members_with_the_same_fields_come_back_as_themselves():
    """The reason a class is written with its name: these two hold one
    `document_id` each, and a reader without the name would rebuild the
    first member it tried."""
    for value in (SameContent("doc0000001"), SamePaper("doc0000001")):
        assert through_the_wire(value, Refusal) == value
        assert type(through_the_wire(value, Refusal)) is type(value)


def test_a_name_outside_what_was_expected_is_refused():
    written = dump(SameContent("doc0000001"))

    with pytest.raises(WireError):
        load(written, SamePaper)
    with pytest.raises(WireError):
        load(written, Event)


def test_a_field_the_class_has_not_got_is_refused():
    written = dump(SameContent("doc0000001"))
    assert isinstance(written, dict) and isinstance(written["fields"], dict)
    written["fields"]["extra"] = "x"

    with pytest.raises(WireError, match="no fields"):
        load(written, SameContent)


def engine_errors() -> list[type[errors.KennisError]]:
    return [
        kind
        for _, kind in inspect.getmembers(errors, inspect.isclass)
        if issubclass(kind, errors.KennisError)
    ]


@pytest.mark.parametrize("kind", engine_errors(), ids=lambda kind: kind.__name__)
def test_every_engine_error_comes_back_as_itself(kind: type[errors.KennisError]):
    raised = kind("what went wrong", resolution="kennis corpus init")
    raised.add_note("a later note")

    back = load_error(json.loads(json.dumps(dump(raised))))

    assert type(back) is kind
    assert str(back) == "what went wrong"
    assert back.resolution == "kennis corpus init"
    assert back.__notes__ == raised.__notes__


def test_an_error_without_a_resolution_keeps_none():
    back = load_error(dump(errors.KennisError("plain", resolution=None)))

    assert back.resolution is None
    assert getattr(back, "__notes__", []) == []


def test_an_error_defined_outside_the_engine_keeps_its_words():
    class Elsewhere(errors.KennisError):
        pass

    back = load_error(dump(Elsewhere("from a front end", resolution="kennis gui")))

    assert type(back) is errors.KennisError
    assert (str(back), back.resolution) == ("from a front end", "kennis gui")


def test_an_exception_that_is_not_kennis_s_is_named_as_a_defect():
    written = dump(ZeroDivisionError("division by zero"))

    assert isinstance(written, dict)
    assert written["error"] is None
    assert written["message"] == "ZeroDivisionError: division by zero"


def test_a_subclass_comes_back_as_itself_where_its_base_was_declared():
    for frontmatter in FRONTMATTERS:
        back = through_the_wire(frontmatter, DocumentFrontmatter)

        assert type(back) is type(frontmatter)
        assert back == frontmatter
