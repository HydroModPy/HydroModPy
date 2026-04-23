MODFLOW 6 Architecture
======================

Scope
-----

This page documents the software architecture of the ``modflow6`` flow backend
as it is used from the launcher and simulation layers.

Architecture role
-----------------

``modflow6`` is the modern MODFLOW-family backend in HydroModPy:

- it is planned as one ``("flow", "modflow6")`` run by the simulation layer,
- it is dispatched through ``solver.modflow6.adapters.flow``,
- it reuses the shared MODFLOW-family execution lifecycle in
  ``solver.modflow_common.flow_adapter_helpers``,
- it builds the concrete numerical model in ``hydromodpy.solver.modflow6``.

Code path
---------

The shortest code-reading path for one ``flow/modflow6`` run is:

1. ``launchers/process_simulation/launcher.py``
2. ``hydromodpy/simulation/planning/planner.py``
3. ``hydromodpy/simulation/execution/runner.py``
4. ``hydromodpy/solver/modflow6/adapters/flow.py``
5. ``hydromodpy/solver/modflow_common/flow_adapter_helpers.py``
6. ``hydromodpy/solver/modflow6/modflow6.py``

Main packages and responsibilities
----------------------------------

- ``hydromodpy/solver/modflow6/adapters/flow.py`` owns only the
  backend-specific bridge from one generic ``ProcessRun`` to one ``Modflow6``
  instance.
- ``hydromodpy/solver/modflow_common/flow_adapter_helpers.py`` owns the shared
  flow lifecycle once a concrete MODFLOW-family solver object exists:
  preprocessing, compatibility pickle, processing, and postprocessing.
- ``hydromodpy/solver/modflow_common`` centralizes grid context, temporal
  discretization, routing helpers, runtime arrays, and raster export shared by
  both MODFLOW-family backends.
- ``hydromodpy/solver/modflow6/modflow6_config.py`` validates the
  ``[modflow6.*]`` configuration tree.
- ``hydromodpy/solver/modflow6/property_mapping.py`` resolves HydroModPy flow
  properties into MF6-ready arrays.
- ``hydromodpy/solver/modflow6/flow_to_modflow_adapter.py`` translates the
  normalized runtime payload into FloPy package inputs.
- ``hydromodpy/solver/modflow6/modflow6.py`` owns concrete FloPy model
  creation, execution, and output shaping.
- ``hydromodpy/solver/modflow6/postprocess.py`` and ``diagnostics.py`` read
  solver outputs back into HydroModPy products.

Mesh contract
-------------

``modflow6`` is the MODFLOW-family backend currently compatible with both:

- the structured ``sgrid`` path,
- runtime Gmsh meshes injected through ``[mesh_catchment]`` or ``[mesh_input]``
  in ``process_simulation``.

That makes it the bridge between the shared MODFLOW postprocess/tooling stack
and the newer runtime catchment-mesh workflow.

See also
--------

- :doc:`../mesh/mesh-catchment-in-process-simulation-activity-diagram`
- :doc:`../mesh/structured-grid-build-sequence-diagram`
- :doc:`boussinesq-uml-diagrams`
