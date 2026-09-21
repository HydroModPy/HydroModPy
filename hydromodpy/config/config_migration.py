"""One-shot TOML config migration for the simulation-management refactor.

Rewrites legacy ``[simulation]`` keys in place, preserving comments and layout:

- ``on_collision`` -> ``if_exists``
- ``run_id`` -> ``name`` (when ``name`` is not already set)
- ``[simulation.results.export]`` -> top-level ``[export]``
- ``[export.variables]`` boolean submodel (``head``, ``concentration``,
  ``derived``, and the dead ``budget``/``pathlines`` toggles) -> flat
  ``export.variables`` list of the names it turned on
- ``export.times`` -> ``export.time`` (when ``time`` is not already set)
- ``[modflow6.tgrid]`` and ``[modflownwt.tgrid]`` dropped: neither backend
  read them, at the root and under a comparison or testbed overlay
- ``solver_scratch`` and ``persistence.save_lock`` dropped: both drove
  nothing. The solver scratch directory is ``<project>/.hmp/scratch`` and
  the lockfile is written on every run.

This is a migration tool, not a backward-compat shim: the runtime model itself
never accepts the old keys (``extra="forbid"``). ``migrate_config_doc`` is the
one pure document-to-document transform; two callers wrap it. ``fix_config_file``
(reached through ``hmp doctor --fix-config``) rewrites a file on disk once, so a
project TOML catches up for good. ``migrate_config_doc_on_load`` runs the same
transform in memory on a payload already parsed by a caller, without touching
the file it came from, and logs what it changed - meant to be called from
``HydroModPyConfig.from_toml`` on the raw payload, before validation, so a
config written for an earlier schema still loads without the doctor having
run on it first. As of this module, that call site is not yet wired in.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomlkit

from hydromodpy.core.logging import get_logger

_logger = get_logger(__name__)

_SOLVER_SECTIONS = ("modflow6", "modflownwt")


def fix_config_file(path: str | Path) -> list[str]:
    """Rewrite legacy ``[simulation]`` keys in ``path`` in place.

    Returns the list of human-readable changes applied (empty when the file is
    already up to date). Raises :class:`FileNotFoundError` when the path is
    missing and :class:`tomlkit.exceptions.ParseError` on malformed TOML.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"No TOML file at {path}")

    # utf-8-sig: several configs in this repository carry a BOM, and tomlkit
    # reads it as an empty key on line 1, so the doctor could not fix them.
    doc = tomlkit.parse(path.read_text(encoding="utf-8-sig"))
    changes = migrate_config_doc(doc)
    if changes:
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changes


def migrate_config_doc(doc: Any) -> list[str]:
    """Apply the legacy ``[simulation]`` key migrations to a parsed doc in place.

    Works on a plain ``dict`` (``tomllib``) or a ``tomlkit`` document, so
    ``fix_config_file`` can rewrite a file while ``migrate_config_doc_on_load``
    migrates an in-memory payload for the read path. Returns the list of
    human-readable changes applied.
    """
    changes: list[str] = _drop_dead_result_options(doc)
    changes.extend(_flatten_boundary_conditions(doc))
    changes.extend(_drop_the_solver_time_grids(doc))

    simulation = doc.get("simulation")
    if simulation is None:
        return _finish(doc, changes)

    if "on_collision" in simulation:
        value = simulation["on_collision"]
        if "if_exists" not in simulation:
            simulation["if_exists"] = value
            changes.append(f"simulation.on_collision -> if_exists ({value!r})")
        else:
            changes.append("simulation.on_collision dropped (if_exists already set)")
        del simulation["on_collision"]

    if "run_id" in simulation:
        value = simulation["run_id"]
        if not simulation.get("name"):
            simulation["name"] = value
            changes.append(f"simulation.run_id -> name ({value!r})")
        else:
            changes.append("simulation.run_id dropped (name already set)")
        del simulation["run_id"]

    changes.extend(_promote_export(doc, simulation))
    return _finish(doc, changes)


def migrate_config_doc_on_load(doc: Any, *, source: str | Path | None = None) -> list[str]:
    """Apply every migration to *doc* in memory, for a config being read, not fixed.

    Meant for ``HydroModPyConfig.from_toml``: called on the freshly parsed
    payload, before Pydantic validation, so a config written for an earlier
    schema still loads. Never touches the file *doc* came from - only
    ``fix_config_file`` writes to disk. Logs one line naming what changed and
    that ``hmp doctor`` persists it; says nothing when the document was
    already current.
    """
    changes = migrate_config_doc(doc)
    if changes:
        where = f"{source}" if source is not None else "config"
        _logger.info(
            "%s: migrated %d legacy key(s) on load, not persisted to disk "
            "(run `hmp doctor --fix-config %s` to persist): %s",
            where,
            len(changes),
            source if source is not None else "<path>",
            "; ".join(changes),
        )
    return changes


def _finish(doc: Any, changes: list[str]) -> list[str]:
    """Run the migrations that must see the promoted top-level tables."""
    changes.extend(_migrate_export_variables(doc))
    changes.extend(_rename_export_times(doc))
    return changes


def _migrate_export_variables(doc: Any) -> list[str]:
    """Rewrite the ``[export.variables]`` boolean submodel as a flat list.

    ``[export.variables]`` used to be a table of booleans: ``head`` and
    ``derived`` (expanding to ``watertable_elevation``, ``watertable_depth``,
    ``seepage_mask``) and ``concentration`` gated a real export; ``budget`` and
    ``pathlines`` gated nothing and were already dead. The schema now carries
    the active set directly as ``export.variables = [...]``, so the table is
    expanded into the names it turned on; the dead toggles simply do not
    survive the expansion.
    """
    export = doc.get("export")
    if export is None:
        return []
    variables = export.get("variables")
    if variables is None or not isinstance(variables, Mapping):
        return []
    names: list[str] = []
    if variables.get("head", False):
        names.append("head")
    if variables.get("concentration", False):
        names.append("concentration")
    if variables.get("derived", False):
        names.extend(["watertable_elevation", "watertable_depth", "seepage_mask"])
    export["variables"] = names
    return [f"export.variables (boolean table) -> list {names!r}"]


def _rename_export_times(doc: Any) -> list[str]:
    """Rename ``export.times`` to ``export.time``, matching ``[[export.artifacts]]``."""
    export = doc.get("export")
    if export is None or "times" not in export:
        return []
    value = export["times"]
    if "time" not in export:
        export["time"] = value
        changes = [f"export.times -> export.time ({value!r})"]
    else:
        changes = ["export.times dropped (export.time already set)"]
    del export["times"]
    return changes


def _drop_the_solver_time_grids(doc: Any) -> list[str]:
    """Drop ``[modflow6.tgrid]`` and ``[modflownwt.tgrid]``, both removed.

    Neither backend ever read the section back. MODFLOW 6 lost it first and the
    runtime refuses it outright, so a file still carrying it does not load at
    all. MODFLOW-NWT kept it longer as a mirror the launcher overwrote from
    ``[simulation.time]``, which made it worse than inert: a file could declare
    ``itmuni = "days"`` next to a run executing in seconds.

    A comparison or testbed file patches its solver sections under ``overlay``,
    and those reach the same loader, so the root alone is not enough.
    """
    changes: list[str] = []
    for path, table in _solver_tables(doc):
        if "tgrid" not in table:
            continue
        del table["tgrid"]
        changes.append(f"{path}.tgrid dropped (removed from the schema, never read)")
    return changes


def _solver_tables(doc: Any) -> list[tuple[str, Any]]:
    """Return every ``(path, table)`` pair holding a MODFLOW solver section."""
    tables: list[tuple[str, Any]] = [(name, doc.get(name)) for name in _SOLVER_SECTIONS]
    for owner, member in (("comparison", "simulation"), ("testbed", "case")):
        entries = (doc.get(owner) or {}).get(member)
        if entries is None:
            continue
        if isinstance(entries, Mapping):
            entries = [entries]
        for index, entry in enumerate(entries):
            overlay = (entry or {}).get("overlay")
            if overlay is None:
                continue
            for name in _SOLVER_SECTIONS:
                tables.append((f"{owner}.{member}[{index}].overlay.{name}", overlay.get(name)))
    return [(path, table) for path, table in tables if table is not None]


def _flow_tables(doc: Any) -> list[tuple[str, Any]]:
    """Return every ``(path, table)`` pair holding a flow section.

    A comparison or testbed file carries no top-level ``[flow]``: it patches
    one per case, under ``overlay``. Those overlays reach the same loader and
    are refused by the same rule, so a migration that only looked at the root
    left the file broken and reported nothing to fix.
    """
    tables = [("flow", doc.get("flow"))]
    for owner, member in (("comparison", "simulation"), ("testbed", "case")):
        entries = (doc.get(owner) or {}).get(member)
        if entries is None:
            continue
        if isinstance(entries, Mapping):
            entries = [entries]
        for index, entry in enumerate(entries):
            overlay = (entry or {}).get("overlay")
            if overlay is None:
                continue
            tables.append((f"{owner}.{member}[{index}].overlay.flow", overlay.get("flow")))
    return [(path, table) for path, table in tables if table is not None]


def _flatten_boundary_conditions(doc: Any) -> list[str]:
    """Rewrite ``[flow.bc.<kind>.<id>]`` as ``[flow.bc.<id>]`` with a kind field.

    A boundary is keyed by what it is; its kind is an attribute the registry
    declares and the table only has to carry when it departs from that default.
    The nested form said the same thing twice and let the two disagree.
    """
    changes: list[str] = []
    for prefix, flow in _flow_tables(doc):
        bc = flow.get("bc")
        if bc is None:
            continue
        for kind in ("dirichlet", "cauchy", "robin"):
            nested = bc.get(kind)
            if nested is None:
                continue
            for bc_id in list(nested):
                entry = nested[bc_id]
                if bc_id in bc:
                    changes.append(
                        f"{prefix}.bc.{kind}.{bc_id} dropped ({prefix}.bc.{bc_id} already set)"
                    )
                    continue
                try:
                    entry["kind"] = kind
                    entry.pop("id", None)
                except (TypeError, AttributeError):
                    # A scalar or list under a family key is not a boundary
                    # payload. The loader refuses it with its own message, so
                    # carry it across unchanged rather than mask that error here.
                    pass
                bc[bc_id] = entry
                changes.append(
                    f"{prefix}.bc.{kind}.{bc_id} -> {prefix}.bc.{bc_id} (kind = {kind!r})"
                )
            del bc[kind]
    return changes


def _persistence_tables(doc: Any) -> list[tuple[str, Any]]:
    """Return every ``(path, table)`` pair holding a persistence section."""
    results = (doc.get("simulation") or {}).get("results")
    candidates = [
        ("persistence", doc.get("persistence")),
        ("simulation.results.persistence", (results or {}).get("persistence")),
        ("calibration.persistence", (doc.get("calibration") or {}).get("persistence")),
    ]
    return [(path, table) for path, table in candidates if table is not None]


def _drop_dead_result_options(doc: Any) -> list[str]:
    """Remove the two result options that never drove anything."""
    changes: list[str] = []
    results = (doc.get("simulation") or {}).get("results")
    if results is not None and "solver_scratch" in results:
        del results["solver_scratch"]
        changes.append("simulation.results.solver_scratch dropped (never read)")
    for path, persistence in _persistence_tables(doc):
        if "save_lock" in persistence:
            del persistence["save_lock"]
            changes.append(f"{path}.save_lock dropped (never read)")
    return changes


def _promote_export(doc: Any, simulation: Any) -> list[str]:
    """Move ``[simulation.results.export]`` to the top-level ``[export]`` table."""
    results = simulation.get("results")
    if results is None or "export" not in results:
        return []
    if "export" in doc:
        # A top-level [export] already exists: drop the buried duplicate.
        del results["export"]
        return ["simulation.results.export dropped (top-level [export] already set)"]
    export_value = results["export"]
    if hasattr(export_value, "unwrap"):
        doc["export"] = tomlkit.item(export_value.unwrap())
    else:
        doc["export"] = export_value
    del results["export"]
    return ["simulation.results.export -> [export]"]


__all__ = ["fix_config_file", "migrate_config_doc", "migrate_config_doc_on_load"]
