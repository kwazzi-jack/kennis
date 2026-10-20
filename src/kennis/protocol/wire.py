"""Every value that crosses between a client and the service, as JSON and back.

Milestone 14 puts the engine in one process and its front ends in others, so
what an operation returns, what it reports while it runs, why it refused an
item and the error it raised all have to survive being written as JSON and
read back. The engine's values are already frozen dataclasses, enums, paths
and a few pydantic models (design section 20), so this module does not
define a second set of types: `dump` writes any of them, and `load` reads
one back **as the type the caller says it expects**, which is what lets the
client hand `render/` exactly the values it was handed in one process - and
what keeps the hit lines byte-identical between front ends (#297).

**A dataclass or model is written with its class's name**, as
`{"type": name, "fields": {...}}`. Without the name a union cannot be read
back: `SameContent` and `SamePaper` both hold one `document_id`, and a
reader trying the members in turn would rebuild whichever came first. The
name only *selects among the members the expected type allows* - it never
causes an import or names a class the caller did not already expect - so a
request cannot make the service build anything its own signature does not
take.

**A `KennisError` is written as its class, message and resolution**, and
read back as the same class when it is one of `engine/errors.py`'s, so a
client raises what the engine raised and `cli/group.py` prints it unchanged.

What does not cross is anything that holds a process's resources - a
`Context`, a `Collection`, a `Repository`, a `LoadedIndex` and its arrays,
an `EventSink`. A request names a collection; it does not carry one.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import inspect
import types
import typing
from collections.abc import Iterable, Mapping, Sequence, Set
from pathlib import PurePath
from typing import Annotated, Literal, TypeAliasType, cast, get_args, get_origin

from pydantic import BaseModel

from kennis.engine import errors

# The version of the API's paths and of these forms, in every address as
# `/api/<version>/`. The service and its clients are one installation, so a
# mismatch is a stale process to replace, not a negotiation.
API_VERSION: typing.Final = 1

type Json = bool | int | float | str | list[Json] | dict[str, Json] | None


class WireError(ValueError):
    """JSON that is not a value of the type it was read as.

    A defect, not a condition a person can act on: the client and the
    service are the same installation, so a mismatch between them means one
    of them is wrong. Not a `KennisError`, so it is never printed as advice.
    """


def wire_name(kind: type) -> str:
    """The name a dataclass or model is written under: its module within
    kennis and its own name, since two classes may share a short name
    (`engine.corpus.document.Document` and `engine.rag.models.Document`)."""
    return f"{kind.__module__.removeprefix('kennis.')}.{kind.__qualname__}"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def dump(value: object) -> Json:
    """`value` as JSON, by its runtime type."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, enum.Enum):
        return dump(value.value)
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    if isinstance(value, BaseException):
        return dump_error(value)
    if isinstance(value, BaseModel):
        return {
            "type": wire_name(type(value)),
            "fields": cast(Json, value.model_dump(mode="json", by_alias=True)),
        }
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "type": wire_name(type(value)),
            "fields": {
                field.name: dump(getattr(value, field.name))
                for field in dataclasses.fields(value)
            },
        }
    if isinstance(value, Mapping):
        return [[dump(key), dump(item)] for key, item in value.items()]
    if isinstance(value, list | tuple | Set):
        return [dump(item) for item in value]
    raise WireError(f"{type(value).__qualname__} has no form on the wire")


def dump_error(error: BaseException) -> Json:
    """A `KennisError` as its class, message, resolution and notes.

    Any other exception is a defect in the service and is written as one,
    with its class's name, so the client can say what failed without
    pretending it is advice.
    """
    if isinstance(error, errors.KennisError):
        return {
            "error": type(error).__name__,
            "message": str(error),
            "resolution": error.resolution,
            "notes": list(getattr(error, "__notes__", [])),
        }
    return {
        "error": None,
        "message": f"{type(error).__qualname__}: {error}",
        "resolution": None,
        "notes": [],
    }


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def load_as[Expected](data: Json, expected: type[Expected]) -> Expected:
    """`data` read as an `Expected`, checked to be one."""
    value = load(data, expected)
    if not isinstance(value, expected):
        raise WireError(f"expected {expected.__qualname__}, read {value!r}")
    return value


def load(data: Json, hint: object) -> object:
    """`data` read as a value of the type `hint` names.

    `hint` is a class, a union, a `Literal`, a parametrised container or a
    `type` alias - whatever a signature or a field says.
    """
    if isinstance(hint, TypeAliasType):
        return load(data, hint.__value__)
    origin = get_origin(hint)
    if isinstance(origin, TypeAliasType):
        return load(data, origin.__value__)
    if origin is Annotated:
        return load(data, get_args(hint)[0])
    if origin is Literal:
        if data not in get_args(hint):
            raise WireError(f"{data!r} is not one of {get_args(hint)}")
        return data
    if origin in (typing.Union, types.UnionType):
        return _load_union(data, get_args(hint))
    if origin is not None:
        return _load_container(data, origin, get_args(hint))
    if hint is typing.Any or hint is object:
        return data
    if isinstance(hint, type):
        return _load_class(data, hint)
    raise WireError(f"cannot read a value as {hint!r}")


def _flattened(members: tuple[object, ...]) -> tuple[object, ...]:
    """A union's members with aliases unwrapped and nested unions opened:
    `Refusal | None` is a union of fifteen classes and `None`, not of a name
    and `None`."""
    flat: list[object] = []
    for member in members:
        while True:
            if isinstance(member, TypeAliasType):
                member = member.__value__
            elif get_origin(member) is Annotated:
                member = get_args(member)[0]
            else:
                break
        if get_origin(member) in (typing.Union, types.UnionType):
            flat.extend(_flattened(get_args(member)))
        else:
            flat.append(member)
    return tuple(flat)


def _load_union(data: Json, members: tuple[object, ...]) -> object:
    members = _flattened(members)
    if data is None:
        if type(None) in members:
            return None
        raise WireError(f"null is not one of {members}")
    if isinstance(data, dict) and "type" in data:
        for member in members:
            if isinstance(member, type) and _named(member, data["type"]):
                return _load_class(data, member)
        raise WireError(f"{data['type']} is not one of {members}")
    candidates = [member for member in members if member is not type(None)]
    if len(candidates) == 1:
        return load(data, candidates[0])
    for member in candidates:
        if _kind_fits(data, member):
            return load(data, member)
    raise WireError(f"{data!r} fits none of {members}")


def _kind_fits(data: Json, member: object) -> bool:
    """Whether untagged JSON could be a value of `member`, judged by its kind
    alone. Used only to choose among union members that are not classes
    written with a tag."""
    origin = get_origin(member)
    if origin is Literal:
        return data in get_args(member)
    target = origin if origin is not None else member
    if isinstance(data, bool):
        return target is bool
    if isinstance(data, int):
        return target in (int, float)
    if isinstance(data, float):
        return target is float
    if isinstance(data, str):
        return isinstance(target, type) and issubclass(
            target, str | PurePath | enum.Enum | datetime.date
        )
    if isinstance(data, list):
        return isinstance(target, type) and issubclass(target, Iterable)
    return False


def _load_container(
    data: Json, origin: object, arguments: tuple[object, ...]
) -> object:
    if not isinstance(data, list):
        raise WireError(f"expected a list for {origin!r}, read {data!r}")
    if isinstance(origin, type) and issubclass(origin, Mapping):
        key_hint, value_hint = arguments
        pairs = [_pair(item) for item in data]
        return {load(key, key_hint): load(value, value_hint) for key, value in pairs}
    if origin is tuple:
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(load(item, arguments[0]) for item in data)
        if len(arguments) != len(data):
            raise WireError(f"expected {len(arguments)} items, read {len(data)}")
        return tuple(load(item, one) for item, one in zip(data, arguments, strict=True))
    (item_hint,) = arguments
    items = [load(item, item_hint) for item in data]
    if origin is list:
        return items
    if origin in (set, frozenset, Set):
        return frozenset(items) if origin is not set else set(items)
    if origin in (Sequence, Iterable):
        return tuple(items)
    raise WireError(f"no reading for a container {origin!r}")


def _pair(item: Json) -> tuple[Json, Json]:
    if not isinstance(item, list) or len(item) != 2:
        raise WireError(f"expected a [key, value] pair, read {item!r}")
    return item[0], item[1]


def _load_class(data: Json, kind: type) -> object:
    if kind is type(None):
        if data is not None:
            raise WireError(f"expected null, read {data!r}")
        return None
    if kind is bool:
        if not isinstance(data, bool):
            raise WireError(f"expected a boolean, read {data!r}")
        return data
    if kind is int:
        if isinstance(data, bool) or not isinstance(data, int):
            raise WireError(f"expected an integer, read {data!r}")
        return data
    if kind is float:
        if isinstance(data, bool) or not isinstance(data, int | float):
            raise WireError(f"expected a number, read {data!r}")
        return float(data)
    if kind is str:
        return _text(data)
    if issubclass(kind, enum.Enum):
        try:
            return kind(data)
        except ValueError as error:
            raise WireError(str(error)) from error
    if issubclass(kind, PurePath):
        return kind(_text(data))
    if kind is datetime.datetime:
        return datetime.datetime.fromisoformat(_text(data))
    if kind is datetime.date:
        return datetime.date.fromisoformat(_text(data))
    if issubclass(kind, BaseException):
        return load_error(data)
    if issubclass(kind, BaseModel) or dataclasses.is_dataclass(kind):
        written = _named(kind, data.get("type") if isinstance(data, dict) else None)
        if written is None:
            raise WireError(f"expected a {wire_name(kind)}, read {data!r}")
        if issubclass(written, BaseModel):
            return written.model_validate(_fields_of(data, written))
        return _load_dataclass(data, written)
    raise WireError(f"{kind.__qualname__} has no form on the wire")


def _named(kind: type, name: Json) -> type | None:
    """`kind`, or the subclass of it already defined, that is written as
    `name`. A field declared as `DocumentFrontmatter` holds a
    `LiteratureFrontmatter`; a class nobody has imported is never found,
    because nothing here imports."""
    pending = [kind]
    while pending:
        candidate = pending.pop()
        if wire_name(candidate) == name:
            return candidate
        pending.extend(candidate.__subclasses__())
    return None


def _text(data: Json) -> str:
    if not isinstance(data, str):
        raise WireError(f"expected text, read {data!r}")
    return data


def _fields_of(data: Json, kind: type) -> dict[str, Json]:
    if not isinstance(data, dict) or data.get("type") != wire_name(kind):
        raise WireError(f"expected a {wire_name(kind)}, read {data!r}")
    fields = data.get("fields")
    if not isinstance(fields, dict):
        raise WireError(f"a {wire_name(kind)} without its fields: {data!r}")
    return fields


def _load_dataclass(data: Json, kind: type) -> object:
    fields = _fields_of(data, kind)
    hints = typing.get_type_hints(kind)
    arguments: dict[str, object] = {}
    for field in dataclasses.fields(kind):
        if not field.init:
            raise WireError(f"{wire_name(kind)}.{field.name} is not settable")
        if field.name in fields:
            arguments[field.name] = load(fields[field.name], hints[field.name])
    unknown = set(fields) - {field.name for field in dataclasses.fields(kind)}
    if unknown:
        raise WireError(f"{wire_name(kind)} has no fields {sorted(unknown)}")
    return kind(**arguments)


def _error_classes() -> dict[str, type[errors.KennisError]]:
    return {
        name: kind
        for name, kind in inspect.getmembers(errors, inspect.isclass)
        if issubclass(kind, errors.KennisError)
    }


def load_error(data: Json) -> errors.KennisError:
    """The error `dump_error` wrote, as its own class where it is one of
    `engine/errors.py`'s and as a plain `KennisError` otherwise - the same
    message and resolution either way, which is all a front end prints."""
    if not isinstance(data, dict) or "error" not in data:
        raise WireError(f"expected an error, read {data!r}")
    name, message, resolution = data["error"], data["message"], data["resolution"]
    notes = data.get("notes", [])
    if not isinstance(message, str) or not isinstance(notes, list):
        raise WireError(f"a malformed error: {data!r}")
    if resolution is not None and not isinstance(resolution, str):
        raise WireError(f"a malformed resolution: {data!r}")
    kind = errors.KennisError
    if isinstance(name, str):
        kind = _error_classes().get(name, errors.KennisError)
    error = kind(message, resolution=resolution)
    error.__notes__ = [str(note) for note in notes]
    return error


__all__ = [
    "API_VERSION",
    "Json",
    "WireError",
    "dump",
    "dump_error",
    "load",
    "load_as",
    "load_error",
    "wire_name",
]
