Package: data
=============

.. include:: ../../../../../hydromodpy/data/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: data

Inside the package
------------------

How a run loads data
~~~~~~~~~~~~~~~~~~~~

The data layer answers three questions before any solver work starts. Which families are
active, which class loads each one, and which provider or local file feeds it.

1. ``DataConfig`` (``loading/config_schema.py``) validates ``[data]`` and reads each typed
   section with the config class that ``VARIABLE_SPECS`` names for it.
2. ``DataPlanner.build`` (``loading/planner.py``) merges the explicit :toml:`data.types` with
   the inference rules and returns an immutable ``DataLoadPlan`` with one reason per inferred
   type. An explicit type always wins. A ``geology`` support activates ``geology``, a
   ``stream`` boundary activates ``hydrography``, an ``ocean`` one activates ``oceanic``, and a
   soil reservoir activates ``precipitation`` and ``etp``. With ``data.inference_mode =
   "warn"`` the inferences are accepted and recorded. With ``"strict"`` each one needs an
   explicit section.
3. ``project/phases.py`` builds the plan. ``LoadDataStep`` (``workflow/steps/data.py``) then
   runs ``DataLoader``, which applies the simulation window and the basin mask, calls
   ``<V>Variable.load()`` for each planned variable and collects a ``LoadResult``.
4. The loader fills ``LoadedDataContext`` (``core/state/run_state.py``), one field per
   variable. The step then binds geology into the ``Domain`` zones with
   ``apply_geology_to_domain``, and oceanic levels, recharge, ETP, lakes and barriers into the
   ``Flow`` with the ``apply_*_to_flow`` functions. Hydrometry stays in the loaded state.

``VARIABLE_SPECS`` in ``loading/_dispatch.py`` is the one list of variables. It names the
classes as text paths, so nothing is imported before it is needed, and it holds the columns
that the workspace scaffold writes. A new variable still needs a field in ``DataConfig``, a
field of ``LoadedDataContext`` and, for a provider, an entry in ``schema/sources.py``.
``tests/unit/data/test_variable_families.py`` names the list you missed. Outside a project,
``DataStore().load_variable("hydrometry", cfg)`` loads one variable by hand.

The variables and their bases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each ``[data.<name>]`` section is one variable, and :doc:`/reference/data-sources` lists the
sources of each. A variable leaves every provider to the registry and names only itself and its unit, for example ``VARIABLE_NAME = "hydrometry"`` and
``INTERNAL_UNIT = "m3/s"``.

``families/`` holds three bases. ``StationVariable`` keeps one chronicle per station and asks
only for the missing periods. ``GridVariable`` keeps one NetCDF or GeoTIFF per box and period.
``FileVariable`` reads only the user's own file. ``dem``, ``geology``, ``hydrography`` and
``crossings`` are written by hand and inherit only ``SourceTable``.

A variable with real code is a package, ``variables/<v>/``, with ``config.py``, ``variable.py``
and an ``apis/`` folder for its network providers. A thin variable has no code of its own, so
its three classes sit in a flat module of its family (``sim2_series.py``, ``forcing_series.py``,
``lake_series.py`` or ``user_rasters.py``). ``dem``, ``crossings`` and ``hydrography`` also
keep a ``resolver.py``, because the geographic step runs before any variable loads and needs
their files on disk first.

The extent of a variable comes from its source config alone (``resolve_source_extent`` in
``common/source_extent.py``), with ``mask_path`` first. No variable takes a project object and
no variable reads the project geometry. During a run, ``DataLoader`` writes the delineated
watershed into ``mask_path`` before it hands the config to the store. A mask with no CRS is refused.

The DataSource port
~~~~~~~~~~~~~~~~~~~

``source/README.md`` is the contract of the port. Every provider is one class of the port,
found with ``data_sources.get(section, source_id)``. A source knows nothing of the catalog, the
workspace, a lock or a cache, and it converts no value, because the SI is reached at the entry
of the ``Model`` through ``core/units``. The variable builds the request and keeps the cache,
and the source only fetches.

``source/registry.py`` names the shipped classes by a dotted path in ``_BUILTIN_PATHS`` and
imports each on first use, so a third-party plugin joins the same table through the
``hydromodpy.data.source`` entry-point group. Source modules import heavy libraries inside their functions, so a lookup loads
nothing heavy. ``file`` is never in ``SOURCES``, because the base class loads the user's files itself
and a user file is no row of the cache.

The cache is its sidecars
~~~~~~~~~~~~~~~~~~~~~~~~~

The data folder is the cache, and there is no database. Next to each fetched file,
``<file>.json`` records the variable, the source, the extent and period, the sha256 and the
licence. ``CacheIndex`` (``provenance/sidecars.py``) scans the folder once and answers ``find``.
A fetched file is written beside its name and renamed in place, then its sidecar is written. A
station chronicle is written inside ``index.chronicle(folder, stem)``, which holds the lock of
that station. A variable that downloads needs the data folder of the call, and without one it
is refused. Your own files live under ``inputs/`` and are never a row, so ``prune`` keeps them.

A frozen run reads only what ``hydromodpy.lock`` names. ``read_locked_inputs`` reads it once
and the run hands the result down as the argument ``locked``. No module global holds the mode,
so two threads of one process never see each other as frozen.

Requests from outside a project
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``request/engine.run_request`` serves a ``DataRequest`` with no project, through
``hmp data get``. A failed source loses its files and is listed, and the others keep theirs.
``file`` and ``custom`` sources are refused, since a request has no project folder.

Boundaries
~~~~~~~~~~

A subpackage imports only what its row of ``tests/unit/architecture/data_layout.yaml`` allows,
and the generated :doc:`layers page <../generated/layers>` gives the edges between packages. A
variable never imports another variable. Another layer imports only the modules listed under
``public`` in ``data_layout.yaml``, and a variable reaches its providers through the registry,
so an ``if`` on a source name has no reason to appear. ``data`` never imports ``results``.

Where to add what
~~~~~~~~~~~~~~~~~

A provider for an existing variable is :doc:`../how-to/add-a-data-source`, and a new variable
is :doc:`../how-to/add-a-data-variable`. A user-file format goes in ``ingest/``, and an import
rule in ``data_layout.yaml``. To start reading, take ``variables/hydrometry/``
and ``families/stations.py`` for a station variable, then ``variables/sim2_series.py`` for a
grid variable, then ``loading/loader.py`` and ``loading/planner.py``.
