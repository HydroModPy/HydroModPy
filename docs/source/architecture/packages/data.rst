data
====

``hydromodpy.data`` is everything a run reads from outside: provider APIs,
user files, their cache and the typed records handed to the layers above.
Twenty-five variables, one per ``[data.<name>]`` section of a project TOML,
share one template: a configuration model, a manager whose ``SOURCES`` table
maps each source name to the function that fetches it, and a DuckDB index of
the cache. The map of the package, with its import rules, is
``hydromodpy/data/README.md``.

Sub-packages
------------

In dependency order, lowest first.

- ``data/contracts/`` -- the records handed upward: ``PointRecord``,
  ``FieldRecord``, ``TableRecord``, ``LoadResult``, ``StationLocation``.
- ``data/schemas/`` -- pandera schemas of the input tables, each with its
  ``validate()``.
- ``data/source/`` -- the ``DataSource`` port and the registry of sources,
  plugins included, see below.
- ``data/common/`` -- helpers with no variable config and no cache: HTTP,
  units, geometry, the extent a source is asked over
  (``source_extent.py``), file naming. ``common/clients/`` holds what several
  variables share: the SIM2 product table and download, the Hub'Eau station
  helpers.
- ``data/ingest/`` -- a user file to the storage format and to records.
- ``data/provenance/`` -- what sits next to a file on disk: sidecars,
  derived copies, ``hydromodpy.lock``.
- ``data/registry/`` -- ``DataCatalogDuckDB``, the index of the cache
  (``data/cache.duckdb``). The files and their sidecars stay the truth.
- ``data/managers/`` -- the bases the variable managers inherit.
- ``data/variables/`` -- one package per variable, on the template below.
- ``data/loading/`` -- ``[data]`` of the TOML to the variables it activates
  to the data loaded: ``DataManagersConfig``, ``DataPlanner``,
  ``DataManagersRuntimeLoader``, ``DataStore``.
- ``data/workspace/`` -- the workspace data folder: scaffold and scan of
  custom files.
- ``data/request/`` -- data asked for from outside a project, see below.
- ``data/cases/`` -- demonstrators driven by a TOML, with their data.

``tests/unit/architecture/data_layout.yaml`` says which sub-package may import
which, and which modules another layer may import;
``tests/unit/architecture/test_package_layouts.py`` checks every import against it.

Variable inventory
------------------

.. list-table::
   :header-rows: 1
   :widths: 30 42 28

   * - Variables
     - Sources besides ``custom``
     - Manager base
   * - ``precipitation``, ``etp``, ``temperature``, ``wind``, ``humidity``,
       ``radiation``, ``soil_moisture``, ``runoff``
     - SIM2 (``sim2``)
     - ``BaseFieldManager``
   * - ``recharge``
     - SIM2, ``synthetic``
     - ``BaseFieldManager``
   * - ``oceanic``
     - SHOM (``shom``), ``constant``
     - ``BaseFieldManager``
   * - ``hydrometry``, ``piezometry``, ``water_quality``, ``intermittency``
     - Hub'Eau (``hubeau``)
     - ``BaseVariableManager``
   * - ``lake_inflow``, ``lake_levels``, ``lake_outflow``, ``lake_withdrawal``
     - none
     - ``BaseVariableManager``
   * - ``lake_abacus``, ``lake_bathymetry``, ``lake_geometry``, ``substratum``
     - none
     - ``BaseFileManager``
   * - ``dem``
     - IGN Geoplateforme (``ign_geoplateforme_dem``)
     - written by hand
   * - ``geology``
     - BRGM 1:1M (``brgm_1m``), BRGM 1:50k (``brgm_50k``)
     - written by hand
   * - ``hydrography``
     - BD TOPAGE (``bdtopage``), EU-Hydro (``euhydro``), OpenStreetMap
       (``osm``), and any installed plugin that serves a network
     - written by hand

The single list of the twenty-five sections is ``VARIABLE_SPECS`` in
``data/loading/_dispatch.py``.

The manager template
--------------------

A manager maps each value a user may write in ``source =`` to the function
that fetches it:

.. code-block:: python

   class HydrometryManager(BaseVariableManager):
       VARIABLE_NAME = "hydrometry"
       INTERNAL_UNIT = "m3/s"
       RECORD_VARIABLE = "discharge"
       SOURCES = {"hubeau": hubeau.fetch_for_config}

- ``RECORD_VARIABLE`` is optional. It names what a record carries when that
  differs from ``VARIABLE_NAME``.
- ``custom`` is never in ``SOURCES``. The base class loads the user's files
  through ``load_custom``; a variable whose format takes real work overrides
  it or keeps a ``custom.py``.
- A ``SOURCES`` function receives the validated source config, the extent and
  a ``SourceContext`` (project extent, cache folder, section dates, nearest
  point). A grid: ``fetch(cfg, *, bbox, period, context)``. Stations:
  ``fetch(cfg, *, bbox, station_ids, start, end, context)``.
- The base class owns the cache. ``BaseFieldManager`` keeps grids,
  ``BaseVariableManager`` keeps chronicles per station and asks only for the
  missing periods, ``BaseFileManager`` converts a user file once and indexes
  the copy.
- The ``source`` field of a config stays a closed ``Literal``, which the JSON
  schema and the configuration reference publish. ``hydrography`` is the
  exception: its sources resolve through the registry, plugins included.
- ``tests/unit/data/test_the_variable_families_agree.py`` ties the lists: the
  ``source`` values of each variable (``custom`` aside) are the keys of
  ``SOURCES``, and each has an entry (licence, network hosts) in
  ``hydromodpy/schema/sources.py``.

The DataSource port
-------------------

``data/source/port.py`` holds a ``DataSource`` Protocol. A source answers one
question about one provider and declares eight things about itself:
``source_id``, ``variables``, ``payload_kind``, ``extent_crs``,
``selectors``, ``period_need``, ``hosts`` and ``writes_out_dir``. An
``Extent`` is a bounding box **and** its CRS; ``extent_for()`` converts it
into the one the source declares, densifying the edges rather than
transforming four corners.

Three sources ship, the river networks ``[data.hydrography]`` resolves
through the registry: ``BdTopageSource``, ``EuHydroSource`` and
``OsmSource``, on a shared ``FeatureSource`` base
(``variables/hydrography/apis/features.py``). A third-party package adds a
source by declaring a ``DataSource`` class on the ``hydromodpy.data.source``
entry-point group; it is then nameable in a hydrography section, and for any
payload kind under the ``installed`` member of a data request.
``tests/contract/test_data_source_contract.py`` holds every source to the
port, with three in-test doubles covering the payload kinds the shipped
sources do not.

``data/source/registry.py`` maps ``source_id`` to class. In-tree sources are
declared once, as dotted paths in ``_BUILTIN_PATHS``, and imported on first
lookup. ``builtin_source_ids()`` answers what this build **ships**,
``list_source_ids()`` what this installation **resolves**.

Data asked for from outside a project
-------------------------------------

``data/request/`` serves ``[data]`` sections to a caller that has no project
and no TOML. One engine, three entries: ``hmp data get``, the
``data-request`` process (``hmp process run data-request --job <dir>``) and
``run_request`` from Python.

- ``model.py`` -- ``DataRequest``: the ``[data]`` sections with the models
  of the TOML, an extent that is exactly one of a box with its CRS, a vector
  mask (a file link, pinnable by ``sha256``) or station codes, an optional
  period, and plugin sources under ``installed``, whose options are bound
  against their constructor before anything runs.
- ``engine.py`` -- ``run_request`` loads each section through its manager,
  over the extent written as a polygon mask in its own CRS. ``hydrography``
  and the installed sources go through the source registry, never through
  the Whitebox manager. A source that fails loses its files and is listed
  with its error; the others keep theirs.
- ``artefacts.py`` -- each answer cut to the extent and period, whatever the
  cache held: chronicles in one long Parquet table, grids in one NetCDF,
  rasters in GeoTIFF, vectors in one GeoPackage layer.
- ``job.py`` -- the ``data-request`` declaration and its body: resolution and
  refusal before anything is written, a cache under ``$TMPDIR`` indexed in
  memory, the seal, the reuse short-circuit. A ``custom`` source is refused.

``request.json`` beside the files lists each one with its sha256, CRS, box,
period and unit, the variables that answered nothing and the ones that
failed.

Where a manager's extent comes from
-----------------------------------

A manager resolves the box it asks a provider over from **the source config
alone**: ``mask_path`` first, then ``extent`` together with
``project_extent``. No manager takes a project-scoped object: during a run,
``DataManagersRuntimeLoader`` writes the watershed file into ``mask_path``
before handing the config to the store.

Every mask is read by ``data/common/source_extent.py``:

- ``mask_geometry(path)`` returns the polygon and the CRS the file declares,
  and refuses a mask without one. A raster mask goes through the valid-cell
  hull and not its footprint: a catchment mask is ``1`` on the catchment and
  nodata elsewhere in a rectangle sized to the accumulation grid.
- ``mask_extent(path)`` and ``mask_extent_in(path, crs)`` give its box;
  the second measures the reprojected shape, which is tighter than a
  reprojected box and keeps a cached download a superset of the request.
- ``mask_geometry_wgs84(path)`` is the polygon the station managers filter
  with: features reprojected before their union, and a mask without a CRS
  read as WGS84.

``project_extent`` is still a bare tuple, read in ``PROJECT_EXTENT_CRS``
(Lambert-93) by the raster managers.

LoadResult contract
-------------------

Every manager returns a ``LoadResult``:

.. code-block:: python

   @dataclass
   class LoadResult:
       points: list[PointRecord]
       fields: list[FieldRecord]
       tables: list[TableRecord]
       warnings: list[str]

- ``PointRecord``: ``station_id``, ``variable``, ``source``, ``unit``,
  ``frequency``, ``data`` (a ``datetime`` / ``value`` table), ``date_start``
  and ``date_end``, ``location`` (``StationLocation``), ``source_unit``.
- ``FieldRecord``: ``variable``, ``source``, ``unit``, ``data`` (an xarray
  dataset or a path to a file), ``bbox``, ``crs``, ``date_start`` and
  ``date_end``, ``frequency``.
- ``TableRecord``: a table with its ``table_id`` (a lake abacus).

Key public symbols
------------------

- ``hydromodpy.data.{DataManagersConfig, DataPlanner, DataLoadPlan,
  DataManagersRuntimeLoader, DataStore, DataRequest, run_request}``
- ``hydromodpy.data.registry.catalog_duckdb.DataCatalogDuckDB``
- ``hydromodpy.data.contracts.load_result.LoadResult``
- ``hydromodpy.data.contracts.timeseries.PointRecord``,
  ``hydromodpy.data.contracts.spatial_field.FieldRecord``,
  ``hydromodpy.data.contracts.table.TableRecord``
- ``hydromodpy.data.source.{DataSource, Extent, Period, FetchRequest,
  FetchResult, BdTopageSource, EuHydroSource, OsmSource}``
- ``hydromodpy.data.source.registry.{get, get_serving, register,
  list_source_ids, builtin_source_ids}``
- ``hydromodpy.data.request.job.{DATA_REQUEST, run}``

Recommended reading path
------------------------

1. ``hydromodpy/data/README.md``
2. ``hydromodpy/data/variables/hydrometry/`` for a station variable, and
   ``hydromodpy/data/managers/base_manager_variable.py`` for its cache.
3. ``hydromodpy/data/variables/wind/`` for a grid variable, and
   ``hydromodpy/data/common/clients/sim2_products.py`` for SIM2.
4. ``hydromodpy/data/loading/loader.py`` for what a run loads, and
   ``hydromodpy/data/loading/planner.py`` for the inference rules.
5. ``hydromodpy/data/request/engine.py`` for a request from outside.
6. ``hydromodpy/data/registry/catalog_duckdb.py`` for the cache index.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``data``, ``spatial``.
- Allowed sources: ``config``, ``simulation``, ``calibration``,
  ``analysis``, ``workflow``, ``catalog``, ``project`` and ``cli``, plus the
  documented ``spatial`` -> ``data`` tolerance for the optional hydrography
  fetch of site selection.

See also
--------

- :doc:`/architecture/how-to/add-a-data-variable` and
  :doc:`/architecture/how-to/add-a-data-source` for contributor recipes.
- :doc:`/user_guide/data/index` for the user-facing data loading guide and
  provider matrix.
