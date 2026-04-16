Data Managers And External Dependencies
=======================================

The data-manager root layer is HydroModPy's orchestration boundary for data
loading. It answers three questions before solver work begins:

- which data families are active for this run,
- which manager loads each family,
- which external providers or local inputs those managers depend on.

This architecture is intentionally centralized under ``hydromodpy.data`` so the
launcher does not need to duplicate activation rules or provider-specific
loading logic.

Root-Layer Responsibilities
---------------------------

The root files under ``hydromodpy/data/`` split responsibilities as follows:

- ``data_managers_config.py`` validates ``[data]`` and normalizes typed
  sections,
- ``planner.py`` merges explicit types with inference rules,
- ``plan.py`` stores the immutable ``DataLoadPlan``,
- ``runtime_loader.py`` dispatches each activated type to its concrete manager,
- ``data_managers.py`` exposes the lightweight runtime container consumed by
  orchestration layers.

This means the launcher can stay focused on execution order while the data layer
owns activation, validation, and loading dispatch.

Activation And Inference
------------------------

The activation contract is deterministic:

- explicit ``data.types`` always wins,
- additional types can be inferred from domain or flow configuration,
- the final decision is stored in ``DataLoadPlan`` with reasons per type.

Current inference rules include:

- ``domain.supports`` using provider ``geology`` -> activate ``geology``,
- ``domain.zone_ids`` containing ``geology`` -> activate ``geology``,
- ``flow.active_bc`` containing ``stream`` -> activate ``hydrography``,
- ``flow.active_bc`` containing ``ocean`` -> activate ``oceanic``.

``data.inference_mode = "warn"`` accepts these inferences and records them.
``data.inference_mode = "strict"`` requires explicit typed sections for the
inferred families, except for the geology defaulting path already handled by
the data layer.

Runtime Dispatch
----------------

``DataManagersRuntimeLoader`` is the concrete dispatcher used after planning.
Its current dispatch table covers:

- terrain and support context: ``dem``, ``geology``, ``hydrography``,
  ``oceanic``,
- observed stations: ``hydrometry``, ``piezometry``, ``intermittency``,
  ``water_quality``,
- climatic or forcing-like fields: ``recharge``, ``runoff``,
  ``precipitation``, ``etp``, ``temperature``, ``wind``, ``humidity``,
  ``radiation``, ``soil_moisture``.

Each family still owns its own typed config and manager package. The root layer
only decides activation and calls the right loader.

Provider Families
-----------------

The current provider inventory documented in ``hydromodpy/data/structure.md``
is summarized below.

.. list-table::
   :header-rows: 1

   * - Provider or source family
     - Main HydroModPy data families
     - Geographic scope
   * - Hub'Eau Hydrometrie
     - ``hydrometry``
     - France metropolitaine
   * - Hub'Eau Piezometrie
     - ``piezometry``
     - France metropolitaine
   * - Hub'Eau ONDE
     - ``intermittency``
     - France metropolitaine
   * - Hub'Eau Qualite
     - ``water_quality``
     - France metropolitaine
   * - SIM2 EDR
     - ``precipitation``, ``etp``, ``temperature``, ``wind``, ``humidity``,
       ``radiation``, ``soil_moisture``, ``recharge``, ``runoff``
     - France metropolitaine
   * - SHOM
     - ``oceanic``
     - French coasts
   * - IGN GeoPlateforme BD ALTI
     - ``dem``
     - France metropolitaine
   * - BRGM 1:1M / 1:50K
     - ``geology``
     - France metropolitaine
   * - Sandre WFS / BD Topage
     - ``hydrography``
     - France metropolitaine
   * - EU-Hydro
     - ``hydrography``
     - Europe
   * - OpenStreetMap / Overpass
     - ``hydrography``
     - global

External Runtime Constraints
----------------------------

The important architectural point is not only "which API is called", but also
"what must be available for that call to succeed".

Typical constraints today are:

- SIM2-backed variables require a bounding box and a project time window,
- SHOM loading requires a geographic context and a resolved date range,
- geology and DEM loading often rely on geographic masks or raster support,
- hydrography and watershed preprocessing depend on the Whitebox backend for
  some derived products,
- local custom sources remain first-class inputs and must not be silently
  overwritten by cache subsumption logic.

The data catalog and cache layer then add another operational constraint:

- empty remote results may be cached as sentinels to avoid repeated failed API
  calls,
- stored paths stay relative for workspace portability,
- ``force_refresh`` bypasses cache reuse when a provider call must be repeated.

What To Read When Touching This Layer
-------------------------------------

Start with:

- ``hydromodpy/data/README.md`` for the root orchestration contract,
- ``hydromodpy/data/planner.py`` for inference rules,
- ``hydromodpy/data/runtime_loader.py`` for the active dispatch surface,
- ``hydromodpy/data/structure.md`` for the broader provider and cache model.

Then inspect one typed family such as:

- ``hydromodpy/data/variables/oceanic/``,
- ``hydromodpy/data/variables/geology/``,
- ``hydromodpy/data/variables/hydrometry/``,
- ``hydromodpy/data/variables/precipitation/``.

Those packages own provider-specific config, IO, and manager behavior.

Current Boundary With Future Work
---------------------------------

The architecture roadmap still mentions future consolidation work, especially:

- deeper planner simplification,
- clearer convergence between some observed-station families,
- integrating PyHELP as a standard data-manager family rather than a more
  isolated coupling path.

Until that happens, this page should be read as the current root-layer contract,
not as the final long-term provider map.
