data
====

``hydromodpy.data`` orchestrates input data acquisition, validation,
and integration. Seventeen variables share the same Variable / Manager
/ Source pattern, with a DuckDB cache that records every fetched
artefact for cache-hit detection and reproducibility.

Sub-modules
-----------

- ``data/managers/base_manager_variable.py`` -- ``BaseVariableManager``
  ABC for point variables (gauges, observations).
- ``data/managers/base_manager_field.py`` -- ``BaseFieldManager`` ABC
  for field variables (rasters, gridded forcing).
- ``data/managers/_base_manager_common.py`` -- shared cache and
  persistence logic.
- ``data/source/`` -- the ``DataSource`` port, its adapters and the
  registry that resolves a ``source_id`` to one of them, see below.
  ``hydrography`` resolves through it; the other variables still dispatch
  on a provider name with an ``if``/``elif`` in their manager.
- ``data/fetch/`` -- the ``data-fetch`` capability: its declaration, the
  body that runs it and the four artefact writers, see below. It is the
  caller of the port, kept out of ``data/source/`` so the port stays
  importable without pydantic.
- ``data/managers/planner.py`` and ``data/managers/plan.py`` --
  ``DataPlanner`` and immutable ``DataLoadPlan``. The planner merges
  ``[data].types`` with rules that infer extra variables from foreign
  sections (for example geology if ``domain.zone_ids`` mentions
  geology).
- ``data/registry/catalog_duckdb.py`` -- ``DataCatalogDuckDB``
  persisting (variable, source, station_id, bbox, dates,
  file_path, mtime, sha256) for cache hits and external-mod
  detection.
- ``data/contracts/`` -- record types: ``PointRecord``,
  ``FieldRecord``, ``LoadResult``, ``StationLocation``.
- ``data/adapters/`` -- bridges to other layers (geology, station
  sets).
- ``data/common/`` -- shared helpers (timezone, units, geometry).
- ``data/schemas/`` -- Pydantic models reused across variables.
- ``data/variables/`` -- one folder per variable.

Variable inventory
------------------

Seventeen variables ship today, each in its own folder under
``data/variables/``:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Variable
     - Sources
   * - ``hydrometry``
     - ``custom``, Hub'Eau (``hubeau``).
   * - ``piezometry``
     - ``custom``, Hub'Eau.
   * - ``water_quality``
     - ``custom``, Hub'Eau.
   * - ``intermittency``
     - ``custom``, Hub'Eau.
   * - ``hydrography``
     - ``custom``, BD TOPAGE (``bdtopage``), EuHydro (``euhydro``),
       OpenStreetMap (``osm``).
   * - ``geology``
     - ``custom``, BRGM 1:1M (``brgm_1m``), BRGM 1:50k
       (``brgm_50k``).
   * - ``dem``
     - ``custom``, IGN Geoplateforme DEM (``ign_geoplateforme_dem``).
   * - ``oceanic``
     - ``custom``, SHOM (``shom``), constant.
   * - ``recharge``
     - ``custom``, SIM2 (``sim2``), synthetic.
   * - ``runoff``
     - ``custom``, SIM2.
   * - ``precipitation``, ``temperature``, ``etp``, ``humidity``,
       ``radiation``, ``soil_moisture``, ``wind``
     - ``custom``, SIM2 across the climate stack.

The DataSource port
-------------------

``data/source/port.py`` holds a ``DataSource`` Protocol that reconciles
the seventeen distinct signatures the twenty-five fetch functions under
``data/variables/*/apis/`` carry. A source answers one question about
one provider, and declares eight things about itself: ``source_id``,
``variables``, ``payload_kind``, ``extent_crs``, ``selectors``,
``period_need``, ``hosts`` and ``writes_out_dir``. Every one of them is
compared against a real call by
``tests/contract/test_data_source_contract.py``.

The member that carries the phase is ``extent_crs``. An ``Extent`` is a
bounding box **and** the CRS it is expressed in, ``extent_for()``
converts it into the one the source declares, and the conversion
densifies the edges rather than transforming four corners. A caller
asking for a DEM and a river network over one basin passes one extent:
it reaches the IGN Geoplateforme in Lambert-93 and the Sandre WFS in
WGS84 without the caller knowing either.

Six adapters ship. Four of them are the conformance spread, one per
payload kind and picked for how much they disagree:
``HubeauPiezometrySource`` (point records, WGS84, a period is required),
``BdTopageSource`` (a feature table, WGS84, no time axis),
``IgnDemSource`` (files, **EPSG:2154**, writes under the directory the
request names) and ``Sim2PrecipitationSource`` (gridded fields,
**EPSG:2154**, a period is required). ``EuHydroSource`` and
``OsmSource`` are the two the hydrography migration brought over.

``data/source/registry.py`` maps ``source_id`` to class. In-tree sources
are declared once, in ``_BUILTIN_PATHS``, and imported on first lookup;
out-of-tree ones join through the ``hydromodpy.data.source`` entry-point
group, with no ``[project.entry-points]`` table here and no patch to this
repository. Two questions are kept apart on purpose: ``builtin_source_ids()``
answers what this build **describes**, ``list_source_ids()`` what this
installation **resolves**. A published, byte-gated description must read
the first, because the wheel was built before any plugin existed.

``tests/unit/architecture/test_data_source_port_stands_alone.py``
refuses any import out of ``data/source/`` that is not ``core``,
``data.contracts`` or the port itself, beyond the declared exceptions
-- the provider entry point each adapter defers into its ``fetch``.
The layer matrix cannot see that edge, ``data`` being one layer.

The data-fetch capability
-------------------------

``data/fetch/`` turns the port into something invocable from outside:
``hmp process run data-fetch --job <dir>`` reads one ``request.json``,
asks one source, and seals what came back. It opens no workspace, no
catalog and no DuckDB, and it never sees a ``geographic`` object -- the
extent is an input, a bounding box carrying its CRS or a vector mask
another job produced.

- ``capability.py`` -- the ``CapabilityDecl`` and the Pydantic request
  model. The ``source`` input is a union tagged on ``source.id``, and it
  is **the** list: ``SERVED_SOURCES`` is read off its own discriminator
  and resolved through the registry, and ``reaches_network`` is the union
  of those sources' ``hosts``. One member of the union tags no source --
  ``{"id": "installed", "name": ...}`` reaches anything the installation
  resolves, including a source this build does not describe, and it is
  excluded from every derivation for that reason. The derivations are
  compared to what they came from by
  ``tests/unit/data/test_data_fetch_declaration.py``.
- ``worker.py`` -- resolution, refusal, fetch, seal and the reuse
  short-circuit, on the pattern ``terrain-delineate`` set. Every fetch
  gets a ``TemporaryDirectory`` as its ``out_dir``, so what a provider
  leaves beside its result never lands under ``outputs/``.
- ``artefacts.py`` -- how each payload kind becomes one sealable file:
  one GeoPackage layer for ``features``, one moved GeoTIFF for
  ``files``, one long Parquet table for ``points``, one merged NetCDF-4
  for ``fields``. Zarr is what a run directory uses for field arrays and
  it is a directory: a seal inventories files, so a job artefact cannot
  be one.

Exactly one payload artefact is written per run, and
``outputs/fetch.json`` is always written: it names which one, the extent
that was really queried and the CRS it was really queried in.

Where a manager's extent comes from
-----------------------------------

``DemManager`` and ``GeologyManager`` resolve the box they ask a
provider over from **the source config alone**, through
``data/common/source_extent.py``: ``mask_path`` first, then ``extent``
together with ``project_extent``. Neither takes a ``geographic``
parameter any more, and neither does ``DataStore.load_dem`` or
``load_geology``.

The seam that replaces the object already existed and had not been
named: ``DataManagersRuntimeLoader`` sets
``src.mask_path = Path(geographic.watershed_shp)`` before handing the
config to the store, so the path where "the watershed" is a **file** was
already the one a project run took. The two managers read
``self.geographic`` *in addition to* that injection, never instead of
it, which is why this is a mechanism removed rather than one added.

``mask_extent()`` returns an ``Extent`` -- the port's, bounds plus the
CRS the file declares -- and the reprojection to the CRS a provider
publishes in is ``Extent.to_crs``. A mask that declares no CRS is
refused; it used to inherit the watershed's, which is right exactly as
often as the two files are the same one.

A raster mask goes through the valid-cell hull and not
``rasterio.bounds``: a catchment mask is ``1`` on the catchment and
nodata everywhere else in a rectangle sized to the accumulation grid,
so its footprint is not its catchment. Measured on a 10x10 mask whose
valid region is the central 4x4, that is ``(0, 0, 100, 100)`` against
``(30, 30, 70, 70)``.

``mask_extent_in(path, crs)`` is the tighter answer when the shape is in
hand, and hydrography's request box takes it: the bounds of a
reprojected polygon are the image of its own vertices, while the bounds
of a reprojected box are the image of a rectangle that contains it.
Measured on a Nancon-sized basin from EPSG:2154 to EPSG:4326, the box
route is 680 m to 1 030 m wider on each side -- and the catalog serves a
cached download only when its entry is a superset of the request, so
that width is a download that did not have to happen.

``HydrographyManager`` and ``OceanicManager`` lost the object too, and
they needed more than a box for it. Hydrography read it for three
things: the project CRS, the polygon it clips to and ``watershed_dem``.
Its mask is declared on the **section** and not on a source, because it
concatenates every source before clipping once; the frame the clip
happens in is the mask's own, so the project CRS stopped being an input
at all; and the reference grid is a ``base_raster`` constructor
argument, because it is not an extent and not a user's choice.
``OceanicManager`` selects a SHOM gauge by ``station_ids`` or, failing
that, by the point at the centre of its extent -- the named station
wins, because the loader fills a mask into every source that declares
the field whether or not it asked for one.

``MANAGERS_STILL_TAKING_GEOGRAPHIC`` is now empty, and
``DataStore.load_variable`` lost the ``**extra_kwargs`` that used to
carry the object to the one manager that took it. No manager on the
generic path receives a project-scoped object, and there is no longer a
door through which one could.

``project_extent`` is still a bare tuple and is **not in one CRS**: the
site-selection pipeline builds it in Lambert-93 for the DEM and in WGS84
for the observation managers, and hands ``GeologyManager`` nothing at
all today. ``PROJECT_EXTENT_CRS`` declares what the raster side
receives, and ``tests/unit/data/test_source_extent.py`` pins it against
``bbox_for_departments`` -- one branch of ``_dem_request_bbox`` out of
four, which is what the test measures and all it claims.

LoadResult contract
-------------------

Every manager returns a ``LoadResult``:

.. code-block:: python

   @dataclass
   class LoadResult:
       points: list[PointRecord] = []
       fields: list[FieldRecord] = []
       warnings: list[str] = []

- ``PointRecord``: ``station_id``, ``variable``, ``source``,
  ``unit``, ``frequency``, ``data`` (datetime-indexed DataFrame),
  ``date_start`` / ``date_end``, ``location`` (``StationLocation``),
  ``source_unit``.
- ``FieldRecord``: ``variable``, ``source``, ``field_path``,
  ``crs``, ``shape``, ``metadata``.

Key public symbols
------------------

- ``hydromodpy.data.managers.base_manager_variable.BaseVariableManager``
- ``hydromodpy.data.managers.base_manager_field.BaseFieldManager``
- ``hydromodpy.data.loading.loader.DataManagersRuntimeLoader``
- ``hydromodpy.data.managers.planner.DataPlanner``
- ``hydromodpy.data.managers.plan.DataLoadPlan``
- ``hydromodpy.data.registry.catalog_duckdb.DataCatalogDuckDB``
- ``hydromodpy.data.contracts.load_result.LoadResult``
- ``hydromodpy.data.contracts.timeseries.{PointRecord, FieldRecord}``
- ``hydromodpy.data.source.{DataSource, Extent, Period, FetchRequest,
  FetchResult}``
- ``hydromodpy.data.source.{HubeauPiezometrySource, BdTopageSource,
  EuHydroSource, IgnDemSource, OsmSource, Sim2PrecipitationSource}``
- ``hydromodpy.data.source.registry.{get, get_serving, register,
  list_source_ids, builtin_source_ids}`` -- ``source_id`` to class, and
  the ``hydromodpy.data.source`` entry-point group a third party joins
- ``hydromodpy.data.fetch.capability.{DATA_FETCH, DataFetchRequest}``
- ``hydromodpy.data.fetch.worker.run``

Recommended reading path
------------------------

1. ``hydromodpy/data/README.md``
2. ``hydromodpy/data/managers/base_manager_variable.py``
3. ``hydromodpy/data/loading/loader.py`` for the dispatch model.
   Its only surface is ``DataManagersRuntimeLoader``: the second,
   module-level ``load_variable`` that used to sit at the bottom had
   no importer and a divergent copy of the dem / geology /
   hydrography branch, and it went with the ``geographic``
   fallback it was the last caller of.
4. ``hydromodpy/data/variables/hydrometry/`` for a complete point
   variable.
5. ``hydromodpy/data/variables/dem/`` for a complete field variable.
6. ``hydromodpy/data/managers/planner.py`` for the inference rules.
7. ``hydromodpy/data/registry/catalog_duckdb.py`` for the cache
   schema.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``core``, ``schema``, ``data``, ``spatial``.
- Documented tolerance: ``data`` -> ``results`` for the read-only
  cross-DB ATTACH bridge.
- Allowed sources: ``simulation``, ``calibration``, ``analysis``,
  ``config``, ``workflow``, ``catalog``, ``project`` and ``cli``.

See also
--------

- :doc:`/architecture/how-to/add-a-data-variable` and
  :doc:`/architecture/how-to/add-a-data-source` for contributor
  recipes.
- :doc:`/user_guide/data/index` for the user-facing data loading
  guide and provider matrix.
