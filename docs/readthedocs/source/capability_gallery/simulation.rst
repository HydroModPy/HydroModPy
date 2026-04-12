.. This file is compatible with ``python -m tools.doc_gallery`` outputs.

Simulation Workflows
====================

.. note::
   This page groups selected, versioned outputs from complete launcher runs. The
   full solver workspaces are not committed; only stable figures and summaries
   are kept for documentation.

These cases show complete HydroModPy workflows, from preprocessing through
solver execution and post-processing figures.

.. grid:: 1 1 2 2
   :gutter: 2 2 3 3

   .. grid-item-card::
      :class-card: sd-shadow-sm sd-rounded-3 sd-p-4
      :link: cases/modflow6_gmsh_mesh_catchment
      :link-type: doc

      **MODFLOW 6 on a Gmsh catchment mesh**
      ^^^
      Embedded Gmsh meshing, MODFLOW 6 flow, GWT transport, and solver-agnostic
      synthesis figures.

.. toctree::
   :hidden:
   :maxdepth: 1

   cases/modflow6_gmsh_mesh_catchment
