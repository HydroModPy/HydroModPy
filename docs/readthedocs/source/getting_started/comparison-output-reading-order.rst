Comparison Output Reading Order
===============================

Use this page after running one comparison case such as the examples in
``examples/projects/09_comparison_workflow/``.

Its purpose is simple: help you decide what to open first, and what each file
really proves.

If you have not yet run a comparison, start with :doc:`comparison-workflow`.

What The Workflow Produces
--------------------------

One comparison run usually leaves two kinds of artifacts:

- normal child simulation outputs, one folder per generated child TOML;
- one comparison output folder that summarizes the differences between those
  child runs.

The comparison output folder is the right place to start. Its role is to make
the evidence readable without reopening each child simulation manually.

Reading Order
-------------

.. uml:: diagrams/comparison_output_reading_order.wsd

Use the order above for a first pass.

1. ``comparison_audit.md``
   Read this first. It tells you whether the workflow still considers the
   child runs to be one comparable physical case.
2. ``comparison_report.md``
   Read this next for context: reference variant, candidate variants,
   observables, and main outputs.
3. ``comparison_figures/case_configuration.png``
   Open this before judging numerical differences. It shows the support,
   topography when available, detected fixed-head boundaries, point/outlet
   observables, and recharge forcing.
4. ``comparison_metrics.csv``
   Use this to quantify the gap: bias, MAE, RMSE, and max error.
5. ``comparison_figures/*triptych*.png``
   Use the figures to see where the discrepancy is concentrated.
6. ``hydrographic_network_metrics.csv``
   Inspect this when the compared runs both expose canonical hydrographic
   networks and geometry matters to the question.
7. ``comparison_manifest.json``
   Keep this for traceability. It is the index that points to the report,
   metrics, generated configs, and child run folders.

Why This Order Matters
----------------------

Starting with figures is tempting, but it is often the wrong first move.

The safer order is:

- audit first, to confirm that the comparison stayed scientifically coherent;
- configuration second, to understand the tested case;
- metrics third, to measure the discrepancy;
- field figures fourth, to locate and diagnose it.

This avoids one common failure mode: reading an impressive difference map
before realizing the compared runs do not actually share the same support,
observable, or physical setup.

Case Configuration Figure
-------------------------

``comparison_figures/case_configuration.png`` is the orientation view. It is
not a solver result; it is a compact description of the case that produced the
results.

Use it to answer:

- what mesh or cell-centroid support is being compared,
- where the fixed-head boundaries are detected,
- which point/outlet observables are sampled,
- which recharge chronicle is applied,
- which solver variants are compared.

Triptych Figures
----------------

The most useful visual artifact is usually one triptych image:

1. reference field,
2. candidate field,
3. candidate minus reference difference.

That layout is valuable because it keeps three questions separate:

- what the reference solution looks like,
- what the candidate solution looks like,
- where the mismatch is actually located.

For map observables, this is usually the fastest way to see whether the main
difference is:

- one broad bias,
- one localized hotspot,
- one boundary effect,
- or one support-resolution artifact.

How To Read Metrics
-------------------

Use the metrics file to answer magnitude questions before making causal claims.

.. list-table::
   :header-rows: 1
   :widths: 18 30 52

   * - Metric
     - Main use
     - What it does not prove by itself
   * - Bias
     - Detect one systematic signed offset
     - A small bias does not mean the fields agree everywhere
   * - MAE
     - Measure the typical absolute discrepancy
     - It can hide a few strong local outliers
   * - RMSE
     - Penalize stronger local deviations more heavily
     - A large RMSE does not tell you where the hotspot is
   * - Max error
     - Flag the worst local mismatch
     - One peak does not mean the whole field is poor

Time Columns In CSV Files
-------------------------

When reading ``observables.csv``, ``timeseries_long.csv``,
``comparison_differences.csv``, or ``budget_timeseries_long.csv``, first check
``time_role``.

- ``initial_state`` is the explicit state before the first transient period.
- ``state_snapshot`` is an instantaneous state such as head or watertable.
- ``period_value`` is an interval value such as recharge, drainage, or a budget
  component.
- ``reduced`` is a statistic computed from several time rows.

For ``period_value`` rows, ``elapsed_seconds`` is the end of the period. Budget
exports also carry ``period_index``, ``period_start_seconds``, and
``period_end_seconds`` so that interval quantities are not confused with
instantaneous states.

Synthetic Shared-Mesh Case
--------------------------

The smallest comparison case is:

- ``examples/projects/09_comparison_workflow/compare_dupuit_mf6_bouss.toml``

For a first reading pass, the right order is:

1. check that both variants use the same irregular shared mesh;
2. confirm that the observable is ``watertable_elevation``;
3. read the point observables to see whether the mismatch is upstream,
   mid-domain, or downstream;
4. then read the map triptych for the spatial pattern.

This case is intentionally small, which makes it the best entry point for
understanding what the workflow does without mixing in too many natural-case
complications.

Natural Shared-Mesh Case
------------------------

The next stronger example is:

- ``examples/projects/09_comparison_workflow/compare_10km2_natural_mesh_mf6_bouss.toml``

Here the same reading order still applies, but one extra check matters:

- inspect the fine-raster products and triptychs as support harmonization
  artifacts, not as exact cell-to-cell truth.

This case is useful because it keeps one shared natural mesh while moving away
from a purely synthetic strip-style setup.

Common Misreadings
------------------

Avoid these shortcuts when reading comparison outputs.

- A small discrepancy is not the same thing as analytical validity.
- A clean triptych does not guarantee the same hydrological assumptions
  upstream.
- A large difference near one boundary does not automatically mean one solver
  is wrong; it may expose a support, closure, or boundary-condition mismatch.
- A fine-raster comparison is a harmonized observable space, not a universal
  proof of exact mesh equivalence.

When To Open The Child Runs
---------------------------

Stay in the comparison folder first.

Open child run folders only when one discrepancy needs a second-level
diagnosis, for example:

- to inspect one solver package setup,
- to check one exported field directly,
- to read one backend-specific log or budget artifact.

That keeps the workflow readable:

- comparison folder for evidence,
- child run folders for diagnosis.

Related Reading
---------------

- :doc:`comparison-workflow`
- :doc:`reading-results-pages`
- :doc:`../scientific/solvers/mesh-and-discretization-strategies`
- :doc:`../scientific/hydrology/recharge-and-surface-exchange-semantics`
