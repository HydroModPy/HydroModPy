MODFLOW Flow Family
===================

This page groups the scientific notes for MODFLOW-family ``flow`` solvers.

Read this family as three explicit sub-categories:

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Sub-category
     - Main page
     - Purpose
   * - Common MODFLOW part
     - :doc:`modflow/common/index`
     - Shared groundwater-flow vocabulary: governing equation, package
       semantics, boundary mapping, stress periods, vertical assumptions, and
       comparison discipline.
   * - MODFLOW 6 version
     - :doc:`modflow/modflow6-version/index`
     - Modern MODFLOW 6 GWF route for ``flow/modflow6``: structured and
       runtime DISV-style supports, XT3D choices, and MODFLOW 6 GWT coupling.
   * - MODFLOW-NWT version
     - :doc:`modflow/modflownwt-version/index`
     - Legacy MODFLOW-NWT route for ``flow/modflownwt``: structured ``sgrid``
       support, continuity with historical studies, MODPATH, and MT3DMS.

In HydroModPy, the two active MODFLOW-family flow versions are:

- ``flow/modflownwt``: legacy MODFLOW-NWT route, structured ``sgrid`` support,
  and compatibility with MODPATH and MT3DMS.
- ``flow/modflow6``: modern MODFLOW 6 route, including structured grids and
  runtime DISV-style unstructured meshes where supported.

Three-Part Internal Structure
-----------------------------

The detailed MODFLOW navigation is organized so that the common part comes
first, then each backend version is readable independently:

.. toctree::
   :caption: Common MODFLOW part
   :maxdepth: 2

   modflow/common/index

.. toctree::
   :caption: MODFLOW 6 version
   :maxdepth: 2

   modflow/modflow6-version/index

.. toctree::
   :caption: MODFLOW-NWT version
   :maxdepth: 2

   modflow/modflownwt-version/index

.. toctree::
   :caption: Cross-cutting MODFLOW pages
   :maxdepth: 1

   modflow/index
   modflow/comparison-and-method-choice
   modflow/worked-cases
   modflow/transport-coupling

Quick Reading Order
-------------------

If you do not know where to start, read the internal pages in this order:

1. :doc:`modflow/common/index`,
2. :doc:`modflow/modflow6-version/index` if you use the modern MODFLOW 6 path,
3. :doc:`modflow/modflownwt-version/index` if you use the legacy MODFLOW-NWT
   path,
4. :doc:`modflow/comparison-and-method-choice` when choosing or comparing,
5. :doc:`modflow/worked-cases`,
6. :doc:`modflow/transport-coupling` when transport is involved.

Backend Version Summary
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 20 28 28 24

   * - Version
     - Shared MODFLOW concepts repeated in that page
     - Version-specific emphasis
     - Downstream transport
   * - ``flow/modflow6``
     - Flow equation, recharge, wells, storage, imposed heads, drainage,
       stress periods, package semantics.
     - MODFLOW 6 package stack, structured or DISV-style support, XT3D,
       modern output and GWT compatibility.
     - ``transport/modflow6gwt``.
   * - ``flow/modflownwt``
     - Flow equation, recharge, wells, storage, imposed heads, drainage,
       stress periods, package semantics.
     - Structured-grid continuity, historical MODFLOW-NWT behavior, legacy
       package assumptions, MODPATH and MT3DMS compatibility.
     - ``transport/modpath`` and ``transport/mt3dms``.

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
