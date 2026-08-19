The catalog door
================

HydroModPy stores its tabular state in three DuckDB files:

- ``<workspace>/data/cache.duckdb`` -- shared input cache.
- ``<project>/.hmp/index.duckdb`` -- index of the runs of one project.
- ``<state_dir>/index.duckdb`` -- machine-wide federation of every
  registered project.

End-user code never needs to know which file holds a given row.
``hmp.open`` is the single door onto the simulation catalog; the input
cache and the machine-wide federation are reached through their own
entry points (``hydromodpy.catalog.InputsNamespace`` / the ``hmp data``
CLI, and ``hmp.index()``).

Opening a catalog
-----------------

.. code-block:: python

   import hydromodpy as hmp

   cat = hmp.open("~/proj/naizin")
   sims = cat.find(solver="modflow6")          # RunSet
   federation = hmp.index()                    # machine-wide federation

``hmp.open`` returns a :class:`~hydromodpy.results.catalog.Catalog`
(the engine itself, not a wrapper). With the default ``create=False`` it
raises ``FileNotFoundError`` when no ``.hmp/index.duckdb`` exists; pass
``create=True`` to initialise an empty catalog instead.

The three databases
-------------------

The simulation catalog -- ``hmp.open``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Backed by ``<project>/.hmp/index.duckdb``, rebuildable from ``runs/``
and ``sessions/`` with ``hmp catalog reindex``.

.. code-block:: python

   cat = hmp.open("~/proj/naizin")

   # All simulations for this project as a DataFrame.
   df = cat.frame

   # Equality filters against ``v_simulation_summary`` columns.
   # An unknown filter raises ValueError listing the valid keys.
   group = cat.find(solver="modflow6", status="completed")

   # Schema discovery.
   cat.describe()
   cat.tables()
   cat.columns()
   cat.variables()
   cat.metrics()
   cat.stations()

   # Ranking and resolution.
   cat.latest()
   cat.best("naizin", metric="nse")
   cat.worst("naizin", metric="nse")
   cat.rank("naizin", "nse", n=5)
   cat.resolve(ref)

   # One sim by reference.
   row = cat["ab12cd34-...-...-...-..."]
   data = cat.read(ref, "head")

   # Raw SQL.
   cat.sql("SELECT * FROM v_simulation_summary LIMIT 5")

The input cache
~~~~~~~~~~~~~~~~

Backed by ``<workspace>/data/cache.duckdb``. Reached through
``hydromodpy.catalog.InputsNamespace`` or the ``hmp data`` CLI, not
through ``hmp.open``.

.. code-block:: python

   from hydromodpy.catalog import InputsNamespace

   inputs = InputsNamespace("~/proj/naizin")
   inputs.has_cache()
   inputs.db_path  # -> ``<workspace>/data/cache.duckdb``

   # List entries, optionally filtered.
   inputs.list(variable="recharge")
   inputs.list(variable="head", source="brgm")

   # Locate a single cached entry covering a given extent.
   entry = inputs.find(
       variable="recharge",
       source="meteofrance",
       station_id=None,
       bbox=(2.0, 48.0, 3.0, 49.0),
   )

The machine global index -- ``hmp.index``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Backed by ``<state_dir>/index.duckdb``. Opened in read-only mode so
concurrent ``hmp run`` writers keep their write-lock.

It registers **projects**, one row per project root, because a project
root is what owns an index database. A workspace root owns none: passing
one to ``register`` adds the projects it holds instead of itself.

.. code-block:: python

   idx = hmp.index()
   idx.list_projects()             # every registered project root
   idx.find(solver="modflow6")     # federated query across all of them

   with hmp.index(read_only=False) as writable:
       writable.register("~/hydromodpy")   # the workspace's projects

The federation (federated search across every registered project,
full-text search across descriptions / scientific objectives) lives on
the index returned by ``hmp.index()``.

Keeping the history bounded
---------------------------

A project accumulates runs. ``hmp catalog gc`` decides how many it
keeps, and it plans before it acts: without ``--apply`` it only prints
what it would do.

.. list-table::
   :header-rows: 1
   :widths: 26 14 60

   * - Rule
     - Default
     - What it selects
   * - ``--keep-versions N|all``
     - ``5``
     - Every version of one run name beyond the ``N`` newest.
       ``cheze``, ``cheze.v2``, ``cheze.v3`` is one lineage. ``all``
       disables the rule.
   * - ``--max-age-days DAYS``
     - disabled
     - Runs created more than ``DAYS`` ago.
   * - ``--purge-figures``
     - disabled
     - The ``figures/`` directory of each run, rebuildable from the run
       outputs.

.. code-block:: bash

   hmp catalog gc                              # plan only, default policy
   hmp catalog gc --keep-versions 2 --apply    # keep the two newest per lineage
   hmp catalog gc --max-age-days 365 --apply   # also retire runs older than a year
   hmp catalog gc --keep-versions all          # keep every version, clean the rest

No rule destroys anything on the spot. A selected run is moved to the
project trash: a reversible status flip stamped on disk as
``runs/<name>/trash.json`` and undone by ``hmp catalog restore``. Its
bytes are freed later, by the trash-expiry rule, once the retention
window has passed. Selected figures are quarantined under
``.hmp/trash/<stamp>/<run>/figures``.

Tag a run ``pinned`` to exempt it from every rule:

.. code-block:: bash

   hmp catalog tag <ref> pinned

Beyond retention, ``gc`` also collects orphan stores, tmp Parquet,
expired trash, stale ``running`` rows, pending purges and orphan
calibration sessions. With ``--apply`` it compacts the DuckDB file and
consolidates the Zarr metadata. The full synopsis is in
:doc:`/cli/catalog`.

Underlying objects
------------------

Callers that need a finer surface (custom SQL, transaction control,
register/unregister) reach the underlying objects directly:

- :class:`hydromodpy.results.catalog.Catalog`
- :class:`hydromodpy.data.registry.DataCatalogDuckDB`
- :class:`hydromodpy.core.state.global_index.GlobalIndex`

These are the V1 implementations and remain the canonical entry points
for low-level work.

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
