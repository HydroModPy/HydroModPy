"""One-shot TOML config migration for the simulation-management refactor.

Rewrites legacy ``[simulation]`` keys in place, preserving comments and layout:

- ``on_collision`` -> ``if_exists``
- ``run_id`` -> ``name`` (when ``name`` is not already set)
- ``[simulation.results.export]`` -> top-level ``[export]``
- ``solver_scratch`` and ``persistence.save_lock`` dropped: both drove
  nothing. The solver scratch directory is ``<project>/.hmp/scratch`` and
  the lockfile is written on every run.

This is a migration tool, not a backward-compat shim: it changes a file on disk
once. The runtime itself never accepts the old keys (``extra="forbid"``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit


def fix_config_file(path: str | Path) -> list[str]:
    """Rewrite legacy ``[simulation]`` keys in ``path`` in place.

    Returns the list of human-readable changes applied (empty when the file is
    already up to date). Raises :class:`FileNotFoundError` when the path is
    missing and :class:`tomlkit.exceptions.ParseError` on malformed TOML.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"No TOML file at {path}")

    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    changes = migrate_config_doc(doc)
    if changes:
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changes


def migrate_config_doc(doc: Any) -> list[str]:
    """Apply the legacy ``[simulation]`` key migrations to a parsed doc in place.

    Works on a plain ``dict`` (``tomllib``) or a ``tomlkit`` document, so
    ``fix_config_file`` can rewrite a file while a caller holding a parsed
    payload migrates it in memory. The runtime loader does **not** call this:
    ``extra="forbid"`` rejects a legacy key until ``hmp doctor --fix-config``
    has run. Returns the list of human-readable changes applied.
    """
    changes: list[str] = _drop_dead_result_options(doc)
    changes.extend(_flatten_boundary_conditions(doc))
    changes.extend(_drop_the_modflow6_time_grid(doc))

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


def _finish(doc: Any, changes: list[str]) -> list[str]:
    """Run the migrations that must see the promoted top-level tables."""
    changes.extend(_drop_dead_export_toggles(doc))
    return changes


def _drop_dead_export_toggles(doc: Any) -> list[str]:
    """Remove the two export toggles that gated nothing.

    ``head``, ``concentration`` and ``derived`` name variables the exporter can
    actually write. ``budget`` and ``pathlines`` named none, so they were removed
    from the schema; ``extra="forbid"`` then refuses a file that still sets them,
    which is why they have to be dropped rather than merely ignored.
    """
    variables = (doc.get("export") or {}).get("variables")
    if variables is None:
        return []
    changes: list[str] = []
    for dead in ("budget", "pathlines"):
        if dead in variables:
            del variables[dead]
            changes.append(f"export.variables.{dead} dropped (gated no export)")
    return changes


def _drop_the_modflow6_time_grid(doc: Any) -> list[str]:
    """Drop [modflow6.tgrid], removed from the schema as an inert mirror.

    The table mirrored a temporal discretization the MODFLOW 6 backend never
    read; ba4a75512 removed the field and the runtime now refuses the section
    outright, so a file still carrying it does not load at all. Its only key in
    this repository, firstpersteady, exists nowhere in the code.
    """
    changes: list[str] = []
    modflow6 = doc.get("modflow6")
    if modflow6 is None or "tgrid" not in modflow6:
        return changes
    del modflow6["tgrid"]
    changes.append("modflow6.tgrid dropped (removed from the schema, never read)")
    return changes


def _flatten_boundary_conditions(doc: Any) -> list[str]:
    """Rewrite ``[flow.bc.<kind>.<id>]`` as ``[flow.bc.<id>]`` with a kind field.

    A boundary is keyed by what it is; its kind is an attribute the registry
    declares and the table only has to carry when it departs from that default.
    The nested form said the same thing twice and let the two disagree.
    """
    changes: list[str] = []
    flow = doc.get("flow")
    if flow is None:
        return changes
    bc = flow.get("bc")
    if bc is None:
        return changes

    for kind in ("dirichlet", "cauchy", "robin"):
        nested = bc.get(kind)
        if nested is None:
            continue
        for bc_id in list(nested):
            entry = nested[bc_id]
            if bc_id in bc:
                changes.append(f"flow.bc.{kind}.{bc_id} dropped (flow.bc.{bc_id} already set)")
                continue
            try:
                entry["kind"] = kind
                entry.pop("id", None)
            except (TypeError, AttributeError):
                pass
            bc[bc_id] = entry
            changes.append(f"flow.bc.{kind}.{bc_id} -> flow.bc.{bc_id} (kind = {kind!r})")
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


__all__ = ["fix_config_file", "migrate_config_doc"]
