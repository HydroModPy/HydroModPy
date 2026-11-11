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

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from hydromodpy.core.io.document_version import check_exact
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import catalog_path_for, runs_dir_for
from hydromodpy.results.catalog.adapters.duckdb import DuckDBBackend
from hydromodpy.results.catalog.discovery import DiscoveryMixin
from hydromodpy.results.catalog.index_file import open_index
from hydromodpy.results.catalog.index_schema import (
    INDEX_SCHEMA_VERSION,
    read_index_schema_version,
)
from hydromodpy.results.catalog.indexer import index_new_runs
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
    from pydantic import BaseModel

    from hydromodpy.results.run.view import Renderer

logger = get_logger(__name__)


def _file_identity(path: Path) -> tuple[int, int] | None:
    """Return the device and inode of *path*, or None when it is missing."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_dev, stat.st_ino)


class Catalog(ReadsMixin, DiscoveryMixin, SchemaDiscoveryMixin):
    """Read-only view of a project index.

    Parameters
    ----------
    project_root
        The project directory, the one holding ``runs/`` and ``.hmp/``.
    read_config
        The function that validates a sealed configuration snapshot, handed to
        every run this catalog builds. Without one, ``run.hydromodpy_config``
        is refused. A catalog opened by ``hmp.open`` or by a ``Project``
        carries it.
    render
        The function that draws a figure or writes a report for a run, a
        session or a set of runs, handed on like *read_config* to every object
        this catalog builds. Without one, ``figure`` is refused. It is
        :func:`hydromodpy.project.show.render` for a catalog opened by a
        ``Project``.

    Raises
    ------
    FileNotFoundError
        If the directory is not a project.
    hydromodpy.core.exceptions.WriteConflictError
        If the index had to be built and another process keeps its lock.
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

    def _open_current_index(self, root: Path) -> duckdb.DuckDBPyConnection:
        """Open the index, building it first when it is missing or of another build."""
        if not self._db_path.is_file():
            index_new_runs(root)
        self._opened_file = _file_identity(self._db_path)
        connection = open_index(root)
        if read_index_schema_version(connection) != INDEX_SCHEMA_VERSION:
            connection.close()
            index_new_runs(root)
            self._opened_file = _file_identity(self._db_path)
            connection = open_index(root)
        version = read_index_schema_version(connection)
        if version != INDEX_SCHEMA_VERSION:
            connection.close()
            check_exact(
                version,
                INDEX_SCHEMA_VERSION,
                document=self._db_path,
                key="schema_version",
                remedy="hmp catalog reindex rebuilds it from the run directories",
            )
        return connection

    def __init__(
        self,
        project_root: Path | str,
        *,
        read_config: Callable[[Mapping[str, Any]], BaseModel] | None = None,
        render: Renderer | None = None,
    ) -> None:
        root = Path(project_root).expanduser().resolve()
        self._workspace = root
        self._read_config = read_config
        self._render = render
        self._db_path = catalog_path_for(root)
        self._runs_dir = runs_dir_for(root)
        if not (self._runs_dir.is_dir() or self._db_path.parent.is_dir()):
            raise FileNotFoundError(f"{root} is not a project directory: it has no runs/ or .hmp/.")
        connection = self._open_current_index(root)
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

    # -- Handles --------------------------------------------------------------

    @property
    def read_config(self) -> Callable[[Mapping[str, Any]], BaseModel] | None:
        """The function the runs of this catalog validate a sealed snapshot with.

        ``None`` when the opener passed none: the runs read their raw
        configuration snapshot, and :attr:`Run.hydromodpy_config` is refused.
        """
        return self._read_config

    @property
    def render(self) -> Renderer | None:
        """The function the runs of this catalog draw a figure with, or ``None``.

        With ``None``, ``run.figure`` and ``run.show(what="figure")`` are refused
        and say to open the run with ``hmp.open``.
        """
        return self._render

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
            If the run has no ``fields.zarr``, with the purge date when ``gc``
            removed it from a kept trial.
        """
        fields = self._paths.fields_path_for(sim_id)
        if not fields.is_dir():
            raise FileNotFoundError(self._missing_fields_message(sim_id, fields))
        handle = SimulationZarr(fields)
        handle._on_close = self._untrack_zarr_handle
        self._open_zarr_handles.append(handle)
        return handle

    def _missing_fields_message(self, sim_id: str | UUID, fields: Path) -> str:
        """Say why a field store is absent, naming the purge when gc made it leave."""
        from hydromodpy.results.storage.json_io import readable
        from hydromodpy.results.storage.kept import read_purged

        purged = readable(read_purged, self.run_dir_for(sim_id))
        if purged is None:
            return f"Run {str(sim_id)[:8]} has no {FIELDS_STORE_NAME} at {fields}"
        return (
            f"Run {str(sim_id)[:8]} had its {FIELDS_STORE_NAME} removed by gc on "
            f"{purged.at.date().isoformat()}; its seal, tables and final state stay."
        )

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

        See :func:`hydromodpy.results.catalog.dataset_loader.load_dataset`.
        """
        from hydromodpy.results.catalog.dataset_loader import load_dataset

        return load_dataset(
            self,
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

    @property
    def reads_the_published_index(self) -> bool:
        """True while the file this handle reads is still the published index.

        A rebuild publishes a new file by rename, and an open handle keeps
        reading the file it opened. Its owner then opens the index again.
        """
        return _file_identity(self._db_path) == self._opened_file

    def _reopen(self) -> Catalog:
        """Return a new handle on the same index, for a run that outlives this one."""
        return type(self)(self._workspace, read_config=self._read_config, render=self._render)

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


__all__ = ["Catalog"]
