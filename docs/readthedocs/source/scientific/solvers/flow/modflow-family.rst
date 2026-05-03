MODFLOW Flow Family
===================

This page groups the scientific notes for MODFLOW-family ``flow`` solvers.

In HydroModPy, this family currently contains:

- ``flow/modflownwt``: legacy MODFLOW-NWT route, structured ``sgrid`` support,
  and compatibility with MODPATH and MT3DMS.
- ``flow/modflow6``: modern MODFLOW 6 route, including structured grids and
  runtime DISV-style unstructured meshes where supported.

Internal Structure
------------------

The detailed MODFLOW navigation is now organized under:

.. toctree::
   :maxdepth: 2

   modflow/index

Quick Reading Order
-------------------

If you do not know where to start, read the internal pages in this order:

1. :doc:`modflow/common-concepts`,
2. :doc:`modflow/modflow6` or :doc:`modflow/modflownwt`,
3. :doc:`modflow/comparison-and-method-choice`,
4. :doc:`modflow/worked-cases`,
5. :doc:`modflow/transport-coupling` when transport is involved.

.. toctree::
   :caption: Direct note links
   :maxdepth: 1

   ../modflow-governing-equation-and-cvfd-formulation
   ../modflow-package-semantics-and-boundary-conditions
   ../modflow-family-methods
   ../modflow6-vs-modflownwt-scientific-comparison
   ../xt3d-on-irregular-disv-meshes
   ../worked-modflow-case-dupuit-fixed-head-1d
   ../worked-modflow-case-linearized-unconfined-recharge-periodic-1d

Selection Notes
---------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Solver
     - Prefer when
     - Be careful when
   * - ``modflownwt``
     - You need continuity with legacy structured-grid workflows or downstream
       MODPATH / MT3DMS transport.
     - You need runtime Gmsh/DISV-style irregular mesh support.
   * - ``modflow6``
     - You need modern MODFLOW package semantics, irregular mesh support, or
       MODFLOW 6 GWT transport compatibility.
     - You compare against legacy studies whose numerical assumptions were
       calibrated on MODFLOW-NWT.

Related Architecture
--------------------

- :doc:`../../../architecture/solver/flow/modflow-family`
- :doc:`../../../architecture/solver/process-solver-registry`
