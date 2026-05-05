Mesh Catchment In Process Simulation
====================================

Scope
-----

This diagram documents how the simulation pipeline accepts, rejects, or
reuses runtime meshes.

It focuses on:

- the mutual exclusion between ``[mesh_catchment]`` and ``[mesh_input]``,
- the early rejection of ``[mesh_catchment_batch]`` inside the
  simulation workflow,
- the solver-compatibility guard that rejects runtime Gmsh meshes with
  ``modflownwt``,
- the handoff of loaded or generated mesh artifacts into the
  ``Project`` runtime state before solver execution.

Code map
--------

- ``hydromodpy/project.py``:
  embedding point for runtime mesh resolution. ``Project.build_mesh()``
  is the public verb.
- ``hydromodpy/spatial/mesh/runtime.py``:
  mono-catchment mesh generation when ``[mesh_catchment]`` is active.
- ``hydromodpy/simulation/execution/runner.py``:
  downstream orchestration once mesh resolution is complete.
- ``hydromodpy/solver/modflow6/adapters/flow.py`` and ``modflownwt.py``:
  backend boundary where mesh compatibility matters.

Recommended reading path
------------------------

1. ``hydromodpy/project.py``
2. ``hydromodpy/spatial/mesh/runtime.py``
3. ``hydromodpy/simulation/execution/runner.py``
4. one backend adapter such as
   ``hydromodpy/solver/modflow6/adapters/flow.py``

Diagram source
--------------

.. uml:: diagrams/mesh_catchment_in_process_simulation_activity.wsd

.. literalinclude:: diagrams/mesh_catchment_in_process_simulation_activity.wsd
   :language: text
   :caption: PlantUML (.wsd) source - mesh-catchment in process_simulation

Notes
-----

- The simulation workflow can embed one mono-catchment mesh phase or
  reuse one precomputed mesh, but not both in the same run.
- Runtime Gmsh meshes are currently intended for ``boussinesq`` and
  ``modflow6``. ``modflownwt`` stays on the structured ``sgrid`` path.
- Once the mesh phase is resolved, solver orchestration continues
  through the standard simulation runner.

Related diagrams
----------------

- :doc:`mesh-catchment-output-layout-activity-diagram`
- :doc:`../simulation/simulation-orchestration-class-diagram`
- :doc:`../solver/modflow6-architecture-notes`
