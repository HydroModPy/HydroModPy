"""Simulation registration into the catalog.

``register_simulation`` is the entry point that allocates a new ``sim_id``
row, applies on-collision rules (replace / fail / version), derives the run
directory from the final run name, and creates the initial
:class:`SimulationZarr` in it when mesh dimensions are known. The rest of the
write surface (``write_parameters``, ``write_timeseries`` ...) lives in
:mod:`hydromodpy.results.catalog.writes`.

The Zarr store is created at its final path, never staged: readers open
``runs/<name>/fields.zarr`` while the run is still solving.

Steady period convention
------------------------
A steady flow run may legitimately declare no ``[simulation.time]`` window:
its solution is time-invariant, so there is nothing to span. Leaving the
period empty would make it indistinguishable from a transient run whose
bounds were lost, and would leave the manifest with an empty period block.
Such a run is therefore registered with the degenerate period
``period_start == period_end == started_at``: zero length says "no simulated
duration", and the reference date is the only date the run can honestly
claim, the instant it was computed. A steady run that *does* declare a
window keeps the window it declared.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import RUNS_DIRNAME, to_workspace_relative
from hydromodpy.results.catalog.audit import audited, emit_audit_event
from hydromodpy.results.catalog.constants import (
    solver_category as _resolve_solver_category,
)
from hydromodpy.results.catalog.constants import (
    validate_solver_code as _validate_solver_code,
)
from hydromodpy.results.catalog.ports import CatalogBackend
from hydromodpy.results.catalog.storage_paths import run_dirname
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.zarr_store import SimulationZarr, _windows_long_path

logger = get_logger(__name__)

IfExistsMode = Literal["replace", "fail", "version"]

STEADY_FLOW_REGIME = "steady"
"""Flow regime whose runs may carry a degenerate period (see module docstring)."""

_VERSION_SUFFIX_RE = re.compile(r"\.v(\d+)$")


def split_stem_version(name: str) -> tuple[str, int | None]:
    """Split ``cheze_baseline.v3`` into ``("cheze_baseline", 3)``.

    A bare name returns ``(name, None)``.
    """
    match = _VERSION_SUFFIX_RE.search(name)
    if match:
        return name[: match.start()], int(match.group(1))
    return name, None


_MEMORABLE_ADJECTIVES = (
    "brisk",
    "calm",
    "bright",
    "swift",
    "quiet",
    "bold",
    "keen",
    "warm",
    "clear",
    "deep",
    "fair",
    "lush",
    "mild",
    "wise",
    "amber",
    "azure",
)
_MEMORABLE_NOUNS = (
    "heron",
    "otter",
    "marten",
    "willow",
    "alder",
    "brook",
    "fern",
    "moss",
    "spring",
    "delta",
    "ridge",
    "meadow",
    "harrier",
    "kestrel",
    "ibis",
    "tern",
)


def _memorable_name(sim_id: str) -> str:
    """Return a deterministic ``adjective_noun`` slug seeded from ``sim_id``.

    Guarantees a programmatic run without an explicit name is still pronounceable
    and never addressable by hex alone.
    """
    digest = int(hashlib.sha256(str(sim_id).encode()).hexdigest(), 16)
    adjective = _MEMORABLE_ADJECTIVES[digest % len(_MEMORABLE_ADJECTIVES)]
    noun = _MEMORABLE_NOUNS[(digest // len(_MEMORABLE_ADJECTIVES)) % len(_MEMORABLE_NOUNS)]
    return f"{adjective}_{noun}"


def _short_id(sim_id: str | UUID) -> str:
    return str(sim_id)[:8]


def _coerce_timestamp(value: Any) -> Any:
    """Return a value suitable for a ``TIMESTAMPTZ`` column."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value
    return str(value)


def portable_config_source(project_root: Path, config_source: str | Path | None) -> str | None:
    """Return ``config_source`` as stored in the index: portable when it can be.

    A configuration that lives inside the project is recorded relative to the
    project root (``project.toml``, ``configs/winter.toml``), so a project that
    is copied or moved still recognises its own runs. A configuration kept
    outside the project has no project-relative form and is recorded as the
    absolute path it is; the leading separator tells the two apart.
    """
    if config_source is None:
        return None
    try:
        return to_workspace_relative(project_root, config_source)
    except ValueError:
        return str(config_source)


def _resolve_registration_name(
    backend: CatalogBackend,
    project: str,
    requested: str,
    if_exists: IfExistsMode,
) -> tuple[str, str, int, str | None]:
    """Resolve the final ``(name, name_stem, version_int, replaced_sid)``.

    Versioning is keyed on ``name_stem`` (the requested name with any trailing
    ``.vN`` stripped). A registered name belongs to its run for good: a sealed
    run is never renamed, so the bare stem *is* version 1 forever and every
    later run of that stem gets the next free ``stem.vN``.

    - ``version`` (default): mint the next free version behind the live runs of
      the stem.
    - ``replace``: trash the colliding predecessor, which keeps its name and
      version (its stored run stays addressable and restorable), then mint the
      next free version for the incoming run.
    - ``fail``: raise :class:`DuplicateSimulationNameError` when a live run
      already holds the stem.

    Trashed rows still count when minting a version, because a trashed run may
    keep its name and ``UNIQUE (project, name)`` spans every row.
    """
    stem, requested_version = split_stem_version(requested)
    rows = backend.fetch_all(
        "SELECT CAST(sim_id AS VARCHAR), name, version_int, "
        "status_id = (SELECT id FROM statuses WHERE code = 'trashed') "
        "FROM simulations WHERE project = ? AND name_stem = ?",
        [project, stem],
    )
    live = [r for r in rows if not r[3]]
    taken = {r[1] for r in rows if r[1]}
    if not live and requested not in taken:
        return requested, stem, (requested_version or 1), None

    if if_exists == "fail" and live:
        raise DuplicateSimulationNameError(project, requested, str(live[0][0]))

    replaced_sid: str | None = None
    if if_exists == "replace" and live:
        target = next((r for r in live if r[1] == requested), None)
        if target is None:
            target = max(live, key=lambda r: r[2] or 1)
        backend.execute(
            "UPDATE simulations SET original_name = COALESCE(original_name, name), "
            "original_status_id = COALESCE(original_status_id, status_id), "
            "trashed_at = current_timestamp, updated_at = current_timestamp, "
            "status_id = (SELECT id FROM statuses WHERE code = 'trashed') "
            "WHERE sim_id = ?",
            [target[0]],
        )
        replaced_sid = str(target[0])

    next_version = max((r[2] or 1) for r in rows) + 1
    return f"{stem}.v{next_version}", stem, next_version, replaced_sid


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
    """Raised when if_exists='fail' and a (project, name) pair already exists."""

    def __init__(self, project: str, name: str, existing_sim_id: str) -> None:
        self.project = project
        self.name = name
        self.existing_sim_id = existing_sim_id
        super().__init__(
            f"Simulation '{name}' already exists in project '{project}' "
            f"(existing sim_id {_short_id(existing_sim_id)}). "
            f"Use if_exists='replace' or 'version' to proceed."
        )


@dataclass(frozen=True)
class RegistrationResult:
    """Outcome of :meth:`Catalog.register_simulation`.

    Attributes
    ----------
    sim_id
        UUID of the newly registered simulation.
    name
        Final name assigned to the simulation (differs from the requested name
        whenever the stem is already taken and a ``.vN`` is minted).
    zarr
        The freshly created :class:`SimulationZarr`, or ``None`` when mesh
        dimensions are not yet known at registration time.
    replaced_sim_id
        UUID of the predecessor trashed by ``if_exists='replace'``. It keeps
        its own name and version. ``None`` when no collision occurred.
    """

    sim_id: str
    name: str | None
    zarr: SimulationZarr | None
    replaced_sim_id: str | None


class RegistrationMixin:
    """``register_simulation`` for :class:`Catalog`."""

    @audited("sim.register", payload_keys=("solver", "name"))
    @with_lock_retry()
    def register_simulation(
        self,
        sim_id: str | UUID,
        project: str,
        solver: str,
        *,
        name: str | None = None,
        if_exists: IfExistsMode = "version",
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
        requested_name = name if name else _memorable_name(sid)
        final_name = requested_name
        name_stem, _ = split_stem_version(requested_name)
        version_int = 1
        zarr_obj: SimulationZarr | None = None
        zarr_final: Path | None = None
        dirname: str | None = None

        try:
            # Transactional block driven by the backend port. The surrounding
            # try/except still owns the filesystem rollback (zarr_tmp /
            # zarr_final), so we open the port transaction inside the
            # try block and let ``CatalogBackend.transaction()`` handle the
            # rollback on exception before the outer cleanup runs.
            with self._backend.transaction():
                final_name, name_stem, version_int, replaced_sid = _resolve_registration_name(
                    self._backend, project, requested_name, if_exists
                )
                if replaced_sid is not None:
                    logger.info(
                        "Replacing '%s' in project '%s' with '%s' (previous sim %s trashed)",
                        requested_name,
                        project,
                        final_name,
                        _short_id(replaced_sid),
                    )
                elif final_name != requested_name:
                    logger.info(
                        "Auto-versioned '%s' -> '%s' in project '%s'",
                        requested_name,
                        final_name,
                        project,
                    )

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

                dirname = run_dirname(final_name)
                zarr_path = f"{RUNS_DIRNAME}/{dirname}/{FIELDS_STORE_NAME}"
                parent_sid = str(parent_sim_id) if parent_sim_id else None
                config_source_str = portable_config_source(self._workspace, config_source)

                if n_cells is not None and n_layers is not None:
                    zarr_final = self._workspace / zarr_path
                    if zarr_final.exists():
                        raise FileExistsError(f"Zarr store already exists: {zarr_final}")
                    _windows_long_path(zarr_final.parent).mkdir(parents=True, exist_ok=True)
                    created = SimulationZarr.create(
                        zarr_final,
                        n_cells=n_cells,
                        n_layers=n_layers,
                        cell_types=cell_types,
                        geographic_fingerprint=geographic_fingerprint,
                    )
                    created.close()

                self._backend.execute(
                    """INSERT INTO simulations
                       (sim_id, name, name_stem, version_int, started_at, project,
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
                       VALUES (?, ?, ?, ?, current_timestamp, ?,
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
                        name_stem,
                        version_int,
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
                        dirname,
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
                if p_start is None and p_end is None and flow_regime == STEADY_FLOW_REGIME:
                    self._backend.execute(
                        """UPDATE simulations
                              SET period_start = started_at, period_end = started_at
                            WHERE sim_id = ?""",
                        [sid],
                    )

                if replaced_sid is not None:
                    try:
                        emit_audit_event(
                            self._db,
                            event_type="sim.trash",
                            sim_id=replaced_sid,
                            project=project,
                            payload={"replaced_by": sid},
                        )
                    except Exception as exc:  # noqa: BLE001 - audit must not raise
                        logger.warning("audit emission failed for sim.trash: %s", exc)

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
        except BaseException:
            # Widened to BaseException so a KeyboardInterrupt mid-registration
            # still removes the promoted-but-uncommitted Zarr store instead of
            # leaving it for the gc orphan sweep to delete.
            self._paths.forget(sid)
            if zarr_final is not None and zarr_final.exists():
                shutil.rmtree(zarr_final)
            raise

        if dirname is not None:
            self._paths.cache_dirname(sid, dirname)
        if zarr_final is not None:
            zarr_obj = self._track_zarr_handle(SimulationZarr(zarr_final))
        return RegistrationResult(
            sim_id=sid,
            name=final_name,
            zarr=zarr_obj,
            replaced_sim_id=replaced_sid,
        )
