"""Simulation registration into the catalog.

``register_simulation`` is the entry point that allocates a new ``sim_id``
row, applies on-collision rules (replace / fail / version), computes a
human-readable storage basename, and creates the initial :class:`SimulationZarr`
when mesh dimensions are known. The rest of the write surface
(``write_parameters``, ``write_timeseries`` ...) lives in
:mod:`hydromodpy.results.catalog.writes`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.results.catalog.audit import audited, emit_audit_event
from hydromodpy.results.catalog.constants import (
    solver_category as _resolve_solver_category,
)
from hydromodpy.results.catalog.constants import (
    validate_solver_code as _validate_solver_code,
)
from hydromodpy.results.catalog.ports import CatalogBackend
from hydromodpy.results.catalog.storage_paths import build_storage_basename
from hydromodpy.results.storage_contract import SIMULATIONS_DIRNAME, ZARR_SUFFIX
from hydromodpy.results.zarr_store import SimulationZarr, _windows_long_path

logger = get_logger(__name__)

OnCollisionMode = Literal["replace", "fail", "version"]


def _short_id(sim_id: str | UUID) -> str:
    return str(sim_id)[:8]


def _coerce_timestamp(value: Any) -> Any:
    """Return a value suitable for a ``TIMESTAMPTZ`` column."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value
    return str(value)


def _next_available_version(
    backend: CatalogBackend,
    project: str,
    base_name: str,
) -> str:
    """Return ``base_name.v{n}`` where ``n`` is the smallest free integer >= 2."""
    rows = backend.fetch_all(
        "SELECT name FROM simulations WHERE project = ? AND (name = ? OR name LIKE ?)",
        [project, base_name, base_name + ".v%"],
    )
    existing = {r[0] for r in rows}
    n = 2
    while f"{base_name}.v{n}" in existing:
        n += 1
    return f"{base_name}.v{n}"


def _epsg_from_crs(crs: str) -> int | None:
    """Best-effort extraction of an EPSG code from a CRS string."""
    if not crs:
        return None
    upper = crs.upper().strip()
    if upper.startswith("EPSG:"):
        try:
            return int(upper.split(":", 1)[1])
        except ValueError:
            return None
    try:
        from pyproj import CRS as _CRS

        return _CRS.from_user_input(crs).to_epsg()
    except Exception:
        return None


class DuplicateSimulationNameError(ValueError):
    """Raised when on_collision='fail' and a (project, name) pair already exists."""

    def __init__(self, project: str, name: str, existing_sim_id: str) -> None:
        self.project = project
        self.name = name
        self.existing_sim_id = existing_sim_id
        super().__init__(
            f"Simulation '{name}' already exists in project '{project}' "
            f"(existing sim_id {_short_id(existing_sim_id)}). "
            f"Use on_collision='replace' or 'version' to proceed."
        )


@dataclass(frozen=True)
class RegistrationResult:
    """Outcome of :meth:`SimulationCatalog.register_simulation`.

    Attributes
    ----------
    sim_id
        UUID of the newly registered simulation.
    name
        Final name assigned to the simulation (may differ from the requested
        name when ``on_collision='version'`` auto-suffixes it).
    zarr
        The freshly created :class:`SimulationZarr`, or ``None`` when mesh
        dimensions are not yet known at registration time.
    replaced_sim_id
        UUID of a previously named simulation whose name was cleared by a
        soft-replace. ``None`` when no collision occurred.
    """

    sim_id: str
    name: str | None
    zarr: SimulationZarr | None
    replaced_sim_id: str | None


class RegistrationMixin:
    """``register_simulation`` for :class:`SimulationCatalog`."""

    @audited("sim.register", payload_keys=("solver", "name"))
    @with_lock_retry()
    def register_simulation(
        self,
        sim_id: str | UUID,
        project: str,
        solver: str,
        *,
        name: str | None = None,
        on_collision: OnCollisionMode = "replace",
        solver_category: str | None = None,
        flow_regime: str | None = None,
        config: dict | None = None,
        config_snapshot: dict | None = None,
        n_cells: int | None = None,
        n_layers: int | None = None,
        n_timesteps: int | None = None,
        cell_types: list[str] | None = None,
        bbox: list[float] | tuple[float, float, float, float] | None = None,
        crs: str | None = None,
        crs_epsg: int | None = None,
        period_start: Any = None,
        period_end: Any = None,
        time_unit: str | None = None,
        parent_sim_id: str | UUID | None = None,
        mesh_hash: str | None = None,
        mesh_type: str | None = None,
        mesh_topology: str | None = None,
        geographic_fingerprint: str | None = None,
        tags: list[str] | None = None,
        notes: str | None = None,
        config_source: str | Path | None = None,
        description: str | None = None,
        scientific_objective: str | None = None,
        contact_email: str | None = None,
        doi: str | None = None,
        study_area_name: str | None = None,
        outlet_x: float | None = None,
        outlet_y: float | None = None,
    ) -> RegistrationResult:
        sid = str(sim_id)
        replaced_sid: str | None = None
        final_name = name
        zarr_obj: SimulationZarr | None = None
        zarr_tmp: Path | None = None
        zarr_final: Path | None = None
        storage_basename: str | None = None

        try:
            # Transactional block driven by the backend port. The surrounding
            # try/except still owns the filesystem rollback (zarr_tmp /
            # zarr_final), so we open the port transaction inside the
            # try block and let ``CatalogBackend.transaction()`` handle the
            # rollback on exception before the outer cleanup runs.
            with self._backend.transaction():
                if name:
                    existing = self._backend.fetch_one(
                        "SELECT sim_id FROM simulations WHERE project = ? AND name = ?",
                        [project, name],
                    )
                    if existing:
                        existing_sid = str(existing[0])
                        if on_collision == "fail":
                            raise DuplicateSimulationNameError(project, name, existing_sid)
                        if on_collision == "replace":
                            self._backend.execute(
                                "UPDATE simulations SET name = NULL WHERE sim_id = ?",
                                [existing_sid],
                            )
                            replaced_sid = existing_sid
                            logger.info(
                                "Reassigning name '%s' in project '%s' "
                                "(previous sim %s kept, name cleared)",
                                name,
                                project,
                                _short_id(existing_sid),
                            )
                        elif on_collision == "version":
                            final_name = _next_available_version(self._backend, project, name)
                            logger.info(
                                "Auto-versioned '%s' -> '%s' in project '%s'",
                                name,
                                final_name,
                                project,
                            )
                        else:
                            raise ValueError(f"Unknown on_collision mode: '{on_collision}'")

                if solver_category is None:
                    solver_category = _resolve_solver_category(solver)
                solver_code_v2 = _validate_solver_code(solver)

                config_json = json.dumps(config) if config else None
                snapshot_source = config_snapshot if config_snapshot is not None else config
                snapshot_json = json.dumps(snapshot_source) if snapshot_source is not None else None
                config_hash = None
                if config:
                    config_hash = hashlib.sha256(
                        json.dumps(config, sort_keys=True).encode()
                    ).hexdigest()

                bbox_xmin = bbox_ymin = bbox_xmax = bbox_ymax = None
                if bbox is not None and len(bbox) == 4:
                    bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax = (float(v) for v in bbox)

                crs_wkt = crs
                if crs_epsg is None and crs:
                    crs_epsg = _epsg_from_crs(crs)

                topology = mesh_topology
                p_start = _coerce_timestamp(period_start)
                p_end = _coerce_timestamp(period_end)

                storage_basename = build_storage_basename(project, final_name, sid)
                zarr_path = f"{SIMULATIONS_DIRNAME}/{storage_basename}{ZARR_SUFFIX}"
                parent_sid = str(parent_sim_id) if parent_sim_id else None
                config_source_str = str(config_source) if config_source is not None else None

                if n_cells is not None and n_layers is not None:
                    zarr_final = self._workspace / zarr_path
                    _windows_long_path(zarr_final.parent).mkdir(parents=True, exist_ok=True)
                    zarr_tmp = zarr_final.with_name(f".{_short_id(sid)}.staging.zarr")
                    if zarr_final.exists():
                        raise FileExistsError(f"Zarr store already exists: {zarr_final}")
                    if zarr_tmp.exists():
                        shutil.rmtree(_windows_long_path(zarr_tmp))
                    staged = SimulationZarr.create(
                        zarr_tmp,
                        n_cells=n_cells,
                        n_layers=n_layers,
                        cell_types=cell_types,
                        geographic_fingerprint=geographic_fingerprint,
                    )
                    staged.close()
                    _windows_long_path(zarr_tmp).rename(_windows_long_path(zarr_final))

                self._backend.execute(
                    """INSERT INTO simulations
                       (sim_id, name, project,
                        solver_id, status_id, flow_regime_id, mesh_topology_id,
                        n_cells, n_layers, n_timesteps,
                        bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax,
                        crs_wkt, crs_epsg,
                        period_start, period_end, time_unit,
                        config_toml, config_snapshot, config_hash, config_source,
                        zarr_path, storage_basename, parent_sim_id, mesh_hash,
                        geographic_fingerprint, notes,
                        description, scientific_objective, contact_email, doi,
                        study_area_name, outlet_x, outlet_y)
                       VALUES (?, ?, ?,
                               (SELECT id FROM solvers WHERE code = ?),
                               (SELECT id FROM statuses WHERE code = ?),
                               (SELECT id FROM flow_regimes WHERE code = ?),
                               (SELECT id FROM mesh_topologies WHERE code = ?),
                               ?, ?, ?, ?, ?, ?, ?, ?, ?,
                               ?, ?, ?, ?, ?, ?, ?,
                               ?, ?, ?, ?,
                               ?, ?,
                               ?, ?, ?, ?,
                               ?, ?, ?)""",
                    [
                        sid,
                        final_name,
                        project,
                        solver_code_v2,
                        "running",
                        flow_regime,
                        topology,
                        n_cells,
                        n_layers,
                        n_timesteps,
                        bbox_xmin,
                        bbox_ymin,
                        bbox_xmax,
                        bbox_ymax,
                        crs_wkt,
                        crs_epsg,
                        p_start,
                        p_end,
                        time_unit,
                        config_json,
                        snapshot_json,
                        config_hash,
                        config_source_str,
                        zarr_path,
                        storage_basename,
                        parent_sid,
                        mesh_hash,
                        geographic_fingerprint,
                        notes,
                        description,
                        scientific_objective,
                        contact_email,
                        doi,
                        study_area_name,
                        outlet_x,
                        outlet_y,
                    ],
                )
                if tags:
                    for tag in tags:
                        self._backend.execute(
                            "INSERT INTO tags (sim_id, tag) VALUES (?, ?)",
                            [sid, str(tag)],
                        )
                        try:
                            emit_audit_event(
                                self._db,
                                event_type="sim.tag_add",
                                sim_id=sid,
                                project=project,
                                payload={"tag": str(tag)},
                            )
                        except Exception as exc:  # noqa: BLE001 - audit must not raise
                            logger.warning("audit emission failed for sim.tag_add: %s", exc)
        except Exception:
            self._paths.forget(sid)
            if zarr_tmp is not None and zarr_tmp.exists():
                shutil.rmtree(zarr_tmp)
            if zarr_final is not None and zarr_final.exists():
                shutil.rmtree(zarr_final)
            raise

        if storage_basename is not None:
            self._paths.cache_basename(sid, storage_basename)
        if zarr_final is not None:
            zarr_obj = self._track_zarr_handle(SimulationZarr(zarr_final))
        return RegistrationResult(
            sim_id=sid,
            name=final_name,
            zarr=zarr_obj,
            replaced_sim_id=replaced_sid,
        )
