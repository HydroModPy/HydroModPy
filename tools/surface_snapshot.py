"""Write the public surfaces of HydroModPy to the files the architecture gate compares.

The contract of ``docs/source/about/versions.md`` covers names, so a gate has to know
them. Each surface is a sorted list of tab-separated rows, written under
``tests/unit/architecture/surface/``. The first column of a row is the name that the
gate tracks, so a diff of two snapshots says which name left, which one came and which
one changed.

Regenerate with one command, after a change of surface made on purpose::

    python -m tools.surface_snapshot

The command refuses to drop a stable TOML key that has no row in
``hydromodpy/config/config_migration.py``. A stable key it drops goes into
``removed_toml_keys.tsv``, so the gate still holds the migration after the old
snapshot is gone.

A row must read the same under every supported Python, so annotations are written out
here and never through ``repr``: a ``pathlib.Path`` is ``pathlib._local.Path`` on 3.13.
"""

from __future__ import annotations

import argparse
import enum
import hashlib
import importlib
import inspect
import json
import re
import sys
import types
import typing
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, get_args, get_origin

from packaging.version import Version
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = REPO_ROOT / "tests" / "unit" / "architecture" / "surface"
REMOVED_TOML_KEYS = "removed_toml_keys.tsv"
TOML_SURFACE = "toml_fields.tsv"
EXPERIMENTAL = "experimental"
REGENERATE = "python -m tools.surface_snapshot"

OBJECTS: tuple[tuple[str, str], ...] = (
    ("Project", "hydromodpy.project.facade:Project"),
    ("Run", "hydromodpy.results.run.view:Run"),
    ("RunSet", "hydromodpy.results.run.group:RunSet"),
    ("Catalog", "hydromodpy.results.catalog.facade:Catalog"),
    ("Session", "hydromodpy.results.session.view:Session"),
    ("Workspace", "hydromodpy.project.accessors:Workspace"),
    ("hmp.Workspace", "hydromodpy.core.workspace.workspace:Workspace"),
)
"""The objects a user holds. ``hmp.open`` returns the first ``Workspace``, ``hmp.Workspace``
is the second, until the two names part."""

_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+")


def _value_text(value: Any) -> str:
    """Write a default as the same text on every run, whatever its hash order."""
    if isinstance(value, BaseModel):
        return "<table>"
    if isinstance(value, enum.Enum):
        return repr(value.value)
    if isinstance(value, PurePath):
        return repr(value.as_posix())
    if isinstance(value, dict):
        items = ", ".join(f"{_value_text(k)}: {_value_text(v)}" for k, v in value.items())
        return "{" + items + "}"
    if isinstance(value, list | tuple):
        items = ", ".join(_value_text(item) for item in value)
        return f"[{items}]" if isinstance(value, list) else f"({items})"
    if isinstance(value, set | frozenset):
        return "{" + ", ".join(sorted(_value_text(item) for item in value)) + "}"
    if inspect.isclass(value) or inspect.isroutine(value):
        return f"<{getattr(value, '__name__', type(value).__name__)}>"
    return _ADDRESS.sub("", " ".join(repr(value).split()))


def _type_text(annotation: Any) -> str:
    """Write a type without class names of models, which are not part of the contract."""
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, str):
        return " ".join(annotation.split())
    origin = get_origin(annotation)
    if origin is typing.Annotated:
        return _type_text(get_args(annotation)[0])
    if origin is typing.Union or origin is types.UnionType:
        return " | ".join(dict.fromkeys(_type_text(arg) for arg in get_args(annotation)))
    if origin is typing.Literal:
        return f"Literal[{', '.join(_value_text(arg) for arg in get_args(annotation))}]"
    if origin is not None:
        args = ", ".join(_type_text(arg) for arg in get_args(annotation))
        return f"{getattr(origin, '__name__', str(origin))}[{args}]"
    if inspect.isclass(annotation):
        if issubclass(annotation, BaseModel):
            return "table"
        if issubclass(annotation, enum.Enum):
            values = ", ".join(sorted(_value_text(member) for member in annotation))
            return f"Literal[{values}]"
        return annotation.__name__
    return "..." if annotation is Ellipsis else " ".join(str(annotation).split())


def _parameter_text(parameter: inspect.Parameter) -> str:
    stars = {parameter.VAR_POSITIONAL: "*", parameter.VAR_KEYWORD: "**"}.get(parameter.kind, "")
    text = f"{stars}{parameter.name}"
    if parameter.annotation is not parameter.empty:
        text += f": {_type_text(parameter.annotation)}"
    if parameter.default is not parameter.empty:
        text += f" = {_value_text(parameter.default)}"
    return text


def _signature_text(target: Callable[..., Any]) -> str:
    """Write a signature, or nothing for a callable that does not state one."""
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return ""
    parts: list[str] = []
    marked = False
    previous: inspect._ParameterKind | None = None
    for parameter in signature.parameters.values():
        if previous is parameter.POSITIONAL_ONLY and parameter.kind is not previous:
            parts.append("/")
        if parameter.kind is parameter.KEYWORD_ONLY and not marked:
            if previous is not parameter.VAR_POSITIONAL:
                parts.append("*")
            marked = True
        parts.append(_parameter_text(parameter))
        previous = parameter.kind
    if previous is inspect.Parameter.POSITIONAL_ONLY:
        parts.append("/")
    text = f"({', '.join(parts)})"
    if signature.return_annotation is not signature.empty:
        text += f" -> {_type_text(signature.return_annotation)}"
    return text


def _resolve(target: str) -> Any:
    module, name = target.split(":")
    return getattr(importlib.import_module(module), name)


def python_facade() -> list[str]:
    """One row per name of ``hydromodpy.__all__``: its kind and its signature."""
    import hydromodpy as hmp

    rows: list[str] = []
    for name in hmp.__all__:
        value = getattr(hmp, name)
        if inspect.ismodule(value):
            kind, signature = "module", ""
        elif inspect.isclass(value):
            # The fields of a config model are the TOML surface, written once, there.
            is_model = issubclass(value, BaseModel)
            kind, signature = "class", "" if is_model else _signature_text(value)
        elif callable(value):
            kind, signature = "function", _signature_text(value)
        else:
            kind, signature = type(value).__name__, ""
        rows.append(f"{name}\t{kind}\t{signature}")
    return rows


def _member_rows(label: str, cls: type) -> Iterator[str]:
    """One row per public member of *cls*, inherited ones included."""
    for name in dir(cls):
        if name.startswith("_"):
            continue
        static = inspect.getattr_static(cls, name)
        if isinstance(static, property):
            kind, signature = "property", ""
            if static.fget is not None:
                return_annotation = inspect.signature(static.fget).return_annotation
                if return_annotation is not inspect.Signature.empty:
                    signature = _type_text(return_annotation)
        elif isinstance(static, classmethod | staticmethod):
            kind, signature = type(static).__name__, _signature_text(getattr(cls, name))
        elif inspect.isroutine(static):
            kind, signature = "method", _signature_text(static)
        else:
            kind, signature = "attribute", ""
        yield f"{label}.{name}\t{kind}\t{signature}"


def python_objects() -> list[str]:
    """The public members of the objects a user holds."""
    return [row for label, target in OBJECTS for row in _member_rows(label, _resolve(target))]


def _action_rows(parser: argparse.ArgumentParser, command: str) -> Iterator[str]:
    yield f"{command}\tcommand"
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                yield from _action_rows(child, f"{command} {name}")
            continue
        if isinstance(action, argparse._HelpAction):
            continue
        label = ",".join(sorted(action.option_strings)) or f"<{action.dest}>"
        extras = [f"nargs={action.nargs}"] if action.nargs is not None else []
        # Python 3.13 stopped calling an optional positional required, so it is not written.
        if action.required and action.nargs not in ("*", "?", argparse.REMAINDER):
            extras.append("required")
        if action.choices is not None:
            extras.append(f"choices={_value_text(sorted(map(str, action.choices)))}")
        if action.default not in (None, False, argparse.SUPPRESS):
            extras.append(f"default={_value_text(action.default)}")
        yield f"{command} {label}\t{' '.join(extras)}"


def cli_tree() -> list[str]:
    """Each command and each flag of ``hmp``."""
    from hydromodpy.cli.main import _build_parser

    return list(_action_rows(_build_parser(), "hmp"))


def exit_codes() -> list[str]:
    """The exit code constants, then the code of each class of ``core.exceptions``."""
    from hydromodpy.cli import helpers
    from hydromodpy.core import exceptions

    rows = [f"{name}\t{value}" for name, value in vars(helpers).items() if name.startswith("EXIT_")]
    for name, value in vars(exceptions).items():
        if not inspect.isclass(value) or not issubclass(value, BaseException):
            continue
        # A StepError exits with the code of the error it wraps, so it has none of its own.
        if value.__module__ == exceptions.__name__ and value is not exceptions.StepError:
            rows.append(f"{name}\t{helpers.exit_code_for(value.__new__(value))}")
    return rows


def _submodels(annotation: Any) -> Iterator[type[BaseModel]]:
    """Yield the config models an annotation holds, whatever wraps them."""
    args = get_args(annotation)
    if args:
        for arg in args:
            yield from _submodels(arg)
    elif inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        yield annotation


def _default_text(field: Any) -> str:
    """Write the default of a field, calling a factory that needs nothing to build it."""
    if field.default_factory is not None:
        if field.default_factory_takes_validated_data:
            return "<factory>"
        return _value_text(field.default_factory())
    if field.default is PydanticUndefined:
        return "<required>"
    return _value_text(field.default)


def _toml_rows(
    model: type[BaseModel], path: str, inherited: str, stack: frozenset[type]
) -> Iterator[str]:
    for name, field in model.model_fields.items():
        extra = field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {}
        if field.exclude or extra.get("toml_exclude") is True:
            continue
        key = f"{path}.{field.alias or name}" if path else (field.alias or name)
        stability = inherited if inherited == EXPERIMENTAL else extra.get("stability", "stable")
        yield "\t".join((key, _type_text(field.annotation), _default_text(field), stability))
        for child in dict.fromkeys(_submodels(field.annotation)):
            if child not in stack:
                yield from _toml_rows(child, key, stability, stack | {child})


def toml_fields() -> list[str]:
    """Each TOML path with its type, its default and whether it is experimental."""
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    return list(_toml_rows(HydroModPyConfig, "", "stable", frozenset({HydroModPyConfig})))


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]


def _description_rows(document: dict[str, Any], label: str) -> Iterator[str]:
    """Write scalars as they are and hash a branch, so one input change is one row."""
    for key, value in document.items():
        if key in ("inputs", "outputs") and isinstance(value, dict):
            for name, entry in value.items():
                yield f"{label} {key}.{name}\t{_digest(entry)}"
        elif isinstance(value, str | int | float | bool):
            yield f"{label} {key}\t{value!r}"
        else:
            yield f"{label} {key}\t{_digest(value)}"


def processes() -> list[str]:
    """The process descriptions a build ships, one row per input and output."""
    from importlib.resources import files

    rows: list[str] = []
    package = files("hydromodpy.schema.processes")
    for entry in sorted(package.iterdir(), key=lambda item: item.name):
        if entry.name.endswith(".json"):
            rows.extend(_description_rows(json.loads(entry.read_text("utf-8")), entry.name))
    return rows


SURFACES: dict[str, Callable[[], list[str]]] = {
    "python_facade.tsv": python_facade,
    "python_objects.tsv": python_objects,
    "cli_tree.tsv": cli_tree,
    "exit_codes.tsv": exit_codes,
    TOML_SURFACE: toml_fields,
    "processes.tsv": processes,
}


def rows_of(surface: str) -> list[str]:
    """Return the sorted rows of *surface* as this build gives them."""
    return sorted(set(SURFACES[surface]()))


def read_rows(path: Path) -> list[str]:
    """Return the rows of a snapshot file, nothing when it does not exist."""
    return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def _by_name(rows: Iterable[str]) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for row in rows:
        names.setdefault(row.split("\t", 1)[0], set()).add(row)
    return names


@dataclass(frozen=True)
class SurfaceDiff:
    """What changed between two snapshots of one surface, by name."""

    removed: tuple[str, ...]
    added: tuple[str, ...]
    changed: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]

    def __bool__(self) -> bool:
        return bool(self.removed or self.added or self.changed)

    def describe(self) -> str:
        """Say what changed, one line per name."""
        lines = [f"  removed: {name}" for name in self.removed]
        lines += [f"  added: {name}" for name in self.added]
        for name, before, after in self.changed:
            lines.append(f"  changed: {name}")
            lines += [f"    was {row}" for row in before]
            lines += [f"    now {row}" for row in after]
        return "\n".join(lines)


def compare(before: Iterable[str], after: Iterable[str]) -> SurfaceDiff:
    """Return what changed from the rows *before* to the rows *after*."""
    old, new = _by_name(before), _by_name(after)
    return SurfaceDiff(
        removed=tuple(sorted(set(old) - set(new))),
        added=tuple(sorted(set(new) - set(old))),
        changed=tuple(
            (name, tuple(sorted(old[name] - new[name])), tuple(sorted(new[name] - old[name])))
            for name in sorted(set(old) & set(new))
            if old[name] != new[name]
        ),
    )


def migration_for(path: str) -> Any | None:
    """Return the old form that covers a TOML path, by its own path or a moved parent."""
    from hydromodpy.config.config_migration import document_path, old_forms

    for form in old_forms():
        old = document_path(form.old)
        if path == old or path.startswith(f"{old}."):
            return form
    return None


def stable_removals(before: Iterable[str], after: Iterable[str]) -> list[str]:
    """Return the TOML paths that left and were not marked experimental."""
    old, new = _by_name(before), _by_name(after)
    return [
        name
        for name in sorted(set(old) - set(new))
        if not all(row.endswith(f"\t{EXPERIMENTAL}") for row in old[name])
    ]


def installed_release() -> str:
    """Return the release of this build, with no pre-release suffix."""
    from hydromodpy.core.version import __version__

    return Version(__version__).base_version


def regenerate(directory: Path = SNAPSHOT_DIR) -> list[str]:
    """Write every surface; return what could not be accepted, without writing anything."""
    current = {surface: rows_of(surface) for surface in SURFACES}
    removed = stable_removals(read_rows(directory / TOML_SURFACE), current[TOML_SURFACE])
    refused = [
        f"{path}: this stable TOML key left and config_migration.py has no row for it. Add the "
        "row, with its `since`, so that hmp doctor --fix-config rewrites it, or mark the key "
        "experimental first if it was never promised."
        for path in removed
        if migration_for(path) is None
    ]
    if refused:
        return refused
    directory.mkdir(parents=True, exist_ok=True)
    for surface, rows in current.items():
        (directory / surface).write_text("\n".join(rows) + "\n", encoding="utf-8")
    ledger = directory / REMOVED_TOML_KEYS
    release = installed_release()
    rows = read_rows(ledger) + [f"{path}\t{release}" for path in removed]
    ledger.write_text("\n".join(sorted(set(rows))) + "\n" if rows else "", encoding="utf-8")
    return []


def main() -> int:
    """Write the snapshots, or say which key still needs its migration."""
    refused = regenerate()
    if refused:
        print("\n".join(refused), file=sys.stderr)
        return 1
    print(f"Wrote {len(SURFACES)} surfaces under {SNAPSHOT_DIR.relative_to(REPO_ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
