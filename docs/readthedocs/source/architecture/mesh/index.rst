Mesh Architecture
=================

This section documents HydroModPy's solver-side meshing and structured-grid
contracts implemented around ``hydromodpy.solver.utils.mesh``.

It focuses on:

- the static object model around ``StructuredGrid``,
- configuration and construction of FloPy ``StructuredGrid`` objects,
- adapter layers that bridge solver grids to field meshes,
- discretization workflows that turn field parameters into solver-ready arrays.

For higher-level runtime handoffs from process objects to solver wrappers, see
:doc:`../process/process-runtime-to-solver-sequence-diagram` and
:doc:`../simulation/launcher-simulation-class-diagram`.

.. toctree::
   :maxdepth: 2

   catchment-conformal-meshing-diagrams
   structured-grid-class-diagram
   structured-grid-build-sequence-diagram
   sgrid-fieldparam-discretization-diagrams
