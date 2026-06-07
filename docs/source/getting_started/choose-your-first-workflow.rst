Choose Your First Workflow
==========================

.. page-badges::
   :difficulty: beginner
   :time: 5 min

Use this page when you know what you want to learn, but not which HydroModPy
entry point to open first.

If you already know the CLI keyword you are looking for and want the full map
of ``[workflow].mode = "..."`` families, use :doc:`../user_guide/workflows/index`.

.. important::

   Default recommendation: start with :doc:`data-overview-walkthrough`. It is
   the fastest way to understand basin setup, data loading, and case structure
   before any solver run.

Match your goal to a first page
-------------------------------

Inspect one basin before any solve
   Start with :doc:`data-overview-walkthrough`. Watershed extraction,
   domain setup, and data loading, without touching any solver.

   .. code-block:: bash

      hmp run examples/projects/04_data_overview/project.toml

Run one complete example end to end
   Start with :doc:`simulation-walkthrough`. See how geographic setup,
   meshing, and flow fit together in a single run.

   .. code-block:: bash

      hmp run examples/projects/06_vire_selune/run_vire_mf6_irregular.toml

Compare two numerical methods on the same support
   Start with :doc:`../user_guide/concepts/comparison-workflow`. A
   dedicated run workflow that generates child simulations, metrics,
   and difference figures.

   .. code-block:: bash

      hmp run examples/projects/09_comparison_workflow/compare_dupuit_mf6_bouss.toml

Check numerical credibility against a reference
   Start with :doc:`../user_guide/concepts/reading-results-pages`.
   Validation pages explain analytical targets, solver coverage, and
   tolerance-based metrics.

   .. code-block:: bash

      python -m validation_cases.run_cases --solver modflow6 --regime both --no-show

Browse the full static inventory first
   Start with :doc:`../capability_gallery/index`. A visual inventory:
   scan curated figures quickly before running anything locally.

   .. code-block:: bash

      python -m tools.doc_gallery

Default path for most users
---------------------------

For most first-time contributors or users working from repository examples:

1. Start with :doc:`data-overview-walkthrough`.
2. Continue with :doc:`simulation-walkthrough`.
3. Use :doc:`../user_guide/concepts/reading-results-pages` once you begin comparing methods or reading
   validation metrics.

Why not start with validation?
------------------------------

Validation pages are useful, but they answer a different question. They tell
you whether one numerical path reproduces an analytical or trusted reference.
They do not teach the full user-facing workflow as directly as the
data-overview and simulation examples.

When to use the static gallery
------------------------------

The :doc:`../capability_gallery/index` is best used as a visual inventory:

- it is fast to browse,
- it helps you find an example family,
- it does not replace the editable config files or the full run workspaces.
