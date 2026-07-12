"""DuckDB write concern for :class:`Catalog`.

Tabular catalog writes against the DuckDB backend: parameters, metrics,
stations, scientific objectives, run environment snapshots, geographic
metadata, provenance, and the registration of observation points and
tracked input files. Methods that also mirror to Parquet (``write_metric``,
``write_provenance``) call ``self._write_parquet_records`` which the facade
inherits from :class:`WritesMixinParquet` via the MRO.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd

from hydromodpy.core.io.db_retry import with_lock_retry
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import encode_workspace_path as _encode_workspace_path
from hydromodpy.results.array_fingerprint import fingerprint
from hydromodpy.results.catalog.audit import audited, emit_audit_event
from hydromodpy.results.catalog.constants import GLOBAL_ZONE
from hydromodpy.results.catalog.writes_helpers import (
    _coerce_timestamp,
    _coerce_timestamp_utc,
    _epsg_from_crs,
    _path_size_bytes,
    _python_value_type,
    _sha256_directory,
    _sha256_streaming,
)
from hydromodpy.results.parquet_schemas import (
    METRICS_SCHEMA,
    PROVENANCE_SCHEMA,
)
from hydromodpy.results.spatial_index import point_in_cell

logger = get_logger(__name__)


class WritesMixinDuckDB:
    """Tabular catalog write operations against the DuckDB backend.

    Relies on facade attributes ``self._backend``, ``self._db``,
    ``self._workspace``, ``self._paths`` and ``self._persistence``. Each
    method early-returns when the relevant ``PersistenceConfig`` flag is
    False, so a single switch governs the DuckDB sink.
    """

    @audited("sim.rename", payload_keys=("new_name",))
    @with_lock_retry()
    def rename_simulation(
        self,
        sim_id: str | UUID,
        new_name: str,
    ) -> None:
        """Rename a simulation row in-place.

        The rename routes through the same stem-versioning accounting as
        registration: the resulting ``(name_stem, version_int)`` slot must be
        free among live rows, otherwise a
        :class:`~hydromodpy.results.catalog.registration.DuplicateSimulationNameError`
        is raised. A bare stem takes version 1, so renaming into a stem that
        already owns ``.v1`` is rejected rather than creating a duplicate
        ``(stem, 1)`` that would later break ``if_exists='version'``.
        """
        if not self._persistence.save_catalog:
            return
        from hydromodpy.results.catalog.registration import (
            DuplicateSimulationNameError,
            _split_stem_version,
        )

        sid = str(sim_id)
        if not new_name or not str(new_name).strip():
            raise ValueError("new_name must be a non-empty string")
        row = self._backend.fetch_one("SELECT project FROM simulations WHERE sim_id = ?", [sid])
        if row is None:
            raise KeyError(f"No simulation with sim_id={sid[:8]}")
        project = row[0]
        stem, requested_version = _split_stem_version(str(new_name))
        target_version = requested_version or 1
        clash = self._backend.fetch_one(
            "SELECT CAST(sim_id AS VARCHAR) FROM simulations "
            "WHERE project = ? AND name_stem = ? AND version_int = ? AND sim_id <> ? "
            "AND status_id <> (SELECT id FROM statuses WHERE code = 'trashed')",
            [project, stem, target_version, sid],
        )
        if clash is not None:
            raise DuplicateSimulationNameError(str(project), str(new_name), str(clash[0]))
        self._backend.execute(
            "UPDATE simulations SET name = ?, name_stem = ?, version_int = ?, "
            "updated_at = current_timestamp WHERE sim_id = ?",
            [str(new_name), stem, target_version, sid],
        )

    @audited("sim.tag_add", payload_keys=("tag",))
    @with_lock_retry()
    def add_tag(
        self,
        sim_id: str | UUID,
        tag: str,
    ) -> bool:
        """Attach a ``(sim_id, tag)`` row to ``tags`` (idempotent).

        Returns ``True`` when a row was inserted, ``False`` when the tag was
        already present.
        """
        if not self._persistence.save_catalog:
            return False
        sid = str(sim_id)
        existing = self._backend.fetch_one(
            "SELECT 1 FROM tags WHERE sim_id = ? AND tag = ?",
            [sid, str(tag)],
        )
        if existing is not None:
            return False
        self._backend.execute(
            "INSERT INTO tags (sim_id, tag) VALUES (?, ?)",
            [sid, str(tag)],
        )
        return True

    def write_tags(self, sim_id: str | UUID, tags: list[str]) -> None:
        """Attach several tags to ``sim_id`` (each idempotent and audited)."""
        for tag in tags:
            if tag and str(tag).strip():
                self.add_tag(sim_id, str(tag).strip())

    @audited("note.add")
    @with_lock_retry()
    def add_note(
        self,
        sim_id: str | UUID,
        note: str,
        *,
        added_by: str | None = None,
    ) -> None:
        """Append a timestamped note to ``sim_notes`` for ``sim_id``."""
        if not self._persistence.save_catalog:
            return
        self._backend.execute(
            "INSERT INTO sim_notes (note_id, sim_id, note, added_by) "
            "VALUES (gen_random_uuid(), ?, ?, ?)",
            [str(sim_id), str(note), added_by],
        )

    def record_export(self, sim_id: str | UUID, *, kind: str, path: str | Path) -> None:
        """Record one emitted export artefact in ``export_log`` (best-effort).

        No-op on a read-only catalog or when persistence is disabled, so read-
        side export helpers never fail over bookkeeping. ``show``/``gc`` read
        this table instead of globbing the export tree. Files get a SHA-256;
        directories record their total size only.
        """
        if self._read_only or not self._persistence.save_catalog:
            return
        p = Path(path)
        if not p.exists():
            return
        try:
            n_bytes = _path_size_bytes(p)
            sha: str | None = _sha256_streaming(p) if p.is_file() else None
        except OSError:
            return
        try:
            rel = str(p.resolve().relative_to(self.project_path.resolve()))
        except ValueError:
            rel = str(p)
        # Idempotent on (sim_id, kind, rel_path): re-exporting the same artefact
        # to the same path refreshes its row instead of accumulating duplicates
        # that no longer map one-to-one to on-disk files.
        self._backend.execute(
            "DELETE FROM export_log WHERE sim_id = ? AND kind = ? AND rel_path = ?",
            [str(sim_id), str(kind), rel],
        )
        self._backend.execute(
            "INSERT INTO export_log (export_id, sim_id, kind, rel_path, bytes, sha256) "
            "VALUES (gen_random_uuid(), ?, ?, ?, ?, ?)",
            [str(sim_id), str(kind), rel, int(n_bytes), sha],
        )
        try:
            emit_audit_event(
                self._db,
                event_type="export.write",
                sim_id=str(sim_id),
                payload={"kind": str(kind), "rel_path": rel},
            )
        except Exception:
            pass

    @audited("sim.tag_remove", payload_keys=("tag",))
    @with_lock_retry()
    def remove_tag(
        self,
        sim_id: str | UUID,
        tag: str,
    ) -> bool:
        """Drop a ``(sim_id, tag)`` row from ``tags``.

        Returns ``True`` when a row was removed, ``False`` when the tag was
        not attached to ``sim_id``.
        """
        if not self._persistence.save_catalog:
            return False
        sid = str(sim_id)
        existing = self._backend.fetch_one(
            "SELECT 1 FROM tags WHERE sim_id = ? AND tag = ?",
            [sid, str(tag)],
        )
        if existing is None:
            return False
        self._backend.execute(
            "DELETE FROM tags WHERE sim_id = ? AND tag = ?",
            [sid, str(tag)],
        )
        return True

    @audited("param.write")
    @with_lock_retry()
    def write_parameters(
        self,
        sim_id: str | UUID,
        params: list[dict],
    ) -> None:
        if not self._persistence.save_catalog:
            return
        sid = str(sim_id)
        for p in params:
            zone = p.get("zone_id")
            zone_val = GLOBAL_ZONE if zone is None else str(zone)
            self._backend.execute(
                """INSERT INTO parameters
                   (sim_id, param_name, zone_id, value, unit, parameterization)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (sim_id, param_name, zone_id)
                   DO UPDATE SET
                       value = EXCLUDED.value,
                       unit = EXCLUDED.unit,
                       parameterization = EXCLUDED.parameterization,
                       valid_from = now()""",
                [
                    sid,
                    p["param_name"],
                    zone_val,
                    p.get("value"),
                    p.get("unit"),
                    p.get("parameterization"),
                ],
            )

    @audited("param.update", payload_keys=("param_name", "value", "zone_id"))
    @with_lock_retry()
    def update_parameter(
        self,
        sim_id: str | UUID,
        param_name: str,
        value: Any,
        *,
        zone_id: str | None = None,
        unit: str | None = None,
        parameterization: str | None = None,
    ) -> None:
        """Update an existing parameter row in-place.

        Distinct from :meth:`write_parameters` (insert + on-conflict-replace):
        targets one ``(sim_id, param_name, zone_id)`` tuple already present
        and refreshes ``value`` plus optional ``unit`` / ``parameterization``.
        Raises ``KeyError`` when the row does not exist so misuse fails loudly.
        """
        if not self._persistence.save_catalog:
            return
        sid = str(sim_id)
        zone_val = GLOBAL_ZONE if zone_id is None else str(zone_id)
        existing = self._backend.fetch_one(
            "SELECT 1 FROM parameters WHERE sim_id = ? AND param_name = ? AND zone_id = ?",
            [sid, param_name, zone_val],
        )
        if existing is None:
            raise KeyError(
                f"No parameter row for sim_id={sid[:8]} param={param_name!r} zone={zone_val!r}"
            )
        self._backend.execute(
            """UPDATE parameters
                  SET value = ?,
                      unit = COALESCE(?, unit),
                      parameterization = COALESCE(?, parameterization),
                      valid_from = now()
                WHERE sim_id = ? AND param_name = ? AND zone_id = ?""",
            [value, unit, parameterization, sid, param_name, zone_val],
        )

    @with_lock_retry()
    def write_station(
        self,
        station_id: str,
        variable_type: str,
        *,
        name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        elevation: float | None = None,
        source: str | None = None,
        first_valid: Any = None,
        last_valid: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._persistence.save_catalog:
            return
        self._backend.execute(
            """
            INSERT INTO stations
                (station_id, variable_type, name, latitude, longitude, elevation,
                 source, first_valid, last_valid, metadata, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE)
            ON CONFLICT (station_id, variable_type) DO UPDATE SET
                name = EXCLUDED.name,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                elevation = EXCLUDED.elevation,
                source = EXCLUDED.source,
                first_valid = EXCLUDED.first_valid,
                last_valid = EXCLUDED.last_valid,
                metadata = EXCLUDED.metadata,
                active = TRUE
            """,
            [
                station_id,
                variable_type,
                name,
                latitude,
                longitude,
                elevation,
                source,
                _coerce_timestamp(first_valid),
                _coerce_timestamp(last_valid),
                json.dumps(metadata or {}),
            ],
        )

    @with_lock_retry()
    def write_run_environment(
        self,
        sim_id: str | UUID,
        *,
        project_root: Path | str | None = None,
        solver_name: str | None = None,
        solver_binary_path: Path | str | None = None,
        rng_seed: int | None = None,
    ) -> None:
        """Capture and persist the host environment snapshot for ``sim_id``.

        Idempotent: re-calling overwrites the previous row. Heavy collection
        steps (``pip list``, ``cpuinfo``) tolerate failures and fall back
        to partial values rather than raising.

        ``rng_seed`` is the master seed driving ``RngManager``. Pass the
        same value to reproduce stochastic stages (mesh sampling, random
        forcing, calibration draws) from the catalog snapshot.
        """
        if not self._persistence.save_catalog:
            return
        from hydromodpy.results.run_environment import capture_environment

        snap = capture_environment(
            project_root=project_root,
            solver_name=solver_name,
            solver_binary_path=solver_binary_path,
        )
        sid = str(sim_id)
        self._backend.execute("DELETE FROM runs_environment WHERE sim_id = ?", [sid])
        self._backend.execute(
            """INSERT INTO runs_environment
               (sim_id, python_version, hydromodpy_version, platform,
                hostname, user_name, cpu_info, memory_gb,
                git_commit, project_git_commit,
                solver_name, solver_binary_path,
                solver_binary_sha256, solver_version_text,
                conda_env_hash, env_packages, rng_seed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                sid,
                snap.get("python_version"),
                snap.get("hydromodpy_version"),
                snap.get("platform"),
                snap.get("hostname"),
                snap.get("user_name"),
                json.dumps(snap.get("cpu_info") or {}),
                snap.get("memory_gb"),
                snap.get("git_commit"),
                snap.get("project_git_commit"),
                snap.get("solver_name"),
                snap.get("solver_binary_path"),
                snap.get("solver_binary_sha256"),
                snap.get("solver_version_text"),
                snap.get("conda_env_hash"),
                json.dumps(snap.get("env_packages") or []),
                None if rng_seed is None else int(rng_seed),
            ],
        )

    @with_lock_retry()
    def update_simulation_grid_metadata(
        self,
        sim_id: str | UUID,
        *,
        n_cells: int | None = None,
        n_layers: int | None = None,
        mesh_hash: str | None = None,
        mesh_topology: str | None = None,
        bbox: tuple[float, float, float, float] | list[float] | None = None,
    ) -> None:
        """Backfill grid metadata known only once the solver grid is built.

        DISV-from-raster runs register before the grid exists, so n_cells/
        n_layers/bbox/mesh_hash/mesh_topology start NULL; this fills them post-run.
        COALESCE keeps any value already present, so passing None never clobbers.
        """
        if not self._persistence.save_catalog:
            return
        bbox_xmin = bbox_ymin = bbox_xmax = bbox_ymax = None
        if bbox is not None and len(bbox) == 4:
            bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax = (float(v) for v in bbox)
        self._backend.execute(
            """UPDATE simulations SET
                   n_cells = COALESCE(?, n_cells),
                   n_layers = COALESCE(?, n_layers),
                   mesh_hash = COALESCE(?, mesh_hash),
                   mesh_topology_id = COALESCE(
                       (SELECT id FROM mesh_topologies WHERE code = ?), mesh_topology_id),
                   bbox_xmin = COALESCE(?, bbox_xmin),
                   bbox_ymin = COALESCE(?, bbox_ymin),
                   bbox_xmax = COALESCE(?, bbox_xmax),
                   bbox_ymax = COALESCE(?, bbox_ymax),
                   updated_at = current_timestamp
               WHERE sim_id = ?""",
            [
                None if n_cells is None else int(n_cells),
                None if n_layers is None else int(n_layers),
                mesh_hash,
                mesh_topology,
                bbox_xmin,
                bbox_ymin,
                bbox_xmax,
                bbox_ymax,
                str(sim_id),
            ],
        )

    @with_lock_retry()
    def update_run_environment_solver_binary(
        self,
        sim_id: str | UUID,
        *,
        solver_binary_path: Path | str | None,
    ) -> None:
        """Refine the recorded binary identity with the path the solver ran.

        Registration records a best-guess managed-cache binary; this overwrites
        it with the exact binary used, honouring a custom ``mf6_executable_name``.
        """
        if not self._persistence.save_catalog or solver_binary_path is None:
            return
        from hydromodpy.results.run_environment import solver_binary_identity

        sha256, version_text = solver_binary_identity(solver_binary_path)
        self._backend.execute(
            """UPDATE runs_environment SET
                   solver_binary_path = ?,
                   solver_binary_sha256 = COALESCE(?, solver_binary_sha256),
                   solver_version_text = COALESCE(?, solver_version_text)
               WHERE sim_id = ?""",
            [str(solver_binary_path), sha256, version_text, str(sim_id)],
        )

    @audited("objective.set", payload_keys=("objective", "study_area_name"))
    @with_lock_retry()
    def write_scientific_objective(
        self,
        sim_id: str | UUID,
        objective: str,
        *,
        description: str | None = None,
        contact_email: str | None = None,
        doi: str | None = None,
        study_area_name: str | None = None,
        outlet_x: float | None = None,
        outlet_y: float | None = None,
    ) -> None:
        """Record the scientific objective and related metadata for ``sim_id``.

        ``objective`` annotates the simulation for downstream filtering. The
        other fields are free annotations for citation, geographic context,
        and contact lookup.
        """
        if not self._persistence.save_catalog:
            return
        if not objective or not str(objective).strip():
            raise ValueError("scientific_objective must be a non-empty string")
        self._backend.execute(
            """UPDATE simulations SET
                   scientific_objective = ?,
                   description = COALESCE(?, description),
                   contact_email = COALESCE(?, contact_email),
                   doi = COALESCE(?, doi),
                   study_area_name = COALESCE(?, study_area_name),
                   outlet_x = COALESCE(?, outlet_x),
                   outlet_y = COALESCE(?, outlet_y)
               WHERE sim_id = ?""",
            [
                str(objective),
                description,
                contact_email,
                doi,
                study_area_name,
                outlet_x,
                outlet_y,
                str(sim_id),
            ],
        )

    @audited("metric.write", payload_keys=("station_id", "metric_name", "value"))
    @with_lock_retry()
    def write_metric(
        self,
        sim_id: str | UUID,
        station_id: str,
        metric_name: str,
        value: float,
        *,
        variable: str = "head",
        n_samples: int | None = None,
        period_start: Any | None = None,
        period_end: Any | None = None,
    ) -> None:
        """Write one metric to the DuckDB ``metrics`` table (authoritative).

        The DuckDB row is the source of truth (queried by find/leaderboards and
        the ``metrics`` view). The Parquet mirror written below is a portable
        columnar copy for export and ML scans, not a second source of truth; the
        two sinks are not written in one transaction, so on any drift DuckDB wins.
        """
        if not self._persistence.save_catalog:
            return
        self._backend.execute(
            """INSERT INTO metrics
               (sim_id, station_id, variable, metric_name, value,
                n_samples, period_start, period_end)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (sim_id, station_id, variable, metric_name)
               DO UPDATE SET
                   value = EXCLUDED.value,
                   n_samples = EXCLUDED.n_samples,
                   period_start = EXCLUDED.period_start,
                   period_end = EXCLUDED.period_end,
                   valid_from = now()""",
            [
                str(sim_id),
                station_id,
                variable,
                metric_name,
                value,
                n_samples,
                period_start,
                period_end,
            ],
        )
        if self._persistence.save_parquet:
            sid = str(sim_id)
            valid_from = _coerce_timestamp_utc(pd.Timestamp.now(tz="UTC"))
            records = [
                {
                    "sim_id": sid,
                    "station_id": station_id,
                    "variable": variable,
                    "metric": metric_name,
                    "value": float(value),
                    "n_samples": int(n_samples) if n_samples is not None else None,
                    "valid_from": valid_from,
                    "period_start": period_start,
                    "period_end": period_end,
                }
            ]
            self._write_parquet_records(
                target=self._paths.parquet_path_for(sid, "metrics"),
                records=records,
                schema=METRICS_SCHEMA,
                pk_cols=("sim_id", "station_id", "variable", "metric"),
                sim_id=sid,
            )

    @with_lock_retry()
    def write_provenance(
        self,
        sim_id: str | UUID,
        variable: str,
        source_ref: str,
        data: np.ndarray,
        *,
        source_type: str = "data_manager",
        source_sha256: str | None = None,
        loader_name: str | None = None,
        loader_version: str | None = None,
        fetched_at: Any = None,
        period_start: Any = None,
        period_end: Any = None,
    ) -> None:
        """Write one provenance record to the DuckDB ``provenance`` table (authoritative).

        As with :meth:`write_metric`, the DuckDB row is the source of truth and
        the Parquet mirror is a portable copy; the two are not written in one
        transaction, so DuckDB wins on any drift.
        """
        if not self._persistence.save_catalog:
            return
        fp = fingerprint(data)
        allowed_source_types = (
            "http_api",
            "custom_file",
            "data_manager",
            "derived",
            "cache",
        )
        if source_type not in allowed_source_types:
            raise ValueError(
                f"Unknown provenance source_type {source_type!r}. "
                f"Expected one of {allowed_source_types}."
            )
        payload = [
            str(sim_id),
            variable,
            source_type,
            source_ref,
            source_sha256,
            loader_name,
            loader_version,
            _coerce_timestamp(fetched_at),
            _coerce_timestamp(period_start),
            _coerce_timestamp(period_end),
            fp["checksum"],
            int(np.prod(data.shape)),
            json.dumps(fp["stats"]),
        ]
        self._backend.execute(
            """INSERT INTO provenance
               (sim_id, variable, source_type, source_ref,
                source_sha256, loader_name, loader_version, fetched_at,
                period_start, period_end, payload_sha256, n_records, stats)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (sim_id, variable, source_ref)
               DO UPDATE SET
                   source_type = EXCLUDED.source_type,
                   source_sha256 = EXCLUDED.source_sha256,
                   loader_name = EXCLUDED.loader_name,
                   loader_version = EXCLUDED.loader_version,
                   fetched_at = EXCLUDED.fetched_at,
                   period_start = EXCLUDED.period_start,
                   period_end = EXCLUDED.period_end,
                   payload_sha256 = EXCLUDED.payload_sha256,
                   n_records = EXCLUDED.n_records,
                   stats = EXCLUDED.stats,
                   valid_from = now()""",
            payload,
        )
        if self._persistence.save_parquet:
            sid = str(sim_id)
            records = [
                {
                    "sim_id": sid,
                    "variable": variable,
                    "source_type": source_type,
                    "source_ref": source_ref,
                    "source_sha256": source_sha256,
                    "loader_name": loader_name,
                    "loader_version": loader_version,
                    "fetched_at": fetched_at,
                    "period_start": period_start,
                    "period_end": period_end,
                    "payload_sha256": fp["checksum"],
                    "n_records": int(np.prod(data.shape)),
                    "stats": json.dumps(fp["stats"]),
                }
            ]
            self._write_parquet_records(
                target=self._paths.parquet_path_for(sid, "provenance"),
                records=records,
                schema=PROVENANCE_SCHEMA,
                pk_cols=("sim_id", "variable", "source_ref"),
                sim_id=sid,
            )

    @with_lock_retry()
    def register_observation_points(
        self,
        sim_id: str | UUID,
        points: dict[str, tuple[float, float]],
        variable: str = "head",
        layer: int = 0,
        *,
        crs: str | None = None,
        crs_epsg: int | None = None,
    ) -> None:
        if not self._persistence.save_catalog:
            return
        sid = str(sim_id)
        if crs is None or crs_epsg is None:
            row = self._backend.fetch_one(
                "SELECT crs_wkt, crs_epsg FROM simulations WHERE sim_id = ?",
                [sid],
            )
            if row is not None:
                crs = crs or row[0]
                crs_epsg = crs_epsg if crs_epsg is not None else row[1]
        if crs is None:
            raise ValueError("Observation point CRS is required.")
        if crs_epsg is None:
            crs_epsg = _epsg_from_crs(crs)
        sz = self.open_zarr(sim_id)
        try:
            mesh = sz.root["mesh"]
            vertices = mesh["vertices"][:]
            connectivity = mesh["face_node_connectivity"][:]

            _ = variable
            mapping = point_in_cell(vertices, connectivity, points)
            for station_id, (x, y) in points.items():
                cell_id = mapping[station_id]
                self._backend.execute(
                    """INSERT INTO observation_points
                       (sim_id, station_id, x, y, cell_id, layer, crs_wkt, crs_epsg)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT (sim_id, station_id)
                       DO UPDATE SET
                           x = EXCLUDED.x,
                           y = EXCLUDED.y,
                           cell_id = EXCLUDED.cell_id,
                           layer = EXCLUDED.layer,
                           crs_wkt = EXCLUDED.crs_wkt,
                           crs_epsg = EXCLUDED.crs_epsg""",
                    [sid, station_id, x, y, cell_id, layer, str(crs), crs_epsg],
                )
        finally:
            sz.close()

    @with_lock_retry()
    def register_tracked_files(
        self,
        sim_id: str | UUID,
        entries: list[Any],
    ) -> int:
        """Persist tracked-file records for a simulation.

        Each entry must expose ``role``, ``category``, ``original_path``,
        ``canonical_path``, and ``portable`` (as produced by
        :func:`hydromodpy.core.tracking.collect_input_files`). The SHA-256
        and size are computed here from the canonical file or directory.
        Paths that disappeared between walker-resolution and this call are
        skipped with a logger warning to keep the setup step non-fatal.
        """
        if not self._persistence.save_catalog:
            return 0
        sid = str(sim_id)
        written = 0
        for entry in entries:
            canonical = Path(entry.canonical_path)
            if canonical.is_file():
                sha = _sha256_streaming(canonical)
            elif canonical.is_dir():
                sha = _sha256_directory(canonical)
            else:
                logger.warning(
                    "Tracked input '%s' does not exist, skipping: %s",
                    entry.role,
                    canonical,
                )
                continue
            size = _path_size_bytes(canonical)
            portable = bool(entry.portable)
            try:
                encoded = _encode_workspace_path(self._workspace, canonical)
            except ValueError:
                # Tracked file lives outside workspace/cache/state anchors.
                # Keep the absolute source path so the .hmp exporter can still
                # bundle InputFile(portable=True) entries from user data dirs.
                encoded = str(canonical)
            self._backend.execute(
                """INSERT INTO tracked_files
                   (sim_id, role, category, original_path, canonical_path,
                    sha256, size_bytes, portable)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (sim_id, role, canonical_path)
                   DO UPDATE SET
                       category = EXCLUDED.category,
                       original_path = EXCLUDED.original_path,
                       sha256 = EXCLUDED.sha256,
                       size_bytes = EXCLUDED.size_bytes,
                       portable = EXCLUDED.portable,
                       recorded_at = now()""",
                [
                    sid,
                    entry.role,
                    entry.category,
                    entry.original_path,
                    encoded,
                    sha,
                    int(size),
                    portable,
                ],
            )
            written += 1
        if written > 0:
            try:
                emit_audit_event(
                    self._db,
                    event_type="tracked_file.add",
                    sim_id=sid,
                    payload={"n_entries": int(written)},
                )
            except Exception as exc:  # noqa: BLE001 - audit must not raise
                logger.warning("audit emission failed for tracked_file.add: %s", exc)
        return written

    @audited("tracked_file.remove", payload_keys=("role", "canonical_path"))
    @with_lock_retry()
    def remove_tracked_file(
        self,
        sim_id: str | UUID,
        role: str,
        canonical_path: str,
    ) -> bool:
        """Drop one ``(sim_id, role, canonical_path)`` row from ``tracked_files``.

        Returns ``True`` when a row was removed, ``False`` when no match was
        found (caller can decide whether the absence is an error).
        """
        if not self._persistence.save_catalog:
            return False
        sid = str(sim_id)
        existing = self._backend.fetch_one(
            "SELECT 1 FROM tracked_files WHERE sim_id = ? AND role = ? AND canonical_path = ?",
            [sid, role, canonical_path],
        )
        if existing is None:
            return False
        self._backend.execute(
            "DELETE FROM tracked_files WHERE sim_id = ? AND role = ? AND canonical_path = ?",
            [sid, role, canonical_path],
        )
        return True

    @with_lock_retry()
    def write_geographic_metadata(
        self,
        sim_id: str | UUID,
        metadata: dict[str, object],
    ) -> None:
        if not self._persistence.save_catalog:
            return
        sid = str(sim_id)
        for key, value in metadata.items():
            value_type = _python_value_type(value)
            self._backend.execute(
                """INSERT INTO geographic_metadata
                   (sim_id, key, value, value_type)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (sim_id, key)
                   DO UPDATE SET
                       value = EXCLUDED.value,
                       value_type = EXCLUDED.value_type""",
                [sid, str(key), None if value is None else str(value), value_type],
            )


__all__ = ["WritesMixinDuckDB"]
