MODFLOW-NWT Architecture
========================

Scope
-----

This page documents the software architecture of the ``modflownwt`` flow
backend as it is used from the launcher and simulation layers.

Architecture role
-----------------

``modflownwt`` is the legacy MODFLOW-family flow backend in HydroModPy:

- it is planned as one ``("flow", "modflownwt")`` run by the simulation layer,
- it is dispatched through ``solver.modflow_nwt.adapters.flow``,
- it reuses the shared MODFLOW-family execution lifecycle in
  ``solver.modflow_common.flow_adapter_helpers``,
- it stays colocated with the ``MT3DMS`` and ``MODPATH`` ecosystem that depends
  on the same flow outputs.

Code path
---------

The shortest code-reading path for one ``flow/modflownwt`` run is:

1. ``launchers/process_simulation/launcher.py``
2. ``hydromodpy/simulation/planning/planner.py``
3. ``hydromodpy/simulation/execution/runner.py``
4. ``hydromodpy/solver/modflow_nwt/adapters/flow.py``
5. ``hydromodpy/solver/modflow_common/flow_adapter_helpers.py``
6. ``hydromodpy/solver/modflow_nwt/modflow/nwt_solver.py``

Main packages and responsibilities
----------------------------------

- ``hydromodpy/solver/modflow_nwt/adapters/flow.py`` owns only the
  backend-specific bridge from one generic ``ProcessRun`` to one ``Modflow``
  instance.
- ``hydromodpy/solver/modflow_common/flow_adapter_helpers.py`` owns the shared
  MODFLOW-family execution lifecycle used by both ``modflownwt`` and
  ``modflow6``.
- ``hydromodpy/solver/modflow_common`` centralizes grid context, temporal
  discretization, routing helpers, runtime arrays, and raster export shared by
  both MODFLOW-family backends.
- ``hydromodpy/solver/modflow_nwt/modflow/nwt_config.py`` validates the
  ``[modflownwt.*]`` configuration tree.
- ``hydromodpy/solver/modflow_nwt/modflow/flow_to_modflow_adapter.py``
  translates HydroModPy runtime state into package-ready MODFLOW inputs.
- ``hydromodpy/solver/modflow_nwt/modflow/nwt_solver.py`` owns concrete FloPy
  model creation, execution, and output shaping.
- ``hydromodpy/solver/modflow_nwt/modpath`` and
  ``hydromodpy/solver/modflow_nwt/mt3dms`` stay next to the flow backend
  because they depend on the same legacy file contracts.

Mesh contract
-------------

``modflownwt`` currently stays on the structured ``sgrid`` path only.

``process_simulation`` explicitly rejects runtime Gmsh meshes with this
backend, so ``[mesh_catchment]`` and ``[mesh_input]`` must be paired with
``modflow6`` or ``boussinesq`` instead.

See also
--------

- :doc:`../mesh/structured-grid-build-sequence-diagram`
- :doc:`../mesh/mesh-catchment-in-process-simulation-activity-diagram`
- :doc:`modflow6-architecture-notes`
