Transport Solver Architecture
=============================

This section groups solver-architecture pages for the ``transport`` process.

The hierarchy is:

1. process: ``transport``,
2. common dependency and adapter lifecycle,
3. solver-specific adapter stack: MODPATH, MT3DMS, or MODFLOW 6 GWT.

This mirrors the scientific transport pages and the ``flow`` solver
architecture layout.

.. toctree::
   :caption: Common lifecycle
   :maxdepth: 2

   shared-lifecycle

.. toctree::
   :caption: Adapter stacks
   :maxdepth: 2

   modpath-stack
   mt3dms-stack
   modflow6gwt-stack

.. toctree::
   :caption: Cross-cutting adapter map
   :maxdepth: 2

   modflow-transport-adapters

Related Scientific Pages
------------------------

- :doc:`../../../scientific/solvers/transport/index`
- :doc:`../../../scientific/solvers/transport/common-concepts`
- :doc:`../process-solver-registry`
