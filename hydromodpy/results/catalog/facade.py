"""Catalog facade composing every concern mixin.

:class:`SimulationCatalog` is the single object every caller depends on.
It owns the DuckDB connection, the workspace layout, the open-Zarr-handle
tracker, and a :class:`StoragePathResolver`. Domain operations live in
sibling modules (writes, reads, discovery, package_io, lifecycle) and
are mixed in here via plain inheritance.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider
from hydromodpy.core.io.db_retry import connect_with_retry
from hydromodpy.core.logging import get_logger
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

    import xarray as xr

logger = get_logger(__name__)


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
    - ``_workspace``: the project catalog root.
    - ``_paths``: a :class:`StoragePathResolver` translating simulation ids to
      on-disk basenames and Parquet/Zarr paths.
    - ``_open_zarr_handles``: live :class:`SimulationZarr` handles, tracked
      so ``finalize`` and ``close`` can release them deterministically.

    Parameters
    ----------
    workspace_path
        Workspace directory, or direct path to a ``.duckdb`` catalog file.
    catalog_path
        Optional explicit catalog database path.
    simulations_dir
        Optional directory containing simulation Zarr and Parquet stores.
    persistence
        Storage policy for packed or unpacked field arrays.
    register_global
        Register this workspace in the user-level global catalog index.

    Examples
    --------
    >>> catalog = SimulationCatalog("~/hmp_workspace")
    >>> latest = catalog.latest()
    >>> latest.summary()

    See Also
    --------
    hydromodpy.results.run.Run
        Per-simulation view returned by catalog queries.
    hydromodpy.results.simulation_group.SimulationGroup
        Multi-run view returned by cohort queries.
    """

    def __init__(
        self,
        workspace_path: Path | str,
        *,
        catalog_path: Path | str | None = None,
        simulations_dir: Path | str | None = None,
        persistence: PersistenceConfig | None = None,
        register_global: bool = False,
    ) -> None:
        root = Path(workspace_path).expanduser()
        if catalog_path is None and root.suffix == ".duckdb":
            catalog = root.resolve()
            root = catalog.parent
        else:
            root = root.resolve()
            catalog = (
                Path(catalog_path).expanduser().resolve()
                if catalog_path is not None
                else root / "hydromodpy.duckdb"
            )

        self._workspace = root
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._persistence = persistence or PersistenceConfig()

        self._db_path = catalog
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = connect_with_retry(str(self._db_path))

        self._simulations_dir = (
            Path(simulations_dir).expanduser().resolve()
            if simulations_dir is not None
            else self._workspace / "simulations"
        )
        self._simulations_dir.mkdir(parents=True, exist_ok=True)
        self._open_zarr_handles: list[SimulationZarr] = []
        self._paths = StoragePathResolver(self._db, self._simulations_dir)

        ensure_schema(self._db, self._workspace, simulations_dir=self._simulations_dir)
        if register_global:
            self._register_global_project()

    @classmethod
    def from_workspace(
        cls,
        workspace: object,
        *,
        persistence: PersistenceConfig | None = None,
        register_global: bool = False,
    ) -> SimulationCatalog:
        """Open the project catalog declared by a runtime workspace object.

        Parameters
        ----------
        workspace
            Object exposing ``project_root``, ``catalog_path``, and
            ``simulations_dir``.
        persistence
            Optional storage policy.
        register_global
            Register this workspace in the global catalog index.

        Returns
        -------
        SimulationCatalog
            Open catalog connected to the workspace database.
        """
        return cls(
            Path(workspace.project_root),
            catalog_path=Path(workspace.catalog_path),
            simulations_dir=Path(workspace.simulations_dir),
            persistence=persistence,
            register_global=register_global,
        )

    @classmethod
    def from_workspace_config(
        cls,
        workspace: object,
        *,
        persistence: PersistenceConfig | None = None,
        register_global: bool = False,
    ) -> SimulationCatalog:
        """Open the project catalog declared by a workspace configuration.

        Parameters
        ----------
        workspace
            Workspace configuration object.
        persistence
            Optional storage policy.
        register_global
            Register this workspace in the global catalog index.

        Returns
        -------
        SimulationCatalog
            Open catalog connected to the configured workspace.
        """
        return cls(
            Path(workspace.project_root),
            catalog_path=Path(workspace.catalog_path),
            simulations_dir=Path(workspace.simulations_dir),
            persistence=persistence,
            register_global=register_global,
        )

    @classmethod
    def from_toml(cls, toml_path: str | Path) -> SimulationCatalog:
        """Open the project catalog declared in a TOML config.

        Parameters
        ----------
        toml_path
            HydroModPy TOML file with a workspace section.

        Returns
        -------
        SimulationCatalog
            Open catalog connected to the resolved workspace.
        """
        cfg = get_root_config_provider().from_toml(toml_path)
        return cls.from_workspace_config(cfg.workspace)

    @classmethod
    def from_json(cls, payload: str | bytes) -> SimulationCatalog:
        """Open the project catalog declared in a JSON config string."""
        cfg = get_root_config_provider().from_json(payload)
        return cls.from_workspace_config(cfg.workspace)

    @classmethod
    def from_dict(cls, payload: dict) -> SimulationCatalog:
        """Open the project catalog declared in a dict config payload."""
        cfg = get_root_config_provider().from_dict(payload)
        return cls.from_workspace_config(cfg.workspace)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Return the DuckDB connection for protocol-based integrations."""
        return self._db

    @property
    def workspace_path(self) -> Path:
        """Workspace directory that owns this catalog."""
        return self._workspace

    @property
    def catalog_path(self) -> Path:
        """Path to the ``hydromodpy.duckdb`` catalog file."""
        return self._db_path

    @property
    def simulations_dir(self) -> Path:
        """Directory where simulation stores are written."""
        return self._simulations_dir

    @property
    def project_path(self) -> Path:
        """Alias for ``workspace_path`` kept for protocol integrations."""
        return self._workspace

    def zarr_path_for(self, sim_id: str | UUID) -> Path:
        """Return the Zarr artefact path on disk (``.zarr.zip`` if packed)."""
        return self._paths.zarr_path_for(sim_id)

    def parquet_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the per-simulation Parquet directory (public accessor)."""
        return self._paths.parquet_dir_for(sim_id)

    def load_dataset(
        self,
        filters: dict[str, Any] | None = None,
        *,
        fields: list[str] | None = None,
        include_params: bool = True,
        include_metrics: bool = True,
        include_env: bool = True,
    ) -> xr.Dataset:
        """Return one ``xr.Dataset`` joining scalars and Zarr fields.

        Composition entry-point for ML/DL pipelines: bundles parameters,
        metrics, ``runs_environment`` metadata, and (optionally) lazy Zarr
        fields into a single :class:`xarray.Dataset` indexed by ``sim_id``.
        See :class:`hydromodpy.results.catalog.dataset_loader.DatasetLoader`.

        Parameters
        ----------
        filters
            Catalog filters used to select the simulation cohort.
        fields
            Optional field names to include from Zarr stores.
        include_params
            Include parameter columns in the dataset.
        include_metrics
            Include metric columns in the dataset.
        include_env
            Include runtime environment metadata.

        Returns
        -------
        xarray.Dataset
            Dataset indexed by ``sim_id`` with scalar tables and optional lazy
            field arrays.
        """
        from hydromodpy.results.catalog.dataset_loader import DatasetLoader

        return DatasetLoader(self).load(
            filters,
            fields=fields,
            include_params=include_params,
            include_metrics=include_metrics,
            include_env=include_env,
        )

    def __repr__(self) -> str:
        try:
            count = self._db.execute("SELECT COUNT(*) FROM simulations").fetchone()[0]
        except Exception:
            count = "?"
        return f"SimulationCatalog(workspace={str(self._workspace)!r}, simulations={count})"

    def _register_global_project(self) -> None:
        try:
            from hydromodpy.results.catalog.global_index import CatalogIndex

            CatalogIndex().register_project(
                project_root=self._workspace,
                catalog_path=self._db_path,
                simulations_dir=self._simulations_dir,
            )
        except Exception:
            logger.debug("Could not register project catalog in global index", exc_info=True)

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
