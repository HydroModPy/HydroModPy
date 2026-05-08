Mesh and Discretization
=======================

.. note::

   Use this page when the question is:
   "How do I make a sound discretization choice for this catchment, and how do
   I inspect a mesh before trusting a solver run?"

The mesh is not an implementation detail. It controls numerical sensitivity,
solver compatibility (structured ``sgrid`` vs unstructured DISV), local
refinement around stream networks and zone interfaces, and the cell budget
that calibration loops will pay for. HydroModPy lets the mesh be built either
inside the standard ``simulation`` workflow or in isolation through the
dedicated ``mesh`` workflow, so discretization choices can be iterated without
running any solver.

Decision matrix
---------------

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Question
     - Best entry point
   * - Which mesh styles does HydroModPy support?
     - :doc:`solver-choice` and :doc:`solver-process-map`
   * - When should I prefer structured over unstructured?
     - :doc:`../theory/solvers/mesh-quality-and-acceptance-criteria`
   * - Which mesh diagnostics matter before any physics?
     - :doc:`concepts/reading-results-pages`
   * - Where are stable mesh examples I can browse?
     - :doc:`../capability_gallery/mesh`
   * - How does a catchment mesh become a solver input?
     - :doc:`../architecture/mesh/mesh-catchment-in-process-simulation-activity-diagram`
   * - How are structured grids represented internally?
     - :doc:`../architecture/mesh/structured-grid-class-diagram`
   * - How is the Gmsh-backed conformal mesh built?
     - :doc:`../architecture/gmsh_meshing`

Minimal mesh-only workflow
--------------------------

The ``mesh`` workflow builds and exports a catchment mesh without invoking
any flow solver. Useful when iterating on refinement policy, geology
constraints, or river-network conformity.

.. code-block:: toml

   [workflow]
   mode = "mesh"

   [workspace]
   project_root = "./my_basin"

   [geographic]
   catch_def = "from_polyg_shp"
   dem_init_path = "data/regional_dem.tif"
   polyg_shp_path = "data/basin.shp"
   buff_area = "500 m"

   [mesh_catchment]
   constraints_mode = "geology_rivers"

   [mesh_catchment.geology]
   path = "data/geology.shp"

.. code-block:: bash

   hmp run mesh_only.toml

Read more
---------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Theory
      :link: ../theory/solvers/meshes-and-numerical-methods
      :link-type: doc

      Discretization strategies, structured vs irregular meshes, and the
      numerical-method context behind each choice.

   .. grid-item-card:: Gallery
      :link: ../capability_gallery/mesh
      :link-type: doc

      Static mesh and geology illustrations produced from versioned bundle
      inputs.

   .. grid-item-card:: Architecture
      :link: ../architecture/mesh/index
      :link-type: doc

      Where mesh construction, export, and solver handoff live in the
      package.

   .. grid-item-card:: Solver coupling
      :link: solver-choice
      :link-type: doc

      Which backend supports which mesh style, and the consequences for
      XT3D and DISV.

See also
--------

- :doc:`../capability_gallery/geographic` for pre-solver watershed context.
- :doc:`../capability_gallery/simulation` for solver runs built on mesh
  artifacts.
- :doc:`comparison` for shared-case studies that vary mesh resolution.
