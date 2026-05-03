Project Workflow Examples
=========================

The ``examples/projects/`` directory contains TOML-first examples. These are
the best entry point when you want to exercise the current workspace, workflow,
catalog, and report machinery instead of stepping through a notebook.

Inventory
---------

.. list-table::
   :header-rows: 1
   :widths: 24 24 52

   * - Directory
     - Main topic
     - Use it when you want to...
   * - ``00_getting_started``
     - First simulation
     - Run the shortest project-level workflow after installation.
   * - ``01_calibration``
     - Calibration
     - Inspect a TOML-driven inverse-problem setup.
   * - ``02_nancon_watershed``
     - Watershed simulation
     - Work with a named catchment example and persisted outputs.
   * - ``03_canut_watershed``
     - Watershed simulation
     - Compare another catchment setup with the same workspace model.
   * - ``03_groundwater_1d``
     - Controlled 1D case
     - Test a small groundwater configuration.
   * - ``04_data_overview``
     - Data overview
     - Load and inspect configured data before solver execution.
   * - ``05_nancon_data_overview``
     - Data overview
     - Read a watershed-specific identity-card workflow.
   * - ``06_vire_selune``
     - Regional case
     - Inspect a larger multi-catchment or regional setup.
   * - ``07_mesh_gallery``
     - Mesh gallery
     - Generate or inspect discretization variants.
   * - ``08_mesh_viewer``
     - Mesh visualization
     - Explore mesh artifacts outside a full solver workflow.
   * - ``09_capability_gallery``
     - Documentation evidence
     - Rebuild curated case-study artifacts.
   * - ``09_comparison_workflow``
     - Solver/method comparison
     - Run shared-case comparisons and read comparison outputs.
   * - ``10_testbed_workflow``
     - Method testbed
     - Run controlled variants through the testbed launcher.

Running an example
------------------

.. code-block:: bash

   hmp run examples/projects/00_getting_started/run_demo.toml --dry-run
   hmp run examples/projects/00_getting_started/run_demo.toml

Use ``--dry-run`` first when you only want to inspect the resolved workflow and
pipeline steps. The exact TOML filenames vary by directory; open the directory
matching the topic and choose the ``run_*.toml`` or workflow-specific config.

Relationship to notebooks
-------------------------

The notebook gallery remains the teaching path. Project examples are the
operational path: they exercise the CLI, workspace layout, result catalog,
exports, and workflow launchers.

See also :doc:`examples`, :doc:`getting_started/index`, and
:doc:`user_guide/workflows/index`.
