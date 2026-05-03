MODFLOW Worked Cases
====================

Worked cases connect the conceptual notes to executable examples.

They are the best entry point when the question is:

"What TOML is used, what does HydroModPy resolve, which MODFLOW packages are
assembled, and what outputs should I inspect?"

Available Worked Cases
----------------------

.. toctree::
   :maxdepth: 1

   ../../worked-modflow-case-dupuit-fixed-head-1d
   ../../worked-modflow-case-linearized-unconfined-recharge-periodic-1d
   ../../worked-modflow-case-linearized-unconfined-drainage-1d

Case Selection
--------------

.. list-table::
   :header-rows: 1
   :widths: 28 36 36

   * - Case
     - Best for
     - Main MODFLOW lesson
   * - Dupuit fixed-head 1D
     - First MODFLOW 6 reading path and support comparison.
     - Structured versus irregular support and fixed-head boundary handling.
   * - Linearized unconfined recharge periodic 1D
     - Transient recharge and MODFLOW-NWT/MODFLOW 6 comparison.
     - Stress periods, recharge forcing, and flow response over time.
   * - Linearized unconfined drainage 1D
     - ``DRN`` semantics in one steady analytical setting.
     - Distributed top drainage as a head-dependent release operator.

Reading Rule
------------

Read worked cases after:

1. :doc:`common-concepts`,
2. :doc:`comparison-and-method-choice`,
3. the backend-specific page for the solver used in the case.

Related Pages
-------------

- :doc:`modflow6`
- :doc:`modflownwt`
