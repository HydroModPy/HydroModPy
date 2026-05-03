MODFLOW Flow Architecture
=========================

This page groups architecture notes for MODFLOW-family ``flow`` solvers.

In the process/solver registry, the active flow pairs are:

- ``flow/modflownwt``,
- ``flow/modflow6``.

Internal Architecture
---------------------

The detailed MODFLOW architecture is now organized under:

.. toctree::
   :maxdepth: 2

   modflow/index

Direct Backend Notes
--------------------

.. toctree::
   :caption: Direct backend notes
   :maxdepth: 1

   ../modflow6-architecture-notes
   ../modflownwt-architecture-notes

Code-Level Split
----------------

.. list-table::
   :header-rows: 1
   :widths: 26 34 40

   * - Package
     - Role
     - Main process pair
   * - ``hydromodpy.solver.modflow6``
     - MODFLOW 6 model assembly, execution, and output handling.
     - ``flow/modflow6``.
   * - ``hydromodpy.solver.modflow_nwt.modflow``
     - MODFLOW-NWT model assembly, execution, and output handling.
     - ``flow/modflownwt``.
   * - ``hydromodpy.solver.modflow_common``
     - Shared MODFLOW-family helpers for grids, forcing, options, and runtime
       arrays.
     - Shared by MODFLOW-family paths where applicable.

Related Scientific Pages
------------------------

- :doc:`../../../scientific/solvers/flow/modflow-family`
- :doc:`../process-solver-registry`
