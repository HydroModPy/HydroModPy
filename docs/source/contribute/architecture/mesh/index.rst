Mesh architecture
=================

.. rst-class:: lead

How HydroModPy turns a project into the cells a solver reads. One request goes to one of three
mesh engines, and every consumer reads the resulting cell mesh the same way.

For the handoff from process objects to solver adapters, see
:doc:`../process/process-architecture` and :doc:`../simulation/toml-to-solver-walkthrough`. For
the scientific choice of a mesh, see :doc:`/theory/mesh`.

Pages
-----

.. grid:: 1 2 2 2
   :gutter: 2 2 3 3

   .. grid-item-card:: The mesh pivot and the cell mesh
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mesh-pivot
      :link-type: doc

      ``HydroMesh``, the exchange format for plotting and I/O, and ``PlanarCellMesh``, the mesh
      every solver reads, with its centre rule, derived geometry and line families.

   .. grid-item-card:: Mesh engines
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: mesh-engines
      :link-type: doc

      The port, the registry, the request and the planner, the ``regular``, ``triangle`` and
      ``voronoi`` engines, and how to add one.

   .. grid-item-card:: Triangle engine
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: triangle-engine
      :link-type: doc

      Gmsh constrained Delaunay triangles with the lines embedded, or a ``.msh`` file, and the
      cache that makes a run repeatable.

   .. grid-item-card:: Voronoi engine
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: voronoi-engine
      :link-type: doc

      Generated generators, mirror pairs on the face lines, Lloyd relaxation, the blocking gates
      and the limits.

.. toctree::
   :hidden:
   :maxdepth: 1

   mesh-pivot
   mesh-engines
   triangle-engine
   voronoi-engine
