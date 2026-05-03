Workflow Families
=================

Use this page when the question is not:
"How do I launch HydroModPy?"

but rather:
"Which kind of user-facing workflow exists, and which detailed page should I
read next?"

This page is now a compact map. The detailed workflow documentation lives in
:doc:`../user_guide/workflows/index`.

Quick Map
---------

.. list-table::
   :header-rows: 1
   :widths: 14 28 30 28

   * - Workflow
     - Primary goal
     - First concrete entry point
     - Detailed documentation
   * - ``overview``
     - Inspect one basin, extract support, and load the main geographic and
       observed data before any solver run.
     - ``examples/projects/04_data_overview/project.toml``
     - :doc:`../user_guide/workflows/overview`
   * - ``simulation``
     - Run one forward model end to end from support construction to solver
       outputs.
     - ``examples/projects/06_vire_selune/run_vire_mf6_irregular.toml``
     - :doc:`../user_guide/workflows/simulation`
   * - ``testbed``
     - Expand controlled method variants and collect robustness evidence,
       including mesh-resolution and mesh-constraint studies.
     - ``examples/projects/10_testbed_workflow/mesh_resolution_testbed.toml``
       or ``flow_k_sensitivity_testbed.toml``
     - :doc:`../user_guide/workflows/testbed`
   * - ``calibration``
     - Estimate parameters against one or several observables.
     - ``examples/projects/02_nancon_watershed/run_calibration_k.toml``
     - :doc:`../user_guide/workflows/calibration`
   * - ``batch``
     - Launch a multi-site or campaign-style execution over several cases.
     - A ``workflow = "batch"`` TOML with ``[regional_lab]``
     - :doc:`../user_guide/workflows/batch`
   * - ``comparison``
     - Compare several child simulations built from one shared physical base
       case.
     - ``examples/projects/09_comparison_workflow/compare_dupuit_mf6_bouss.toml``
     - :doc:`../user_guide/workflows/comparison`

Why This Split Matters
----------------------

HydroModPy distinguishes three concepts that are easy to confuse:

- a workflow is the user-facing operation requested by ``workflow = "..."``;
- a usage mode is the entry interface, such as CLI TOML, Python, JSON, or
  notebook cells;
- a solver is one numerical backend used by some workflows.

For example, ``simulation`` is a workflow. ``modflow6`` is a solver that can be
used by that workflow. ``hmp run`` is one usage mode for launching it.
Similarly, meshing is now documented as a ``testbed`` subject rather than as a
separate user guide workflow. Use ``subject = "mesh"`` with
``runner.type = "mesh_catchment"`` when the scientific question is about
resolution, constraints, or discretization robustness.

Recommended Reading Order
-------------------------

1. Read :doc:`choose-your-first-workflow` if you are still choosing your first
   example.
2. Use this page to identify the workflow family.
3. Open the detailed page in :doc:`../user_guide/workflows/index`.
4. Jump to :doc:`../scientific/index` for equations and assumptions.
5. Jump to :doc:`../architecture/index` for package boundaries and runtime
   diagrams.

Related Pages
-------------

- :doc:`../seven-modes` explains how HydroModPy is driven.
- :doc:`../user_guide/workflows/index` explains each workflow in detail.
- :doc:`../scientific/index` explains scientific methods.
- :doc:`../architecture/index` explains implementation structure.

.. toctree::
   :hidden:
   :maxdepth: 1

   Overview workflow <../user_guide/workflows/overview>
   Simulation workflow <../user_guide/workflows/simulation>
   Testbed workflow <../user_guide/workflows/testbed>
   Calibration workflow <../user_guide/workflows/calibration>
   Batch workflow <../user_guide/workflows/batch>
   Comparison workflow <../user_guide/workflows/comparison>
