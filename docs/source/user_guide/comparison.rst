Comparison Workflows
====================

.. note::

   Use this page when the question is:
   "How do I compare several methods on the same physical case, with the
   physics held constant?"

The ``comparison`` workflow generates several child simulations from a single
shared base configuration. The base config holds the catchment, mesh, data,
and physics; each child is an overlay that varies only the solver, the
backend-specific options, or a controlled parameter sweep. This is what makes
solver-to-solver, structured-vs-unstructured, or XT3D-on-off studies
interpretable: nothing else moves.

Overlays in the ``comparison`` workflow are intentionally restricted to
``[solver]``, ``[modflow6]``, ``[modflownwt]``, ``[flow.runtime_backend]``,
``[flow.param]``, and ``[display]``. Sections that change physics
(``[domain]``, ``[flow.bc]``, ``[flow.sinks_sources]``) are rejected. Cross
the boundary by writing a different base config rather than a forbidden
overlay.

Decision matrix
---------------

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - Question
     - Best entry point
   * - How do I set up and run a comparison?
     - :doc:`concepts/comparison-workflow`
   * - Which output should I read first?
     - :doc:`concepts/comparison-output-reading-order`
   * - Where are stable comparison examples?
     - :doc:`../capability_gallery/simulation_comparison`
   * - How do MODFLOW 6 and MODFLOW-NWT differ scientifically?
     - :doc:`../theory/solvers/modflow6-vs-modflownwt-scientific-comparison`
   * - How do I distinguish gallery, comparison, and validation pages?
     - :doc:`concepts/reading-results-pages`
   * - Where is the comparison implementation documented?
     - :doc:`../architecture/simulation/index`

Minimal comparison setup
------------------------

Two TOML files cooperate: a base simulation TOML for the shared physics, and
a comparison TOML that lists the children and the observables to extract.

.. code-block:: toml

   [workflow]
   mode = "comparison"

   [comparison]
   comparison_id = "mf6_vs_bouss"
   base_simulation_config = "base_dupuit_shared_mesh.toml"
   output_root = "outputs/mf6_vs_bouss"
   reference_simulation = "mf6_ref"

   [[comparison.simulation]]
   id = "mf6_ref"
   solver = "modflow6"

   [[comparison.simulation]]
   id = "bouss_candidate"
   solver = "boussinesq"

   [[comparison.observable]]
   name = "head_map_last"
   variable = "watertable_elevation"
   support = "map"
   time = "last"
   unit = "m"

.. code-block:: bash

   hmp run mf6_vs_bouss.toml

Read more
---------

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Concepts
      :link: concepts/comparison-workflow
      :link-type: doc

      Shared-case workflow, generated child TOMLs, observable extraction,
      and audit logic.

   .. grid-item-card:: Gallery
      :link: ../capability_gallery/simulation_comparison
      :link-type: doc

      Curated solver-to-solver comparison cases with figures and metrics.

   .. grid-item-card:: Theory
      :link: ../theory/solvers/modflow6-vs-modflownwt-scientific-comparison
      :link-type: doc

      Scientific contrast of MODFLOW 6 and MODFLOW-NWT for method-level
      interpretation.

   .. grid-item-card:: Solver choice
      :link: solver-choice
      :link-type: doc

      Backend trade-offs and numerical options worth comparing.

See also
--------

- :doc:`../theory/solvers/solver-capability-matrix` for a compact solver
  capability overview.
- :doc:`mesh` when the comparison varies mesh resolution rather than
  solver.
- :doc:`../api/index` for the generated API reference.
