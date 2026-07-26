"""Run manifest: the seal that makes a run directory readable without the index.

Why
---
``.hmp/index.duckdb`` is a rebuildable index, not the truth. Deleting it must
cost nothing but time. That only holds if every value the index carries and
that *execution code* reads back is also written into the run directory. This
module writes those files at the end of a run and seals the directory with
``manifest.json``.

Files written here, in order
----------------------------
1. ``tables.parquet/parameters.parquet`` - the run parameters, tabular.
2. ``provenance.json`` - tool, git, python, platform, packages, solver, timing.
3. ``manifest.json`` - identity, geometry, period, config fingerprint, artefact
   list, parameters, metric summary. Written **last** and **atomically**
   (``manifest.json.tmp-<uuid>`` then ``os.replace``), so a run directory
   without a manifest is, by construction, an incomplete run.

``config.toml`` is not written here: the workflow freezes it into the run
directory at registration time (``workflow.steps.prepare_solver.dispatch
._freeze_run_config``). The manifest only lists it and records its hash, and
says so loudly when it is missing.

Index column -> on-disk home
----------------------------
Every column below is read by execution code (not just by listings), so each
one has a place on disk. ``M`` = ``manifest.json``, ``P`` = ``provenance.json``.

===============================================  ============================  ====================================
Index column                                     Read at runtime by            On disk
===============================================  ============================  ====================================
simulations.sim_id / name / version_int          Run, naming, exports          M ``run``; tables.parquet/simulation
simulations.project / status / solver            Run._load_row, reports        M ``run``; tables.parquet/simulation
simulations.n_cells / n_layers                   results.grid, zarr readers    M ``geometry``
simulations.n_timesteps / time_unit              time index rebuild            M ``period``
simulations.period_start / period_end            run.timeseries index,         M ``period``
                                                 catchment_aggregation
simulations.crs_wkt / crs_epsg                   display.figure, exporters     M ``geometry``
simulations.bbox_*                               display, exporters            M ``geometry.bbox``
simulations.mesh_hash / mesh_topology            mesh reuse, comparison        M ``geometry``
simulations.zarr_path                            field reads                   fields.zarr in the run directory
simulations.config_hash / config_source          comparison, audit             M ``config``
simulations.config_toml / config_snapshot        audit, .hmp packaging         config.toml
simulations.geographic_fingerprint               geographic cache reuse        M ``geometry``
simulations.parent_sim_id                        lineage, spin-up chains       M ``run.parent_sim_id``
simulations.outlet_x / outlet_y                  declared study outlet         M ``geometry.declared_outlet``
simulations.started_at / ended_at / duration_s   reports                       P ``timing``
geographic_metadata.catch_area                   discharge from runoff         M ``geometry.catchment``
geographic_metadata.x_outlet / y_outlet          Run.outlet, watershed figures M ``geometry.catchment``
geographic_metadata.dem_res / nrow / ncol        results.grid, mf6 extractor   M ``geometry.catchment``
geographic_metadata.crs_proj / epsg              results.grid                  M ``geometry.catchment``
parameters.*                                     Run.params, calibration       tables.parquet/parameters; M
metrics.*                                        calibration, reporting        tables.parquet/metrics; M ``metrics``
runs_environment.*                               provenance, reports           P
timeseries / budgets / mass_balance / provenance readers everywhere            tables.parquet/<view>.parquet
geographic_features.*                            watershed and river figures   tables.parquet/geographic_*.parquet
===============================================  ============================  ====================================

Losing ``catch_area`` or the outlet is the dangerous case: discharge derived
from runoff is scaled by the catchment area, so a missing area yields a
silently wrong series rather than an error. They are therefore mandatory
members of the manifest geometry block whenever the run recorded them.

Known gap: ``tags`` and ``sim_notes`` are annotations, mutable after the run
ends; they are not part of the seal and belong to the annotation sidecar.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pyarrow as pa

from hydromodpy.core.logging import get_logger
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    RUN_ANNOTATIONS_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_MANIFEST_FILENAME,
    RUN_PROVENANCE_FILENAME,
    RUN_TRASH_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.parquet_io import write_table_atomic
from hydromodpy.results.storage.parquet_schemas import PARAMETERS_SCHEMA

if TYPE_CHECKING:
    from hydromodpy.results.catalog.facade import Catalog

logger = get_logger(__name__)

MANIFEST_SCHEMA_VERSION = 1
"""Generation of the seal files (``manifest.json`` and ``provenance.json``).

They are written together and read together, so one number versions both.
Bump it on any breaking change to either layout.
"""

PARAMETERS_TABLE_NAME = "parameters"
"""Stem of the run-local parameter payload inside ``tables.parquet``."""

KEY_PACKAGES: tuple[str, ...] = (
    "duckdb",
    "flopy",
    "geopandas",
    "gmsh",
    "matplotlib",
    "netCDF4",
    "numpy",
    "pandas",
    "pyarrow",
    "pyproj",
    "rasterio",
    "scipy",
    "shapely",
    "xarray",
    "zarr",
)
"""Scientific packages whose version changes a result. Pinned in provenance."""

_ARTEFACT_ROLES: dict[str, str] = {
    FIELDS_STORE_NAME: "fields",
    RUN_CONFIG_FILENAME: "config",
    RUN_PROVENANCE_FILENAME: "provenance",
    RUN_MANIFEST_FILENAME: "manifest",
}

_GEOGRAPHIC_METADATA_TYPES: dict[str, str] = {
    "catch_area": "double",
    "dem_res": "double",
    "x_outlet": "double",
    "y_outlet": "double",
    "epsg": "int",
    "nrow": "int",
    "ncol": "int",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def seal_run(catalog: Catalog, sim_id: str | UUID) -> Path:
    """Write the run parameters, provenance and manifest, and return its path.

    Called once, at the end of a completed run, after every other artefact
    has landed. The manifest goes last so its presence certifies the rest.
    """
    sid = str(sim_id)
    run_dir = catalog.run_dir_for(sid)
    run_dir.mkdir(parents=True, exist_ok=True)

    write_parameters_table(catalog, sid)
    write_provenance(catalog, sid)
    return write_manifest(catalog, sid)


def read_manifest(run_dir: Path | str) -> dict[str, Any]:
    """Return the manifest of a run directory.

    Raises
    ------
    FileNotFoundError
        When the directory carries no manifest, i.e. the run never completed.
    """
    path = Path(run_dir) / RUN_MANIFEST_FILENAME
    if not path.is_file():
        raise FileNotFoundError(
            f"No {RUN_MANIFEST_FILENAME} in {run_dir}: this run directory is incomplete."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def is_sealed(run_dir: Path | str) -> bool:
    """Return True when the run directory holds a manifest."""
    return (Path(run_dir) / RUN_MANIFEST_FILENAME).is_file()


# ---------------------------------------------------------------------------
# parameters.parquet
# ---------------------------------------------------------------------------


def write_parameters_table(catalog: Catalog, sim_id: str | UUID) -> Path | None:
    """Write ``tables.parquet/parameters.parquet``, or None when the run has none.

    The values are read back by ``Run.params`` and by the calibration bridge,
    so they cannot live in the index alone.
    """
    sid = str(sim_id)
    records = _parameter_records(catalog, sid)
    if not records:
        return None
    target = catalog.tables_dir_for(sid) / f"{PARAMETERS_TABLE_NAME}{PARQUET_FILE_SUFFIX}"
    target.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(records, schema=PARAMETERS_SCHEMA)
    return write_table_atomic(
        table,
        target,
        pk_cols=("sim_id", "param_name", "zone_id"),
    )


def _parameter_records(catalog: Catalog, sid: str) -> list[dict[str, Any]]:
    """Return the ``parameters`` rows of a run as plain dicts."""
    rows = catalog.backend.fetch_all(
        "SELECT param_name, zone_id, value, unit, parameterization, valid_from "
        "FROM parameters WHERE sim_id = ? ORDER BY param_name, zone_id",
        [sid],
    )
    return [
        {
            "sim_id": sid,
            "param_name": str(row[0]),
            "zone_id": str(row[1]),
            "value": None if row[2] is None else float(row[2]),
            "unit": None if row[3] is None else str(row[3]),
            "parameterization": None if row[4] is None else str(row[4]),
            "valid_from": _utc_instant(row[5]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# provenance.json
# ---------------------------------------------------------------------------


def build_provenance(catalog: Catalog, sim_id: str | UUID) -> dict[str, Any]:
    """Return the provenance payload of a run: what produced these numbers."""
    sid = str(sim_id)
    env = _environment_row(catalog, sid)
    timing = _timing_row(catalog, sid)
    packages = _package_versions(env.get("env_packages"))
    return {
        "provenance_version": MANIFEST_SCHEMA_VERSION,
        "sim_id": sid,
        "tool": {
            "name": "hydromodpy",
            "version": env.get("hydromodpy_version"),
        },
        "git": {
            "commit": env.get("git_commit"),
            "dirty": env.get("git_dirty"),
            "project_commit": env.get("project_git_commit"),
        },
        "python": {"version": env.get("python_version")},
        "platform": {
            "platform": env.get("platform"),
            "hostname": env.get("hostname"),
            "user": env.get("user_name"),
            "cpu": _decode_json(env.get("cpu_info")) or {},
            "memory_gb": env.get("memory_gb"),
        },
        "packages": packages,
        "environment": {
            "conda_env_hash": env.get("conda_env_hash"),
            "rng_seed": env.get("rng_seed"),
            "packages_frozen": _decode_json(env.get("env_packages")) or [],
        },
        "solver": {
            "name": env.get("solver_name"),
            "engine": env.get("solver_engine"),
            "execution_mode": env.get("solver_execution_mode"),
            "version": env.get("solver_version_text"),
            "binary_path": env.get("solver_binary_path"),
            "binary_sha256": env.get("solver_binary_sha256"),
        },
        "timing": timing,
    }


def write_provenance(catalog: Catalog, sim_id: str | UUID) -> Path:
    """Write ``provenance.json`` in the run directory and return its path."""
    sid = str(sim_id)
    target = catalog.run_dir_for(sid) / RUN_PROVENANCE_FILENAME
    _write_json_atomic(target, build_provenance(catalog, sid))
    return target


def _environment_row(catalog: Catalog, sid: str) -> dict[str, Any]:
    """Return the ``runs_environment`` row of a run, empty when unrecorded."""
    columns = (
        "python_version",
        "hydromodpy_version",
        "platform",
        "hostname",
        "user_name",
        "cpu_info",
        "memory_gb",
        "git_commit",
        "git_dirty",
        "project_git_commit",
        "solver_name",
        "solver_engine",
        "solver_execution_mode",
        "solver_binary_path",
        "solver_binary_sha256",
        "solver_version_text",
        "conda_env_hash",
        "env_packages",
        "rng_seed",
    )
    row = catalog.backend.fetch_one(
        f"SELECT {', '.join(columns)} FROM runs_environment WHERE sim_id = ?",
        [sid],
    )
    if row is None:
        return {}
    return dict(zip(columns, row, strict=True))


def _timing_row(catalog: Catalog, sid: str) -> dict[str, Any]:
    """Return the start/end/duration of a run."""
    row = catalog.backend.fetch_one(
        "SELECT started_at, ended_at, duration_s FROM simulations WHERE sim_id = ?",
        [sid],
    )
    if row is None:
        return {"started_at": None, "ended_at": None, "duration_s": None}
    return {
        "started_at": _iso(row[0]),
        "ended_at": _iso(row[1]),
        "duration_s": None if row[2] is None else float(row[2]),
    }


def _package_versions(frozen: Any) -> dict[str, str]:
    """Extract the :data:`KEY_PACKAGES` versions from a ``pip freeze`` list."""
    lines = _decode_json(frozen) or []
    wanted = {name.lower(): name for name in KEY_PACKAGES}
    found: dict[str, str] = {}
    for line in lines:
        text = str(line)
        if "==" not in text:
            continue
        name, _, version = text.partition("==")
        canonical = wanted.get(name.strip().lower())
        if canonical is not None:
            found[canonical] = version.strip()
    return dict(sorted(found.items()))


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------


def build_manifest(catalog: Catalog, sim_id: str | UUID) -> dict[str, Any]:
    """Return the manifest payload of a run."""
    sid = str(sim_id)
    row = _simulation_row(catalog, sid)
    run_dir = catalog.run_dir_for(sid)
    return {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "sealed_at": datetime.now(UTC).isoformat(),
        "run": _identity_block(row),
        "geometry": _geometry_block(catalog, sid, row),
        "period": {
            "start": _iso(row.get("period_start")),
            "end": _iso(row.get("period_end")),
            "n_timesteps": _int_or_none(row.get("n_timesteps")),
            "time_unit": row.get("time_unit"),
        },
        "config": {
            "file": RUN_CONFIG_FILENAME if (run_dir / RUN_CONFIG_FILENAME).is_file() else None,
            "hash": row.get("config_hash"),
            "source": row.get("config_source"),
        },
        "artifacts": list_artifacts(run_dir),
        "parameters": _manifest_parameters(catalog, sid),
        "metrics": _manifest_metrics(catalog, sid),
    }


def write_manifest(catalog: Catalog, sim_id: str | UUID) -> Path:
    """Write ``manifest.json`` atomically and return its path.

    Last write of a run: everything it inventories is already on disk.
    """
    sid = str(sim_id)
    run_dir = catalog.run_dir_for(sid)
    payload = build_manifest(catalog, sid)
    if payload["config"]["file"] is None:
        logger.warning(
            "Run %s has no %s: the resolved configuration was not frozen on disk.",
            sid[:8],
            RUN_CONFIG_FILENAME,
        )
    target = run_dir / RUN_MANIFEST_FILENAME
    _write_json_atomic(target, payload)
    return target


def list_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    """Inventory the run directory: relative path, role and format of each item.

    Directories that are stores in their own right (``fields.zarr``) are listed
    as one entry, not walked. Sizes are reported for files only: hashing or
    walking a multi-gigabyte Zarr at seal time would cost more than the index
    it replaces. The manifest lists itself, without a size, since it cannot
    know its own length before it is written. ``annotations.json`` and
    ``trash.json`` are left out entirely: both change after the seal, so any
    size recorded for them would be wrong by the next ``hmp catalog tag`` or
    ``hmp catalog trash``.
    """
    entries: list[dict[str, Any]] = [
        {"path": RUN_MANIFEST_FILENAME, "role": "manifest", "format": "json"}
    ]
    for path in sorted(run_dir.iterdir()):
        name = path.name
        if name in (RUN_MANIFEST_FILENAME, RUN_ANNOTATIONS_FILENAME, RUN_TRASH_FILENAME):
            continue
        if name == FIELDS_STORE_NAME:
            entries.append({"path": name, "role": "fields", "format": "zarr"})
        elif name == TABLES_DIRNAME and path.is_dir():
            entries.extend(_table_artifacts(run_dir, path))
        elif name == RUN_FIGURES_DIRNAME and path.is_dir():
            entries.extend(_figure_artifacts(run_dir, path))
        elif path.is_file():
            entries.append(
                {
                    "path": name,
                    "role": _ARTEFACT_ROLES.get(name, "other"),
                    "format": path.suffix.lstrip(".") or "unknown",
                    "bytes": path.stat().st_size,
                }
            )
    return entries


def _table_artifacts(run_dir: Path, tables_dir: Path) -> list[dict[str, Any]]:
    """List the Parquet payloads of a run, one entry per table."""
    return [
        {
            "path": path.relative_to(run_dir).as_posix(),
            "role": f"table:{path.stem}",
            "format": "parquet",
            "bytes": path.stat().st_size,
        }
        for path in sorted(tables_dir.glob(f"*{PARQUET_FILE_SUFFIX}"))
        if path.is_file()
    ]


def _figure_artifacts(run_dir: Path, figures_dir: Path) -> list[dict[str, Any]]:
    """List the figures rendered for a run."""
    return [
        {
            "path": path.relative_to(run_dir).as_posix(),
            "role": "figure",
            "format": path.suffix.lstrip(".") or "unknown",
            "bytes": path.stat().st_size,
        }
        for path in sorted(figures_dir.rglob("*"))
        if path.is_file()
    ]


def _simulation_row(catalog: Catalog, sid: str) -> dict[str, Any]:
    """Return the ``simulations`` row of a run with its vocabulary resolved."""
    columns = (
        "sim_id",
        "name",
        "name_stem",
        "version_int",
        "project",
        "solver",
        "solver_category",
        "status",
        "flow_regime",
        "mesh_topology",
        "mesh_hash",
        "n_cells",
        "n_layers",
        "n_timesteps",
        "crs_wkt",
        "crs_epsg",
        "bbox_xmin",
        "bbox_ymin",
        "bbox_xmax",
        "bbox_ymax",
        "period_start",
        "period_end",
        "time_unit",
        "config_hash",
        "config_source",
        "parent_sim_id",
        "geographic_fingerprint",
        "created_at",
        "started_at",
        "ended_at",
        "duration_s",
        "description",
        "scientific_objective",
        "study_area_name",
        "contact_email",
        "doi",
        "outlet_x",
        "outlet_y",
    )
    row = catalog.backend.fetch_one(
        """SELECT s.sim_id, s.name, s.name_stem, s.version_int, s.project,
                  sv.code, sv.category, st.code, fr.code, mt.code,
                  s.mesh_hash, s.n_cells, s.n_layers, s.n_timesteps,
                  s.crs_wkt, s.crs_epsg,
                  s.bbox_xmin, s.bbox_ymin, s.bbox_xmax, s.bbox_ymax,
                  s.period_start, s.period_end, s.time_unit,
                  s.config_hash, s.config_source, s.parent_sim_id,
                  s.geographic_fingerprint,
                  s.created_at, s.started_at, s.ended_at, s.duration_s,
                  s.description, s.scientific_objective, s.study_area_name,
                  s.contact_email, s.doi, s.outlet_x, s.outlet_y
             FROM simulations s
             JOIN solvers sv ON s.solver_id = sv.id
             JOIN statuses st ON s.status_id = st.id
             LEFT JOIN flow_regimes fr ON s.flow_regime_id = fr.id
             LEFT JOIN mesh_topologies mt ON s.mesh_topology_id = mt.id
            WHERE s.sim_id = ?""",
        [sid],
    )
    if row is None:
        raise KeyError(f"No simulation {sid[:8]} to seal")
    return dict(zip(columns, row, strict=True))


def _identity_block(row: dict[str, Any]) -> dict[str, Any]:
    """Return who this run is: name, version, status, project, dates."""
    return {
        "sim_id": str(row["sim_id"]),
        "name": row.get("name"),
        "name_stem": row.get("name_stem"),
        "version": _int_or_none(row.get("version_int")),
        "status": row.get("status"),
        "project": row.get("project"),
        "solver": row.get("solver"),
        "solver_category": row.get("solver_category"),
        "flow_regime": row.get("flow_regime"),
        "parent_sim_id": None if row.get("parent_sim_id") is None else str(row["parent_sim_id"]),
        "created_at": _iso(row.get("created_at")),
        "started_at": _iso(row.get("started_at")),
        "ended_at": _iso(row.get("ended_at")),
        "duration_s": None if row.get("duration_s") is None else float(row["duration_s"]),
        "description": row.get("description"),
        "scientific_objective": row.get("scientific_objective"),
        "study_area_name": row.get("study_area_name"),
        "contact_email": row.get("contact_email"),
        "doi": row.get("doi"),
    }


def _geometry_block(catalog: Catalog, sid: str, row: dict[str, Any]) -> dict[str, Any]:
    """Return the spatial identity of a run, catchment metadata included.

    ``declared_outlet`` is the outlet the user declared in the configuration;
    ``catchment.x_outlet`` / ``y_outlet`` is the pour point the delineation
    actually used. They are recorded separately because they can differ.
    """
    bbox = [row.get(f"bbox_{k}") for k in ("xmin", "ymin", "xmax", "ymax")]
    return {
        "n_cells": _int_or_none(row.get("n_cells")),
        "n_layers": _int_or_none(row.get("n_layers")),
        "mesh_topology": row.get("mesh_topology"),
        "mesh_hash": row.get("mesh_hash"),
        "crs_wkt": row.get("crs_wkt"),
        "crs_epsg": _int_or_none(row.get("crs_epsg")),
        "bbox": None if any(v is None for v in bbox) else [float(v) for v in bbox],
        "geographic_fingerprint": row.get("geographic_fingerprint"),
        "declared_outlet": _outlet(row.get("outlet_x"), row.get("outlet_y")),
        "catchment": _catchment_metadata(catalog, sid),
    }


def _catchment_metadata(catalog: Catalog, sid: str) -> dict[str, Any]:
    """Return ``geographic_metadata`` with its declared types applied.

    Keys keep their index names so a rebuild restores the table verbatim.
    ``catch_area`` is in km2, ``dem_res`` in metres, ``x_outlet`` / ``y_outlet``
    in the project CRS.
    """
    rows = catalog.backend.fetch_all(
        "SELECT key, value, value_type FROM geographic_metadata WHERE sim_id = ? ORDER BY key",
        [sid],
    )
    metadata: dict[str, Any] = {}
    for key, value, value_type in rows:
        declared = _GEOGRAPHIC_METADATA_TYPES.get(str(key), str(value_type))
        metadata[str(key)] = _coerce(value, declared)
    return metadata


def _manifest_parameters(catalog: Catalog, sid: str) -> list[dict[str, Any]]:
    """Return the run parameters, readable straight from the manifest."""
    return [
        {
            "name": record["param_name"],
            "zone": record["zone_id"],
            "value": record["value"],
            "unit": record["unit"],
            "parameterization": record["parameterization"],
        }
        for record in _parameter_records(catalog, sid)
    ]


def _manifest_metrics(catalog: Catalog, sid: str) -> list[dict[str, Any]]:
    """Return the metric summary of a run."""
    rows = catalog.backend.fetch_all(
        "SELECT station_id, variable, metric_name, value, n_samples "
        "FROM metrics WHERE sim_id = ? ORDER BY station_id, variable, metric_name",
        [sid],
    )
    return [
        {
            "station": str(row[0]),
            "variable": str(row[1]),
            "metric": str(row[2]),
            "value": None if row[3] is None else float(row[3]),
            "n_samples": _int_or_none(row[4]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _write_json_atomic(target: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` as indented JSON through a temporary sibling file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=False, default=str) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def _decode_json(value: Any) -> Any:
    """Return a JSON column as Python, passing through already-decoded values."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(str(value))


def _coerce(value: Any, value_type: str) -> Any:
    """Cast a stringly-typed metadata value to its declared type."""
    if value is None:
        return None
    text = str(value)
    if value_type == "double":
        return float(text)
    if value_type == "int":
        return int(float(text))
    if value_type == "bool":
        return text.strip().lower() in {"1", "true", "yes"}
    return text


def _utc_instant(value: Any) -> datetime | None:
    """Return a timestamp column as a UTC-aware instant.

    ``valid_from`` is declared ``timestamp[ms, tz=UTC]`` in the Parquet schema
    and pyarrow *labels* whatever it receives: hand it a naive datetime and the
    wall clock it carries is stamped as UTC, shifting the instant by the local
    offset. ``astimezone`` reads a naive value as local time - which is what a
    bare ``datetime`` out of a driver means - and converts it, so the file
    always holds the real instant.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return datetime.fromisoformat(str(value)).astimezone(UTC)


def _int_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


def _outlet(x: Any, y: Any) -> dict[str, float] | None:
    if x is None or y is None:
        return None
    return {"x": float(x), "y": float(y)}


def _iso(value: Any) -> str | None:
    """Render a timestamp column as ISO-8601, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


__all__ = [
    "KEY_PACKAGES",
    "MANIFEST_SCHEMA_VERSION",
    "PARAMETERS_TABLE_NAME",
    "build_manifest",
    "build_provenance",
    "is_sealed",
    "list_artifacts",
    "read_manifest",
    "seal_run",
    "write_manifest",
    "write_parameters_table",
    "write_provenance",
]
