The three workspace databases
=============================

HydroModPy v2 splits SQL state across three levels: machine, workspace,
project. Each level has its own DuckDB file with a focused role and an
independent lifecycle.

For the complete layout, see :doc:`../storage-layout`. For the migration
policy applied to every database below, see :doc:`schema-evolution`.

Machine global index - ``$XDG_STATE_HOME/hydromodpy/index.duckdb``
------------------------------------------------------------------

Federates registered workspaces and exposes cross-workspace queries
through ATTACH read-only. Exposed through:

- :class:`~hydromodpy.core.state.global_index.GlobalIndex`
- ``hmp.index()`` Python facade
- ``hmp index search / forget / prune`` CLI verbs

Workspace input cache - ``<workspace>/data/cache.duckdb``
---------------------------------------------------------

Tracks downloaded or custom datasets used as model inputs. One per
workspace, scope ``data/`` mutualised across projects. Exposed through:

- ``DataCatalogDuckDB`` (low-level)
- ``DataStore`` (facade)
- ``DataEntry`` (view on one row)
- ``project.data`` / ``workspace.data`` accessors

Each row carries a workspace-relative POSIX ``file_path`` so caches
remain portable between machines.

Project simulation catalog - ``<project>/catalog.duckdb``
---------------------------------------------------------

Holds simulation metadata, parameters, metrics, provenance, calibration
history, and the workflow ledger. Scoped to one project (typically one
catchment) and irreplaceable. Each simulation gets a row plus
per-simulation Zarr and Parquet artefacts under
``<project>/simulations/``. Exposed through:

- :class:`~hydromodpy.results.catalog.SimulationCatalog`
- :class:`~hydromodpy.results.run.Run`
- :class:`~hydromodpy.results.simulation_group.SimulationGroup`
- ``project.runs`` / ``hmp.open(project_path)`` accessors

Provenance bridge
-----------------

Each simulation records, in its ``provenance`` rows, which input-cache
entries it consumed. ``run.input_entries()`` walks the bridge to list
them, and ``entry.used_by()`` returns the simulations that referenced a
given entry. Cross-workspace lookups go through the global index.

Why three levels
----------------

- Machine index: cross-workspace discovery without copying data.
- Workspace cache: input mutualisation between projects sharing a
  geographic area.
- Project catalog: irreplaceable results that warrant their own backup
  policy.

The split also matches three distinct lifecycles: the index is fully
recreatable from registered workspaces, the cache is purgeable and
reconstructible from upstream sources, the project catalog is the only
SQL store that holds science output that cannot be regenerated without
re-running simulations.

V1 unified runner and facade
----------------------------

V1 ships three additions that sit on top of the three-database split:

- **Single migrations runner**:
  :mod:`hydromodpy.core.migrations.runner` exposes
  ``apply_migrations(db_path, migrations_dir)`` (with a
  ``<db_path>.lock`` filelock to serialise concurrent callers) and is
  used by all three databases. Each scope owns a flat ``migrations/``
  directory containing exactly one ``0001_initial.sql`` for V1.
- **High-level ``hmp.catalog`` facade**:
  :class:`hydromodpy.catalog.CatalogFacade` exposes the three databases
  through ``simulations`` (project catalog), ``inputs`` (workspace
  cache) and ``projects`` (machine index) namespaces. Users write
  ``hmp.catalog.simulations.find(...)`` without knowing which file
  holds the row.
- **ML hook tables**: the project catalog now seeds four empty
  ``ml_datasets`` / ``ml_splits`` / ``ml_splits_members`` /
  ``ml_scalers`` tables. The ``hydromodpy/ml/`` module that fills them
  ships in V2; the schema is already in place so V2 reads against V1
  catalogs work.
- **AuthBackend Protocol**: :class:`hydromodpy.core.auth.AuthBackend`
  is a structural protocol with a permissive
  :class:`~hydromodpy.core.auth.LocalAuthBackend` default. V1 does not
  enforce ACLs; the abstraction lets V2 wire keyring / IAM / SSO
  backends without touching the catalog layer.
- **UPath-ready paths**: every workspace / cache / state path argument
  is typed ``Path | UPath`` and ``resolve_workspace`` accepts
  ``file://`` URIs (other schemes raise ``NotImplementedError`` with a
  V2 pointer). :class:`hydromodpy.results.zarr_store.adapters.FsspecZarrStore`
  and :class:`hydromodpy.results.catalog.adapters.PostgresBackend` stay
  V1 stubs that satisfy their respective protocols.
