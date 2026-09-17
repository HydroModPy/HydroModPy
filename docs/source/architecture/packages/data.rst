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
- ``data/source/`` -- the ``DataSource`` port and its adapters, see
  below. There is no source registry: dispatch on a provider name is
  still an ``if``/``elif`` in each variable manager.
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

Four adapters ship, one per payload kind, picked for how much they
disagree: ``HubeauPiezometrySource`` (point records, WGS84, a period is
required), ``BdTopageSource`` (a feature table, WGS84, no time axis),
``IgnDemSource`` (files, **EPSG:2154**, writes under the directory the
request names) and ``Sim2PrecipitationSource`` (gridded fields,
**EPSG:2154**, a period is required).

``tests/unit/architecture/test_data_source_port_stands_alone.py``
refuses any import out of ``data/source/`` that is not ``core``,
``data.contracts`` or the port itself, beyond the declared exceptions
-- the provider entry point each adapter defers into its ``fetch``.
The layer matrix cannot see that edge, ``data`` being one layer.

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
  IgnDemSource, Sim2PrecipitationSource}``

Recommended reading path
------------------------

1. ``hydromodpy/data/README.md``
2. ``hydromodpy/data/managers/base_manager_variable.py``
3. ``hydromodpy/data/loading/loader.py`` for the dispatch model.
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
