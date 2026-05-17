The ``hmp.catalog`` facade
==========================

HydroModPy stores its tabular state in three DuckDB files:

- ``<workspace>/data/cache.duckdb`` -- shared input cache.
- ``<project>/catalog.duckdb`` -- simulation results for one project.
- ``<state_dir>/index.duckdb`` -- machine-wide federation of every
  registered workspace.

End-user code never needs to know which file holds a given row. The
:mod:`hydromodpy.catalog` module exposes the three databases behind one
facade with three namespaces: ``simulations``, ``inputs`` and
``projects``.

Opening a catalog
-----------------

.. code-block:: python

   import hydromodpy as hmp

   with hmp.open_catalog("~/proj/naizin") as cat:
       sims = cat.simulations.find(solver="modflow6")
       inputs = cat.inputs.list(variable="recharge")
       workspaces = cat.projects.list()

``open_catalog`` accepts an explicit workspace path, falls back to the
``HMP_WORKSPACE`` environment variable, then to the current working
directory. The facade is usable both as a context manager (preferred)
and as a long-lived object whose ``.close()`` method releases the
underlying DuckDB handles.

The three namespaces
--------------------

``cat.simulations`` -- project simulation catalog
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Backed by ``<workspace>/catalog.duckdb``. Lazy: the catalog is opened
on the first call, not when the facade itself is constructed.

.. code-block:: python

   # Has a catalog at all?
   cat.simulations.has_catalog()

   # All simulations for this project as a DataFrame.
   df = cat.simulations.list()

   # Equality filters against ``v_simulation_summary`` columns.
   # Unknown filters are silently ignored so callers can stay generic.
   df = cat.simulations.find(solver="modflow6", status="completed")

   # One sim by id.
   row = cat.simulations.get("ab12cd34-...-...-...-...")

``cat.inputs`` -- workspace input cache
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Backed by ``<workspace>/data/cache.duckdb``. Lazy.

.. code-block:: python

   cat.inputs.has_cache()
   cat.inputs.db_path  # -> ``<workspace>/data/cache.duckdb``

   # List entries, optionally filtered.
   cat.inputs.list(variable="recharge")
   cat.inputs.list(variable="head", source="brgm")

   # Locate a single cached entry covering a given extent.
   entry = cat.inputs.find(
       variable="recharge",
       source="meteofrance",
       station_id=None,
       bbox=(2.0, 48.0, 3.0, 49.0),
   )

``cat.projects`` -- machine global index
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Backed by ``<state_dir>/index.duckdb``. Opens the index in read-only
mode so concurrent ``hmp run`` writers keep their write-lock.

.. code-block:: python

   # Every registered workspace.
   cat.projects.list()

   # Federated simulation search across every workspace.
   cat.projects.find(solver="modflow6")

   # Full-text search across descriptions / scientific objectives.
   cat.projects.search("Bretagne fissured aquifer")

What the facade abstracts away
------------------------------

The facade hides:

- Which file backs which row.
- The DuckDB connection lifecycle (``open / close``).
- The migrations runner (each namespace asserts its DDL on first use).
- The ``CatalogBackend`` indirection (Protocol vs. concrete adapter).
- The federation rebuild (``cat.projects.find`` triggers
  ``GlobalIndex.refresh_federation`` if needed).

Callers that need a finer surface (custom SQL, transaction control,
register/unregister) keep direct access to the underlying objects:

- :class:`hydromodpy.results.catalog.SimulationCatalog`
- :class:`hydromodpy.data.registry.DataCatalogDuckDB`
- :class:`hydromodpy.core.state.global_index.GlobalIndex`

These are the V1 implementations and remain the canonical entry points
for low-level work. The facade is a convenience layer on top of them.

Direct submodule access
-----------------------

``hmp.catalog`` is a module, not a function. The submodules are
importable directly:

.. code-block:: python

   from hydromodpy.catalog import CatalogFacade, open_catalog
   from hydromodpy.catalog.simulations import SimulationsNamespace

Both styles (``hmp.open_catalog(...)`` and
``hmp.catalog.open_catalog(...)``) resolve to the same function. Use
whichever fits your import conventions.

Migrations runner
-----------------

Each of the three DuckDB files owns a flat ``migrations/`` directory
holding one ``0001_initial.sql``. They share a single runner under
:mod:`hydromodpy.core.migrations.runner`:

.. code-block:: python

   from hydromodpy.core.migrations import apply_migrations

   apply_migrations(
       db_path="path/to/some.duckdb",
       migrations_dir="path/to/migrations/",
       component="catalog",  # or "data_cache", "index"
   )

``apply_migrations`` acquires a ``<db_path>.lock`` filelock so
concurrent callers serialise. Already-applied migrations are skipped
based on a checksum recorded in ``schema_migrations``.

Authentication
--------------

The catalog reads ``hydromodpy.core.auth`` to resolve the current
operator. V1 ships a permissive default
(:class:`~hydromodpy.core.auth.LocalAuthBackend`) that returns the OS
user and allows every operation. Switching backends happens via the
``HMP_AUTH_BACKEND`` environment variable; no code change is needed in
the catalog layer.

Path types
----------

Every workspace / cache / state path argument is typed
``pathlib.Path | upath.UPath``. The runtime accepts local paths and
``file://`` URIs; any other scheme raises ``NotImplementedError`` with
a clear message. The type widening lets callers pass a raw URI today
even though only local URIs are honoured.
