MODFLOW-Linked Transport Adapters
=================================

This page groups the architecture of current ``transport`` process adapters.

Current Adapter Pairs
---------------------

.. list-table::
   :header-rows: 1
   :widths: 24 30 46

   * - Pair
     - Adapter
     - Dependency
   * - ``transport/modpath``
     - ``ModpathTransportAdapter``
     - Requires an earlier ``flow/modflownwt`` run.
   * - ``transport/mt3dms``
     - ``Mt3dmsTransportAdapter``
     - Requires an earlier ``flow/modflownwt`` run.
   * - ``transport/modflow6gwt``
     - ``Modflow6GwtTransportAdapter``
     - Requires an earlier ``flow/modflow6`` run.

Code Reading Map
----------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Path
     - Role
   * - ``hydromodpy.solver.modflow_nwt.adapters.transport_modpath``
     - Binds ``transport/modpath`` to a previous MODFLOW-NWT flow model.
   * - ``hydromodpy.solver.modflow_nwt.adapters.transport_mt3dms``
     - Binds ``transport/mt3dms`` to a previous MODFLOW-NWT flow model.
   * - ``hydromodpy.solver.modflow6.adapters.transport``
     - Binds ``transport/modflow6gwt`` to a previous MODFLOW 6 flow model.
   * - ``hydromodpy.simulation.adapters.transport_helpers``
     - Shared dependency resolution helpers for transport adapters.
   * - ``hydromodpy.solver.modflow_nwt.extractors.modpath``
     - Ingests MODPATH pathline and endpoint outputs.
   * - ``hydromodpy.solver.modflow_nwt.extractors.mt3dms``
     - Ingests MT3DMS concentration outputs.
   * - ``hydromodpy.solver.modflow6.extractors.transport``
     - Ingests MODFLOW 6 GWT concentration outputs.

Planner Contract
----------------

The transport adapters declare ``requires`` at class level. The planner checks
that a compatible flow run appears earlier in the plan. It does not reorder
the user declaration.

Internal Architecture Pages
---------------------------

.. toctree::
   :maxdepth: 1

   shared-lifecycle
   modpath-stack
   mt3dms-stack
   modflow6gwt-stack

Related Scientific Pages
------------------------

- :doc:`../../../scientific/solvers/transport/particle-tracking`
- :doc:`../../../scientific/solvers/transport/concentration-transport`
- :doc:`../../../scientific/solvers/transport/common-concepts`
- :doc:`../process-solver-registry`
