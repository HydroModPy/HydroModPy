MODFLOW Transport Coupling Architecture
=======================================

This page shows how MODFLOW-family flow runs become upstream providers for
transport adapters.

Current Dependency Pairs
------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 28 44

   * - Upstream flow pair
     - Downstream transport pair
     - Adapter path
   * - ``flow/modflownwt``
     - ``transport/modpath``
     - ``hydromodpy.solver.modflow_nwt.adapters.transport_modpath``.
   * - ``flow/modflownwt``
     - ``transport/mt3dms``
     - ``hydromodpy.solver.modflow_nwt.adapters.transport_mt3dms``.
   * - ``flow/modflow6``
     - ``transport/modflow6gwt``
     - ``hydromodpy.solver.modflow6.adapters.transport``.

Planner Contract
----------------

Transport adapters declare an explicit ``requires`` tuple. The planner binds
the transport run to the most recent compatible flow run that appeared earlier
in the plan.

.. code-block:: python

   class Modflow6GwtTransportAdapter:
       process_type = "transport"
       solver_name = "modflow6gwt"
       requires = (("flow", "modflow6"),)

If the required flow pair has not appeared earlier, planning fails. The
planner does not reorder user declarations.

Related Pages
-------------

- :doc:`../../transport/modflow-transport-adapters`
- :doc:`../../../../scientific/solvers/flow/modflow/transport-coupling`
- :doc:`../../process-solver-registry`
