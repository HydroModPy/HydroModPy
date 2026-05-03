MODFLOW-NWT Version
===================

This section contains the MODFLOW-NWT-specific material for
``flow/modflownwt``.

Use it when the selected flow backend is the legacy structured-grid
MODFLOW-NWT route, especially when the workflow must remain compatible with
MODPATH or MT3DMS.

What Belongs Here
-----------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Topic
     - MODFLOW-NWT-specific emphasis
   * - Backend route
     - ``flow/modflownwt`` and the legacy MODFLOW-NWT package stack.
   * - Mesh support
     - Structured ``sgrid`` support.
   * - Legacy continuity
     - Reproduction and comparison of historical structured-grid workflows.
   * - Transport compatibility
     - ``transport/modpath`` for particle tracking and ``transport/mt3dms`` for
       concentration transport.
   * - Comparison role
     - Legacy MODFLOW-family baseline when comparing with MODFLOW 6 or
       Boussinesq.

.. toctree::
   :maxdepth: 1

   MODFLOW-NWT flow page <../modflownwt>
   MODFLOW 6 versus MODFLOW-NWT comparison <../../../modflow6-vs-modflownwt-scientific-comparison>
   Nancon transient NWT worked case <../../../worked-modflow-case-nancon-transient-nwt-etp-evt>

Related Common And Comparison Pages
-----------------------------------

- :doc:`../common/index`
- :doc:`../cross-cutting/index`
