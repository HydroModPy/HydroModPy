"""The run manifest: the schema of the seal and its reader.

Why
---
``.hmp/index.duckdb`` is a rebuildable index, not the truth. Every value the
index carries and that execution code reads back is also written into the
run directory, and ``manifest.json`` seals that directory. The seal is built
in memory by :class:`~hydromodpy.results.record.RunRecord` from the facts the
run accumulated in its store and written by it, ``manifest.json`` last and
durable; this module is the schema of that document and its reader.

Schema, version 2
-----------------
:class:`Manifest` is the typed seal (:data:`RUN_RECORD_MANIFEST_VERSION`).
Its blocks: ``run`` (who), ``site`` (which basin, with its fingerprint),
``geometry``, ``period``, ``config``, ``lineage`` (by ids), ``identity`` (the
block every exported file carries, without a label), ``checks`` (the
measured facts a label derives from), ``inputs`` (the files the configuration
declared), ``artifacts`` (the sealed entries of the directory, ``inputs.json``
and ``mesh/`` included), ``parameters`` (with their origin), ``metrics`` (with
their window and rule version), ``score`` (the headline metric under its
rule), the calibration ``objective_*`` and ``budget``.

A manifest exists only for a completed run: its presence is what
``completed`` means. A failed or aborted attempt writes ``outcome.json``,
``README.md`` and the tables it has, never ``manifest.json``.

``config.toml`` is not written here: the workflow freezes it into the run
directory when the run is prepared. The manifest lists it and records its
hash.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import Field, field_validator

from hydromodpy.core.config_kit.base import HydroModelBase
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
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.json_io import read_sealed_json
from hydromodpy.schema.generated_views import GENERATED_VIEWS

RUN_RECORD_MANIFEST_VERSION = 2
"""Generation of the seal files, written by :class:`~hydromodpy.results.record.RunRecord`.

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
    license: str | None = Field(
        default=None, description="SPDX licence the run may state, from the inputs it read"
    )

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


RUNTIME_VARIABLE: Final[str] = "runtime"
"""Variable of a metric row that is a number of the run itself (solve time, budget), not a score."""


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

    @property
    def is_runtime(self) -> bool:
        """Whether the row is a number of the run itself, which no score reader lists."""
        return self.variable == RUNTIME_VARIABLE


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


def read_manifest(run_dir: Path | str) -> dict[str, Any]:
    """Return the manifest of a run directory.

    Raises
    ------
    FileNotFoundError
        When the directory carries no manifest, i.e. the run never completed.
    hydromodpy.core.exceptions.SchemaVersionMismatchError
        When its ``manifest_version`` is missing or is not
        :data:`RUN_RECORD_MANIFEST_VERSION`; the message names the version
        that wrote it.
    """
    path = Path(run_dir) / RUN_MANIFEST_FILENAME
    if not path.is_file():
        raise FileNotFoundError(
            f"No {RUN_MANIFEST_FILENAME} in {run_dir}: this run directory is incomplete."
        )
    return read_sealed_json(path, RUN_RECORD_MANIFEST_VERSION, key="manifest_version")


def is_sealed(run_dir: Path | str) -> bool:
    """Return True when the run directory holds a manifest."""
    return (Path(run_dir) / RUN_MANIFEST_FILENAME).is_file()


def list_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    """Inventory the run directory: relative path, role, format and size of each item.

    Directories that are stores in their own right (``fields.zarr``) are listed
    as one entry, not walked, but their ``bytes`` is the sum of the files they
    hold: the field store is the heaviest thing a run owns, and a manifest that
    sizes only the small files cannot answer *what does this run weigh*. The
    walk costs a stat per chunk, under a millisecond for a typical store. The
    manifest lists itself, without a size, since it cannot know its own length
    before it is written. ``annotations.json`` is left out entirely: it
    changes after the seal, so any size recorded for it would be wrong by the
    next ``hmp catalog tag``. The
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
        if name in (RUN_MANIFEST_FILENAME, RUN_ANNOTATIONS_FILENAME):
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


__all__ = [
    "KEY_PACKAGES",
    "PARAMETERS_TABLE_NAME",
    "RUN_RECORD_MANIFEST_VERSION",
    "RUNTIME_VARIABLE",
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
    "is_sealed",
    "list_artifacts",
    "read_manifest",
]
