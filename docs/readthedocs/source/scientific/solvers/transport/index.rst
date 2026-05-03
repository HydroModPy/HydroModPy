Transport Solvers
=================

This section groups solver documentation for the ``transport`` process.

Transport is downstream from flow: the current transport solvers need a
previous compatible ``flow`` run. HydroModPy therefore documents transport by
transport type first, then by solver implementation.

The hierarchy is:

1. process: ``transport``,
2. solver type: particle tracking or concentration transport.

Current Transport Solver Types
------------------------------

.. list-table::
   :header-rows: 1
   :widths: 26 28 46

   * - Solver type
     - Solver names
     - Required upstream flow
   * - Particle tracking
     - ``modpath``
     - ``flow/modflownwt``.
   * - Concentration transport
     - ``mt3dms``, ``modflow6gwt``
     - ``mt3dms`` requires ``flow/modflownwt``;
       ``modflow6gwt`` requires ``flow/modflow6``.

.. toctree::
   :maxdepth: 2

   particle-tracking
   concentration-transport

Related Pages
-------------

- :doc:`../solver-capability-matrix`
- :doc:`../../../user_guide/solver-process-map`
- :doc:`../../../architecture/solver/transport/index`
