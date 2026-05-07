Code Reading Guide
==================

Scope
-----

This page complements the UML diagrams with a developer-facing map of
the actual code entry points.

Use it when you want:

- the first file to open for one workflow family,
- the package README that already explains a subsystem in prose,
- a non-scientific reading path through CLI, project, simulation,
  process, and solver code.

Code-oriented docs already present in the repository
----------------------------------------------------

Several prose documents already exist in the repository, but they were
not previously surfaced from the published architecture pages:

- ``hydromodpy/cli/README.md`` for the CLI dispatcher and the
  registered subcommands,
- ``hydromodpy/simulation/README.md`` for planner / runner / adapter
  roles,
- ``hydromodpy/calibration/README.md`` for the calibration package map,
- ``hydromodpy/solver/boussinesq/README.md`` for the in-house solver
  package,
- ``docs/developers/*.md`` for focused engineering notes and design
  documents.

Recommended reading paths
-------------------------

CLI-driven simulation
^^^^^^^^^^^^^^^^^^^^^

When the question is "how does one TOML turn into solver runs?":

1. ``hydromodpy/cli/commands/run.py`` and ``cli/workflows.py``
2. ``hydromodpy/project.py`` (``Project`` facade)
3. ``hydromodpy/simulation/planning/planner.py``
4. ``hydromodpy/simulation/execution/runner.py``
5. ``hydromodpy/solver/base/registry.py``
6. one adapter under ``hydromodpy/solver/<backend>/adapters/``
7. the concrete solver package under ``hydromodpy/solver/``

Catchment meshing
^^^^^^^^^^^^^^^^^

When the question is "how is a runtime mesh generated and injected?":

1. ``hydromodpy/spatial/mesh/runtime.py``
2. ``hydromodpy/spatial/mesh/hydro_mesh.py``
3. ``hydromodpy/spatial/mesh/batch.py`` for multi-outlet runs
4. ``hydromodpy/spatial/mesh/gmsh_grid/``
5. the pages under :doc:`../mesh/index`

Calibration
^^^^^^^^^^^

When the question is "how does HydroModPy calibrate a simulation
workflow?":

1. ``hydromodpy/cli/commands/run.py`` ([workflow].mode = "calibration"
   dispatch)
2. ``hydromodpy/calibration/runner.py`` (calibration entry point)
3. ``hydromodpy/calibration/engine.py`` and the ``CalibrationEngine``
   protocol
4. ``hydromodpy/simulation/execution/trial.py`` (prepare-once,
   evaluate-many primitive)
5. one case under ``hydromodpy/calibration/cases/`` if available

Flow solvers
^^^^^^^^^^^^

When the question is "where does backend-specific logic start?":

1. ``hydromodpy/solver/modflow_common/flow_adapter_helpers.py`` for the
   shared lifecycle,
2. ``hydromodpy/solver/modflow6/adapters/flow.py`` or ``modflownwt.py``
   for backend selection,
3. ``hydromodpy/solver/modflow_common/`` for shared MODFLOW support
   code,
4. ``hydromodpy/solver/modflow6/`` or ``hydromodpy/solver/modflow_nwt/``
   for the concrete backend implementation,
5. ``hydromodpy/solver/boussinesq/`` for the in-house backend.

What would still improve the published docs
-------------------------------------------

The architecture section is now much better at guiding code reading,
but a few useful additions still stand out:

- one equivalent package-map page for ``hydromodpy.spatial.field`` and
  one for ``hydromodpy.spatial.domain``,
- one explicit data-loading page organized by manager family rather
  than only by activation and transfer flow,
- one tighter bridge from architecture pages to the generated API
  section so developers can jump from conceptual maps to symbol-level
  docs more directly.
