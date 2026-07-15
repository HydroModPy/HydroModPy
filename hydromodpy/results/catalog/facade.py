"""Catalog facade composing every concern mixin.

:class:`Catalog` is the single object every caller depends on.
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
from hydromodpy.core.io.db_retry import HMP_DUCKDB_BLOCK_SIZE, connect_with_retry
from hydromodpy.core.state.paths import CATALOG_FILENAME
from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend
from hydromodpy.results.catalog.discovery import DiscoveryMixin
from hydromodpy.results.catalog.lifecycle import LifecycleMixin
from hydromodpy.results.catalog.package_io import PackageIOMixin
from hydromodpy.results.catalog.parquet_views import ensure_parquet_views
from hydromodpy.results.catalog.ports import CatalogBackend
from hydromodpy.results.catalog.reads import ReadsMixin
from hydromodpy.results.catalog.registration import RegistrationMixin
from hydromodpy.results.catalog.schema import SchemaDiscoveryMixin
from hydromodpy.results.catalog.storage_paths import StoragePathResolver
from hydromodpy.results.catalog.views import ensure_views
from hydromodpy.results.catalog.writes import WritesMixin
from hydromodpy.results.storage.contract import SIMULATIONS_DIRNAME
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    from uuid import UUID

    import xarray as xr


class Catalog(
    LifecycleMixin,
    RegistrationMixin,
    WritesMixin,
    ReadsMixin,
    DiscoveryMixin,
    SchemaDiscoveryMixin,
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

    Raises
    ------
    hydromodpy.core.exceptions.CatalogError
        If the DuckDB catalog cannot be opened or the schema migration fails.
    hydromodpy.results.errors.SchemaVersionMismatchError
        If the stored catalog schema version is older than the runtime expects.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> catalog = hmp.open("~/hmp_workspace")  # doctest: +SKIP
    >>> latest = catalog.latest()  # doctest: +SKIP
    >>> latest.summary()  # doctest: +SKIP

    See Also
    --------
    hydromodpy.results.run.Run
        Per-simulation view returned by catalog queries.
    hydromodpy.results.run.group.RunSet
        Multi-run view returned by cohort queries.
    """

    def __init__(
        self,
        workspace_path: Path | str,
        *,
        catalog_path: Path | str | None = None,
        simulations_dir: Path | str | None = None,
        persistence: PersistenceConfig | None = None,
        read_only: bool = False,
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
                else root / CATALOG_FILENAME
            )

        self._read_only = read_only
        self._workspace = root
        self._persistence = persistence or PersistenceConfig()
        self._db_path = catalog
        self._simulations_dir = (
            Path(simulations_dir).expanduser().resolve()
            if simulations_dir is not None
            else self._workspace / SIMULATIONS_DIRNAME
        )

        if read_only:
            # Inspection path: open read-only, never mutate. No mkdir, no
            # migration, no DDL persisted; views are session-local TEMPORARY.
            if not self._db_path.is_file():
                raise FileNotFoundError(
                    f"No catalog at {self._db_path} to open read-only. "
                    f"Run a workflow there first, or open writable with create."
                )
            self._db = connect_with_retry(str(self._db_path), read_only=True)
            self._backend = DuckDBBackend.from_connection(
                self._db, path=self._db_path, read_only=True
            )
            self._require_schema_current()
        else:
            self._workspace.mkdir(parents=True, exist_ok=True)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = connect_with_retry(str(self._db_path), block_size=HMP_DUCKDB_BLOCK_SIZE)
            self._backend = DuckDBBackend.from_connection(self._db, path=self._db_path)
            self._simulations_dir.mkdir(parents=True, exist_ok=True)

        self._open_zarr_handles: list[SimulationZarr] = []
        self._paths = StoragePathResolver(self._backend, self._simulations_dir)

        if read_only:
            ensure_parquet_views(self._db, self._simulations_dir, temporary=True)
            ensure_views(self._db, temporary=True)
        else:
            self._backend.ensure_schema()
            ensure_parquet_views(self._db, self._simulations_dir)
            ensure_views(self._db)

    def _require_schema_current(self) -> None:
        """Raise when a read-only open hits a catalog whose schema is behind."""
        from hydromodpy.results.catalog.migrations import current_version, target_version
        from hydromodpy.results.errors import SchemaVersionMismatchError

        current = current_version(self._db)
        target = target_version()
        if current < target:
            raise SchemaVersionMismatchError(
                f"Catalog schema is at version {current} but the runtime expects "
                f"{target}. Run `hmp doctor --migrate` to upgrade it."
            )

    @classmethod
    def from_workspace(
        cls,
        workspace: object,
        *,
        persistence: PersistenceConfig | None = None,
    ) -> Catalog:
        """Open the project catalog declared by a runtime workspace object.

        Parameters
        ----------
        workspace
            Object exposing ``project_root``, ``catalog_path``, and
            ``simulations_dir``.
        persistence
            Optional storage policy.

        Returns
        -------
        Catalog
            Open catalog connected to the workspace database.
        """
        return cls(
            Path(workspace.project_root),
            catalog_path=Path(workspace.catalog_path),
            simulations_dir=Path(workspace.simulations_dir),
            persistence=persistence,
        )

    @classmethod
    def from_workspace_config(
        cls,
        workspace: object,
        *,
        persistence: PersistenceConfig | None = None,
    ) -> Catalog:
        """Open the project catalog declared by a workspace configuration.

        Parameters
        ----------
        workspace
            Workspace configuration object.
        persistence
            Optional storage policy.

        Returns
        -------
        Catalog
            Open catalog connected to the configured workspace.
        """
        return cls(
            Path(workspace.project_root),
            catalog_path=Path(workspace.catalog_path),
            simulations_dir=Path(workspace.simulations_dir),
            persistence=persistence,
        )

    @classmethod
    def from_toml(cls, toml_path: str | Path) -> Catalog:
        """Open the project catalog declared in a TOML config.

        Parameters
        ----------
        toml_path
            HydroModPy TOML file with a workspace section.

        Returns
        -------
        Catalog
            Open catalog connected to the resolved workspace.

        Raises
        ------
        FileNotFoundError
            If the TOML path does not exist.
        ConfigValidationError
            If the TOML payload fails Pydantic validation.
        """
        cfg = get_root_config_provider().from_toml(toml_path)
        return cls.from_workspace_config(cfg.workspace)

    @classmethod
    def from_json(cls, payload: str | bytes) -> Catalog:
        """Open the project catalog declared in a JSON config string.

        Parameters
        ----------
        payload
            JSON payload validated against ``HydroModPyConfig``.

        Returns
        -------
        Catalog
            Open catalog connected to the resolved workspace.

        Raises
        ------
        ConfigValidationError
            If the JSON payload fails validation.
        """
        cfg = get_root_config_provider().from_json(payload)
        return cls.from_workspace_config(cfg.workspace)

    @classmethod
    def from_dict(cls, payload: dict) -> Catalog:
        """Open the project catalog declared in a dict config payload.

        Parameters
        ----------
        payload
            Mapping validated against ``HydroModPyConfig``.

        Returns
        -------
        Catalog
            Open catalog connected to the resolved workspace.

        Raises
        ------
        ConfigValidationError
            If the mapping fails Pydantic validation.
        """
        cfg = get_root_config_provider().from_dict(payload)
        return cls.from_workspace_config(cfg.workspace)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Return the DuckDB connection for protocol-based integrations."""
        return self._db

    @property
    def backend(self) -> CatalogBackend:
        """Return the storage backend port driving SQL reads and writes."""
        return self._backend

    @property
    def workspace_path(self) -> Path:
        """Workspace directory that owns this catalog."""
        return self._workspace

    @property
    def catalog_path(self) -> Path:
        """Path to the ``catalog.duckdb`` catalog file."""
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

    @property
    def frame(self):
        """Every simulation as one DataFrame row (alias of ``list_simulations``)."""
        return self.list_simulations()

    def read(
        self,
        ref: str,
        var: str,
        *,
        time: int | slice | None = None,
        layer: int | None = None,
        sel: dict | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> Any:
        """Read ``var`` for the run referenced by ``ref`` (the by-id read path).

        ``ref`` is resolved through :meth:`resolve` (full UUID, unique prefix,
        or name). For an already-resolved :class:`~hydromodpy.results.run.Run`,
        use :func:`hydromodpy.read`.
        """
        from hydromodpy.results.derive.reading import read_variable

        return read_variable(self[ref], var, time=time, layer=layer, sel=sel, bbox=bbox)

    def __repr__(self) -> str:
        try:
            row = self._backend.fetch_one("SELECT COUNT(*) FROM simulations")
            count = row[0] if row is not None else "?"
        except Exception:
            count = "?"
        return f"Catalog(workspace={str(self._workspace)!r}, simulations={count})"

    def _repr_html_(self) -> str:
        try:
            count = self._backend.fetch_one(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN st.code='completed' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN st.code='failed' THEN 1 ELSE 0 END) "
                "FROM simulations s JOIN statuses st ON s.status_id = st.id"
            )
            total, ok, failed = count if count is not None else (0, 0, 0)
            projects = [
                str(r[0])
                for r in self._backend.fetch_all("SELECT DISTINCT project FROM simulations")
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
            "<div><b>Catalog</b>"
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            f"{body}</table></div>"
        )
