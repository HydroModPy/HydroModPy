Mesh Architecture
=================

.. raw:: html

   <p class="lead">
   How HydroModPy turns a watershed support into a solver-ready mesh:
   the catchment-conformal Gmsh pipeline, the structured-grid path
   used by MODFLOW-family solvers, and the cross-mesh pivot format
   consumed by plotting and I/O.
   </p>

For higher-level runtime handoffs from process objects to solver
adapters, see :doc:`../process/process-architecture` and
:doc:`../simulation/simulation-orchestration-class-diagram`. For the
scientific side of mesh choice, see :doc:`../../theory/mesh/index`.

Pages
-----

.. grid:: 1 2 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: Catchment mesh architecture
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: catchment-mesh-architecture
      :link-type: doc

      The dedicated ``mesh_catchment`` workflow, batch loop,
      simulation embedding, output layout, and the conformal Gmsh
      meshing core.

   .. grid-item-card:: Structured grid architecture
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: structured-grid-architecture
      :link-type: doc

      The FloPy ``StructuredGrid`` path used by MODFLOW-family
      solvers, the build sequence, and the SGrid / FieldParam
      discretization bridge.

   .. grid-item-card:: Conformal Gmsh meshing
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: gmsh-meshing
      :link-type: doc

      The low-level Gmsh integration: constraint geometry, sizing
      callbacks, mesh-quality checks, and the boundary recovery
      that keeps geology and rivers honoured.

   .. grid-item-card:: Mesh pivot format
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mesh-pivot
      :link-type: doc

      The cross-mesh pivot representation consumed by plotting,
      I/O, and downstream postprocessing. Bridges structured and
      irregular supports.

.. toctree::
   :hidden:
   :maxdepth: 1

   catchment-mesh-architecture
   structured-grid-architecture
   gmsh-meshing
   mesh-pivot
