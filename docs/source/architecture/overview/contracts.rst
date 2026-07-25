Protocols and public contracts
==============================

HydroModPy V1 makes its public surface explicit through three layers:

- the **public facade** ``hydromodpy`` (re-exports ``open``, ``read``,
  ``run``, ``calibrate``, ``index``, ``viz``, ``ml`` stubs);
- a small set of **Protocols** that pin the structural contract for
  storage backends and field readers;
- a **field registry** that maps logical names to physical readers.

This page documents what users and integrators can rely on.

The hmp public facade
---------------------

The single supported import path is ``import hydromodpy as hmp``. The
package exposes a flat set of verbs and helpers re-exported from
``hydromodpy._api``:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Symbol
     - Role
   * - ``hmp.open(project_path)``
     - Open a project catalog. Returns a ``Catalog``
       backed by ``catalog.duckdb`` at the project root. Calls
       ``ensure_schema()`` on the underlying backend.
   * - ``hmp.read(run, field, **selectors)``
     - Read a logical field from a ``Run``. Dispatches to a Zarr
       reader or a Parquet reader through the field registry.
   * - ``hmp.run(toml_path, **overrides)``
     - Execute a workflow declared in the project TOML.
   * - ``hmp.calibrate(toml_path, **overrides)``
     - Drive a calibration session.
   * - ``hmp.index(db_path=None)``
     - Open the machine-wide ``GlobalIndex``.
   * - ``hmp.viz.show(run, figure, **kwargs)``
     - Render one figure for a run. Scalable defaults via
       datashader / LTTB.

Storage Protocol: ``CatalogBackend``
------------------------------------

Source: ``hydromodpy/results/catalog/ports.py``.

The catalog facade interacts with the SQL store only through this
Protocol. The in-tree adapter is ``DuckDBBackend``.

Required surface:

.. code-block:: python

   class CatalogBackend(Protocol):
       def ensure_schema(self) -> None: ...
       def query(self, sql: str, params: ...) -> pandas.DataFrame: ...
       def execute(self, sql: str, params: ...) -> None: ...
       def fetch_one(self, sql: str, params: ...) -> tuple | None: ...
       def fetch_all(self, sql: str, params: ...) -> list[tuple]: ...
       def insert(self, table: str, row: dict[str, Any]) -> None: ...
       # ... plus transaction context manager and close()

Conformance is structural (``@runtime_checkable``). No base class to
inherit. ``ensure_schema()`` runs the Alembic-like migration runner so
the catalog is always at the version pinned by the library.

Simulation store Protocol
-------------------------

Source: ``hydromodpy/results/storage_contract.py``
(``SimulationStore`` Protocol).

Covers the minimal write/read surface that workflow steps, solver
adapters, and post-run extractors actually call:

- registration: ``register_simulation``;
- per-simulation writes: ``write_parameters``, ``write_timeseries``,
  ``write_field``, ``write_time``, ``write_crs``, ``write_mesh``,
  ``write_provenance``, ``write_metric``,
  ``write_run_environment``, ``register_tracked_files``;
- reads: ``query_timeseries``, ``list_simulations``,
  ``__getitem__``, ``open_zarr``;
- lifecycle: ``finalize``, ``close`` and the context-manager
  protocol.

The default implementation is
:class:`~hydromodpy.results.catalog.Catalog`. Conforming
alternative backends (PostgreSQL, Parquet-only, in-memory, remote
object storage) can plug in without touching workflow code.

Field registry
--------------

Source: ``hydromodpy/results/field_registry.py``.

Maps a logical field name (``"head"``, ``"watertable_depth"``,
``"accumulation_flux"``, ...) to:

- the physical store kind (``"zarr"`` or ``"parquet"``);
- the canonical path inside that store
  (``field/head``, ``timeseries.parquet?variable=head``);
- the CF ``standard_name`` and the unit.

``hmp.read`` reads the registry first and dispatches to the matching
reader. Adding a new field is a registry entry plus a writer; readers
keep working unchanged.

Versioned schema constants
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 36 64

   * - Constant
     - Definition
   * - ``schema_migrations.version`` (project catalog)
     - one row per applied migration; latest is the active version.
   * - ``schema_migrations.version`` (workspace cache)
     - separate ledger row scoped to the cache component.
   * - ``schema_migrations.version`` (machine index)
     - separate ledger row scoped to the index component.
   * - ``ZARR_SCHEMA_VERSION``
     - Pinned to ``"2"`` in
       ``hydromodpy/results/zarr_store/constants.py``.
   * - ``PARQUET_SCHEMA_VERSION``
     - Pinned to ``"v2"`` in
       ``hydromodpy/results/storage/parquet_schemas.py``.
   * - ``GEOPARQUET_SCHEMA_VERSION``
     - Pinned to ``"1.1.0"`` in
       ``hydromodpy/core/io/geoparquet.py``.

For the migration runner mechanics, see :doc:`schema-evolution`.

Stability promise
-----------------

The public facade ``hmp.*`` and the two Protocols above are the V1
stable surface. Backwards-compatibility shims, aliases, and
re-exports outside the facade are forbidden (see ``CLAUDE.md`` under
"What this codebase forbids").

A change to any of the four areas above is a breaking change that
requires:

- a migration entry under the relevant
  ``hydromodpy/.../migrations/`` directory;
- a version bump of the matching constant
  (``ZARR_SCHEMA_VERSION``, ``PARQUET_SCHEMA_VERSION``,
  ``GEOPARQUET_SCHEMA_VERSION``);
- a docs update on this page and on
  :doc:`/architecture/storage-layout`.

The project index is the exception being built: because it is rebuilt
from the run directories, its schema is meant to evolve by replacing the
initial DDL and rebuilding, not by chaining migrations. See
:doc:`schema-evolution` and :doc:`/architecture/storage-layout`.

See also
--------

- :doc:`/architecture/storage-layout` for the on-disk layout these
  Protocols cover.
- :doc:`schema-evolution` for the migration policy.
- :doc:`/architecture/packages/results` for the Python surface.
