MODFLOW Internals
=================

This section structures the MODFLOW-family documentation inside the ``flow``
process.

The hierarchy is intentionally split into three first-class sub-categories:

1. **Common MODFLOW part**: governing equation, package semantics,
   boundary-condition mapping, stress periods, and shared method vocabulary;
2. **MODFLOW 6 version**: modern MODFLOW 6 GWF path for ``flow/modflow6``;
3. **MODFLOW-NWT version**: legacy structured-grid path for
   ``flow/modflownwt``.

Other pages then compare, illustrate, or connect these three blocks to
transport.

Three Sub-Categories
--------------------

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Sub-category
     - Contains
     - Use it when
   * - Common MODFLOW part
     - :doc:`common/index`
     - You need the concepts that apply to both MODFLOW 6 and MODFLOW-NWT.
   * - MODFLOW 6 version
     - :doc:`modflow6-version/index`
     - You run or interpret ``flow/modflow6``.
   * - MODFLOW-NWT version
     - :doc:`modflownwt-version/index`
     - You run or interpret ``flow/modflownwt``.

Current MODFLOW Flow Backends
-----------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 28 28 22

   * - Process/solver pair
     - Backend family
     - Main support
     - Downstream transport
   * - ``flow/modflow6``
     - MODFLOW 6 GWF.
     - Structured grids and runtime DISV-style meshes where supported.
     - ``transport/modflow6gwt``.
   * - ``flow/modflownwt``
     - MODFLOW-NWT.
     - Structured ``sgrid`` support.
     - ``transport/modpath`` and ``transport/mt3dms``.

.. toctree::
   :caption: Common MODFLOW part
   :maxdepth: 2

   common/index

.. toctree::
   :caption: MODFLOW 6 version
   :maxdepth: 2

   modflow6-version/index

.. toctree::
   :caption: MODFLOW-NWT version
   :maxdepth: 2

   modflownwt-version/index

.. toctree::
   :caption: Comparison, cases, and coupling
   :maxdepth: 1

   comparison-and-method-choice
   worked-cases
   transport-coupling

Related Pages
-------------

- :doc:`../modflow-family`
- :doc:`../../solver-capability-matrix`
- :doc:`../../modflow6-vs-modflownwt-scientific-comparison`
- :doc:`../../worked-modflow-case-dupuit-fixed-head-1d`
- :doc:`../../worked-modflow-case-linearized-unconfined-recharge-periodic-1d`
- :doc:`../../../../architecture/solver/flow/modflow/index`
