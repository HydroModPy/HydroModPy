MODFLOW 6 Version
=================

This section contains the MODFLOW 6-specific material for ``flow/modflow6``.

Use it when the selected flow backend is MODFLOW 6 GWF, including structured
support and runtime DISV-style support where enabled by the workflow.

What Belongs Here
-----------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Topic
     - MODFLOW 6-specific emphasis
   * - Backend route
     - ``flow/modflow6`` and the MODFLOW 6 GWF package stack.
   * - Mesh support
     - Structured grids and runtime DISV-style irregular meshes where
       supported.
   * - Numerical method choices
     - XT3D policy, especially on irregular DISV-style supports.
   * - Surface and drainage diagnostics
     - Active drainage outputs, routed fluxes, and simulated active-network
       interpretation.
   * - Downstream transport
     - ``transport/modflow6gwt``.

.. toctree::
   :maxdepth: 2

   MODFLOW 6 flow page <../modflow6>
   XT3D on irregular DISV meshes <../../../xt3d-on-irregular-disv-meshes>
   MODFLOW 6 versus MODFLOW-NWT comparison <../../../modflow6-vs-modflownwt-scientific-comparison>
   Simulated active network <../../../../hydrology/simulated-active-network>

Related Common And Comparison Pages
-----------------------------------

- :doc:`../common/index`
- :doc:`../comparison-and-method-choice`
- :doc:`../transport-coupling`
- :doc:`../worked-cases`
