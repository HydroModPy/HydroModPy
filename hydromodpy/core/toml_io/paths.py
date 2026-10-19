"""Config-declared file paths, and the one parser of dotted key paths.

Two kinds of path live here. File paths a config declares are resolved by
:func:`resolve_declared_path` and :func:`resolve_path`. Dotted key paths,
``geographic.catchment.x_outlet`` or ``sites.recipes."k2e-5".file``, name a key
of a TOML document: ``hmp run --set``, the ``HMP_SET_*`` variables, the
``[sites.bind]`` keys, the ``set`` table of an inline recipe and the docs all
read them through :func:`parse`, so they speak one grammar.

Grammar of a dotted key path, the TOML dotted-key grammar without indices:
parts joined by ``.``, each part a bare key (``[A-Za-z0-9_-]+``) or a quoted
key (``"..."`` with ``\\"`` and ``\\\\`` escapes, or ``'...'`` taken
literally). ``x[0]`` is refused: a list is set whole, or merged table by table
with the ``__merge`` directive of :mod:`hydromodpy.core.toml_io.merge`.
"""

from __future__ import annotations

import difflib
import os
import re
import types
import typing
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, get_args, get_origin

from hydromodpy.core.config_kit.introspect import iter_basemodels
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.toml_io.merge import DIRECTIVE_SUFFIXES

if TYPE_CHECKING:
    from pydantic import BaseModel
    from pydantic.fields import FieldInfo


def is_declared_absolute_path(path: Path) -> bool:
    """Return True for absolute paths, including drive-less rooted paths."""
    if path.is_absolute():
        return True
    return path.drive == "" and path.root in {"/", "\\"}


def _is_bare_filename(path: Path) -> bool:
    """True when ``path`` has no separator and no ``..`` traversal."""
    parts = path.parts
    if len(parts) != 1:
        return False
    if parts[0] in ("", ".", ".."):
        return False
    return True


def resolve_declared_path(
    raw_value: str | Path,
    *,
    base_dir: Path,
    fallback_dirs: Iterable[Path] | None = None,
) -> Path:
    """Resolve one config path against ``base_dir`` (or a fallback dir).

    Resolution order:

    1. Absolute paths (including ``~``) are returned as-is.
    2. Paths that contain a separator or a ``..`` segment are resolved
       against ``base_dir`` (legacy behaviour).
    3. Bare filenames (e.g. ``"etp_sim2.nc"``) are looked up against
       ``base_dir`` first, then each ``fallback_dirs`` entry. The first
       existing match wins. If nothing exists yet (the file may be
       generated later), the ``base_dir`` resolution is returned so the
       error message stays predictable.
    """
    path = Path(raw_value).expanduser()
    if is_declared_absolute_path(path):
        return path

    primary = (base_dir / path).resolve()
    if not _is_bare_filename(path) or fallback_dirs is None:
        return primary

    if primary.exists():
        return primary
    for candidate_dir in fallback_dirs:
        if candidate_dir is None:
            continue
        candidate = (Path(candidate_dir) / path).resolve()
        if candidate.exists():
            return candidate
    return primary


def get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    """Resolve one nested section using dotted syntax (for example ``case.mesh``)."""
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


def resolve_path(path_value: str | Path, base_dir: Path) -> str:
    """Resolve a possibly-relative path against *base_dir* and return a string."""
    path = Path(str(path_value)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def portable_declared_path(
    path: str | Path,
    *,
    role: str | None,
    project_root: Path,
    data_dir: Path | None,
) -> str:
    """Return the form of a resolved config path that resolves back to it in any workspace.

    The inverse of :func:`resolve_declared_path` for a configuration read
    from the project root, in this order:

    1. a bare name, when the bare name resolves to the same file through the
       ``<data_dir>/<role>/`` and ``<data_dir>/`` fallbacks
       (``DEM_armorican_massif.tif``, ``hydrometry``);
    2. a path under the project root, relative to it (``inputs/zones.shp``);
    3. a path under the workspace that holds *data_dir*, relative to the
       project root (``../../data/geology/map.gpkg``);
    4. any other path, absolute as it is: it names a place outside the
       workspace, which no copy of the workspace carries.
    """
    target = Path(path).expanduser()
    if not is_declared_absolute_path(target):
        return str(path)
    target = target.resolve()
    root = Path(project_root).resolve()
    data = None if data_dir is None else Path(data_dir).resolve()
    if data is not None:
        fallback = [data / role, data] if role else [data]
        if resolve_declared_path(target.name, base_dir=root, fallback_dirs=fallback) == target:
            return target.name
    if target.is_relative_to(root):
        return target.relative_to(root).as_posix()
    if data is not None and target.is_relative_to(data.parent):
        return Path(os.path.relpath(target, root)).as_posix()
    return str(target)
    data = Path(data_dir).resolve()
    fallback = [data / role, data] if role else [data]
    bare = target.name
    if resolve_declared_path(bare, base_dir=root, fallback_dirs=fallback) == target:
        return bare
    workspace = data.parent
    if target.is_relative_to(workspace):
        return Path(os.path.relpath(target, root)).as_posix()
    return str(target)


# Dotted key paths ------------------------------------------------------------

_BARE_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")
_PLAIN_PART_RE = re.compile(r"[A-Za-z0-9_]+")
_NEIGHBOUR_COUNT = 5


class UnknownPathError(ConfigError):
    """A dotted key path names a key the schema or the document does not have."""


@dataclass(frozen=True, slots=True)
class DottedPath:
    """A parsed dotted key path: the keys from the root, one per part."""

    parts: tuple[str, ...]

    def __str__(self) -> str:
        """Return the path in the grammar :func:`parse` reads, quoting where needed."""
        return ".".join(_render_part(part) for part in self.parts)


def _render_part(part: str) -> str:
    """Return one part bare when it is plain, double-quoted otherwise."""
    if _PLAIN_PART_RE.fullmatch(part):
        return part
    escaped = part.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _read_quoted(text: str, start: int) -> tuple[str, int]:
    """Read the quoted part opening at *start*; return it and the index after it."""
    quote = text[start]
    out: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == quote:
            return "".join(out), index + 1
        if quote == '"' and char == "\\":
            if index + 1 >= len(text) or text[index + 1] not in {'"', "\\"}:
                raise ValueError(f'{text!r}: only \\" and \\\\ are escapes in a quoted key')
            out.append(text[index + 1])
            index += 2
            continue
        out.append(char)
        index += 1
    raise ValueError(f"{text!r}: quoted key opened at {start} is never closed")


def parse(text: str) -> DottedPath:
    """Parse a dotted key path; refuse indices, empty parts and stray characters."""
    source = str(text)
    if "[" in source or "]" in source:
        # Brackets are allowed inside a quoted key only.
        unquoted = re.sub(r'"(?:\\.|[^"\\])*"|\'[^\']*\'', "", source)
        if "[" in unquoted or "]" in unquoted:
            raise ValueError(
                f"{source!r}: a key path takes no index. Set the whole list, or merge a "
                "list of tables with the __merge directive."
            )
    parts: list[str] = []
    index = 0
    length = len(source)
    while True:
        while index < length and source[index] in " \t":
            index += 1
        if index >= length:
            raise ValueError(f"{source!r}: empty part in a key path")
        if source[index] in {'"', "'"}:
            part, index = _read_quoted(source, index)
        else:
            match = _BARE_KEY_RE.match(source, index)
            if match is None:
                raise ValueError(
                    f"{source!r}: unexpected {source[index]!r} at {index}; quote a key "
                    "that holds anything but letters, digits, '_' and '-'"
                )
            part, index = match.group(0), match.end()
        if not part:
            raise ValueError(f"{source!r}: empty part in a key path")
        parts.append(part)
        while index < length and source[index] in " \t":
            index += 1
        if index >= length:
            return DottedPath(tuple(parts))
        if source[index] != ".":
            raise ValueError(f"{source!r}: expected '.' at {index}, found {source[index]!r}")
        index += 1


def _as_path(path: DottedPath | str) -> DottedPath:
    return path if isinstance(path, DottedPath) else parse(path)


def _neighbours(name: str, candidates: Iterable[str]) -> list[str]:
    """Return the candidates closest to *name*, or all of them when none is close."""
    pool = sorted(set(candidates))
    close = difflib.get_close_matches(name, pool, n=_NEIGHBOUR_COUNT, cutoff=0.6)
    return close or pool[:_NEIGHBOUR_COUNT]


def _neighbour_hint(prefix: str, name: str, candidates: Iterable[str]) -> str:
    near = _neighbours(name, candidates)
    where = prefix or "the root"
    if not near:
        return f"{where} has no key {name!r}"
    return f"{where} has no key {name!r}; nearest: {', '.join(near)}"


def assign(payload: MutableMapping[str, Any], path: DottedPath | str, value: Any) -> None:
    """Set *value* at *path* in a nested mapping, creating the tables on the way.

    A part that already holds something other than a table is refused: the
    path would replace a value by a table.
    """
    parsed = _as_path(path)
    cursor: MutableMapping[str, Any] = payload
    for depth, part in enumerate(parsed.parts[:-1]):
        existing = cursor.get(part)
        if existing is None:
            existing = {}
            cursor[part] = existing
        if not isinstance(existing, MutableMapping):
            prefix = str(DottedPath(parsed.parts[: depth + 1]))
            raise ValueError(f"{parsed}: {prefix} holds a value, not a table")
        cursor = existing
    cursor[parsed.parts[-1]] = value


def lookup(payload: Mapping[str, Any], path: DottedPath | str) -> Any:
    """Return the value at *path*; a missing key raises ``KeyError`` naming the neighbours."""
    parsed = _as_path(path)
    cursor: Any = payload
    for depth, part in enumerate(parsed.parts):
        prefix = str(DottedPath(parsed.parts[:depth]))
        if not isinstance(cursor, Mapping):
            raise KeyError(f"{parsed}: {prefix} holds a value, not a table")
        if part not in cursor:
            raise KeyError(f"{parsed}: {_neighbour_hint(prefix, part, cursor)}")
        cursor = cursor[part]
    return cursor


def _members(annotation: Any) -> list[Any]:
    """Return the members of an annotation, with ``Annotated`` and ``None`` removed."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _members(get_args(annotation)[0])
    if origin is typing.Union or origin is types.UnionType:
        out: list[Any] = []
        for arg in get_args(annotation):
            out.extend(_members(arg))
        return out
    if annotation is type(None):
        return []
    return [annotation]


def _is_sequence(member: Any) -> bool:
    origin = get_origin(member)
    return origin in {list, tuple, set, frozenset} or (
        origin is not None
        and isinstance(origin, type)
        and issubclass(origin, Sequence)
        and origin is not str
    )


def _is_mapping(member: Any) -> bool:
    origin = get_origin(member)
    if member in {dict, Mapping}:
        return True
    return origin is not None and isinstance(origin, type) and issubclass(origin, Mapping)


def _is_model(member: Any) -> bool:
    from pydantic import BaseModel as _BaseModel

    return isinstance(member, type) and issubclass(member, _BaseModel)


def _field_of(model: type[BaseModel], name: str) -> FieldInfo | None:
    fields = model.model_fields
    if name in fields:
        return fields[name]
    for info in fields.values():
        if info.alias == name:
            return info
    return None


def _strip_directive(name: str) -> str:
    for suffix in DIRECTIVE_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def resolve_field(model: type[BaseModel], path: DottedPath | str) -> FieldInfo:
    """Return the Pydantic field a dotted key path names in *model*.

    The walk goes through nested models, ``Optional`` and unions (the first
    variant that declares the next key wins) and through ``dict[str, Model]``
    tables, where a part is the table key. A list field ends the walk: a key
    below it is refused, since a path takes no index. A free-form table
    (``dict[str, Any]``) ends it too, and its own field is returned. The last
    part may carry a merge directive (``sources__merge``). An unknown key
    raises :class:`UnknownPathError` with the nearest field names.
    """
    parsed = _as_path(path)
    candidates: list[type[BaseModel]] = [model]
    parts = parsed.parts
    index = 0
    while True:
        name = parts[index] if index < len(parts) - 1 else _strip_directive(parts[index])
        prefix = str(DottedPath(parts[:index]))
        info = next(
            (found for cls in candidates if (found := _field_of(cls, name)) is not None),
            None,
        )
        if info is None:
            names = {key for cls in candidates for key in cls.model_fields}
            raise UnknownPathError(f"{parsed}: {_neighbour_hint(prefix, name, names)}")
        index += 1
        if index == len(parts):
            return info
        members = _members(info.annotation)
        here = str(DottedPath(parts[:index]))
        if any(_is_sequence(member) for member in members):
            raise UnknownPathError(
                f"{parsed}: {here} is a list, and a key path takes no index. Set the "
                "whole list, or merge a list of tables with the __merge directive."
            )
        nested = [member for member in members if _is_model(member)]
        following = _strip_directive(parts[index]) if index == len(parts) - 1 else parts[index]
        if any(_field_of(cls, following) is not None for cls in nested):
            candidates = nested
            continue
        mappings = [member for member in members if _is_mapping(member)]
        if mappings:
            value_types = [args[1] for member in mappings if len(args := get_args(member)) == 2]
            value_models = [cls for value in value_types for cls in iter_basemodels(value)]
            if not value_models:
                # A free-form table: the schema stops here.
                return info
            index += 1  # the part is a key of the table
            if index == len(parts):
                return info
            candidates = value_models
            continue
        if not nested:
            raise UnknownPathError(f"{parsed}: {here} is a value, not a table")
        candidates = nested
