Calibration Workflows
=====================

This page is the user-facing map for calibration documentation. Calibration
crosses the boundary between forward modelling, inverse problems, optimizer
configuration, and reporting, so the detailed material lives in several
sections.

Start here when the question is:
"How do I understand parameter estimation in HydroModPy?"

User path
---------

1. Read :doc:`../getting_started/workflow-families` to see how the
   ``calibration`` workflow differs from ``simulation`` and ``comparison``.
2. Open :doc:`../scientific/calibration/index` for inverse-problem formulation
   and implemented calibration methods.
3. Open :doc:`../capability_gallery/calibration` for stable calibration
   benchmark pages.
4. Use :doc:`../architecture/calibration/index` when you need package layout,
   runtime classes, or execution flows.

Common questions
----------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Question
     - Best entry point
   * - What inverse problem is being solved?
     - :doc:`../scientific/calibration/inverse-problem-formulation`
   * - Which calibration methods are implemented?
     - :doc:`../scientific/calibration/calibration-methods`
   * - Where can I inspect calibration benchmark outputs?
     - :doc:`../capability_gallery/calibration`
   * - How does the calibration engine run?
     - :doc:`../architecture/calibration/calibration-execution-flows`
   * - Which classes hold calibration configuration and runtime state?
     - :doc:`../architecture/calibration/calibration-core-classes`

Related sections
----------------

- :doc:`../scientific/foundations/index` for physical scope and assumptions.
- :doc:`../getting_started/reading-results-pages` for reading generated result
  pages.
- :doc:`../api/index` for generated API documentation.
