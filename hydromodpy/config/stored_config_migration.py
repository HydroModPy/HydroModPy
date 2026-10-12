"""Migrate a configuration a run stored on disk before it is validated again.

A run keeps its configuration three times: the ``config_snapshot`` of its
catalog row, the ``runs/<name>/config.toml`` frozen in its run directory, and
the checkpoint ``resolved_config.json``. Each is a full dump of the model of
the version that made the run. ``hmp catalog rerun``, ``Project.rerun``,
``hmp run --resume`` and the checkpoint check read them back, so a key removed
from the schema since must not make a sealed run unreadable.

This module drops or moves those keys, in memory, and logs one line naming
what it did. It is called only on a stored payload. A file a user writes still
goes through the model alone, which refuses every key listed here and names
the key to write instead.

What is migrated, and why it is safe:

- the root ``[persistence]`` table: no run read it;
- ``[simulation.results.derived]`` and ``[simulation.results.budget]``, at the
  root and under every comparison or testbed overlay, whatever they hold: a run
  keeps its whole per-cell budget and rebuilds every derived field on read. The
  ``spatial_fields`` of a sealed config is false, so it is never carried to the
  new key;
- ``solver.backend``, when a flow process names the solver: the backend
  follows the process, which is the solver the run built. A stored backend
  that names another solver predates that rule and is dropped;
- ``calibration.outputs.<name>.cell_id`` when it is null: the model dumped it
  for every cell output;
- ``data.lake_abacus.id``, ``data.lake_bathymetry.id`` and ``data.lake_geometry.id``:
  no step read these names;
- every ``fill_method`` of a CSV forcing: no step read it;
- the ``site_selection`` keys removed from the schema. Three of them did the
  job of another key, and move to it the way the selection read them:
  ``criteria.observations.flow_station_mode`` and
  ``flow_station_max_distance_km`` fill ``criteria.observations.flow_station``
  where it held its default. ``strategy.candidate_mode`` is dropped: candidate
  generation always read ``outlets.candidate_mode``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.config.config_migration import drop_retired_results_tables
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.base.solver_config import solver_name_of_backend

_logger = get_logger(__name__)

_SITE_SELECTION_DROPS: tuple[tuple[tuple[str, ...], str], ...] = (
    ((), "random_seed"),
    (("dem",), "resolution_m"),
    (("dem",), "cache_policy"),
    (("criteria",), "ruleset"),
    (("criteria",), "hard_reject"),
    (("criteria",), "warning"),
    (("criteria",), "soft_score"),
    (("criteria",), "report_only"),
    (("criteria", "geology"), "prefer_diversity"),
    (("strategy",), "candidate_mode"),
)


def raw_flow_process_solver(simulation: Any) -> tuple[str, str] | None:
    """Return the id and first solver of the first flow process, before validation."""
    if isinstance(simulation, Mapping):
        processes = simulation.get("process")
    else:
        processes = getattr(simulation, "process", None)
    if not isinstance(processes, list | tuple):
        return None
    for process in processes:
        if isinstance(process, Mapping):
            kind = str(process.get("type", "")).strip().lower()
            solvers = process.get("solvers")
            process_id = process.get("id")
        else:
            kind = str(getattr(process, "type", "")).strip().lower()
            solvers = getattr(process, "solvers", None)
            process_id = getattr(process, "id", None)
        if kind != "flow" or not isinstance(solvers, list | tuple):
            continue
        names = [str(name).strip() for name in solvers if name and str(name).strip()]
        if names:
            return str(process_id or "flow"), names[0]
    return None


def migrate_stored_config(
    payload: Mapping[str, Any], *, source: str | Path | None = None
) -> dict[str, Any]:
    """Return a copy of a stored configuration that this version validates.

    *payload* is the configuration a run stored: a catalog snapshot, a frozen
    ``config.toml`` once parsed, or a checkpoint ``resolved_config.json``.
    The copy has the keys removed since dropped or moved. One log line names
    them; a payload already current logs nothing.
    """
    doc = copy.deepcopy(dict(payload))
    changes: list[str] = []
    if "persistence" in doc:
        del doc["persistence"]
        changes.append("persistence dropped (no run read the root table)")
    dropped = drop_retired_results_tables(doc)
    if dropped:
        changes.append(f"{', '.join(dropped)} dropped (every field is rebuilt on read)")
    changes.extend(_drop_the_stored_backend(doc))
    changes.extend(_drop_the_null_cell_ids(doc))
    changes.extend(_drop_the_unread_names(doc))
    changes.extend(_drop_the_fill_methods(doc))
    changes.extend(_migrate_site_selection(doc))
    if changes:
        where = str(source) if source is not None else "stored config"
        _logger.info(
            "%s: migrated %d key(s) removed since the run was stored: %s",
            where,
            len(changes),
            "; ".join(changes),
        )
    return doc


def _drop_the_stored_backend(doc: dict[str, Any]) -> list[str]:
    """Drop ``solver.backend`` when a flow process names the solver.

    The backend follows the process, so dropping it loses nothing when both
    agree, and lets an override of the process change the solver. Only a
    backend that named another solver is reported: it predates the rule, and
    the process named the solver the run built.
    """
    flow = raw_flow_process_solver(doc.get("simulation"))
    solver = doc.get("solver")
    if flow is None or not isinstance(solver, Mapping) or "backend" not in solver:
        return []
    process_id, process_solver = flow
    stored = solver_name_of_backend(solver.get("backend"))
    doc["solver"] = {key: value for key, value in solver.items() if key != "backend"}
    if stored is None or stored.lower() == process_solver.lower():
        return []
    return [
        f"solver.backend {stored!r} dropped (the flow process {process_id!r} ran "
        f"{process_solver!r}, which the backend now follows)"
    ]


def _drop_the_null_cell_ids(doc: dict[str, Any]) -> list[str]:
    """Drop the null ``cell_id`` the model dumped for every cell output.

    A value is left in place: the model refuses it and names what to write.
    """
    outputs = (doc.get("calibration") or {}).get("outputs")
    if not isinstance(outputs, Mapping):
        return []
    changes: list[str] = []
    for name, output in outputs.items():
        if isinstance(output, dict) and "cell_id" in output and output["cell_id"] is None:
            del output["cell_id"]
            changes.append(f"calibration.outputs.{name}.cell_id dropped (null)")
    return changes


def _drop_the_unread_names(doc: dict[str, Any]) -> list[str]:
    """Drop the ``id`` of the lake data sections, which no step read."""
    data = doc.get("data") or {}
    changes: list[str] = []
    for variable in ("lake_abacus", "lake_bathymetry", "lake_geometry"):
        section = data.get(variable)
        if isinstance(section, dict) and "id" in section:
            del section["id"]
            changes.append(f"data.{variable}.id dropped (no step read it)")
    return changes


def _drop_the_fill_methods(doc: Any) -> list[str]:
    """Drop every ``fill_method`` the model dumped for a CSV forcing; no step read it."""
    dropped = 0
    stack = [doc]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "fill_method" in node:
                del node["fill_method"]
                dropped += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return [f"{dropped} fill_method key(s) dropped (no step read them)"] if dropped else []


def _migrate_site_selection(doc: dict[str, Any]) -> list[str]:
    """Move or drop the ``site_selection`` keys removed from the schema."""
    selection = doc.get("site_selection")
    if not isinstance(selection, dict):
        return []
    changes = _fold_flow_station_keys(selection)
    for parents, key in _SITE_SELECTION_DROPS:
        table: Any = selection
        for parent in parents:
            table = table.get(parent) if isinstance(table, dict) else None
        if isinstance(table, dict) and key in table:
            del table[key]
            path = ".".join(("site_selection", *parents, key))
            changes.append(f"{path} dropped")
    return changes


def _fold_flow_station_keys(selection: dict[str, Any]) -> list[str]:
    """Move the flat flow-station keys into ``flow_station``, the way they were read.

    The selection read ``flow_station.mode`` and fell back to
    ``flow_station_mode`` while the former held ``report_only``. It read
    ``flow_station.max_station_to_outlet_distance_km`` and fell back to
    ``flow_station_max_distance_km`` while the former was unset.
    """
    observations = (selection.get("criteria") or {}).get("observations")
    if not isinstance(observations, dict):
        return []
    changes: list[str] = []
    detail = observations.get("flow_station")
    if not isinstance(detail, dict):
        detail = {}
    if "flow_station_mode" in observations:
        flat = observations.pop("flow_station_mode")
        prefix = "site_selection.criteria.observations"
        if detail.get("mode", "report_only") == "report_only" and flat not in (
            None,
            "report_only",
        ):
            detail["mode"] = flat
            changes.append(f"{prefix}.flow_station_mode -> flow_station.mode ({flat!r})")
        else:
            changes.append(f"{prefix}.flow_station_mode dropped (flow_station.mode is read)")
    if "flow_station_max_distance_km" in observations:
        flat = observations.pop("flow_station_max_distance_km")
        prefix = "site_selection.criteria.observations"
        if detail.get("max_station_to_outlet_distance_km") is None and flat is not None:
            detail["max_station_to_outlet_distance_km"] = flat
            changes.append(
                f"{prefix}.flow_station_max_distance_km -> "
                f"flow_station.max_station_to_outlet_distance_km ({flat!r})"
            )
        else:
            changes.append(
                f"{prefix}.flow_station_max_distance_km dropped "
                "(flow_station.max_station_to_outlet_distance_km is read)"
            )
    if changes:
        observations["flow_station"] = detail
    return changes


__all__ = ["migrate_stored_config", "raw_flow_process_solver"]
