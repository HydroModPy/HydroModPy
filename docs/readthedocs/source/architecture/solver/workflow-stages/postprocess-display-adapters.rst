Postprocess And Display Adapters
================================

This page documents the architectural role of non-numerical process adapters
registered under ``postprocess`` and ``display``.

Current Stub Pairs
------------------

.. list-table::
   :header-rows: 1
   :widths: 24 32 44

   * - Pair
     - Adapter class
     - Intended role
   * - ``postprocess/timeseries``
     - ``TimeseriesPostprocessAdapter``
     - Wrap time-series post-processing.
   * - ``postprocess/netcdf``
     - ``NetcdfPostprocessAdapter``
     - Wrap NetCDF export post-processing.
   * - ``display/flow``
     - ``FlowDisplayAdapter``
     - Wrap flow display generation.
   * - ``display/transport``
     - ``TransportDisplayAdapter``
     - Wrap transport display generation.

Code Reading Map
----------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Path
     - Role
   * - ``hydromodpy.simulation.adapters.postprocess.stub``
     - Stub classes for planned postprocess stages.
   * - ``hydromodpy.simulation.adapters.display.stub``
     - Stub classes for planned display stages.
   * - ``hydromodpy.solver.base.registry``
     - Declares these pairs so the taxonomy remains open beyond numerical
       flow and transport solvers.

Implementation Rule
-------------------

When these adapters become concrete, they should keep the same architecture as
numerical solvers:

1. declare ``process_type`` and ``solver_name``,
2. declare upstream ``requires`` when needed,
3. receive a ``RunContext``,
4. return a ``RunExecutionResult`` or equivalent catalog output,
5. document generated artifacts and result paths.

Related Scientific Pages
------------------------

- :doc:`../../../scientific/solvers/workflow-stages/postprocess-adapters`
- :doc:`../../../scientific/solvers/workflow-stages/display-adapters`
- :doc:`../process-solver-registry`
