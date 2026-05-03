Transport Solvers
=================

This section groups solver documentation for the ``transport`` process.

Transport is downstream from flow: the current transport solvers need a
previous compatible ``flow`` run. HydroModPy therefore documents transport by
transport type first, then by solver implementation.

The hierarchy is:

1. process: ``transport``,
2. solver type or family: common transport contract, particle tracking, or
   concentration transport;
3. solver implementation: MODPATH, MT3DMS, or MODFLOW 6 GWT.

This mirrors the ``flow`` documentation: first understand the process, then
open the relevant family, then read the backend-specific page.

Three-Part Transport Structure
------------------------------

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
   * - Particle tracking family
     - :doc:`particle-tracking`
     - Advective path and travel-time analysis, currently through MODPATH.
   * - Concentration transport family
     - :doc:`concentration-transport`
     - Species concentration, dispersivity, diffusion, input concentration,
       and decay through MT3DMS or MODFLOW 6 GWT.

Current Transport Solver Families
---------------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 28 28 20

   * - Solver type
     - Solver names
     - Required upstream flow
     - Detailed internals
   * - Particle tracking
     - ``modpath``
     - ``flow/modflownwt``.
     - :doc:`particle-tracking/index`
   * - Concentration transport
     - ``mt3dms``, ``modflow6gwt``
     - ``mt3dms`` requires ``flow/modflownwt``;
       ``modflow6gwt`` requires ``flow/modflow6``.
     - :doc:`concentration-transport/index`

.. toctree::
   :caption: Common transport part
   :maxdepth: 2

   common-concepts

.. toctree::
   :caption: Transport families
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
