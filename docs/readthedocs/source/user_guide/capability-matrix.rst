Capability Matrix
=================

This page is a user-facing inventory of what HydroModPy currently exposes. It
distinguishes code support from validation evidence and documentation coverage.

Status terms
------------

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Term
     - Meaning
   * - Supported
     - The code exposes a public or workflow-level entry point.
   * - Demonstrated
     - At least one example, gallery case, or workflow page shows the feature.
   * - Validated
     - Regression or scientific validation cases exercise the behavior.
   * - Documented
     - The docs explain how to use the feature without reading implementation
       code.

Workflow coverage
-----------------

.. list-table::
   :header-rows: 1
   :widths: 18 20 20 20 22

   * - Workflow
     - CLI / Python entry
     - Demonstration
     - Documentation
     - Main gap
   * - Overview
     - ``hmp run`` / ``Project.overview``
     - Strong
     - Strong
     - Data-source reference is separate and still concise.
   * - Simulation
     - ``hmp run`` / ``Project.run`` / ``hmp.run``
     - Strong for flow
     - Strong
     - Pipeline flags and transport examples need more depth.
   * - Mesh
     - ``workflow = "mesh"`` / ``Project.build_mesh``
     - Strong
     - Strong
     - External mesh-input recipes can be expanded.
   * - Testbed
     - ``workflow = "testbed"``
     - Good
     - Partial
     - Operational recipes and result-reading examples are thinner.
   * - Calibration
     - ``workflow = "calibration"`` / ``Project.calibrate``
     - Good
     - Good
     - More API examples for custom objectives and optimizers would help.
   * - Batch
     - ``workflow = "batch"`` / ``Project.batch``
     - Partial
     - Partial
     - Regional production recipes and failure handling need more examples.
   * - Comparison
     - ``workflow = "comparison"`` / ``Project.compare``
     - Good
     - Good
     - Pairwise Python API examples are still short.

Process and solver coverage
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 18 26 18 18 20

   * - Process
     - Implemented engines
     - Demonstration
     - Validation
     - Main gap
   * - Groundwater flow
     - MODFLOW-NWT, MODFLOW 6, Boussinesq
     - Strong
     - Strong
     - Solver-selection tradeoffs should stay linked to benchmarks.
   * - Particle tracking
     - MODPATH / MODPATH 7
     - Partial
     - Limited
     - Needs curated examples and validation pages.
   * - Solute transport
     - MT3DMS, MODFLOW 6 GWT
     - Partial
     - Limited
     - Needs transport-specific assumptions, examples, and checks.
   * - Postprocess
     - Derived fields, metrics, exports
     - Partial
     - Partial
     - User guide for queries and exports was historically thin.
   * - Display
     - Registered figure catalog
     - Good
     - Partial
     - Figure compatibility and required inputs need explicit tables.

Data, results, and integration coverage
---------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 24 18 18 18

   * - Area
     - Code surface
     - Demonstration
     - Documentation
     - Main gap
   * - Data managers
     - ``hydromodpy.data`` and ``[data.*]`` sections
     - Good
     - Partial
     - Provider matrix and cache behavior.
   * - Result catalog
     - ``SimulationCatalog`` / ``Run``
     - Good
     - Partial
     - Query examples and storage schema.
   * - Exporters
     - CSV, GeoTIFF, NetCDF, Shapefile, VTU, ``.hmp``
     - Partial
     - Partial
     - Format-by-format cookbook.
   * - Python facade
     - ``Project``, ``hmp.open``, ``hmp.run``
     - Good
     - Partial
     - Full lifecycle examples.
   * - Frontend schema
     - ``hmp schema`` / ``hydromodpy.schema``
     - Limited
     - Partial
     - End-to-end UI integration guide.

Recommended reading order
-------------------------

1. Use :doc:`workflows/index` to choose the workflow family.
2. Use :doc:`data-sources` to decide which inputs can be loaded directly.
3. Use :doc:`results-and-exports` to understand persisted outputs.
4. Use :doc:`figures` to choose report figures.
5. Use :doc:`../api-reference` when scripting against the Python API.
