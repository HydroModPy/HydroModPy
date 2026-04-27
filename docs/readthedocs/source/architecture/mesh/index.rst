Mesh Architecture
=================

This section documents HydroModPy's meshing stack, from catchment-mesh
generation to solver-side structured-grid contracts implemented around
``hydromodpy.spatial.mesh``.

It focuses on:

- the dedicated ``mesh_catchment`` workflow and its runtime integration,
- the package and batch views around catchment mesh generation,
- output and handoff rules for runtime Gmsh meshes,
- the static object model around ``StructuredGrid``,
- configuration and construction of FloPy ``StructuredGrid`` objects,
- adapter layers that bridge solver grids to field meshes,
- discretization workflows that turn field parameters into solver-ready arrays.

For higher-level runtime handoffs from process objects to solver
adapters, see
:doc:`../process/process-runtime-to-solver-sequence-diagram` and
:doc:`../simulation/simulation-orchestration-class-diagram`.

.. toctree::
   :maxdepth: 2

   catchment-conformal-meshing-diagrams
   mesh-catchment-package-component-diagram
   mesh-catchment-batch-activity-diagram
   mesh-catchment-in-process-simulation-activity-diagram
   mesh-catchment-output-layout-activity-diagram
   structured-grid-class-diagram
   structured-grid-build-sequence-diagram
   sgrid-fieldparam-discretization-diagrams
