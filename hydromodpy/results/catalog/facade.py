"""``Catalog``: the reader of a project index.

:class:`Catalog` opens ``<project>/.hmp/index.duckdb`` read-only and composes
the read concerns onto one object: typed queries (:mod:`reads`), reference
resolution and discovery (:mod:`discovery`), schema introspection
(:mod:`schema`). It writes nothing. The index is written by the indexer
(:mod:`hydromodpy.results.catalog.indexer`), which stages a new file and
publishes it in one rename, so a reader holding the previous file keeps
reading it and the next opener gets the new one. A run and a calibration
never open the index.

An index written under another schema version is refused with the command
that rebuilds it. A project without an index is refused the same way: a
reader never creates one.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from hydromodpy.core.config_kit.root_config_protocol import get_root_config_provider
from hydromodpy.core.io.db_retry import connect_with_retry
from hydromodpy.core.io.document_version import check_exact
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import catalog_path_for, runs_dir_for
from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend
from hydromodpy.results.catalog.discovery import DiscoveryMixin
from hydromodpy.results.catalog.index_schema import (
    INDEX_SCHEMA_VERSION,
    read_index_schema_version,
)
from hydromodpy.results.catalog.parquet_views import ensure_parquet_views
from hydromodpy.results.catalog.ports import CatalogBackend
from hydromodpy.results.catalog.reads import ReadsMixin
from hydromodpy.results.catalog.schema import SchemaDiscoveryMixin
from hydromodpy.results.catalog.storage_paths import StoragePathResolver
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.zarr_store import SimulationZarr

if TYPE_CHECKING:
    from uuid import UUID

    import xarray as xr

logger = get_logger(__name__)

REINDEX_HINT = "Run `hmp catalog reindex` to build the index from the run directories."


class Catalog(ReadsMixin, DiscoveryMixin, SchemaDiscoveryMixin):
    """Read-only view of a project index.

    Parameters
    ----------
    project_root
        The project directory, the one holding ``runs/`` and ``.hmp/``.

    Raises
    ------
    FileNotFoundError
        If the project has no index yet.
    hydromodpy.core.exceptions.SchemaVersionMismatchError
        If the index was written under another schema version.
    hydromodpy.core.exceptions.CatalogUnreadableError
        If the index file exists but DuckDB cannot open it.

    Examples
    --------
    >>> import hydromodpy as hmp
    >>> catalog = hmp.open("~/hmp_workspace/projects/nancon")  # doctest: +SKIP
    >>> catalog.latest().summary()  # doctest: +SKIP

    See Also
    --------
    hydromodpy.results.run.Run
        Per-simulation view returned by catalog queries.
    hydromodpy.results.run.group.RunSet
        Multi-run view returned by cohort queries.
    """

    def __init__(self, project_root: Path | str) -> None:
        root = Path(project_root).expanduser().resolve()
        self._workspace = root
        self._db_path = catalog_path_for(root)
        self._runs_dir = runs_dir_for(root)
        if not self._db_path.is_file():
            raise FileNotFoundError(f"No index at {self._db_path}. {REINDEX_HINT}")
        connection = connect_with_retry(str(self._db_path), read_only=True)
        version = read_index_schema_version(connection)
        if version != INDEX_SCHEMA_VERSION:
            connection.close()
            check_exact(
                version,
                INDEX_SCHEMA_VERSION,
                document=self._db_path,
                key="schema_version",
                remedy=REINDEX_HINT,
            )
        # The payload views name the run directories of this project, so they
        # are session-local and installed on the connection, never in the file.
        ensure_parquet_views(connection, self._runs_dir, temporary=True)
        self._db = connection
        self._closed = False
        self._backend = DuckDBBackend.from_connection(
            connection, path=self._db_path, read_only=True
        )
        self._paths = StoragePathResolver(self._backend, self._workspace)
        self._open_zarr_handles: list[SimulationZarr] = []

    # -- Factories ------------------------------------------------------------

    @classmethod
    def from_workspace(cls, workspace: object) -> Catalog:
        """Open the index of the project a workspace names by its ``project_root``.

        ``workspace`` is a ``[workspace]`` configuration or a runtime
        workspace object: both carry the project directory.
        """
        return cls(Path(workspace.project_root))  # type: ignore[attr-defined]

    @classmethod
    def from_toml(cls, toml_path: str | Path) -> Catalog:
        """Open the index of the project a TOML configuration names."""
        cfg = get_root_config_provider().from_toml(toml_path)
        return cls.from_workspace(cfg.workspace)

    @classmethod
    def from_json(cls, payload: str | bytes) -> Catalog:
        """Open the index of the project a JSON configuration names."""
        cfg = get_root_config_provider().from_json(payload)
        return cls.from_workspace(cfg.workspace)

    @classmethod
    def from_dict(cls, payload: dict) -> Catalog:
        """Open the index of the project a mapping configuration names."""
        cfg = get_root_config_provider().from_dict(payload)
        return cls.from_workspace(cfg.workspace)

    # -- Handles --------------------------------------------------------------

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """The read-only DuckDB connection, for ad-hoc SQL."""
        return self._db

    @property
    def backend(self) -> CatalogBackend:
        """The storage backend port driving the SQL reads."""
        return self._backend

    @property
    def workspace_path(self) -> Path:
        """The project directory that owns this index."""
        return self._workspace

    @property
    def project_path(self) -> Path:
        """Alias of :attr:`workspace_path`."""
        return self._workspace

    @property
    def catalog_path(self) -> Path:
        """Path of the index database."""
        return self._db_path

    @property
    def runs_dir(self) -> Path:
        """Directory holding one sub-directory per run."""
        return self._runs_dir

    def run_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the directory of a run."""
        return self._paths.run_dir_for(sim_id)

    def fields_path_for(self, sim_id: str | UUID) -> Path:
        """Return the Zarr directory store of a run."""
        return self._paths.fields_path_for(sim_id)

    def tables_dir_for(self, sim_id: str | UUID) -> Path:
        """Return the Parquet payload directory of a run."""
        return self._paths.tables_dir_for(sim_id)

    def open_zarr(self, sim_id: str | UUID) -> SimulationZarr:
        """Open the field store of a run for reading.

        The handle is tracked and closed by :meth:`close`.

        Raises
        ------
        FileNotFoundError
            If the run has no ``fields.zarr``.
        """
        fields = self._paths.fields_path_for(sim_id)
        if not fields.is_dir():
            raise FileNotFoundError(f"Run {str(sim_id)[:8]} has no {FIELDS_STORE_NAME} at {fields}")
        handle = SimulationZarr(fields)
        handle._on_close = self._untrack_zarr_handle
        self._open_zarr_handles.append(handle)
        return handle

    def _untrack_zarr_handle(self, handle: SimulationZarr) -> None:
        try:
            self._open_zarr_handles.remove(handle)
        except ValueError:
            pass

    # -- Composite reads ------------------------------------------------------

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

        See :class:`hydromodpy.results.catalog.dataset_loader.DatasetLoader`.
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
        """Every sealed run as one DataFrame row (alias of ``list_simulations``)."""
        return self.list_simulations()

    def read(
        self,
        ref: str,
        variable: str,
        *,
        time: Any = None,
        layer: int | None = None,
        sel: dict | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> Any:
        """Read ``variable`` for the run referenced by ``ref``, as :func:`hydromodpy.read` does.

        ``ref`` is resolved through :meth:`resolve`. ``time`` takes what
        :func:`hydromodpy.read` takes: a period index, a date, ``"first"`` or
        ``"last"``, or a slice of indexes.
        """
        from hydromodpy.results.derive.reading import read_variable

        return read_variable(self[ref], variable, time=time, layer=layer, sel=sel, bbox=bbox)

    # -- Lifetime -------------------------------------------------------------

    def close(self) -> None:
        """Close the open field stores and the connection."""
        while self._open_zarr_handles:
            handle = self._open_zarr_handles.pop()
            try:
                handle.close()
            except Exception:
                logger.warning("Could not close SimulationZarr handle", exc_info=True)
        if not self._closed:
            self._closed = True
            self._db.close()

    @property
    def closed(self) -> bool:
        """True once :meth:`close` ran."""
        return self._closed

    def _reopen(self) -> Catalog:
        """Return a new handle on the same index, for a run that outlives this one."""
        return type(self)(self._workspace)

    def __enter__(self) -> Catalog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        try:
            row = self._backend.fetch_one("SELECT COUNT(*) FROM simulations")
            count = row[0] if row is not None else "?"
        except Exception:
            count = "?"
        return f"Catalog(project={str(self._workspace)!r}, runs={count})"

    def _repr_html_(self) -> str:
        try:
            counts = self._backend.fetch_one(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN label = 'calibrated' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN label = 'failed' THEN 1 ELSE 0 END) FROM simulations"
            )
            total, calibrated, failed = counts if counts is not None else (0, 0, 0)
            sites = [
                str(r[0]) for r in self._backend.fetch_all("SELECT site FROM sites ORDER BY site")
            ]
        except Exception:
            total, calibrated, failed, sites = 0, 0, 0, []
        rows = [
            ("project", f"<code>{self._workspace}</code>"),
            ("runs", f"{total or 0} ({calibrated or 0} calibrated, {failed or 0} failed)"),
            ("sites", ", ".join(sites) if sites else "&mdash;"),
        ]
        body = "".join(
            f"<tr><th style='text-align:left'>{k}</th><td>{v}</td></tr>" for k, v in rows
        )
        return (
            "<div><b>Catalog</b>"
            "<table style='font-size:0.85em;border-collapse:collapse'>"
            f"{body}</table></div>"
        )


__all__ = ["REINDEX_HINT", "Catalog"]
