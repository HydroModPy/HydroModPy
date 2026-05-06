Workflow Families
=================

Use this page when the question is not:
"How do I launch HydroModPy?"

but rather:
"Which kind of user-facing workflow exists, and what does it teach?"

This page complements :doc:`../../seven-modes`:

- :doc:`../../seven-modes` explains usage modes;
- this page explains workflow families;
- :doc:`../../theory/index` explains equations, assumptions, and methods;
- :doc:`../../architecture/index` explains runtime structure and package
  boundaries.

Quick Map
---------

.. list-table::
   :header-rows: 1
   :widths: 14 28 28 30

   * - Workflow
     - Primary goal
     - First concrete entry point
     - Best current next page
   * - ``overview``
     - Inspect one basin, extract support, and load the main geographic and
       observed data before any solver run
     - ``examples/projects/04_data_overview/project.toml``
     - :doc:`../../getting_started/data-overview-walkthrough`
   * - ``simulation``
     - Run one forward model end to end from support construction to solver
       outputs
     - ``examples/projects/06_vire_selune/run_vire_mf6_irregular.toml``
     - :doc:`../../getting_started/simulation-walkthrough`
   * - ``mesh``
     - Build and export a catchment mesh as a reusable discretization artifact
     - public example set still thin; current runtime anchor lives in the mesh
       architecture pages and regression fixtures
     - :doc:`../../architecture/mesh/index`
   * - ``calibration``
     - Run parameter estimation against one or several observables
     - ``examples/projects/01_calibration/project.toml``
     - :doc:`../../theory/calibration/index`
   * - ``batch``
     - Launch a multi-site or campaign-style execution over several cases
     - no polished public example yet
     - :doc:`../../architecture/index`
   * - ``comparison``
     - Compare several child simulations built from one shared physical base
       case
     - ``examples/projects/09_comparison_workflow/compare_dupuit_mf6_bouss.toml``
     - :doc:`comparison-workflow`

Why This Split Matters
----------------------

HydroModPy already distinguishes ``workflow`` from ``Pipeline`` and from
usage modes in both the code and the glossary.

Keeping that distinction visible in the public docs avoids three common
confusions:

- a workflow is not a solver;
- a workflow is not an entry interface;
- a workflow page should not try to replace a scientific method note.

Recommended Editorial Split
---------------------------

The most robust documentation split is:

- ``seven-modes`` answers how HydroModPy is driven;
- ``workflow-families`` answers what the user is trying to do;
- ``theory/*`` answers which physical and numerical methods are used;
- ``architecture/*`` answers where those responsibilities live in code.

That split stays coherent with ``hydromodpy/workflow/dispatch.py`` and with the
developer glossary.

Workflow Profiles
-----------------

Overview Workflow
^^^^^^^^^^^^^^^^^

This workflow is the right starting point when the first question is:
"What basin am I about to model, and what input data exist?"

It is mainly about:

- catchment delineation,
- support construction,
- geographic overlays,
- observed data loading and caching.

It is not yet about:

- solver comparison,
- calibration,
- numerical-method trade-offs.

Current best public anchors:

- :doc:`../../getting_started/data-overview-walkthrough`
- :doc:`../../getting_started/choose-your-first-workflow`
- :doc:`../../architecture/spatial_support/index`

Simulation Workflow
^^^^^^^^^^^^^^^^^^^

This is the canonical forward-model workflow. It is where HydroModPy turns one
scientific configuration into one persisted run.

It is mainly about:

- physical configuration of ``[flow]``,
- support and discretization choices,
- forcing preparation,
- backend execution,
- result persistence and reading.

It should link out to scientific pages rather than restating them in full.
The main scientific companion pages are:

- :doc:`../../theory/foundations/groundwater-flow-problem-definition`
- :doc:`../../theory/hydrology/hydrological-forcing-chain`
- :doc:`../../theory/solvers/index`

Current best public anchors:

- :doc:`../../getting_started/simulation-walkthrough`
- :doc:`../../architecture/simulation/toml-to-solver-walkthrough`

Mesh Workflow
^^^^^^^^^^^^^

This workflow deserves its own explicit public narrative because it is not
just a preprocessing convenience. It is where discretization choices become
visible and testable.

It should explain:

- why a mesh is generated separately from the solver in some workflows,
- how structured and catchment-conformal meshes differ,
- which artifacts are exported for reuse,
- which mesh diagnostics matter before any physical interpretation.

Today, the code clearly exposes the workflow, but the public example path is
still thinner than for ``overview`` or ``simulation``.

Current best public anchors:

- :doc:`../../architecture/mesh/index`
- :doc:`../../theory/solvers/meshes-and-numerical-methods`

Calibration Workflow
^^^^^^^^^^^^^^^^^^^^

This workflow sits at the boundary between forward modelling and inverse
problem solving.

It should explain:

- which observables can constrain the model,
- which objective functions or posterior logic are used,
- which parameters are estimated,
- which uncertainties remain outside the calibration layer.

Current best public anchors:

- :doc:`../../theory/calibration/index`
- :doc:`../../architecture/calibration/index`

Batch Workflow
^^^^^^^^^^^^^^

This workflow is important conceptually because HydroModPy was designed for
repeated deployment across many basins, not only for one-off local runs.

It should eventually document:

- campaign-scale execution,
- per-site reproducibility,
- aggregation of outputs across basins,
- what remains shared versus site-specific.

Current public documentation is still sparse. A dedicated user-facing example
page is still missing.

Comparison Workflow
^^^^^^^^^^^^^^^^^^^

This workflow is especially valuable for method assessment because it compares
several child simulations while keeping the physical case as constant as
possible.

It should be the main public place for:

- solver-to-solver comparison,
- structured-versus-irregular discretization comparison,
- controlled comparison of numerical options on the same case.

The main public entry point is now:

- :doc:`comparison-workflow`

The most useful companion sources remain:

- :doc:`reading-results-pages`
- ``docs/developers/simulation_comparison_workflow.md``
- ``examples/projects/09_comparison_workflow/README.md``

Next Public Pages Worth Adding
------------------------------

The highest-value additions after this workflow map would be:

1. one public ``mesh`` walkthrough that starts from a single catchment and
   ends with a reusable mesh bundle,
2. one public ``batch`` example page so the campaign-scale purpose of
   HydroModPy is visible outside the code and developer notes.
