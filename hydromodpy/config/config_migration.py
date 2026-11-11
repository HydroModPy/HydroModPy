"""How a file written against an earlier grammar still loads.

The migration is the ``document = "config"`` rows of the register of changes,
``hydromodpy/schema/changes.toml``, applied in the order of the file. A ``move`` row
writes a key or a table at its new path, and the dotted paths that name it follow. A
``value`` row renames one value. A ``retire`` row refuses a key that left. A row names
a function of :data:`RULES` when it cannot say the whole change.

The models refuse an old key (``extra="forbid"``), so two callers use this module.
``hmp doctor --fix-config`` (:func:`fix_config_chain`) rewrites each file of a chain on
disk. The loader migrates each layer in memory (:func:`migrate_layers`), then the
merged document (:func:`migrate_merged_doc`), and warns once per key and per file.

A live file reads a ``move`` or a ``value`` row with a warning for two minor versions,
then it is refused with the new name. A sealed run reads every row in silence, so a
run on disk replays. A key only a pre-release of 2.0 wrote is listed in
``prerelease_forms.txt`` and refused with one sentence that names the doctor of 2.0.x.
"""

from __future__ import annotations

import copy
import difflib
import re
import tomllib
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Final

import tomlkit
from packaging.version import Version

from hydromodpy.core.config_kit.base import CANNOT_REWRITE, refuse_old_forms, warn_old_form
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.plugin_registry import check_registered_name
from hydromodpy.core.state.result_dirs import is_sealed_run_config
from hydromodpy.core.toml_io.error_locator import json_pointer
from hydromodpy.core.toml_io.loader import read_toml_chain
from hydromodpy.core.toml_io.merge import DIRECTIVE_SUFFIXES
from hydromodpy.core.toml_io.overrides import COMMAND_LINE_SOURCES
from hydromodpy.core.toml_io.paths import DottedPath, parse
from hydromodpy.core.version import __version__
from hydromodpy.schema.changes import (
    FIRST_EDITION,
    REGISTER,
    Migration,
    Register,
    editions,
    migrations_of,
    outlived,
    prerelease_refusal,
)

_logger = get_logger(__name__)

Layer = tuple[str | Path | None, Any]
"""Where a part of a document came from, and what it writes."""

_PHASES = "calibration.phases[*]"
_PATH_KEYS = ("sites.bind", "sites.recipes.{*}.set")
"""Tables of the document whose keys are dotted paths, besides the overrides of a phase."""

_PARAMETERS = "calibration.parameters.{*}"
_PATH_VALUES = ("path", "target")
"""The keys of a calibration parameter whose value is a dotted path."""

_BACKEND = "solver.backend"
_BACKEND_KEYS = ("kind", "name")

#: The refusal a forward model earns, which names what a global model is today.
_FORWARD_MODEL_REFUSAL = (
    "a forward model is a solver backend since 2.1.0: name it by solver.backend, "
    "register it in the hydromodpy.solver entry-point group, and calibrate it with "
    "the pipeline evaluator"
)

#: The old paths of the ``sgrid`` table of each flow solver, which ``[mesh]`` replaced.
RETIRED_SGRID_KEYS = tuple(
    f"{solver}.sgrid.{key}"
    for key in ("planar", "grid_dual")
    for solver in ("modflow6", "modflownwt")
)

PRERELEASE_FORMS_FILENAME: Final[str] = "prerelease_forms.txt"
"""The keys and values only a pre-release of 2.0 wrote, package data of this module.

The list was retired in 2.1.0 and leaves with the delay of a refused name,
``schema.changes.removal_of("2.1.0")``. ``tests/unit/config/test_prerelease_forms.py``
fails from that version on.
"""

_SEALED_SOURCE = "a sealed run config"

_STILL_A_FIELD = frozenset({"workspace.project_root"})
"""Forms of the list that are runtime fields today: the model refuses them in a file."""


class _Refused(str):
    """A change the doctor makes and a load refuses, with the new form it names."""


class _Retired(str):
    """A key that left with nothing to write in its place. The doctor leaves it."""


def _backend_name_of(table: Mapping[str, Any]) -> Any:
    """Return the name a ``solver.backend`` table says: ``kind``, or ``name`` when it is custom."""
    kind = _plain(table.get("kind"))
    if isinstance(kind, str) and kind.strip().lower() == "custom":
        return _plain(table.get("name"))
    return kind


def _flatten_the_backend_table(doc: Any, *, sealed: bool) -> list[str]:
    """Write ``solver.backend`` as the name of the flow solver, not as a table.

    ``{kind = "custom", name = "x"}`` becomes ``"x"``, the dotted keys of a phase and of
    ``[sites]`` too. A table that holds another key is left for the loader to refuse.
    """
    del sealed
    changes: list[str] = []
    solver = doc.get("solver")
    if isinstance(solver, Mapping):
        changes.extend(_flatten_one_backend(solver, _BACKEND))
    for where, phase in _tables_at(doc, _PHASES):
        overrides = phase.get("overrides")
        if not isinstance(overrides, Mapping):
            continue
        nested = overrides.get("solver")
        if isinstance(nested, Mapping):
            changes.extend(_flatten_one_backend(nested, f"{where}.overrides.{_BACKEND}"))
        changes.extend(_flatten_backend_keys(overrides, f"{where}.overrides"))
    for scope in _PATH_KEYS:
        for where, table in _tables_at(doc, scope):
            changes.extend(_flatten_backend_keys(table, where))
    return changes


def _flatten_one_backend(solver: Any, label: str) -> list[str]:
    backend = solver.get("backend")
    if not isinstance(backend, Mapping) or set(backend) - set(_BACKEND_KEYS):
        return []
    name = _backend_name_of(backend)
    if not isinstance(name, str) or not name.strip():
        return []
    solver["backend"] = name.strip()
    return [f"{label}.kind -> {label} = {name.strip()!r}"]


def _flatten_backend_keys(table: Any, where: str) -> list[str]:
    """Fold the dotted keys ``solver.backend.kind`` and ``.name`` of *table* into one key."""
    dotted = {key: f"{_BACKEND}.{key}" for key in _BACKEND_KEYS}
    written = {key: table[path] for key, path in dotted.items() if path in table}
    if not written or _BACKEND in table:
        return []
    name = _backend_name_of(written)
    if not isinstance(name, str) or not name.strip():
        return []
    for path in dotted.values():
        if path in table:
            del table[path]
    table[_BACKEND] = name.strip()
    return [f'{where}."{_BACKEND}.kind" -> "{_BACKEND}"']


def _move_the_dem_init_path(doc: Any, *, sealed: bool) -> list[str]:
    """Move ``geographic.catchment.dem_init_path`` into one ``[[data.dem.sources]]`` row.

    The path is kept as written, so a sealed run reads the file it recorded.
    """
    del sealed
    geographic = doc.get("geographic")
    if not isinstance(geographic, Mapping):
        return []
    catchment = geographic.get("catchment")
    if not isinstance(catchment, Mapping) or "dem_init_path" not in catchment:
        return []
    raw = _plain(catchment.pop("dem_init_path"))
    if not catchment:
        geographic.pop("catchment", None)
    data = doc.setdefault("data", {})
    if not isinstance(data, Mapping):
        return []
    dem = data.setdefault("dem", {})
    if not isinstance(dem, Mapping):
        data["dem"] = {}
        dem = data["dem"]
    held = _plain(dem.get("sources"))
    held = held if isinstance(held, list) else ([] if held is None else [held])
    dem["sources"] = [{"source": "file", "path": str(raw)}, *held]
    return [
        f"geographic.catchment.dem_init_path -> [[data.dem.sources]] path {raw!r} "
        "(dem_init_path was removed in 2.1.0: declare the DEM as [[data.dem.sources]] "
        'with source = "file" and the same path)'
    ]


def _drop_the_forward_model(doc: Any, *, sealed: bool) -> list[str]:
    """Drop ``[calibration] forward_model`` and the value ``scored_forward_model``.

    A sealed run loses a ``null`` in silence and warns on a value.
    """
    changes: list[str] = []
    for where, table in _tables_at(doc, "calibration"):
        if "forward_model" in table:
            value = _plain(table.pop("forward_model"))
            label = f"{where}.forward_model"
            if not sealed:
                changes.append(f"{label} dropped: {_FORWARD_MODEL_REFUSAL}")
            elif value is not None:
                warn_old_form(None, f"{label} retired ({_FORWARD_MODEL_REFUSAL})", rewritable=False)
        if table.get("evaluator") == "scored_forward_model":
            del table["evaluator"]
            if not sealed:
                changes.append(f"{where}.evaluator dropped: {_FORWARD_MODEL_REFUSAL}")
            else:
                warn_old_form(
                    None, f"evaluator retired ({_FORWARD_MODEL_REFUSAL})", rewritable=False
                )
    return changes


def _drop_the_cache_switches(doc: Any, *, sealed: bool) -> list[str]:
    """Retire the cache switches of ``[geographic]``, one row of the register per key.

    Each row carries the ``since`` and the ``instead`` of its key, and ``_retire``
    refuses a live file on them and drops a sealed one in silence.
    """
    keys = {"geographic.reuse_existing_outputs", "geographic.reg_fold"}
    return [
        change
        for row in migrations_of("config")
        if str(row.old) in keys
        for change in _retire(doc, row, sealed=sealed)
    ]


RULES: dict[str, Callable[..., list[str]]] = {
    "flatten_the_backend_table": _flatten_the_backend_table,
    "move_the_dem_init_path": _move_the_dem_init_path,
    "drop_the_forward_model": _drop_the_forward_model,
    "drop_the_cache_switches": _drop_the_cache_switches,
}
"""The functions a row names by ``rule``, each ``f(doc, *, sealed)``, run once per pass."""


def _wild(path: str) -> bool:
    return "[*]" in path or "{*}" in path


_UNKNOWN_RULES = {row.rule for row in migrations_of("config")} - {None, *RULES}
if _UNKNOWN_RULES:
    raise ValueError(f"changes.toml names rules that RULES lacks: {sorted(_UNKNOWN_RULES)}")


def _rows(doc: Any, *, sealed: bool, register: Register) -> list[str]:
    """Apply the config rows of *register* to *doc*, in place, and return what changed."""
    changes: list[str] = []
    ran: set[str] = set()
    for row in migrations_of("config", register):
        if row.rule is not None:
            if row.rule not in ran:
                ran.add(row.rule)
                changes.extend(_as_told(row, RULES[row.rule](doc, sealed=sealed), sealed=sealed))
        elif row.shape == "move":
            changes.extend(_as_told(row, _move(doc, row), sealed=sealed))
        elif row.shape == "value":
            changes.extend(_as_told(row, _rename_value(doc, row), sealed=sealed))
        else:
            changes.extend(_retire(doc, row, sealed=sealed))
    changes.extend(_rewrite_dotted_paths(doc, sealed=sealed, register=register))
    return changes


def _as_told(row: Migration, told: Sequence[str], *, sealed: bool) -> list[str]:
    """Mark what a live file is refused on: a key that left, or a form past its delay."""
    if sealed:
        return list(told)
    late = row.shape == "retire" or outlived(row.since, __version__)
    return [
        _Refused(change) if late and CANNOT_REWRITE not in change else change for change in told
    ]


def _move(doc: Any, row: Migration, *, prefix: str = "") -> list[str]:
    """Write the key or table of ``row.old`` at ``row.new``, with its directives.

    A path under ``[*]`` or ``{*}`` is renamed in its own table, to the last part of ``new``.
    """
    old, new = str(row.old), str(row.new)
    if _wild(old):
        return _rename_in_place(doc, old, new, prefix=prefix)
    changes: list[str] = []
    value = _value_at(doc, old)
    if value is not None:
        existing = _value_at(doc, new)
        if isinstance(existing, Mapping) and _holds_only_the_old_table(existing, new, old):
            # [transport.mt3dms.parameters] leads to [transport.mt3dms], which only holds it.
            existing = None
        _drop_table(doc, old)
        if existing is None:
            _set_at(doc, new, value)
            changes.append(f"{prefix}{old} -> [{prefix}{new}]")
        else:
            changes.append(
                f"{prefix}{old} dropped ([{prefix}{new}] already set; {_held(value, existing)})"
            )
    for suffix in DIRECTIVE_SUFFIXES:
        directive = _value_at(doc, old + suffix)
        if directive is not None:
            _drop_table(doc, old + suffix)
            _set_at(doc, new + suffix, _plain(directive))
            changes.append(f"{prefix}{old}{suffix} -> {prefix}{new}{suffix}")
    return changes


def _rename_in_place(doc: Any, old: str, new: str, *, prefix: str) -> list[str]:
    """Rename the last key of *old* in each table its scope walks."""
    scope, _, old_key = old.rpartition(".")
    new_key = new.rpartition(".")[2]
    changes: list[str] = []
    for where, table in _tables_at(doc, scope):
        for suffix in ("", *DIRECTIVE_SUFFIXES):
            if old_key + suffix not in table:
                continue
            label = f"{prefix}{where}.{old_key}{suffix}"
            value = _plain(table[old_key + suffix])
            if new_key + suffix in table:
                del table[old_key + suffix]
                kept = table[new_key + suffix]
                changes.append(
                    f"{label} dropped ({new_key + suffix!r} already set; {_held(value, kept)})"
                )
            else:
                _move_key(table, old_key + suffix, new_key + suffix, value)
                changes.append(f"{label} -> {new_key}{suffix}")
    return changes


def _holds_only_the_old_table(existing: Mapping, new: str, old: str) -> bool:
    """Whether *existing*, the table at *new*, holds nothing but the head of *old* below it."""
    if not old.startswith(f"{new}."):
        return False
    return set(existing) <= {old[len(new) + 1 :].split(".")[0]}


def _rename_value(doc: Any, row: Migration) -> list[str]:
    """Rewrite ``row.old_value`` as ``row.new_value`` wherever ``row.key`` holds it."""
    scope, _, name = str(row.key).rpartition(".")
    changes: list[str] = []
    for where, table in _tables_at(doc, scope) if scope else [("", doc)]:
        if name in table and _plain(table[name]) == row.old_value:
            table[name] = row.new_value
            label = f"{where}.{name}" if where else name
            changes.append(f"{label}: {row.old_value!r} -> {row.new_value!r}")
    return changes


def _retire(doc: Any, row: Migration, *, sealed: bool) -> list[str]:
    """Refuse a key that left. A sealed run drops it when ``sealed = "drop"``."""
    scope, _, name = str(row.old).rpartition(".")
    changes: list[str] = []
    for where, table in _tables_at(doc, scope) if scope else [("", doc)]:
        if name not in table:
            continue
        label = f"{where}.{name}" if where else name
        if sealed and row.sealed == "drop":
            del table[name]
            changes.append(f"{label} dropped (sealed)")
        elif sealed:
            raise ConfigValidationError(
                f"{_SEALED_SOURCE} holds {label}, which left in {row.since}: {row.instead}"
            )
        else:
            changes.append(
                _Retired(f"{label}{CANNOT_REWRITE}it left in {row.since}. {row.instead}")
            )
    return changes


@dataclass(frozen=True)
class MovedPath:
    """One dotted path that moved, from a ``move`` row. A path below ``old`` moves too."""

    old: tuple[str, ...]
    new: tuple[str, ...]
    row: Migration

    def rewrite(self, path: str) -> str | None:
        """Return *path* under the new name, or ``None`` when it does not start with ``old``."""
        try:
            parts = list(parse(path).parts)
        except ValueError:
            # Not a path this table can read: the place that reads it refuses it.
            return None
        suffix = next((s for s in DIRECTIVE_SUFFIXES if parts[-1].endswith(s)), "")
        parts[-1] = parts[-1].removesuffix(suffix)
        if len(parts) < len(self.old):
            return None
        free: list[str] = []
        for token, part in zip(self.old, parts, strict=False):
            if token == "{*}":
                free.append(part)
            elif token != part:
                return None
        names = iter(free)
        moved = [next(names) if token == "{*}" else token for token in self.new]
        return f"{DottedPath((*moved, *parts[len(self.old) :]))}{suffix}"


def moved_paths(*, sealed: bool = False, register: Register = REGISTER) -> tuple[MovedPath, ...]:
    """Return every dotted path that moved, a row past its delay for a sealed document only.

    A row whose path walks a list has none: a path takes no index.
    """
    return tuple(
        MovedPath(tuple(str(row.old).split(".")), tuple(str(row.new).split(".")), row)
        for row in migrations_of("config", register)
        if row.shape == "move"
        and "[*]" not in str(row.old)
        and (sealed or not outlived(row.since, __version__))
    )


def rewrite_dotted_path(path: str, *, sealed: bool = False, register: Register = REGISTER) -> str:
    """Return a dotted path of the document under its current name."""
    for row in moved_paths(sealed=sealed, register=register):
        path = row.rewrite(path) or path
    return path


def _rewrite_dotted_paths(doc: Any, *, sealed: bool, register: Register) -> list[str]:
    """Rewrite the paths *doc* writes as keys and as values."""
    rows = moved_paths(sealed=True, register=register)
    changes: list[str] = []
    for where, phase in _tables_at(doc, _PHASES):
        overrides = phase.get("overrides")
        if not isinstance(overrides, Mapping):
            continue
        label = f"{where}.overrides"
        changes.extend(_rewrite_path_keys(overrides, label, rows, sealed=sealed))
        # A phase may write the same keys as nested tables instead.
        for row in migrations_of("config", register):
            if row.shape == "move" and row.rule is None:
                moved = _move(overrides, row, prefix=f"{label}.")
                changes.extend(_as_told(row, moved, sealed=sealed))
    for scope in _PATH_KEYS:
        for where, table in _tables_at(doc, scope):
            changes.extend(_rewrite_path_keys(table, where, rows, sealed=sealed))
    for where, table in _tables_at(doc, _PARAMETERS):
        for name in _PATH_VALUES:
            value = _plain(table.get(name))
            if not isinstance(value, str):
                continue
            for row in rows:
                moved = row.rewrite(value)
                if moved is not None and moved != value:
                    table[name] = moved
                    told = [f"{where}.{name} {value!r} -> {moved!r}"]
                    changes.extend(_as_told(row.row, told, sealed=sealed))
                    value = moved
    return changes


def _rewrite_path_keys(
    table: Any, where: str, rows: Sequence[MovedPath], *, sealed: bool
) -> list[str]:
    """Rewrite the dotted keys of *table*. A row with a rule moves its own keys."""
    changes: list[str] = []
    # A key one row leaves stays where it is: a later row does not move it on.
    left: set[str] = set()
    for row in rows:
        if row.row.rule is not None:
            continue
        for key in [str(key) for key in table if str(key) not in left]:
            renamed = row.rewrite(key)
            if renamed is None:
                continue
            label = f'{where}."{key}"'
            if renamed in table:
                left.add(key)
                changes.append(f'{label}{CANNOT_REWRITE}"{renamed}" is given too, keep one')
                continue
            _move_key(table, key, renamed, _plain(table[key]))
            changes.extend(_as_told(row.row, [f'{label} -> "{renamed}"'], sealed=sealed))
    return changes


@dataclass(frozen=True)
class PrereleaseForm:
    """One key, or one value of a key, that only a pre-release of 2.0 wrote."""

    path: str
    value: Any = None
    has_value: bool = False

    def found_in(self, doc: Any) -> list[str]:
        """Return where *doc* writes this form, as tables and keys."""
        scope, _, name = self.path.rpartition(".")
        if name == "{*}":
            # A table that held tables under free names.
            return [where for where, table in _tables_at(doc, scope) if table]
        found = []
        for where, table in _tables_at(doc, scope) if scope else [("", doc)]:
            for key in (name, *(name + suffix for suffix in DIRECTIVE_SUFFIXES)):
                if key in table and (not self.has_value or self._holds(_plain(table[key]))):
                    found.append(f"{where}.{key}" if where else key)
        return found

    def _holds(self, written: Any) -> bool:
        """Whether *written* is the value of this form, or a list that holds it."""
        if isinstance(written, list) and not isinstance(self.value, list):
            return self.value in written
        return written == self.value


def _read_prerelease_forms(text: str) -> tuple[PrereleaseForm, ...]:
    """Read ``path`` or ``path = value`` per line; ``#`` starts a comment line."""
    forms = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        path, equals, raw = line.partition(" = ")
        if not equals:
            forms.append(PrereleaseForm(path.strip()))
            continue
        try:
            value = tomllib.loads(f"v = {raw.strip()}")["v"]
        except tomllib.TOMLDecodeError:
            value = raw.strip()
        forms.append(PrereleaseForm(path.strip(), value, has_value=True))
    return tuple(forms)


PRERELEASE_FORMS: Final[tuple[PrereleaseForm, ...]] = _read_prerelease_forms(
    files(__package__).joinpath(PRERELEASE_FORMS_FILENAME).read_text(encoding="utf-8")
)
"""The forms of :data:`PRERELEASE_FORMS_FILENAME`, in the order of the file."""


def prerelease_keys(doc: Any, *, register: Register = REGISTER) -> list[str]:
    """Return every key of *doc* only a pre-release wrote. A path a row moves is not one."""
    moved = {row.old for row in migrations_of("config", register) if row.old is not None}
    forms = [form for form in PRERELEASE_FORMS if form.path not in moved | _STILL_A_FIELD]
    found: list[str] = []
    for form in forms:
        found.extend(form.found_in(doc))
    dotted = [("", doc)] + [
        (f"{where}.overrides.", phase["overrides"])
        for where, phase in _tables_at(doc, _PHASES)
        if isinstance(phase.get("overrides"), Mapping)
    ]
    dotted += [
        (f"{where}.", table) for scope in _PATH_KEYS for where, table in _tables_at(doc, scope)
    ]
    for where, table in dotted:
        for key in [str(key) for key in table if "." in str(key)]:
            # A dotted key reads as the tables it names.
            try:
                nested: Any = _plain(table[key])
                for part in reversed(parse(key).parts):
                    nested = {part: nested}
            except ValueError:
                continue
            if any(form.found_in(nested) for form in forms):
                found.append(f'{where}"{key}"')
    return list(dict.fromkeys(found))


_LOC_PART = re.compile(r'"([^"]*)"|\[(\d+)\]|([^.\["]+)')


def _prerelease_details(keys: Sequence[str], sentence: str) -> list[dict[str, Any]]:
    """Return one fault per key with its pointer; a quoted part stays whole, ``[n]`` is an index."""
    details = []
    for key in keys:
        loc = [int(i) if i else bare or quoted for quoted, i, bare in _LOC_PART.findall(key)]
        details.append(
            {"pointer": json_pointer(loc), "loc": loc, "msg": sentence, "type": "prerelease_form"}
        )
    return details


def refuse_prerelease_forms(layers: Sequence[Layer], *, register: Register = REGISTER) -> None:
    """Refuse the layers that write a pre-release form, naming every such key at once."""
    refusals: list[str] = []
    details: list[dict[str, Any]] = []
    files_refused: list[str] = []
    for source, doc in layers:
        if keys := prerelease_keys(doc, register=register):
            where = "config" if source is None else str(source)
            rewritable = source not in COMMAND_LINE_SOURCES
            refusals.append(prerelease_refusal(where, keys, rewritable=rewritable))
            details.extend(_prerelease_details(keys, refusals[-1]))
            files_refused += [str(source)] if source is not None and rewritable else []
    if refusals:
        file = files_refused[0] if files_refused else None
        raise ConfigValidationError("\n".join(refusals), details=details, source=file)


def apply_edition(
    doc: Any,
    *,
    edition: str,
    register: Register = REGISTER,
    optional_sections: Collection[str] = (),
) -> list[str]:
    """Write ``old`` of each ``[[default]]`` of a later edition than *edition* *doc* leaves out.

    A file keeps the defaults of the edition it writes. Return the keys written. An
    edition this version does not serve is refused, with the editions it serves.
    A root section named in *optional_sections* is never created: a document that does
    not write it keeps it absent, so a simulation stays without ``[calibration]``.
    """
    try:
        check_registered_name(edition, editions(register), key="edition")
    except ValueError as exc:
        fault = {"pointer": "/edition", "loc": ["edition"], "msg": str(exc), "type": "edition"}
        raise ConfigValidationError(str(exc), details=[fault]) from exc
    written: list[str] = []
    for row in register.defaults:
        if Version(f"{row.edition}.0") <= Version(f"{edition}.0"):
            continue
        root = row.key.split(".", 1)[0]
        if root in optional_sections and not isinstance(doc.get(root), Mapping):
            continue
        if not _wild(row.key):
            if _value_at(doc, row.key) is None:
                _set_at(doc, row.key, row.old)
                written.append(row.key)
            continue
        scope, _, name = row.key.rpartition(".")
        for where, table in _tables_at(doc, scope):
            if name not in table:
                table[name] = row.old
                written.append(f"{where}.{name}")
    return written


def edition_of(doc: Any) -> str:
    """Return the edition *doc* writes, the first one when it writes none."""
    edition = _plain(doc.get("edition")) if isinstance(doc, Mapping) else None
    return str(edition) if edition is not None else FIRST_EDITION


def _is_sealed(source: str | Path | None) -> bool:
    """Whether *source* is the frozen config of a run, which no one edits."""
    return (
        source is not None and source not in COMMAND_LINE_SOURCES and is_sealed_run_config(source)
    )


def _tell(source: str | Path | None, changes: Sequence[str]) -> None:
    """Warn about *changes* under the name of *source*, in silence for a sealed file."""
    if _is_sealed(source):
        if changes:
            _logger.debug("%s: sealed config read as renamed: %s", source, "; ".join(changes))
        return
    where = "config" if source is None else str(source)
    retired = [change for change in changes if isinstance(change, _Retired)]
    if retired:
        raise ConfigValidationError(f"{where}: {'; '.join(retired)}.")
    rewritable = source not in COMMAND_LINE_SOURCES
    refused = [change for change in changes if isinstance(change, _Refused)]
    if refused:
        refuse_old_forms(source, refused, rewritable=rewritable)
    for change in changes:
        warn_old_form(source, change, rewritable=rewritable)


def migrate_layers(layers: Sequence[Layer], *, register: Register = REGISTER) -> list[str]:
    """Migrate each layer on its own, in place, before the merge, and warn under its name.

    A pre-release form is refused first. A key a row cannot move stays for the merge.
    """
    refuse_prerelease_forms(layers, register=register)
    changes: list[str] = []
    for source, doc in layers:
        own = _rows(doc, sealed=_is_sealed(source), register=register)
        _tell(source, [c for c in own if CANNOT_REWRITE not in c or isinstance(c, _Retired)])
        changes.extend(own)
    return changes


def _change_label(change: str) -> str:
    """Return the key a change speaks of: what comes before its verb."""
    for verb in (" -> ", CANNOT_REWRITE, " dropped", " (", ": "):
        change = change.split(verb, 1)[0]
    return change


def _labels_of(doc: Any, register: Register) -> set[str]:
    """Return the keys the rows would touch in *doc*, which stays as it is."""
    try:
        probe = copy.deepcopy(_plain(doc))
        return {_change_label(change) for change in _rows(probe, sealed=False, register=register)}
    except ValueError:
        # A value only the whole document can refuse: the merged pass says it.
        return set()


def optional_root_sections() -> frozenset[str]:
    """Return the root sections of ``HydroModPyConfig`` that are ``None`` when a document omits them."""
    from hydromodpy.config.hydromodpy_config import HydroModPyConfig

    return frozenset(
        name for name, field in HydroModPyConfig.model_fields.items() if field.default is None
    )


def migrate_merged_doc(
    doc: Any,
    layers: Sequence[Layer] = (),
    *,
    register: Register = REGISTER,
    optional_sections: Collection[str] | None = None,
) -> list[str]:
    """Run the rows on the merged document, in place, then fill in the defaults of its edition.

    A change is told under the last layer that holds its key. With no *layers*, nothing
    is told and a pre-release form is refused, as in a layer.
    """
    if not layers:
        refuse_prerelease_forms([(None, doc)], register=register)
    leaf = layers[-1][0] if layers else None
    sealed = _is_sealed(leaf)
    changes: list[str] = []
    if _rows(copy.deepcopy(_plain(doc)), sealed=sealed, register=register):
        held = [(source, _labels_of(own, register)) for source, own in layers]
        changes = _rows(doc, sealed=sealed, register=register)
        for change in changes if layers else ():
            label = _change_label(change)
            holder = next(
                (
                    source
                    for source, labels in reversed(held)
                    if any(label.startswith(key) or key.startswith(label) for key in labels)
                ),
                leaf,
            )
            _tell(holder, [change])
    apply_edition(
        doc,
        edition=edition_of(doc),
        register=register,
        optional_sections=optional_root_sections()
        if optional_sections is None
        else optional_sections,
    )
    return changes


def migrate_config_doc_on_load(
    doc: Any, *, source: str | Path | None = None, register: Register = REGISTER
) -> list[str]:
    """Migrate one whole *doc* in memory and warn under *source*, in silence for a sealed run."""
    layers = [(source, doc)]
    changes = migrate_layers(layers, register=register)
    changes.extend(migrate_merged_doc(doc, layers, register=register))
    return changes


def migrate_config_doc(doc: Any, *, register: Register = REGISTER) -> list[str]:
    """Apply every row to a ``dict`` or ``tomlkit`` *doc* in place, tell nothing, return the changes."""
    refuse_prerelease_forms([(None, doc)], register=register)
    return _rows(doc, sealed=False, register=register)


def migrate_sealed_config_doc(
    doc: Any,
    *,
    register: Register = REGISTER,
    optional_sections: Collection[str] | None = None,
) -> list[str]:
    """Read a sealed run config under today's names, in silence, every row past its delay too.

    ``[workspace] project_root`` is dropped: a snapshot names its project there and the
    caller reads it first. A run sealed by a pre-release is refused.
    """
    workspace = doc.get("workspace")
    if isinstance(workspace, Mapping):
        workspace.pop("project_root", None)
        if not workspace:
            del doc["workspace"]
    keys = prerelease_keys(doc, register=register)
    if keys:
        sentence = prerelease_refusal(_SEALED_SOURCE, keys)
        raise ConfigValidationError(sentence, details=_prerelease_details(keys, sentence))
    changes = _rows(doc, sealed=True, register=register)
    apply_edition(
        doc,
        edition=edition_of(doc),
        register=register,
        optional_sections=optional_root_sections()
        if optional_sections is None
        else optional_sections,
    )
    return changes


def fix_config_chain(
    path: str | Path,
    *,
    dry_run: bool = False,
    diffs: dict[Path, str] | None = None,
    register: Register = REGISTER,
) -> dict[Path, list[str]]:
    """Rewrite each file of the ``base_config`` chain of *path* that holds an old form.

    Returns the changes of each file, root first. A pre-release form refuses the
    chain with :class:`ConfigValidationError` before any write. A key that left stays,
    with what to write. *diffs* receives the unified diff of each rewrite.
    """
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"No TOML file at {target}")
    # utf-8-sig: several configs carry a BOM, which tomlkit reads as an empty key.
    docs = {
        item.path: tomlkit.parse(item.path.read_text(encoding="utf-8-sig"))
        for item in read_toml_chain(target, root=None)
    }
    layers = list(docs.items())
    refuse_prerelease_forms(layers, register=register)
    # The loader applies the same rows to each file alone, so a rewrite file by file
    # reads as the chain did.
    changes = {file: _rows(doc, sealed=False, register=register) for file, doc in layers}
    for file, doc in docs.items():
        if any(CANNOT_REWRITE not in change for change in changes[file]):
            if diffs is not None:
                diffs[file] = _unified_diff(file, tomlkit.dumps(doc))
            if not dry_run:
                file.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changes


def fix_config_file(path: str | Path) -> list[str]:
    """Rewrite the chain of *path*, as :func:`fix_config_chain`; return the changes of *path*."""
    return fix_config_chain(path)[Path(path).expanduser().resolve()]


def _unified_diff(file: Path, after: str) -> str:
    """Return the unified diff from the text of *file* on disk to *after*."""
    before = file.read_text(encoding="utf-8-sig")
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=str(file),
            tofile=f"{file} (migrated)",
        )
    )


def _plain(value: Any) -> Any:
    """Return a tomlkit item as the plain Python value it holds."""
    return value.unwrap() if hasattr(value, "unwrap") else value


def _tables_at(doc: Any, scope: str) -> list[tuple[str, Any]]:
    """Return each table of *doc* that *scope* names, with where it sits.

    ``a[*]`` walks the tables of a list, ``a__append`` and ``a__merge`` included, and
    ``{*}`` the tables under free names.
    """
    found: list[tuple[str, Any]] = [("", doc)]
    for token in scope.split("."):
        stepped: list[tuple[str, Any]] = []
        for where, node in found:
            if not isinstance(node, Mapping):
                continue
            join = f"{where}." if where else ""
            if token == "{*}":
                stepped.extend(
                    (f"{join}{key}", child)
                    for key, child in node.items()
                    if isinstance(child, Mapping)
                )
            elif token.endswith("[*]"):
                for name in (token[:-3], f"{token[:-3]}__append", f"{token[:-3]}__merge"):
                    child = node.get(name)
                    members = [child] if isinstance(child, Mapping) else child
                    if isinstance(members, Sequence) and not isinstance(members, str):
                        stepped.extend(
                            (f"{join}{name}[{index}]", member)
                            for index, member in enumerate(members)
                            if isinstance(member, Mapping)
                        )
            elif isinstance(node.get(token), Mapping):
                stepped.append((f"{join}{token}", node[token]))
        found = stepped
    return found


def _descend(scope: Any, parents: list[str]) -> Any:
    """Return the nested table at ``parents`` of *scope*, or ``None``."""
    node = scope
    for part in parents:
        node = node.get(part) if isinstance(node, Mapping) else None
    return node if isinstance(node, Mapping) else None


def _value_at(doc: Any, path: str) -> Any:
    """Return what *doc* holds at the dotted *path*, or ``None``."""
    *parents, key = path.split(".")
    table = _descend(doc, parents)
    return None if table is None else table.get(key)


def _set_at(doc: Any, path: str, value: Any) -> None:
    """Write *value* at the dotted *path* of *doc*, creating the tables on the way."""
    *parents, key = path.split(".")
    is_file = isinstance(doc, tomlkit.TOMLDocument)
    table = doc
    for part in parents:
        child = table.get(part)
        if not isinstance(child, Mapping):
            table[part] = tomlkit.table(is_super_table=True) if is_file else {}
            child = table[part]
        table = child
    moved = _moved_table(value)
    table[key] = value if moved is None else moved


def _drop_table(doc: Any, path: str) -> None:
    """Delete the table at *path*, then each parent table it leaves empty."""
    parts = path.split(".")
    while parts:
        parent = _descend(doc, parts[:-1])
        del parent[parts[-1]]
        parts.pop()
        if parent:
            return


def _held(dropped: Any, kept: Any) -> str:
    """Say what a dropped value held against the kept one."""
    dropped, kept = _plain(dropped), _plain(kept)
    if dropped in ({}, kept):
        return "it was empty" if dropped == {} else "same values"
    if not (isinstance(dropped, Mapping) and isinstance(kept, Mapping)):
        return f"it held other values: {dropped!r} against {kept!r}"

    def shown(table: Mapping[str, Any], key: str) -> str:
        return repr(table[key]) if key in table else "unset"

    return "it held other values: " + ", ".join(
        f"{key} = {shown(dropped, key)} against {shown(kept, key)}"
        for key in sorted(set(dropped) | set(kept))
        if dropped.get(key) != kept.get(key)
    )


def _moved_table(original: Any) -> Any:
    """Return a tomlkit table as an item for its new key, with its comments, or ``None``."""
    if isinstance(original, tomlkit.items.InlineTable):
        return original
    if not isinstance(original, tomlkit.items.Table):
        return None
    fresh = tomlkit.table()
    for key, item in original.value.body:
        fresh.append(key, item)
    return fresh


def _move_key(table: Any, old: str, new: str, value: Any) -> None:
    """Write *value* under ``new`` where ``old`` stood, and keep the comment of the line."""
    position = _position(table, old)
    original = table.get(old)
    comment = _comment_of(table, old)
    del table[old]
    item = _moved_table(original) or _scalar_item(value, comment)
    if position is None or item is None:
        table[new] = value
        if comment.startswith("#") and hasattr(table[new], "comment"):
            table[new].comment(comment[1:].strip())
        return
    table.value._insert_at(position, new, item)


def _comment_of(table: Any, key: str) -> str:
    """Return the comment of the line of ``key``, empty for a plain mapping."""
    # A tomlkit table hands out a boolean as a plain bool, which holds no comment.
    item = table.value.item(key) if _position(table, key) is not None else table.get(key)
    return getattr(getattr(item, "trivia", None), "comment", "") or ""


def _position(table: Any, key: str) -> int | None:
    """Return where a tomlkit table holds ``key``, or ``None`` for any other mapping."""
    found = getattr(getattr(getattr(table, "value", None), "_map", None), "get", None)
    where = found(key) if callable(found) else None
    return where if isinstance(where, int) and hasattr(table.value, "_insert_at") else None


def _scalar_item(value: Any, comment: str) -> Any:
    """Return *value* as a tomlkit item carrying *comment*, or ``None`` for a table or a list."""
    if not isinstance(value, int | float | str):
        return None
    item = tomlkit.item(value)
    if comment.startswith("#"):
        item.comment(comment[1:].strip())
    return item


def _raw_flow_process_solver(simulation: Any) -> tuple[str, str] | None:
    """Return the id and first solver of the first flow process, before validation."""
    if isinstance(simulation, Mapping):
        processes = simulation.get("process")
    else:
        processes = getattr(simulation, "process", None)
    if not isinstance(processes, list | tuple):
        return None
    for process in processes:
        if isinstance(process, Mapping):
            kind = str(process.get("kind", process.get("type", ""))).strip().lower()
            solvers = process.get("solvers")
            process_id = process.get("id")
        else:
            kind = str(getattr(process, "kind", "")).strip().lower()
            solvers = getattr(process, "solvers", None)
            process_id = getattr(process, "id", None)
        if kind != "flow" or not isinstance(solvers, list | tuple):
            continue
        names = [str(name).strip() for name in solvers if name and str(name).strip()]
        if names:
            return str(process_id or "flow"), names[0]
    return None


def document_path(form_path: str) -> str:
    """Return a form's path as the docs and the snapshots write it, with no list marker."""
    return form_path.replace("[*]", "").replace(".{*}", "")


__all__ = [
    "PRERELEASE_FORMS",
    "PRERELEASE_FORMS_FILENAME",
    "RETIRED_SGRID_KEYS",
    "RULES",
    "Layer",
    "MovedPath",
    "PrereleaseForm",
    "apply_edition",
    "optional_root_sections",
    "document_path",
    "edition_of",
    "fix_config_chain",
    "fix_config_file",
    "migrate_config_doc",
    "migrate_config_doc_on_load",
    "migrate_layers",
    "migrate_merged_doc",
    "migrate_sealed_config_doc",
    "moved_paths",
    "prerelease_keys",
    "refuse_prerelease_forms",
    "rewrite_dotted_path",
]
