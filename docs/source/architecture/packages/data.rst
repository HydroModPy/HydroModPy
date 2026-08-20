data
====

``hydromodpy.data`` orchestrates input data acquisition, validation,
and integration. Seventeen variables share the same Variable / Manager
/ Source pattern, with a DuckDB cache that records every fetched
artefact for cache-hit detection and reproducibility.

Sub-modules
-----------

- ``data/base_manager_variable.py`` -- ``BaseVariableManager`` ABC
  for point variables (gauges, observations).
- ``data/base_manager_field.py`` -- ``BaseFieldManager`` ABC for
  field variables (rasters, gridded forcing).
- ``data/_base_manager_common.py`` -- shared cache and persistence
  logic.
- ``data/sources.py`` -- source registry with ``@register_source``
  decorator and ``get_source(variable_type, source_name)`` lookup.
- ``data/planner.py`` and ``data/plan.py`` -- ``DataPlanner`` and
  immutable ``DataLoadPlan``. The planner merges ``[data].types``
  with rules that infer extra variables from foreign sections (for
  example geology if ``domain.zone_ids`` mentions geology).
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
