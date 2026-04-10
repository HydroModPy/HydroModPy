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

Diagram source
--------------

.. uml:: diagrams/mesh_catchment_in_process_simulation_activity.wsd

.. literalinclude:: diagrams/mesh_catchment_in_process_simulation_activity.wsd
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
