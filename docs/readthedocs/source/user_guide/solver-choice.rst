Solver Choice
=============

This page points to the documentation that helps choose a process, select a
compatible solver, and compare numerical assumptions. It is a routing page, not
a new scientific reference.

Start here when the question is:
"Which backend or numerical option should I inspect for this case?"

User path
---------

1. Read :doc:`solver-process-map` to choose by process first: ``flow``,
   ``transport``, ``postprocess``, or ``display``.
2. Open :doc:`../scientific/solvers/flow/index` or
   :doc:`../scientific/solvers/transport/index` depending on the process.
3. Read :doc:`../scientific/solvers/solver-capability-matrix` for a compact
   overview of solver capabilities and maturity.
4. Read :doc:`../scientific/solvers/modflow6-vs-modflownwt-scientific-comparison`
   when comparing MODFLOW 6 and MODFLOW-NWT.
5. Read :doc:`../scientific/solvers/xt3d-on-irregular-disv-meshes` when an
   irregular MODFLOW 6 DISV mesh is involved.
6. Open :doc:`../capability_gallery/validation` and
   :doc:`../capability_gallery/method_comparison` for curated result pages.
7. Use :doc:`../architecture/solver/index` when you need software structure
   rather than method interpretation.

Common questions
----------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Question
     - Best entry point
   * - Which solver names belong to each process?
     - :doc:`solver-process-map`
   * - Where are flow solvers grouped by type?
     - :doc:`../scientific/solvers/flow/index`
   * - Where is the internal MODFLOW documentation?
     - :doc:`../scientific/solvers/flow/modflow/index`
   * - Where are transport solvers grouped by type?
     - :doc:`../scientific/solvers/transport/index`
   * - What can each solver family represent?
     - :doc:`../scientific/solvers/solver-capability-matrix`
   * - How is the solver taxonomy generalized beyond Flow and Transport?
     - :doc:`../scientific/solvers/process-solver-taxonomy`
   * - How do MODFLOW 6 and MODFLOW-NWT differ scientifically?
     - :doc:`../scientific/solvers/modflow6-vs-modflownwt-scientific-comparison`
   * - Why is XT3D important on irregular meshes?
     - :doc:`../scientific/solvers/xt3d-on-irregular-disv-meshes`
   * - Where are analytical or semi-analytical validation cases?
     - :doc:`../capability_gallery/validation`
   * - Where is the solver package architecture?
     - :doc:`../architecture/solver/index`
   * - Where is the process/solver registry documented?
     - :doc:`../architecture/solver/process-solver-registry`

Related sections
----------------

- :doc:`mesh` for mesh and discretization documentation.
- :doc:`comparison` for shared-case method comparisons.
- :doc:`../api/hydromodpy-modeling` for solver-facing API reference.
