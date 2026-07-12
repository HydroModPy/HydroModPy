"""Simulation registration into the catalog.

``register_simulation`` is the entry point that allocates a new ``sim_id``
row, applies on-collision rules (replace / fail / version), computes a
human-readable storage basename, and creates the initial :class:`SimulationZarr`
when mesh dimensions are known. The rest of the write surface
(``write_parameters``, ``write_timeseries`` ...) lives in
:mod:`hydromodpy.results.catalog.writes`.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import re
import shutil
import time
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
from hydromodpy.results.storage_contract import (
    PARQUET_DIR_SUFFIX,
    PARQUET_FILE_SUFFIX,
    SIMULATIONS_DIRNAME,
    ZARR_SUFFIX,
    ZARR_ZIP_SUFFIX,
)
from hydromodpy.results.zarr_store import SimulationZarr, _windows_long_path

logger = get_logger(__name__)

IfExistsMode = Literal["replace", "fail", "version"]

STAGED_ZARR_RENAME_ATTEMPTS = 8
STAGED_ZARR_RENAME_BASE_DELAY_SECONDS = 0.05

_VERSION_SUFFIX_RE = re.compile(r"\.v(\d+)$")


def _split_stem_version(name: str) -> tuple[str, int | None]:
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


def _is_retryable_staged_zarr_rename_error(exc: BaseException) -> bool:
    """Return True for transient Windows directory promotion failures."""
    if os.name != "nt" or not isinstance(exc, PermissionError):
        return False
    winerror = getattr(exc, "winerror", None)
    return winerror in (None, 5, 32)


def _promote_staged_zarr(source: Path, target: Path) -> None:
    """Atomically promote a staged Zarr directory to its final location."""
    source_io = _windows_long_path(source)
    target_io = _windows_long_path(target)
    for attempt in range(STAGED_ZARR_RENAME_ATTEMPTS):
        try:
            source_io.rename(target_io)
            return
        except PermissionError as exc:
            if (
                not _is_retryable_staged_zarr_rename_error(exc)
                or attempt == STAGED_ZARR_RENAME_ATTEMPTS - 1
            ):
                raise
            gc.collect()
            time.sleep(STAGED_ZARR_RENAME_BASE_DELAY_SECONDS * (attempt + 1))


def _resolve_registration_name(
    backend: CatalogBackend,
    project: str,
    requested: str,
    if_exists: IfExistsMode,
) -> tuple[str, str, int, str | None]:
    """Resolve the final ``(name, name_stem, version_int, replaced_sid)``.

    Versioning is keyed on ``name_stem`` (the requested name with any trailing
    ``.vN`` stripped), so collisions never rely on the buggy ``LIKE`` scan.
    Only live (non-trashed) rows count as collisions.

    - ``version`` (default): mint the next free version. A bare original still
      holding the clean stem is demoted to ``stem.v1`` so the bare name always
      resolves to the latest version of the stem.
    - ``replace``: trash the colliding predecessor (name freed, ``original_name``
      kept, restorable) and let the new run take the requested name.
    - ``fail``: raise :class:`DuplicateSimulationNameError`.
    """
    stem, requested_version = _split_stem_version(requested)
    rows = backend.fetch_all(
        "SELECT CAST(sim_id AS VARCHAR), name, version_int FROM simulations "
        "WHERE project = ? AND name_stem = ? "
        "AND status_id <> (SELECT id FROM statuses WHERE code = 'trashed')",
        [project, stem],
    )
    if not rows:
        return requested, stem, (requested_version or 1), None

    if if_exists == "fail":
        raise DuplicateSimulationNameError(project, requested, str(rows[0][0]))

    if if_exists == "replace":
        target = next((r for r in rows if r[1] == requested), None)
        if target is None:
            target = max(rows, key=lambda r: r[2] or 1)
        backend.execute(
            "UPDATE simulations SET name = NULL, original_name = ?, "
            "original_status_id = COALESCE(original_status_id, status_id), "
            "trashed_at = current_timestamp, updated_at = current_timestamp, "
            "status_id = (SELECT id FROM statuses WHERE code = 'trashed') "
            "WHERE sim_id = ?",
            [target[1], target[0]],
        )
        return requested, stem, (requested_version or 1), str(target[0])

    # version (default): demote a bare original, then mint the next version.
    # Skip the demote when ``stem.v1`` already exists (a rename may have poisoned
    # the accounting) so the UNIQUE (project, name) constraint never trips.
    existing_names = {name_x for _, name_x, _ in rows}
    for sid_x, name_x, _ in rows:
        if name_x == stem and f"{stem}.v1" not in existing_names:
            backend.execute(
                "UPDATE simulations SET name = ?, version_int = 1 WHERE sim_id = ?",
                [f"{stem}.v1", sid_x],
            )
    next_version = max((r[2] or 1) for r in rows) + 1
    return f"{stem}.v{next_version}", stem, next_version, None


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
        Final name assigned to the simulation (may differ from the requested
        name when ``if_exists='version'`` auto-suffixes it).
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
        name_stem, _ = _split_stem_version(requested_name)
        version_int = 1
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
                final_name, name_stem, version_int, replaced_sid = _resolve_registration_name(
                    self._backend, project, requested_name, if_exists
                )
                if replaced_sid is not None:
                    logger.info(
                        "Hard-replacing '%s' in project '%s' (previous sim %s trashed)",
                        requested_name,
                        project,
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

                storage_basename = build_storage_basename(project, sid)
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
                    _promote_staged_zarr(zarr_tmp, zarr_final)

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

    @with_lock_retry()
    def adopt(self, store_path: Path | str) -> str:
        """Re-register an orphan store from its ``simulation.parquet`` snapshot.

        *store_path* may point at any of the run's stores (``.zarr``,
        ``.zarr.zip`` or ``.parquet``); the one-row snapshot is read from the
        matching Parquet store directory. Returns the adopted ``sim_id``.

        Raises
        ------
        FileNotFoundError
            When no snapshot is present (the run predates snapshot adoption).
        ValueError
            When the store name is unrecognised, the run is already
            registered, or the snapshot is empty.
        """
        name = Path(store_path).name
        basename: str | None = None
        # Longest suffix first so .zarr.zip wins over .zarr and .parquet.d over
        # a hypothetical .parquet.
        for suffix in (ZARR_ZIP_SUFFIX, PARQUET_DIR_SUFFIX, ZARR_SUFFIX):
            if name.endswith(suffix):
                basename = name[: -len(suffix)]
                break
        if basename is None:
            raise ValueError(
                f"{name!r} is not a recognised store "
                f"({ZARR_SUFFIX}/{ZARR_ZIP_SUFFIX}/{PARQUET_DIR_SUFFIX})"
            )
        snapshot = (
            self._simulations_dir
            / f"{basename}{PARQUET_DIR_SUFFIX}"
            / f"simulation{PARQUET_FILE_SUFFIX}"
        )
        if not snapshot.exists():
            raise FileNotFoundError(
                f"No simulation.parquet snapshot for {basename!r}; this run predates "
                "snapshot-based adoption and cannot be re-registered."
            )
        posix = snapshot.as_posix().replace("'", "''")
        row = self._backend.fetch_one(
            f"SELECT CAST(sim_id AS VARCHAR), project FROM read_parquet('{posix}')"
        )
        if row is None:
            raise ValueError(f"Empty snapshot at {snapshot}")
        sid, project = row[0], row[1]
        if self._backend.fetch_one("SELECT 1 FROM simulations WHERE sim_id = ?", [sid]) is not None:
            raise ValueError(f"Run {sid[:8]} is already registered")
        # Insert only the columns common to the live table and the snapshot, in
        # table order, so a snapshot written under an older or newer schema still
        # adopts cleanly (removed columns are skipped; new columns take their
        # default) instead of failing on a ``SELECT *`` column-count mismatch.
        table_cols = [r[0] for r in self._backend.fetch_all("DESCRIBE simulations")]
        snap_cols = {
            r[0] for r in self._backend.fetch_all(f"DESCRIBE SELECT * FROM read_parquet('{posix}')")
        }
        col_list = ", ".join(f'"{c}"' for c in table_cols if c in snap_cols)
        with self._backend.transaction():
            self._backend.execute(
                f"INSERT INTO simulations ({col_list}) "
                f"SELECT {col_list} FROM read_parquet('{posix}')"
            )
            emit_audit_event(
                self._db,
                event_type="import",
                sim_id=sid,
                project=project,
                payload={"adopted_from": str(store_path)},
            )
        return sid
