Common MODFLOW Part
===================

This section contains the material that is shared by the two MODFLOW-family
flow versions exposed by HydroModPy:

- ``flow/modflow6``;
- ``flow/modflownwt``.

Read this part before choosing a version. It defines the shared vocabulary used
by both paths: governing equation, package semantics, forcing and boundary
mapping, stress periods, vertical assumptions, and comparison discipline.

Shared Scientific Contract
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Topic
     - Common role
   * - Governing equation
     - Both versions are MODFLOW-family groundwater-flow paths solving
       hydraulic head through a cell-based balance.
   * - Package vocabulary
     - Recharge, wells, storage, drainage, imposed heads, output control, and
       solver settings must be understood before reading backend differences.
   * - Stress periods
     - Both versions receive time aggregation through stress-period-like
       backend inputs.
   * - Boundary semantics
     - HydroModPy boundary declarations are interpreted through MODFLOW package
       concepts before version-specific assembly.
   * - Comparison discipline
     - Differences between MODFLOW 6 and MODFLOW-NWT should not be attributed
       to the solver before checking support, forcing, vertical representation,
       and package mapping.

.. toctree::
   :maxdepth: 1

   Governing equation and CVFD formulation <../../../modflow-governing-equation-and-cvfd-formulation>
   Package semantics and boundary conditions <../../../modflow-package-semantics-and-boundary-conditions>
   MODFLOW family methods <../../../modflow-family-methods>

Related Version Pages
---------------------

- :doc:`../modflow6-version/index`
- :doc:`../modflownwt-version/index`
- :doc:`../cross-cutting/index`
