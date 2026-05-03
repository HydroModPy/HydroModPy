MODFLOW Internals Architecture
==============================

This section structures the software architecture inside the MODFLOW family.

The hierarchy is:

1. common MODFLOW lifecycle and shared helpers;
2. MODFLOW 6 flow stack;
3. MODFLOW-NWT flow stack;
4. transport coupling to MODPATH, MT3DMS, and MODFLOW 6 GWT.

.. toctree::
   :caption: Common MODFLOW architecture
   :maxdepth: 2

   /architecture/solver/flow/modflow/shared-lifecycle

.. toctree::
   :caption: MODFLOW 6 architecture
   :maxdepth: 2

   /architecture/solver/flow/modflow/modflow6-stack

.. toctree::
   :caption: MODFLOW-NWT architecture
   :maxdepth: 2

   /architecture/solver/flow/modflow/modflownwt-stack

.. toctree::
   :caption: Transport coupling
   :maxdepth: 2

   /architecture/solver/flow/modflow/transport-coupling

Related Scientific Pages
------------------------

- :doc:`../../../../scientific/solvers/flow/modflow/index`
- :doc:`../../../../scientific/solvers/flow/modflow/common/index`
- :doc:`../../../../scientific/solvers/flow/modflow/modflow6-version/index`
- :doc:`../../../../scientific/solvers/flow/modflow/modflownwt-version/index`
- :doc:`../modflow-family`
- :doc:`../../process-solver-registry`
