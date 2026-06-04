The three workspace databases
=============================

HydroModPy splits SQL state across three scopes: machine, workspace,
project. Each scope owns a DuckDB file with a focused role and an
independent lifecycle. The :mod:`hydromodpy.catalog` layer exposes each
scope through its own door: ``hmp.open(ws)`` for the project catalog,
``hmp.index()`` for the machine-wide federation, and
:class:`~hydromodpy.catalog.InputsNamespace` (or the ``hmp data`` CLI)
for the input cache.

For the complete layout, see :doc:`../storage-layout`. For the migration
policy applied to every database below, see :doc:`schema-evolution`.

Machine global index -- ``$XDG_STATE_HOME/hydromodpy/index.duckdb``
-------------------------------------------------------------------

Federates every registered workspace and exposes cross-workspace
queries through ``ATTACH`` in read-only mode. Recreated from the
registered workspaces alone -- it carries no science output of its own.

Tables: ``workspaces``, ``projects``, ``simulations_cache``,
``index_metadata`` plus the view ``v_workspace_health``.

Exposed through:

- :class:`hydromodpy.core.state.global_index.GlobalIndex`
- ``hmp.index()`` (machine-wide discovery and federation)
- CLI verbs ``hmp index search / forget / prune``

Workspace input cache -- ``<workspace>/data/cache.duckdb``
----------------------------------------------------------

Tracks downloaded or custom datasets used as model inputs. One file per
workspace, mutualised across every project of that workspace. Purgeable
and reconstructible from upstream sources.

Tables: ``entries``, ``api_coverage``, ``artifacts``, ``provenance``,
``stations``, ``coverage``, ``failures``, ``validation_reports`` plus
the view ``v_entries_summary``.

Exposed through:

- :class:`hydromodpy.data.registry.DataCatalogDuckDB` (low-level)
- :class:`hydromodpy.catalog.InputsNamespace` (or the ``hmp data`` CLI)
- ``project.data`` / ``workspace.data`` accessors

Each row carries a workspace-relative POSIX ``file_path`` so caches
remain portable between machines.

Project simulation catalog -- ``<project>/catalog.duckdb``
-----------------------------------------------------------

Holds the science output: simulation metadata, parameters, metrics,
per-sim provenance, calibration history, workflow ledger and audit
trail. Scoped to one project (typically one catchment) and
irreplaceable. Each simulation gets a row plus per-simulation Zarr and
Parquet artefacts under ``<project>/simulations/``.

Tables: 26 (dim_*, solvers, statuses, flow_regimes, mesh_topologies,
simulations, parameters, metrics, metric_definitions, observations,
observation_points, provenance, runs_environment, audit_log, deletions,
tracked_files, geographic_features, geographic_metadata, parquet_files,
tags, stations, calibration_sessions, calibration_iterations,
workflow_steps) plus the views ``v_simulation_summary`` and
``v_metrics_pivot``.

Exposed through:

- :class:`hydromodpy.results.catalog.SimulationCatalog`
- :class:`hydromodpy.results.run.Run`
- :class:`hydromodpy.results.simulation_group.SimulationGroup`
- ``hmp.open(project_path)`` door (returns the ``SimulationCatalog``;
  ``cat.find(...)``, ``cat.frame``, ``cat.latest()``, ``cat[ref]``)
- CLI verb ``hmp catalog ...``

Provenance bridge
-----------------

Each simulation records, in its ``provenance`` rows, which input-cache
entries it consumed. ``run.input_entries()`` walks the bridge to list
them, and ``entry.used_by()`` returns the simulations that referenced a
given entry. Cross-workspace lookups go through the machine index.

Why three scopes
----------------

- **Machine index** -- cross-workspace discovery without copying data.
- **Workspace cache** -- input mutualisation between projects sharing a
  geographic area.
- **Project catalog** -- irreplaceable science output that warrants its
  own backup policy and stays writable while other projects keep using
  the same workspace cache.

Three scopes match three distinct lifecycles: the index is fully
recreatable from registered workspaces, the cache is purgeable and
reconstructible from upstream sources, the project catalog is the only
SQL store that holds output which cannot be regenerated without
re-running the simulations.

Unified architecture
--------------------

A single set of patterns governs the three databases:

- **Single migrations runner**:
  :mod:`hydromodpy.core.migrations.runner` exposes
  ``apply_migrations(db_path, migrations_dir)`` (with a
  ``<db_path>.lock`` filelock to serialise concurrent callers) and is
  used by all three databases. Each scope owns a flat ``migrations/``
  directory containing one ``0001_initial.sql``.
- **Per-scope doors**:
  :mod:`hydromodpy.catalog` exposes each database through its own door:
  ``hmp.open(ws)`` returns the project ``SimulationCatalog``,
  ``hmp.index()`` federates the machine-wide scope, and
  :class:`~hydromodpy.catalog.InputsNamespace` reaches the input cache.
  Users write ``hmp.open(ws).find(solver="modflow6")`` on the catalog
  itself.
- **Backend Protocol**:
  :class:`hydromodpy.results.catalog.ports.CatalogBackend` is a
  ``typing.Protocol`` with ``execute / query / fetch_one / fetch_all /
  insert / upsert / transaction / close``. The catalog mixins call the
  protocol so swapping the adapter does not touch call sites.
- **Authentication Protocol**:
  :class:`hydromodpy.core.auth.AuthBackend` exposes a structural
  ``current_user / can_read / can_write`` surface with
  :class:`~hydromodpy.core.auth.LocalAuthBackend` as the V1 default.
- **URI-aware paths**: every workspace / cache / state argument is
  typed ``Path | UPath``. The runtime accepts local paths and
  ``file://`` URIs; any other scheme raises ``NotImplementedError``.

Refactor outcomes
-----------------

The catalog stack used to concentrate three god-classes (each above
1000 LOC). V1 split them into single-concern modules:

- ``SimulationZarr`` -> ``simulation_zarr`` (facade) +
  ``zarr_schema`` + ``zarr_writer`` + ``zarr_reader`` +
  ``zarr_finalizer``.
- ``DataCatalogDuckDB`` -> ``catalog_duckdb`` (facade) +
  ``cache_store`` + ``cache_queries`` + ``cache_lifecycle``.
- ``WritesMixin`` -> ``writes`` (facade) + ``writes_duckdb`` +
  ``writes_parquet`` + ``writes_zarr`` + ``writes_helpers``.

The original public symbols (``SimulationZarr``, ``DataCatalogDuckDB``,
``SimulationCatalog``, ``WritesMixin``) keep their import path and
their full API; golden tests pin bit-identical artefacts before and
after each split.
