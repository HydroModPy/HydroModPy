MODFLOW Internals
=================

This section structures the MODFLOW-family documentation inside the
``flow`` process.

The hierarchy is:

1. **common MODFLOW concepts**: governing equation, package semantics,
   boundary-condition mapping, and shared method vocabulary;
2. **backend-specific flow solvers**: MODFLOW 6 and MODFLOW-NWT;
3. **comparison and method choice**: when the two MODFLOW paths differ and how
   to interpret those differences;
4. **worked cases**: concrete examples that show the resolved TOML, package
   choices, and generated outputs;
5. **transport coupling**: how MODFLOW flow results feed MODPATH, MT3DMS, or
   MODFLOW 6 GWT.

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
   :maxdepth: 2

   common-concepts
   modflow6
   modflownwt
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
