"""Write the public surfaces of HydroModPy to the files the architecture gate compares.

The contract of ``docs/source/about/versions.md`` covers names, so a gate has to know
them. Each surface is a sorted list of tab-separated rows, written under
``tests/unit/architecture/surface/``. The first column of a row is the name that the
gate tracks, so a diff of two snapshots says which name left, which one came and which
one changed.

Regenerate with one command, after a change of surface made on purpose::

    python -m tools.surface_snapshot

The command refuses to drop a stable TOML key that has no row in
``hydromodpy/schema/changes.toml``, a ``[[migration]]`` row of ``document = "config"``
that rewrites the key. A stable key it drops goes into ``removed_toml_keys.tsv``, so the gate still holds the migration after
the old snapshot is gone. From the first stable version on, it also refuses a name of
``hydromodpy.__all__`` with no entry in ``hydromodpy/_lazy.py``, a command or a flag of
``hmp`` with no entry in ``hydromodpy/cli/conventions.py``, and a stable TOML key marked
experimental. What it drops goes into ``removed_names.tsv``. Before that version a name
or a flag has no alias, so it leaves with no entry, and a stable key marked experimental
stays in ``demoted_toml_keys.tsv``, so that it still needs its migration to leave.

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

from hydromodpy.schema.changes import Migration, migrations_of, outlived

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = REPO_ROOT / "tests" / "unit" / "architecture" / "surface"
REMOVED_TOML_KEYS = "removed_toml_keys.tsv"
DEMOTED_TOML_KEYS = "demoted_toml_keys.tsv"
REMOVED_NAMES = "removed_names.tsv"
TOML_SURFACE = "toml_fields.tsv"
FACADE_SURFACE = "python_facade.tsv"
CLI_SURFACE = "cli_tree.tsv"
EXPERIMENTAL = "experimental"
FIRST_STABLE = "2.0.0"
"""The first stable version. Before it, nothing is promised and no name needs an entry."""
REGENERATE = "python -m tools.surface_snapshot"

OBJECTS: tuple[tuple[str, str], ...] = (
    ("Project", "hydromodpy.project.facade:Project"),
    ("Run", "hydromodpy.results.run.view:Run"),
    ("RunSet", "hydromodpy.results.run.group:RunSet"),
    ("Catalog", "hydromodpy.results.catalog.facade:Catalog"),
    ("Session", "hydromodpy.results.session.view:Session"),
    ("Workspace", "hydromodpy.project.accessors:Workspace"),
)
"""The objects a user holds."""

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
    from hydromodpy.cli.conventions import OldFlag, OldVerb

    yield f"{command}\tcommand"
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                # An old form is not surface any more, like a TOML key only a migration reads.
                if not isinstance(child, OldVerb):
                    yield from _action_rows(child, f"{command} {name}")
            continue
        if isinstance(action, argparse._HelpAction | OldFlag):
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
    from hydromodpy.cli import exit_codes as helpers
    from hydromodpy.core import exceptions

    rows = [
        f"{name}\t{value}"
        for name, value in vars(helpers).items()
        if name.startswith("EXIT_") and isinstance(value, int)
    ]
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
    """Write one row per key under *model*, its named tables (``solver.modflow6``) included.

    The named tables are those this build ships, so the rows do not depend on what is
    installed beside it.
    """
    from hydromodpy.core.config_kit.introspect import fields_and_tables

    for name, field in fields_and_tables(model).items():
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


def pipeline_steps() -> list[str]:
    """The names of the steps of a simulation, with their order."""
    from hydromodpy.core.pipeline_steps import STEP_NAMES

    return [f"{name}\t{index:02d}" for index, name in enumerate(STEP_NAMES)]


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
    FACADE_SURFACE: python_facade,
    "python_objects.tsv": python_objects,
    CLI_SURFACE: cli_tree,
    "exit_codes.tsv": exit_codes,
    TOML_SURFACE: toml_fields,
    "processes.tsv": processes,
    "pipeline_steps.tsv": pipeline_steps,
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


def _config_path(path: str) -> str:
    """Return a path of the register as the snapshots write it, with no list marker."""
    from hydromodpy.config.config_migration import document_path

    return document_path(path)


def _covers(old: str, path: str) -> bool:
    return path == old or path.startswith(f"{old}.")


def migration_for(path: str) -> Migration | None:
    """Return the row of the register that rewrites a TOML path, itself or by a moved parent.

    A ``move`` row and a ``value`` row rewrite. A ``retire`` row does when it names a
    ``rule``, which writes the key somewhere else. A key that the loader only refuses is
    no migration: ``hmp doctor --fix-config`` cannot rewrite it, and the promise of
    ``versions.md`` is that it does.
    """
    for row in migrations_of("config"):
        if row.shape == "retire" and row.rule is None:
            continue
        old = _config_path(row.key if row.shape == "value" else str(row.old))
        if _covers(old, path):
            return row
    return None


def prerelease_form_for(path: str) -> Any | None:
    """Return the form of ``prerelease_forms.txt`` that refuses a TOML path, or ``None``.

    Such a key left the grammar before 2.0.0 was released, so the ledger holds it and
    the doctor of 2.0.x rewrites it. It never covers a key that leaves today. A form of a
    value refuses one value of a key that stays, so it covers no path. A form that ends
    in ``{*}`` refuses the tables a pre-release wrote under a key, so it covers what lies
    below that key and not the key itself.
    """
    from hydromodpy.config.config_migration import PRERELEASE_FORMS

    for form in PRERELEASE_FORMS:
        if form.has_value:
            continue
        old = _config_path(form.path)
        if path.startswith(f"{old}.") or (path == old and not form.path.endswith(".{*}")):
            return form
    return None


def toml_entry_for(path: str) -> Any | None:
    """Return what keeps a removed TOML key answered: a row of the register or a refusal.

    The ledger of removed keys holds rewrites and refusals. A rewrite is a row of the
    register, a refusal is a line of ``prerelease_forms.txt``, and it stays until that
    list leaves.
    """
    return migration_for(path) or prerelease_form_for(path)


def _is_stable(rows: Iterable[str]) -> bool:
    return not all(row.endswith(f"\t{EXPERIMENTAL}") for row in rows)


def stable_removals(
    before: Iterable[str], after: Iterable[str], demoted: Iterable[str] = ()
) -> list[str]:
    """Return the TOML paths that left, not marked experimental or marked so after a promise."""
    old, new = _by_name(before), _by_name(after)
    promised = set(demoted)
    return [
        name for name in sorted(set(old) - set(new)) if name in promised or _is_stable(old[name])
    ]


def demotions(before: Iterable[str], after: Iterable[str]) -> list[str]:
    """Return the TOML paths that were stable and are marked experimental now."""
    old, new = _by_name(before), _by_name(after)
    return [
        name
        for name in sorted(set(old) & set(new))
        if _is_stable(old[name]) and not _is_stable(new[name])
    ]


def _facade_names(rows: Iterable[str]) -> set[str]:
    return set(_by_name(rows))


def _cli_names(rows: Iterable[str]) -> set[str]:
    """Return each command and each flag of the rows. A positional is neither."""
    names: set[str] = set()
    for label in _by_name(rows):
        command, _, last = label.rpartition(" ")
        if last.startswith("-"):
            names.update(f"{command} {flag}" for flag in last.split(","))
        elif not last.startswith("<"):
            names.add(label)
    return names


INTERFACE_NAMES: dict[str, Callable[[Iterable[str]], set[str]]] = {
    FACADE_SURFACE: _facade_names,
    CLI_SURFACE: _cli_names,
}
"""The surfaces whose names keep working for their delay, and how to read their names."""


@dataclass(frozen=True)
class InterfaceForm:
    """An old name of the facade or an old form of ``hmp``, and the entry that keeps it working."""

    old: str
    new: str | None
    since: str


def interface_forms() -> tuple[InterfaceForm, ...]:
    """Return the entries of the tables of old names and old forms of ``hmp``."""
    from hydromodpy import _lazy
    from hydromodpy.cli import conventions

    return (
        *(InterfaceForm(name, entry.new, entry.since) for name, entry in _lazy.OLD_NAMES.items()),
        *(InterfaceForm(form.old, form.new, form.since) for form in conventions.OLD_CLI_FORMS),
    )


def outlived_interface_forms(version: str) -> tuple[InterfaceForm, ...]:
    """Return the entries of the two tables that *version* should no longer hold."""
    return tuple(form for form in interface_forms() if outlived(form.since, version))


def entry_for(name: str) -> InterfaceForm | None:
    """Return the entry that keeps a name of the facade or of ``hmp`` working.

    The entry of a command covers its flags and the commands under it.
    """
    for form in interface_forms():
        if name == form.old or name.startswith(f"{form.old} "):
            return form
    return None


def before_the_tag() -> bool:
    """Whether this build comes before the first stable version, when nothing is promised."""
    from hydromodpy.core.version import __version__

    return Version(__version__) < Version(FIRST_STABLE)


def installed_release() -> str:
    """Return the release of this build, with no pre-release suffix."""
    from hydromodpy.core.version import __version__

    return Version(__version__).base_version


def _names_that_left(directory: Path, current: dict[str, list[str]]) -> list[str]:
    """Return the names of the facade and of ``hmp`` the snapshots hold and this build does not."""
    left: set[str] = set()
    for surface, names_of in INTERFACE_NAMES.items():
        if surface in current:
            left |= names_of(read_rows(directory / surface)) - names_of(current[surface])
    return sorted(left)


def _extend_ledger(ledger: Path, rows: list[str]) -> None:
    rows = read_rows(ledger) + rows
    ledger.write_text("\n".join(sorted(set(rows))) + "\n" if rows else "", encoding="utf-8")


def regenerate(directory: Path = SNAPSHOT_DIR) -> list[str]:
    """Write every surface; return what could not be accepted, without writing anything."""
    current = {surface: rows_of(surface) for surface in SURFACES}
    before, after = read_rows(directory / TOML_SURFACE), current[TOML_SURFACE]
    demoted = [row.split("\t")[0] for row in read_rows(directory / DEMOTED_TOML_KEYS)]
    removed = stable_removals(before, after, demoted)
    newly_demoted = demotions(before, after)
    promised = not before_the_tag()
    left = _names_that_left(directory, current) if promised else []
    refused = [
        f"{path}: this stable TOML key left and hydromodpy/schema/changes.toml has no migration row "
        "that rewrites it. Add the row, with its `since`, so that hmp doctor --fix-config "
        "rewrites it, or mark the key experimental first if it was never promised and has never "
        "been stable."
        for path in removed
        if migration_for(path) is None
    ]
    refused += [
        f"{name}: this public name left and nothing keeps it working. Add an entry with its "
        "`since`: OLD_NAMES in hydromodpy/_lazy.py for Python, OLD_CLI_FORMS in "
        "hydromodpy/cli/conventions.py for hmp."
        for name in left
        if entry_for(name) is None
    ]
    if promised:
        refused += [
            f"{path}: this stable TOML key is marked experimental. A stable version made a promise "
            "on it: keep it stable, or rename it with its row in hydromodpy/schema/changes.toml."
            for path in newly_demoted
        ]
    if refused:
        return refused
    directory.mkdir(parents=True, exist_ok=True)
    for surface, rows in current.items():
        (directory / surface).write_text("\n".join(rows) + "\n", encoding="utf-8")
    release = installed_release()
    _extend_ledger(directory / REMOVED_TOML_KEYS, [f"{path}\t{release}" for path in removed])
    _extend_ledger(directory / REMOVED_NAMES, [f"{name}\t{release}" for name in left])
    _extend_ledger(directory / DEMOTED_TOML_KEYS, newly_demoted)
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
