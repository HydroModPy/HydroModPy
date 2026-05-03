Transport Solver Architecture
=============================

This section groups solver-architecture pages for the ``transport`` process.

The hierarchy is:

1. process: ``transport``,
2. common dependency and adapter lifecycle,
3. MODFLOW-NWT transport stack: MODPATH and MT3DMS downstream from
   ``flow/modflownwt``;
4. MODFLOW 6 transport stack: GWT downstream from ``flow/modflow6``.

This mirrors the scientific transport pages and the ``flow`` solver
architecture layout.

.. toctree::
   :caption: Common lifecycle
   :maxdepth: 2

   shared-lifecycle

.. toctree::
   :caption: MODFLOW-NWT transport stack
   :maxdepth: 2

   modpath-stack
   mt3dms-stack

.. toctree::
   :caption: MODFLOW 6 transport stack
   :maxdepth: 2

   modflow6gwt-stack

.. toctree::
   :caption: Cross-cutting adapter map
   :maxdepth: 2

   modflow-transport-adapters

Related Scientific Pages
------------------------

- :doc:`../../../scientific/solvers/transport/index`
- :doc:`../../../scientific/solvers/transport/common-concepts`
- :doc:`../../../scientific/solvers/transport/equations-and-unknowns`
- :doc:`../../../scientific/solvers/transport/modflow-nwt-transport`
- :doc:`../../../scientific/solvers/transport/modflow6-transport`
- :doc:`../process-solver-registry`
