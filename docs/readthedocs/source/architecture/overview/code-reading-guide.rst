Code Reading Guide
==================

Scope
-----

This page complements the UML diagrams with a developer-facing map of the
actual code entry points.

Use it when you want:

- the first file to open for one workflow family,
- the package README that already explains a subsystem in prose,
- a non-scientific reading path through launcher, simulation, process, and
  solver code.

Code-oriented docs already present in the repository
----------------------------------------------------

Several prose documents already exist in the repository, but they were not
previously surfaced from the published architecture pages:

- ``launchers/README.md`` for launcher families and CLI entry points,
- ``hydromodpy/simulation/README.md`` for planner / runner / adapter roles,
- ``hydromodpy/analysis/calibration/README.md`` for the calibration package map,
- ``hydromodpy/solver/boussinesq/README.md`` for the in-house solver package,
- ``docs/developers/*.md`` for focused engineering notes and design documents.

Recommended reading paths
-------------------------

Launcher-driven simulation
^^^^^^^^^^^^^^^^^^^^^^^^^^

When the question is "how does one TOML turn into solver runs?":

1. ``launchers/process_simulation/launcher.py``
2. ``hydromodpy/simulation/planning/planner.py``
3. ``hydromodpy/simulation/execution/runner.py``
4. ``hydromodpy/simulation/adapters/registry.py``
5. one adapter under ``hydromodpy/simulation/adapters/flow`` or ``transport``
6. the concrete solver package under ``hydromodpy/solver``

Catchment meshing
^^^^^^^^^^^^^^^^^

When the question is "how is a runtime mesh generated and injected?":

1. ``launchers/mesh_catchment/runtime.py``
2. ``launchers/mesh_catchment/batch.py``
3. ``hydromodpy/solver/utils/mesh/gmsh_grid/``
4. the pages under :doc:`../mesh/index`

Calibration
^^^^^^^^^^^

When the question is "how does HydroModPy calibrate a simulation workflow?":

1. ``launchers/model_calibration/launcher.py``
2. ``launchers/model_calibration/runtime.py``
3. ``hydromodpy/simulation/model_calibration_support.py``
4. ``hydromodpy/analysis/calibration/core/``
5. one runnable case under ``hydromodpy/analysis/calibration/cases/``

Flow solvers
^^^^^^^^^^^^

When the question is "where does backend-specific logic start?":

1. ``hydromodpy/simulation/adapters/flow/modflow_common.py`` for the shared
   lifecycle,
2. ``hydromodpy/simulation/adapters/flow/modflow6.py`` or
   ``modflownwt.py`` for backend selection,
3. ``hydromodpy/solver/modflow_common/`` for shared MODFLOW support code,
4. ``hydromodpy/solver/modflow6/`` or ``hydromodpy/solver/modflow_nwt/`` for
   concrete backend implementation,
5. ``hydromodpy/solver/boussinesq/`` for the in-house backend.

What would still improve the published docs
-------------------------------------------

The architecture section is now much better at guiding code reading, but a few
useful additions still stand out:

- one equivalent package-map page for ``hydromodpy.spatial.field`` and one for
  ``hydromodpy.spatial.domain``,
- one explicit data-loading page organized by manager family rather than only
  by activation and transfer flow,
- one tighter bridge from architecture pages to the generated API section so
  developers can jump from conceptual maps to symbol-level docs more directly.
