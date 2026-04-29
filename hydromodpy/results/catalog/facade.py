"""Catalog facade composing every concern mixin.

:class:`SimulationCatalog` is the single object every caller depends on.
It owns the DuckDB connection, the workspace layout, the open-Zarr-handle
tracker, and a :class:`StoragePathResolver`. Domain operations live in
sibling modules (writes, reads, discovery, package_io, lifecycle) and
are mixed in here via plain inheritance.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from hydromodpy.core.io.db_retry import connect_with_retry
from hydromodpy.results.catalog.discovery import DiscoveryMixin
from hydromodpy.results.catalog.lifecycle import LifecycleMixin
from hydromodpy.results.catalog.package_io import PackageIOMixin
from hydromodpy.results.catalog.reads import ReadsMixin
from hydromodpy.results.catalog.registration import RegistrationMixin
from hydromodpy.results.catalog.storage_paths import StoragePathResolver
from hydromodpy.results.catalog.writes import WritesMixin
from hydromodpy.results.catalog_schema import ensure_schema
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    from uuid import UUID


class SimulationCatalog(
    LifecycleMixin,
    RegistrationMixin,
    WritesMixin,
    ReadsMixin,
    DiscoveryMixin,
    PackageIOMixin,
):
    """Workspace-level catalog of finished simulations.

    Backed by DuckDB for tabular state (simulations, parameters, metrics,
    provenance, calibration sessions) and by Zarr / Parquet for field arrays
    and timeseries written under ``<workspace>/simulations/``.

    The facade owns four pieces of state:

    - ``_db``: the DuckDB connection (re-acquired with retry on contention).
    - ``_workspace``: the workspace root.
    - ``_paths``: a :class:`StoragePathResolver` translating ``sim_id``s to
      on-disk basenames and Parquet/Zarr paths.
    - ``_open_zarr_handles``: live :class:`SimulationZarr` handles, tracked
      so ``finalize`` and ``close`` can release them deterministically.
    """

    def __init__(self, workspace_path: Path | str) -> None:
        self._workspace = Path(workspace_path)
        self._workspace.mkdir(parents=True, exist_ok=True)

        self._db_path = self._workspace / "hydromodpy.duckdb"
        self._db = connect_with_retry(str(self._db_path))

        self._simulations_dir = self._workspace / "simulations"
        self._simulations_dir.mkdir(exist_ok=True)
        self._open_zarr_handles: list[SimulationZarr] = []
        self._paths = StoragePathResolver(self._db, self._simulations_dir)

        ensure_schema(self._db, self._workspace)

    @classmethod
    def from_toml(cls, toml_path: str | Path) -> SimulationCatalog:
        """Open the catalog whose workspace is declared in a TOML config."""
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

        cfg = HydroModPyConfig.from_toml(toml_path)
        return cls(cfg.workspace.root)

    @classmethod
    def from_json(cls, payload: str | bytes) -> SimulationCatalog:
        """Open the catalog whose workspace is declared in a JSON config string."""
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

        cfg = HydroModPyConfig.model_validate_json(payload)
        return cls(cfg.workspace.root)

    @classmethod
    def from_dict(cls, payload: dict) -> SimulationCatalog:
        """Open the catalog whose workspace is declared in a dict config payload."""
        from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig

        cfg = HydroModPyConfig.model_validate(payload)
        return cls(cfg.workspace.root)

    @property
    def _connection(self) -> duckdb.DuckDBPyConnection:
        return self._db

    @property
    def workspace_path(self) -> Path:
        return self._workspace

    @property
    def project_path(self) -> Path:
        return self._workspace

    def zarr_path_for(self, sim_id: str | UUID) -> Path:
        """Return the Zarr artefact path on disk (``.zarr.zip`` if packed)."""
        return self._paths.zarr_path_for(sim_id)

    def parquet_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the per-simulation Parquet directory (public accessor)."""
        return self._paths.parquet_dir_for(sim_id)

    def __repr__(self) -> str:
        try:
            count = self._db.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
        except Exception:
            count = "?"
        return f"SimulationCatalog(workspace={str(self._workspace)!r}, simulations={count})"

    def _repr_html_(self) -> str:
        try:
            count = self._db.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) FROM simulations"
            ).fetchone()
            total, ok, failed = count
            projects = [
                str(r[0])
                for r in self._db.execute("SELECT DISTINCT project FROM simulations").fetchall()
            ]
        except Exception:
            total, ok, failed, projects = 0, 0, 0, []
        projects_str = ", ".join(sorted(projects)) if projects else "&mdash;"
        rows = [
            ("workspace", f"<code>{self._workspace}</code>"),
            ("simulations", f"{total or 0} ({ok or 0} success, {failed or 0} failed)"),
            ("projects", projects_str),
        ]
        body = "".join(
            f"<tr><th style='text-align:left'>{k}</th><td>{v}</td></tr>" for k, v in rows
        )
        return (
            "<div><b>SimulationCatalog</b>"
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            f"{body}</table></div>"
        )
