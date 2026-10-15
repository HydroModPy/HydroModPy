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
3. ``manifest.json`` - identity, geometry, period, config fingerprint, input
   list, artefact list, parameters, metric summary. Written **last** and
   **atomically** (``manifest.json.tmp-<uuid>`` then ``os.replace``), so a run
   directory without a manifest is, by construction, an incomplete run.

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
(none: attributes of fields.zarr/mesh)           engine of the mesh            M ``geometry.mesh_engine``
simulations.zarr_path                            field reads                   fields.zarr in the run directory
(none: attributes of fields.zarr/budget)         missing-field messages        M ``budget``
simulations.config_hash / config_source          comparison, audit             M ``config``
simulations.config_toml / config_snapshot        audit, .hmp packaging         config.toml
simulations.geographic_fingerprint               geographic cache reuse        M ``geometry``
simulations.parent_sim_id                        lineage, spin-up chains       M ``run.parent_sim_id``
simulations.outlet_x / outlet_y                  declared study outlet         M ``geometry.declared_outlet``
simulations.started_at / ended_at / duration_s   reports                       P ``timing``
geographic_metadata.catch_area                   discharge from runoff         M ``geometry.catchment``
geographic_metadata.x_outlet / y_outlet          Run.outlet, watershed figures M ``geometry.catchment``
geographic_metadata.*_outlet_snapped             watershed figures             M ``geometry.catchment``
geographic_metadata.dem_res / nrow / ncol        results.grid, mf6 extractor   M ``geometry.catchment``
geographic_metadata.crs_proj / epsg              results.grid                  M ``geometry.catchment``
parameters.*                                     Run.params, calibration       tables.parquet/parameters; M
metrics.*                                        calibration, reporting        tables.parquet/metrics; M ``metrics``
tracked_files.*                                  .hmp packaging, data reuse    M ``inputs``
runs_environment.*                               provenance, reports           P
timeseries / budgets / mass_balance / provenance readers everywhere            tables.parquet/<view>.parquet
geographic_features.*                            watershed and river figures   tables.parquet/geographic_*.parquet
===============================================  ============================  ====================================

Losing ``catch_area`` or the outlet is the dangerous case: discharge derived
from runoff is scaled by the catchment area, so a missing area yields a
silently wrong series rather than an error. They are therefore mandatory
members of the manifest geometry block whenever the run recorded them.

The ``inputs`` block answers the other provenance question: *which data fed
this run*. Every file the configuration declares as an input is walked at
setup time (``core.tracking.collect_input_files``), hashed, and stored in
``tracked_files``; the seal copies path, digest, size and origin into the
manifest, so the run directory carries its own input provenance and needs
neither the index nor the project lockfile to state it. The lockfile answers
a wider question - the state of the whole data cache before a run - and is
kept for that (see :mod:`hydromodpy.project.lockfile`).

The ``budget`` block repeats what the ``budget/`` group of ``fields.zarr``
says it kept of the per-cell budget: the policy (``all`` or ``consumers``) and
the kept terms. It is absent for a store written before those attributes.

Known gap: ``tags`` and ``sim_notes`` are annotations, mutable after the run
ends; they are not part of the seal and belong to the annotation sidecar.

Schema, version 2
-----------------
:class:`Manifest` is the typed seal (:data:`RUN_RECORD_MANIFEST_VERSION`), built in memory by
:class:`~hydromodpy.results.record.RunRecord` and written by it, without the
index. Its blocks: ``run`` (who), ``site`` (which basin, with its
fingerprint), ``geometry``, ``period``, ``config``, ``lineage`` (by ids),
``identity`` (the block every exported file carries, without a label),
``checks`` (the measured facts a label derives from), ``inputs`` (the files
the configuration declared), ``artifacts`` (the sealed entries of the
directory, ``inputs.json`` and ``mesh/`` included), ``parameters`` (with their
origin), ``metrics`` (with their window and rule version), ``score`` (the
headline metric under its rule), the calibration ``objective_*`` and
``budget``. The block models below are the schema; the functions that still
build a manifest from the index are the writer of version 1
(:data:`MANIFEST_SCHEMA_VERSION`) and go with it.

A manifest exists only for a completed run: its presence is what
``completed`` means. A failed or aborted attempt writes ``outcome.json``,
``README.md`` and the tables it has, never ``manifest.json``.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import pyarrow as pa
import zarr
from pydantic import Field, field_validator

from hydromodpy.core.budget_terms import kept_budget
from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.logging import get_logger
from hydromodpy.results.catalog.writes_helpers import kv_metadata_for_sim
from hydromodpy.results.checks import Checks
from hydromodpy.results.identity import Identity
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.metric_rule import DateWindow, MetricScore
from hydromodpy.results.rel_dir import checked_rel_dir
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    RUN_ANNOTATIONS_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_MANIFEST_FILENAME,
    RUN_PROVENANCE_FILENAME,
    RUN_SCRATCH_ENTRIES,
    RUN_TRASH_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.parquet_io import write_table_atomic
from hydromodpy.results.storage.parquet_schemas import PARAMETERS_SCHEMA
from hydromodpy.schema.generated_views import GENERATED_VIEWS

if TYPE_CHECKING:
    from hydromodpy.results.catalog.facade import Catalog

logger = get_logger(__name__)

MANIFEST_SCHEMA_VERSION = 1
"""Generation of the seal files written from the index by :func:`write_manifest`.

They are written together and read together, so one number versions both.
Bump it on any breaking change to either layout.
"""

RUN_RECORD_MANIFEST_VERSION = 2
"""Generation of the seal files written by :class:`~hydromodpy.results.record.RunRecord`.

Version 2 adds the ``site``, ``lineage``, ``identity``, ``checks``, ``score``
and ``objective_*`` entries, the origin of the parameters and the window of
the metrics.
"""

RunStatus = Literal["completed"]
"""The status of a sealed run: a manifest exists only for a completed run."""

_UNSEALED_STATUS_MESSAGE = (
    "a manifest exists only for a completed run, not a {status!r} one: "
    "a failed or aborted attempt writes outcome.json, README.md and its tables, "
    "never manifest.json"
)

ParameterOrigin = Literal["declared", "site_table", "site_override", "recipe", "calibrated"]
"""Where a parameter value came from."""


class ManifestSite(HydroModelBase):
    """The basin a run was computed on, as the run itself declares it."""

    name: str = Field(description="Site name")
    label: str | None = Field(default=None, description="Human label of the site")
    gauge: str | None = Field(default=None, description="Gauging station of the site")
    uri: str | None = Field(
        default=None, description="Registry uri, hubeau:<code> or bdtopage:<code>"
    )
    fingerprint: str = Field(description="Fingerprint of the site declaration")
    x_outlet: float | None = Field(default=None, description="Declared outlet easting, in crs")
    y_outlet: float | None = Field(default=None, description="Declared outlet northing, in crs")
    crs: str | None = Field(default=None, description="CRS of the outlet")
    area_km2: float | None = Field(default=None, description="Delineated catchment area, km2")
    dem_resolution_m: float | None = Field(default=None, description="DEM cell size used, m")
    snapped_outlet: tuple[float, float] | None = Field(
        default=None, description="Outlet the delineation used, in crs"
    )


class ManifestRun(HydroModelBase):
    """Who this run is: name, version, case, attempt, solver, dates."""

    sim_id: str
    name: str = Field(description="Run name, with its .vN")
    name_stem: str = Field(description="Run name without its .vN")
    version: int = Field(ge=1, description="Version number, 1 for the bare name")
    status: RunStatus = Field(description="Always completed: a seal certifies a completed run")
    project: str
    case_id: str = Field(description="The run name, or site-recipe under [sites]")
    recipe: str | None = Field(default=None, description="Recipe of a planned case")
    rel_dir: str = Field(description="Directory of the run, relative to the project root")
    attempt: int = Field(ge=1, description="Attempt that sealed the run")
    attempt_id: str
    solver: str
    solver_category: str | None = None
    flow_regime: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_s: float | None = Field(default=None, description="Wall clock, started_at to ended_at")
    description: str | None = None
    scientific_objective: str | None = None
    contact_email: str | None = None
    doi: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _completed_only(cls, value: Any) -> Any:
        if value != "completed":
            raise ValueError(_UNSEALED_STATUS_MESSAGE.format(status=value))
        return value

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str) -> str:
        return checked_rel_dir(value)


class ManifestGeometry(HydroModelBase):
    """The spatial identity of a run, catchment metadata included."""

    n_cells: int | None = None
    n_layers: int | None = None
    mesh_topology: str | None = None
    mesh_engine: str | None = None
    mesh_engine_version: str | None = None
    mesh_hash: str | None = None
    crs_wkt: str | None = None
    crs_epsg: int | None = None
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="xmin, ymin, xmax, ymax in the run CRS"
    )
    catchment: dict[str, Any] = Field(
        default_factory=dict,
        description="Catchment metadata: catch_area (km2), dem_res (m), x_outlet, y_outlet...",
    )


class ManifestPeriod(HydroModelBase):
    """The simulated period; empty for a steady run."""

    start: datetime | None = None
    end: datetime | None = None
    n_timesteps: int | None = None
    time_unit: str | None = None


class ManifestConfig(HydroModelBase):
    """The frozen configuration of the run and its identity hash."""

    file: str | None = Field(default=None, description="config.toml when it was frozen")
    hash: str | None = Field(default=None, description="Identity hash, without [workspace]")
    source: str | None = Field(default=None, description="File the run was launched from")


class TrackedInput(HydroModelBase):
    """One file the configuration declared and the run read."""

    role: str
    category: str
    path: str = Field(description="Workspace-encoded location the run read")
    declared_path: str = Field(description="Value written in the configuration")
    sha256: str
    bytes: int | None = None
    portable: bool


class InputEntry(HydroModelBase):
    """One loaded input, as ``inputs.json`` records it: provider, product, request, digest."""

    variable: str = Field(description="Variable the input fed")
    provider: str = Field(description="Provider of the input: hubeau, sim2, bdtopage, file...")
    product: str | None = Field(default=None, description="Product of the provider")
    product_version: str | None = Field(default=None, description="Version of the product")
    request: dict[str, Any] = Field(
        default_factory=dict, description="bbox, period, stations, step"
    )
    fetched_at: datetime | None = Field(default=None, description="Instant the bytes were fetched")
    path: str = Field(description="Location of the bytes, relative to the workspace or the run")
    sha256: str | None = Field(default=None, description="Digest of the bytes")
    bytes: int | None = None
    license: str | None = Field(default=None, description="Licence of the provider")


class ParameterRow(HydroModelBase):
    """One parameter value of a run, in one zone."""

    name: str = Field(description="Parameter name as the solver builder knows it")
    zone: str = Field(default="__global__", description="Zone the value applies to")
    value: float | None = None
    unit: str | None = None
    parameterization: str | None = Field(default=None, description="uniform, zonal, field...")
    origin: ParameterOrigin
    calibrated: bool = Field(description="True when a calibration set the value")


class MetricRow(HydroModelBase):
    """One metric of a run, with the window and rule it was computed under.

    The window columns keep the ``nse_`` prefix whatever the metric, as in
    :class:`~hydromodpy.results.metric_rule.MetricScore` and
    ``simulation.parquet``.
    """

    station: str | None = None
    variable: str | None = None
    metric: str
    value: float | None = None
    nse_window_start: date | None = Field(default=None, description="First day scored")
    nse_window_end: date | None = Field(default=None, description="Last day scored, included")
    nse_n: int | None = Field(default=None, ge=0, description="Samples the score used")
    metric_rule_version: str | None = None


class ManifestArtifact(HydroModelBase):
    """One sealed entry of the run directory."""

    path: str
    role: str
    format: str
    bytes: int | None = None


class ManifestBudget(HydroModelBase):
    """What the field store kept of the per-cell budget."""

    policy: str
    kept_terms: list[str]


class Manifest(HydroModelBase):
    """The seal of a completed run directory, version 2."""

    manifest_version: int = Field(default=RUN_RECORD_MANIFEST_VERSION)
    sealed_at: datetime
    run: ManifestRun
    site: ManifestSite | None = None
    geometry: ManifestGeometry
    period: ManifestPeriod
    config: ManifestConfig
    lineage: Lineage
    identity: Identity
    checks: Checks
    inputs: list[TrackedInput] = Field(default_factory=list)
    artifacts: list[ManifestArtifact] = Field(default_factory=list)
    parameters: list[ParameterRow] = Field(default_factory=list)
    metrics: list[MetricRow] = Field(default_factory=list)
    score: MetricScore | None = None
    objective_name: str | None = Field(default=None, description="Objective of the session")
    objective_value: float | None = Field(default=None, description="Its value for this run")
    objective_window: DateWindow | None = Field(
        default=None, description="Window the session scored the objective on"
    )
    budget: ManifestBudget | None = None


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
    "x_outlet_snapped": "double",
    "y_outlet_snapped": "double",
    "outlet_snap_distance_m": "double",
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
        kv_metadata=kv_metadata_for_sim(catalog.backend, sid, workspace=catalog.workspace_path),
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
            "origin": "calibrated" if row[4] == "calibrated" else "declared",
            "calibrated": row[4] == "calibrated",
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
    payload: dict[str, Any] = {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "sealed_at": datetime.now(UTC).isoformat(),
        "run": _identity_block(row),
        "geometry": _geometry_block(catalog, sid, row, run_dir),
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
        "inputs": _manifest_inputs(catalog, sid),
        "artifacts": list_artifacts(run_dir),
        "parameters": _manifest_parameters(catalog, sid),
        "metrics": _manifest_metrics(catalog, sid),
    }
    budget = _budget_block(run_dir)
    if budget is not None:
        payload["budget"] = budget
    return payload


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
    """Inventory the run directory: relative path, role, format and size of each item.

    Directories that are stores in their own right (``fields.zarr``) are listed
    as one entry, not walked, but their ``bytes`` is the sum of the files they
    hold: the field store is the heaviest thing a run owns, and a manifest that
    sizes only the small files cannot answer *what does this run weigh*. The
    walk costs a stat per chunk, under a millisecond for a typical store. The
    manifest lists itself, without a size, since it cannot know its own length
    before it is written. ``annotations.json`` and ``trash.json`` are left out
    entirely: both change after the seal, so any size recorded for them would
    be wrong by the next ``hmp catalog tag`` or ``hmp catalog trash``. The
    generated views are left out for the same reason: they are rendered from
    the seal, after it, and rendered again on request. The
    runtime scratch of :data:`RUN_SCRATCH_ENTRIES` is left out too, and for a
    different reason: it is not a result. Everything else found in the
    directory is inventoried, named or not, so a stray file stays visible.
    """
    entries: list[dict[str, Any]] = [
        {"path": RUN_MANIFEST_FILENAME, "role": "manifest", "format": "json"}
    ]
    for path in sorted(run_dir.iterdir()):
        name = path.name
        if name in (RUN_MANIFEST_FILENAME, RUN_ANNOTATIONS_FILENAME, RUN_TRASH_FILENAME):
            continue
        if name in GENERATED_VIEWS:
            continue
        if name in RUN_SCRATCH_ENTRIES:
            continue
        if name == FIELDS_STORE_NAME:
            entries.append(
                {
                    "path": name,
                    "role": "fields",
                    "format": "zarr",
                    "bytes": _directory_bytes(path),
                }
            )
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
        elif path.is_dir():
            entries.append(
                {
                    "path": name,
                    "role": "other",
                    "format": "directory",
                    "bytes": _directory_bytes(path),
                }
            )
    return entries


def _directory_bytes(directory: Path) -> int:
    """Return the total size of the files under ``directory``, recursively.

    Unreadable entries count as zero: a size is inventory, never a reason for a
    seal to fail.
    """
    total = 0
    for dirpath, _dirnames, filenames in os.walk(directory):
        for filename in filenames:
            try:
                total += os.stat(os.path.join(dirpath, filename)).st_size
            except OSError:
                continue
    return total


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


def _geometry_block(
    catalog: Catalog, sid: str, row: dict[str, Any], run_dir: Path
) -> dict[str, Any]:
    """Return the spatial identity of a run, catchment metadata included.

    ``declared_outlet`` is the outlet the user declared in the configuration;
    ``catchment.x_outlet`` / ``y_outlet`` is the pour point the delineation
    actually used. They are recorded separately because they can differ.
    ``mesh_engine`` and ``mesh_engine_version`` come from the attributes of the
    ``mesh/`` group, so they are absent for a run sealed before it stored them.
    """
    bbox = [row.get(f"bbox_{k}") for k in ("xmin", "ymin", "xmax", "ymax")]
    return {
        "n_cells": _int_or_none(row.get("n_cells")),
        "n_layers": _int_or_none(row.get("n_layers")),
        "mesh_topology": row.get("mesh_topology"),
        **_mesh_engine_keys(run_dir),
        "mesh_hash": row.get("mesh_hash"),
        "crs_wkt": row.get("crs_wkt"),
        "crs_epsg": _int_or_none(row.get("crs_epsg")),
        "bbox": None if any(v is None for v in bbox) else [float(v) for v in bbox],
        "geographic_fingerprint": row.get("geographic_fingerprint"),
        "declared_outlet": _outlet(row.get("outlet_x"), row.get("outlet_y")),
        "catchment": _catchment_metadata(catalog, sid),
    }


def _open_fields_root(run_dir: Path) -> zarr.Group | None:
    """Return the root of the field store of a run, read-only; None when it has none."""
    store_path = run_dir / FIELDS_STORE_NAME
    if not store_path.is_dir():
        return None
    try:
        return zarr.open_group(str(store_path), mode="r", use_consolidated=False)
    except (FileNotFoundError, KeyError, ValueError, zarr.errors.GroupNotFoundError):
        return None


def _mesh_engine_keys(run_dir: Path) -> dict[str, str]:
    """Return the engine and its version that the ``mesh/`` group names.

    Empty for a run without a field store or sealed before the group named them.
    """
    root = _open_fields_root(run_dir)
    mesh = None if root is None else root.get("mesh")
    if mesh is None:
        return {}
    return {
        f"mesh_{key}": str(mesh.attrs[key])
        for key in ("engine", "engine_version")
        if mesh.attrs.get(key) is not None
    }


def _budget_block(run_dir: Path) -> dict[str, Any] | None:
    """Return what the field store says it kept of the per-cell budget.

    None when the run has no field store or its ``budget/`` group carries no
    policy, which is a store written before the attributes existed.
    """
    root = _open_fields_root(run_dir)
    if root is None:
        return None
    kept = kept_budget(root)
    if kept is None:
        return None
    return {"policy": kept.policy, "kept_terms": list(kept.terms)}


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


def _manifest_inputs(catalog: Catalog, sid: str) -> list[dict[str, Any]]:
    """Return the input files this run consumed: path, digest, size, origin.

    Read from ``tracked_files``, which the setup step fills from the
    configuration tree. ``path`` is the workspace-encoded location the run
    actually read, ``declared_path`` the value written in the configuration,
    and ``role`` / ``category`` say what the file was used for.
    """
    rows = catalog.backend.fetch_all(
        "SELECT role, category, original_path, canonical_path, sha256, size_bytes, portable "
        "FROM tracked_files WHERE sim_id = ? ORDER BY role, canonical_path",
        [sid],
    )
    return [
        {
            "role": str(row[0]),
            "category": str(row[1]),
            "path": str(row[3]),
            "declared_path": str(row[2]),
            "sha256": str(row[4]),
            "bytes": _int_or_none(row[5]),
            "portable": bool(row[6]),
        }
        for row in rows
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
    "RUN_RECORD_MANIFEST_VERSION",
    "InputEntry",
    "Manifest",
    "ManifestArtifact",
    "ManifestBudget",
    "ManifestConfig",
    "ManifestGeometry",
    "ManifestPeriod",
    "ManifestRun",
    "ManifestSite",
    "MetricRow",
    "ParameterOrigin",
    "ParameterRow",
    "RunStatus",
    "TrackedInput",
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
