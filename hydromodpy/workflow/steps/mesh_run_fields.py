"""Read the fields of earlier runs that the refinement zones of ``[mesh]`` name.

A zone that reads ``watertable_depth`` or ``seepage`` names an earlier run of
the project, the way ``[flow] restart_from`` does: a run name, with or
without its ``.vN``, or a full ``sim_id``. The run must be sealed, so the
mesh can record the ``sim_id`` it depends on. Its field is read in passes
over time and reduced to its minimum and maximum per cell, with the mesh of
that run, which is all the planner needs (:class:`RunFieldEnvelope`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.field_routing import DRN_TO_MVR_KEYS, find_drain_budget_key
from hydromodpy.core.state.paths import runs_dir_for
from hydromodpy.results.catalog.registration import run_dir_holding
from hydromodpy.results.derive.virtual_fields import (
    cell_area_from_mesh,
    outflow_drain_rows,
    watertable_depth_rows,
)
from hydromodpy.results.manifest import is_sealed, read_manifest
from hydromodpy.results.storage.attempt import run_dir_for_name
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.spatial.mesh.refinement.refinement_zones import RUN_FIELDS, RefinementZoneConfig
from hydromodpy.spatial.mesh.refinement.run_fields import RunFieldEnvelope

__all__ = ["read_run_field", "read_run_fields"]

STEPS_PER_PASS = 64
"""Time steps read at once, which bounds the memory of a long daily run."""

MM_PER_DAY = 1000.0 * 86400.0
"""mm/d in one m/s."""


def read_run_fields(
    project_root: Path, zones: Sequence[RefinementZoneConfig]
) -> dict[tuple[str, str], RunFieldEnvelope]:
    """The field of each ``(run, where)`` the *zones* name, each read once."""
    fields: dict[tuple[str, str], RunFieldEnvelope] = {}
    for zone in zones:
        if zone.where not in RUN_FIELDS or zone.run is None:
            continue
        key = (zone.run, zone.where)
        if key not in fields:
            fields[key] = read_run_field(project_root, zone.run, zone.where)
    return fields


def read_run_field(project_root: Path, reference: str, field: str) -> RunFieldEnvelope:
    """Return the extremes over time of *field* in the run *reference* names.

    ``watertable_depth`` is in metres. ``seepage`` is the drain outflow,
    drain-to-mover included, divided by the cell area, in mm/d. Raises
    :class:`ConfigError` when no sealed run of the project matches, or when
    the run holds no mesh or not the field.
    """
    run_dir = _run_dir(Path(project_root), reference)
    sim_id = _sim_id(run_dir, reference)
    store = run_dir / FIELDS_STORE_NAME
    if not store.is_dir():
        raise ConfigError(
            f"[[mesh.refinement_zone]] run = {reference!r}: {run_dir.name} has no "
            f"{FIELDS_STORE_NAME}."
        )
    with SimulationZarr(store) as handle:
        root = handle.root
        mesh = root.get("mesh")
        if mesh is None or "vertices" not in mesh or "face_node_connectivity" not in mesh:
            raise ConfigError(
                f"[[mesh.refinement_zone]] run = {reference!r}: {run_dir.name} stores no "
                "mesh, so its cells cannot be laid on the DEM."
            )
        vertices = np.asarray(mesh["vertices"][:], dtype=float)
        connectivity = np.asarray(mesh["face_node_connectivity"][:])
        n_cells = int(connectivity.shape[0])
        rows, unit, n_steps = _rows(root, field, n_cells, reference=reference, name=run_dir.name)
        minimum = np.full(n_cells, np.nan)
        maximum = np.full(n_cells, np.nan)
        for start in range(0, n_steps, STEPS_PER_PASS):
            block = np.asarray(rows(start, min(start + STEPS_PER_PASS, n_steps)), dtype=float)
            block = block.reshape(block.shape[0], -1)[:, :n_cells]
            minimum = np.fmin(minimum, np.fmin.reduce(block, axis=0))
            maximum = np.fmax(maximum, np.fmax.reduce(block, axis=0))
    return RunFieldEnvelope(
        sim_id=sim_id,
        run=run_dir.name,
        field=field,
        unit=unit,
        vertices=vertices,
        connectivity=connectivity,
        minimum=minimum,
        maximum=maximum,
    )


def _rows(
    root: object, field: str, n_cells: int, *, reference: str, name: str
) -> tuple[Callable[[int, int], np.ndarray], str, int]:
    """The rows of *field* over a step range, their unit, and the number of steps."""
    if field == "watertable_depth":
        if "head" not in root:
            raise ConfigError(
                f"[[mesh.refinement_zone]] run = {reference!r}: {name} stores no head, so it "
                "gives no water-table depth."
            )
        steps = int(root["head"].shape[0])
        return (lambda start, stop: watertable_depth_rows(root, start, stop)), "m", steps
    budget = root.get("budget")
    drains = (
        []
        if budget is None
        else [
            key
            for key in (find_drain_budget_key(budget), *DRN_TO_MVR_KEYS)
            if key is not None and key in budget
        ]
    )
    if not drains:
        raise ConfigError(
            f"[[mesh.refinement_zone]] run = {reference!r}: {name} kept no drain budget, so "
            "it gives no seepage. Run it with a drainage boundary and its budget kept."
        )
    area = cell_area_from_mesh(root, n_cells)
    if area is None:
        raise ConfigError(
            f"[[mesh.refinement_zone]] run = {reference!r}: the cell areas of {name} cannot "
            "be read from its mesh, so the seepage per area is undefined."
        )
    per_area = np.where(area > 0.0, MM_PER_DAY / np.where(area > 0.0, area, 1.0), np.nan)
    steps = int(budget[drains[0]].shape[0])
    return (lambda start, stop: outflow_drain_rows(root, start, stop) * per_area), "mm/d", steps


def _run_dir(project_root: Path, reference: str) -> Path:
    """The run directory a run name or a full sim_id names."""
    run_dir = run_dir_for_name(project_root, reference)
    if run_dir is not None:
        return run_dir
    rel_dir = run_dir_holding(project_root, reference)
    if rel_dir is not None:
        return project_root / rel_dir
    raise ConfigError(
        f"[[mesh.refinement_zone]] run = {reference!r} names no run under "
        f"{runs_dir_for(project_root)}: no run has that name and no run carries that sim_id. "
        "A frozen configuration names the run its mesh came from by sim_id, so a replay needs "
        "that run to be still there. Otherwise give a run name, with or without its .vN, or a "
        "full sim_id, and run the first pass before the run whose mesh reads it."
    )


def _sim_id(run_dir: Path, reference: str) -> str:
    """The sim_id of a sealed run: the mesh records the run it depends on by it."""
    if not is_sealed(run_dir):
        raise ConfigError(
            f"[[mesh.refinement_zone]] run = {reference!r}: {run_dir.name} is not sealed. A "
            "mesh depends on a finished run only."
        )
    try:
        return str(read_manifest(run_dir)["run"]["sim_id"])
    except (KeyError, TypeError) as exc:
        raise ConfigError(
            f"[[mesh.refinement_zone]] run = {reference!r}: the manifest of {run_dir.name} "
            "names no sim_id."
        ) from exc
