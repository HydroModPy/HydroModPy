Comparison Workflows
====================

This page groups the comparison documentation behind one user-facing entry
point. The goal is to keep solver-to-solver comparison, output reading, and
scientific interpretation connected without duplicating the detailed pages.

Start here when the question is:
"How do I compare several methods while keeping the physical case controlled?"

User path
---------

1. Read :doc:`../getting_started/comparison-workflow` to understand the
   shared-case workflow and run one comparison.
2. Read :doc:`../getting_started/comparison-output-reading-order` before
   opening generated metrics, audits, and figures.
3. Open :doc:`../capability_gallery/method_comparison` for curated comparison
   cases.
4. Use :doc:`../scientific/solvers/modflow6-vs-modflownwt-scientific-comparison`
   for method-level interpretation.

Common questions
----------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Question
     - Best entry point
   * - How do I run a comparison?
     - :doc:`../getting_started/comparison-workflow`
   * - Which output should I read first?
     - :doc:`../getting_started/comparison-output-reading-order`
   * - Where are stable comparison examples?
     - :doc:`../capability_gallery/method_comparison`
   * - How do I distinguish gallery, comparison, and validation pages?
     - :doc:`../getting_started/reading-results-pages`
   * - Where is the comparison implementation documented?
     - :doc:`../architecture/simulation/index`

Related sections
----------------

- :doc:`solver-choice` for backend and numerical-option trade-offs.
- :doc:`../scientific/solvers/solver-capability-matrix` for a compact solver
  capability overview.
- :doc:`../api-reference` for the generated API reference.
