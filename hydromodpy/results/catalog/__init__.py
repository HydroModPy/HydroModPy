"""The project index: its reader, its indexer and its errors.

Public API
----------
- :class:`Catalog`: read-only view of ``<project>/.hmp/index.duckdb``. Methods
  cover the typed reads (``query_field``, ``query_timeseries``,
  ``list_simulations``, ``cases``, ``sql``), reference resolution
  (``resolve``, ``__getitem__``, ``find``, ``latest``, ``best``) and schema
  discovery (``tables``, ``columns``, ``describe``).
- :func:`rebuild_index`, :func:`index_new_runs`: the writers of the index,
  from the run and session directories; never called by a run.
- :func:`read_workspace_runs`: the sealed runs of several projects, read from
  their ``simulation.parquet`` files without any index.
- Errors: :class:`SimulationNotFoundError`, :class:`AmbiguousReferenceError`.
- :func:`short_id`: Git-style short identifier (first 8 hex chars).
"""

from hydromodpy.results.catalog.discovery import (
    AmbiguousReferenceError,
    SimulationNotFoundError,
    iter_project_catalog_roots,
    short_id,
)
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.federation import read_workspace_runs
from hydromodpy.results.catalog.indexer import IndexReport, index_new_runs, rebuild_index

__all__ = [
    "AmbiguousReferenceError",
    "Catalog",
    "IndexReport",
    "SimulationNotFoundError",
    "index_new_runs",
    "iter_project_catalog_roots",
    "read_workspace_runs",
    "rebuild_index",
    "short_id",
]
