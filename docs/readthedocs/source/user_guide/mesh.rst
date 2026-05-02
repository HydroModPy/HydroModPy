Mesh Workflows
==============

This page is a user-facing map for mesh-related documentation. It does not
replace the detailed scientific or architecture pages; it tells you which page
to open for each question.

Start here when the question is:
"How do I understand or inspect the discretization before trusting a run?"

User path
---------

1. Read :doc:`../getting_started/workflow-families` to see where the ``mesh``
   workflow fits relative to ``overview`` and ``simulation``.
2. Open :doc:`../capability_gallery/mesh` to inspect stable mesh examples and
   diagnostics without running anything locally.
3. Use :doc:`../scientific/solvers/meshes-and-numerical-methods` when you need
   the numerical-method context behind structured and irregular meshes.
4. Use :doc:`../architecture/mesh/index` when you need to understand where mesh
   construction, export, and solver handoff live in the code.

Common questions
----------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Question
     - Best entry point
   * - Which mesh cases are already documented?
     - :doc:`../capability_gallery/mesh`
   * - Which diagnostics should I inspect first?
     - :doc:`../getting_started/reading-results-pages`
   * - Why do mesh quality and discretization strategy matter?
     - :doc:`../scientific/solvers/mesh-quality-and-acceptance-criteria`
   * - How does a catchment mesh become a solver input?
     - :doc:`../architecture/mesh/mesh-catchment-in-process-simulation-activity-diagram`
   * - How are structured grids represented?
     - :doc:`../architecture/mesh/structured-grid-class-diagram`

Related sections
----------------

- :doc:`../capability_gallery/geographic` for pre-solver watershed context.
- :doc:`../capability_gallery/simulation` for solver runs built on mesh
  artifacts.
- :doc:`solver-choice` for solver and discretization trade-offs.
