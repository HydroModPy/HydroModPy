Choose Your First Workflow
==========================

Use this page when you know what you want to learn, but not which HydroModPy
entry point to open first.

.. important::

   Default recommendation: start with :doc:`data-overview-walkthrough`. It is
   the fastest way to understand basin setup, data loading, and case structure
   before any solver run.

Match your goal to a first page
-------------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 26 28 22

   * - Goal
     - Start here
     - Why this is the right first step
     - Primary command
   * - Inspect one basin before any solve
     - :doc:`data-overview-walkthrough`
     - You only work with watershed extraction, domain setup, and data loading.
     - ``python -m launchers data-overview run examples/projects/data_overview/project.toml``
   * - Run one complete example end to end
     - :doc:`simulation-walkthrough`
     - You see how geographic setup, meshing, flow, transport, and display fit together.
     - ``python -m hydromodpy run examples/projects/launcher_simulation/run_fast_mf6_mesh_catchment.toml``
   * - Compare two numerical methods on the same support
     - :doc:`reading-results-pages`
     - You need to read solver-to-solver discrepancies without confusing them with validation.
     - ``python -m launchers method-comparison run examples/projects/launcher_simulation/run_method_comparison_example12_map_existing.toml``
   * - Check numerical credibility against a reference
     - :doc:`reading-results-pages`
     - Validation pages explain analytical targets, solver coverage, and tolerance-based metrics.
     - ``python -m validation_cases.run_cases --solver modflow6 --regime both --no-show``
   * - Browse the full static inventory first
     - :doc:`../capability_gallery/index`
     - The capability gallery lets you scan curated figures quickly before running anything locally.
     - ``python -m tools.doc_gallery``

Default path for most users
---------------------------

For most first-time contributors or users working from repository examples:

1. Start with :doc:`data-overview-walkthrough`.
2. Continue with :doc:`simulation-walkthrough`.
3. Use :doc:`reading-results-pages` once you begin comparing methods or reading
   validation metrics.

Why not start with validation?
------------------------------

Validation pages are useful, but they answer a different question. They tell
you whether one numerical path reproduces an analytical or trusted reference.
They do not teach the full user-facing workflow as directly as the
data-overview and simulation examples.

When to use the static gallery
------------------------------

The :doc:`../capability_gallery/index` is best used as a visual inventory:

- it is fast to browse,
- it helps you find an example family,
- it does not replace the editable config files or the full run workspaces.
