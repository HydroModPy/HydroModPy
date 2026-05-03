Transport Solvers
=================

This section groups solver documentation for the ``transport`` process.

Transport is downstream from flow: the current transport solvers need a
previous compatible ``flow`` run. HydroModPy therefore documents transport in
the same classical structure used for ``flow``.

The hierarchy is:

1. process: ``transport``,
2. equations and unknowns: particle paths or concentration fields;
3. solver route: MODFLOW-NWT transport or MODFLOW 6 transport;
4. solver implementation: MODPATH, MT3DMS, or MODFLOW 6 GWT.

This mirrors the ``flow`` documentation: first understand the governing
problem, then open the relevant solver route, then read backend-specific pages.

Four-Part Transport Structure
-----------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Sub-category
     - Main page
     - Purpose
   * - Common transport part
     - :doc:`common-concepts`
     - Shared dependency contract, process ordering, parameter layout, and
       interpretation rules for all transport solvers.
   * - Equations and unknowns
     - :doc:`equations-and-unknowns`
     - Particle trajectory equation, concentration transport equation, and
       mapping from equation families to current solvers.
   * - MODFLOW-NWT transport route
     - :doc:`modflow-nwt-transport`
     - ``flow/modflownwt`` followed by ``transport/modpath`` and/or
       ``transport/mt3dms``.
   * - MODFLOW 6 transport route
     - :doc:`modflow6-transport`
     - ``flow/modflow6`` followed by ``transport/modflow6gwt``.

Current Transport Solver Routes
-------------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 26 28 22

   * - Route
     - Required upstream flow
     - Transport solvers
     - Detailed pages
   * - MODFLOW-NWT route
     - ``flow/modflownwt``.
     - ``transport/modpath`` for particle tracking;
       ``transport/mt3dms`` for concentration transport.
     - :doc:`modflow-nwt-transport`
   * - MODFLOW 6 route
     - ``flow/modflow6``.
     - ``transport/modflow6gwt`` for concentration transport.
     - :doc:`modflow6-transport`

.. toctree::
   :caption: Common formulation
   :maxdepth: 2

   common-concepts
   equations-and-unknowns

.. toctree::
   :caption: Solver routes
   :maxdepth: 2

   modflow-nwt-transport
   modflow6-transport

.. toctree::
   :caption: Transport mechanisms
   :maxdepth: 2

   particle-tracking
   concentration-transport

.. toctree::
   :caption: Backend internals
   :maxdepth: 2

   particle-tracking/index
   concentration-transport/index

Related Pages
-------------

- :doc:`../solver-capability-matrix`
- :doc:`../../../user_guide/solver-process-map`
- :doc:`../../../architecture/solver/transport/index`
