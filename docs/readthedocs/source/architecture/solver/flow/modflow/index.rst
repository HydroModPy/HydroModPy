MODFLOW Internals Architecture
==============================

This section structures the software architecture inside the MODFLOW family.

The hierarchy is:

1. shared MODFLOW lifecycle and common helpers,
2. MODFLOW 6 flow stack,
3. MODFLOW-NWT flow stack,
4. transport coupling to MODPATH, MT3DMS, and MODFLOW 6 GWT.

.. toctree::
   :maxdepth: 2

   /architecture/solver/flow/modflow/shared-lifecycle
   /architecture/solver/flow/modflow/modflow6-stack
   /architecture/solver/flow/modflow/modflownwt-stack
   /architecture/solver/flow/modflow/transport-coupling

Related Scientific Pages
------------------------

- :doc:`../../../../scientific/solvers/flow/modflow/index`
- :doc:`../modflow-family`
- :doc:`../../process-solver-registry`
