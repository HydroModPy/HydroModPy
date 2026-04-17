Mesh Catchment In Process Simulation
====================================

Scope
-----

This diagram documents how ``process_simulation`` accepts, rejects, or reuses
runtime meshes.

It focuses on:

- the mutual exclusion between ``[mesh_catchment]`` and ``[mesh_input]``,
- the early rejection of ``[mesh_catchment_batch]`` inside
  ``process_simulation``,
- the solver-compatibility guard that rejects runtime Gmsh meshes with
  ``modflownwt``,
- the handoff of loaded or generated mesh artifacts into launcher runtime
  state before solver execution.

Code map
--------

- ``launchers/process_simulation/launcher.py``:
  embedding point for runtime mesh resolution.
- ``launchers/mesh_catchment/runtime.py``:
  mono-catchment mesh generation when ``[mesh_catchment]`` is active.
- ``hydromodpy/simulation/execution/runner.py``:
  downstream orchestration once mesh resolution is complete.
- ``hydromodpy/simulation/adapters/flow/modflow6.py`` and ``modflownwt.py``:
  backend boundary where mesh compatibility matters.

Recommended reading path
------------------------

1. ``launchers/process_simulation/launcher.py``
2. ``launchers/mesh_catchment/runtime.py``
3. ``hydromodpy/simulation/execution/runner.py``
4. one backend adapter such as ``hydromodpy/simulation/adapters/flow/modflow6.py``

Diagram source
--------------

.. uml:: ../launchers/diagrams/mesh_catchment_in_process_simulation_activity.wsd

.. literalinclude:: ../launchers/diagrams/mesh_catchment_in_process_simulation_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - mesh-catchment in process_simulation

Notes
-----

- ``process_simulation`` can embed one mono-catchment mesh phase or reuse one
  precomputed mesh, but not both in the same run.
- Runtime Gmsh meshes are currently intended for ``boussinesq`` and
  ``modflow6``. ``modflownwt`` stays on the structured ``sgrid`` path.
- Once the mesh phase is resolved, solver orchestration continues through the
  standard simulation runner.
- For the higher-level launcher flow around this embedded mesh phase, see
  :doc:`../launchers/launcher-simulation-activity-diagram`.

Related diagrams
----------------

- :doc:`mesh-catchment-output-layout-activity-diagram`
- :doc:`../launchers/launcher-simulation-activity-diagram`
- :doc:`../solver/modflow6-architecture-notes`
