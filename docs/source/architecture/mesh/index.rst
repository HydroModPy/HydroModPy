Mesh Architecture
=================

This section documents HydroModPy's meshing stack:

- :doc:`catchment-mesh-architecture` covers the dedicated
  ``mesh_catchment`` workflow, batch loop, simulation embedding,
  output layout, and the conformal Gmsh meshing core.
- :doc:`structured-grid-architecture` covers the FloPy
  ``StructuredGrid`` path used by MODFLOW-family solvers, the build
  sequence, and the SGrid / FieldParam discretization bridge.

For higher-level runtime handoffs from process objects to solver
adapters, see :doc:`../process/process-architecture` and
:doc:`../simulation/simulation-orchestration-class-diagram`.

For the cross-mesh pivot format consumed by plotting and I/O, see
:doc:`../mesh_pivot`.

.. toctree::
   :maxdepth: 2

   catchment-mesh-architecture
   structured-grid-architecture
