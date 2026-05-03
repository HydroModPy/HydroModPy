Shared MODFLOW Lifecycle
========================

This page describes the shared architecture used by MODFLOW-family flow
backends before execution reaches backend-specific FloPy calls.

Shared Code Areas
-----------------

.. list-table::
   :header-rows: 1
   :widths: 36 64

   * - Path
     - Role
   * - ``hydromodpy.solver.base.registry``
     - Maps ``("flow", "modflow6")`` and ``("flow", "modflownwt")`` to their
       adapter classes.
   * - ``hydromodpy.simulation.planning``
     - Expands ``[[simulation.process]]`` into concrete ``ProcessRun`` objects.
   * - ``hydromodpy.simulation.execution.runner``
     - Instantiates the registered adapter and stores produced models by run
       id.
   * - ``hydromodpy.solver.modflow_common``
     - Centralizes shared grid, forcing, options, runtime-array, and temporal
       helper code for MODFLOW-family paths.
   * - ``hydromodpy.solver.modflow_common.flow_adapter_helpers``
     - Owns shared lifecycle helpers once the adapter has selected a concrete
       MODFLOW-family model.

Execution Shape
---------------

.. code-block:: text

   [[simulation.process]]
       type = "flow"
       solvers = ["modflow6" or "modflownwt"]
            |
            v
   SimulationPlanner -> ProcessRun("flow_main::<solver>")
            |
            v
   SimulationRunner -> registry.get_solver_adapter("flow", "<solver>")
            |
            v
   Flow adapter -> backend-specific model assembly and execution

Related Pages
-------------

- :doc:`modflow6-stack`
- :doc:`modflownwt-stack`
- :doc:`../../process-solver-registry`
