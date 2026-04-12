How To Read Gallery, Comparison, and Validation Pages
=====================================================

HydroModPy exposes several kinds of result pages. They do not answer the same
question, so it helps to separate them early.

.. important::

   Use this page after one walkthrough. It is meant to help you interpret
   published result pages, not to replace the editable case guides.

Know which question the page answers
------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 34 42

   * - Page type
     - Main question
     - What not to infer too quickly
   * - Example or walkthrough page
     - How do I run and modify one workflow?
     - It is not automatically a numerical validation of the method.
   * - Capability-gallery case
     - What does this workflow or artifact look like as a stable, curated snapshot?
     - It is not the full run workspace and not always the best place to learn the editable config from scratch.
   * - Method-comparison page
     - How different are two solver outputs on the same saved support?
     - A small discrepancy is not the same thing as analytical correctness.
   * - Validation page
     - Does one numerical path reproduce an analytical or trusted reference within explicit tolerances?
     - Good validation does not automatically mean every complex real-case setup is configured correctly.

Method-comparison pages
-----------------------

Use a method-comparison page such as
:doc:`../capability_gallery/cases/example12_map_method_comparison` when the
main question is solver agreement.

Read them in this order:

1. Confirm support equality.
   The comparison is strongest when both runs use the same saved mesh or grid.
2. Confirm observable equality.
   Make sure the compared field really represents the same quantity in both runs.
3. Read the parity shape.
   A compact cloud around the ``1:1`` line means broad agreement.
4. Read MAE and RMSE together.
   MAE is the typical mismatch; RMSE highlights stronger local deviations.

Validation pages
----------------

Validation pages under :doc:`../capability_gallery/validation` answer a
different question: whether one solver path matches a reference solution or a
benchmark expectation.

Read them in this order:

1. Read the ``Case Setup``.
   This tells you what is actually being benchmarked.
2. Read the ``Analytical Reference`` if present.
   This is the truth model for the page.
3. Read ``Solver Coverage``.
   Some pages compare several backends side by side.
4. Read the displayed metrics and tolerances.
   A passing case means the chosen metrics stayed within explicit thresholds,
   not that every output is exactly equal.

Static gallery pages versus editable configs
--------------------------------------------

The capability gallery is intentionally static and versioned. It is excellent
for:

- scanning one family of cases quickly,
- teaching from stable figures,
- checking which artifacts are considered documentation-worthy.

It is not the best place to learn the editable case structure from scratch.
When you want that, go back to:

- :doc:`data-overview-walkthrough`
- :doc:`simulation-walkthrough`
- :doc:`choose-your-first-workflow`
