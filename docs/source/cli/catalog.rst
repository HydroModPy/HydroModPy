hmp catalog
===========

The :command:`hmp catalog` family inspects, queries, and maintains the
DuckDB + Zarr catalog of a workspace. All actions auto-detect the
catalog root by walking up from the current directory; pass
``--workspace`` to point at a different project.

ls
--

Synopsis: ``hmp catalog ls [--solver <name>] [--catchment <name>] [--project <label>]``

List the simulations in the catalog, with one row per simulation
showing the short identifier, the solver, and the run name. Filters
restrict the listing to a solver, a catchment, or a project.

Example::

   hmp catalog ls --solver mf6

query
-----

Synopsis: ``hmp catalog query "<SQL>"``

Run a raw SQL statement against the catalog DuckDB. Read-only by
convention; favour it for ad-hoc exploration that does not fit the
canned filters of :command:`hmp catalog ls`.

Example::

   hmp catalog query "SELECT solver, COUNT(*) FROM simulations GROUP BY 1"

show
----

Synopsis: ``hmp catalog show <sim_ref> [--detail]``

Show one simulation by full UUID, unique prefix, or run name. ``--detail``
expands provenance fields, lockfile state, and per-output sizes.

Example::

   hmp catalog show 1a2b3c4d --detail

gc
--

Synopsis: ``hmp catalog gc [--dry-run]``

Garbage-collect orphan Zarr/Parquet caches and reap simulations that
were left in the ``running`` state by a hard crash. ``--dry-run`` only
reports what would be removed.

vacuum
------

Synopsis: ``hmp catalog vacuum``

Compact the DuckDB file in place and consolidate Zarr metadata. Safe
to run periodically; recommended after a long :command:`hmp catalog gc`.

delete
------

Synopsis: ``hmp catalog delete <sim_ref> [--force]``

Delete one simulation row and its Zarr store. For policy-grade hard
deletion with an audit certificate, use :command:`hmp privacy purge`.

Example::

   hmp catalog delete 1a2b3c4d
