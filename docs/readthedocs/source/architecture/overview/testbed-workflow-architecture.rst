Testbed Workflow Architecture
=============================

``workflow = "testbed"`` is an orchestration workflow for method robustness
studies. It deliberately sits above domain workflows such as mesh generation or
flow simulation.

The key design rule is:

.. code-block:: text

   testbed owns variants and evidence
   child runners own domain execution

This keeps method experiments reproducible without turning the testbed package
into another simulation engine.

.. figure:: /_static/workflows/testbed/testbed_orchestration.svg
   :alt: Testbed orchestration model
   :align: center

   The testbed layer expands variants into generated child configs, delegates
   execution, then collects evidence artifacts.

Package Boundary
----------------

The implementation is intentionally narrow:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Module
     - Responsibility
   * - ``hydromodpy.analysis.testbed.config``
     - Validate the ``[testbed]`` contract, supported subject/runner pairs,
       variants, metrics, and path resolution.
   * - ``hydromodpy.analysis.testbed.runtime``
     - Load the base TOML, materialize generated child TOMLs, delegate child
       execution, extract metrics, and persist evidence files.
   * - ``hydromodpy.workflow.dispatch``
     - Expose ``run_testbed`` as the CLI adapter.
   * - Child runner packages
     - Keep ownership of mesh generation, simulation execution, solver
       persistence, and future transport execution.

Supported Runtime Pairs
-----------------------

The current contract accepts only explicit subject/runner pairs:

.. list-table::
   :header-rows: 1
   :widths: 20 24 28 28

   * - Subject
     - Runner
     - Generated workflow
     - Purpose
   * - ``mesh``
     - ``mesh_catchment``
     - ``workflow = "mesh"``
     - Resolution ladders, constraint sensitivity, conformity checks.
   * - ``flow``
     - ``simulation``
     - ``workflow = "simulation"``
     - Parameter sensitivity, boundary-condition variants, solver-option
       robustness.

Generated children never contain ``[testbed]``. They are ordinary child
workflow TOMLs that can be opened, inspected, and in many cases run directly.

Data Flow
---------

One testbed run follows this sequence:

1. Load the testbed TOML.
2. Load ``testbed.base_config`` when present.
3. Remove ``[testbed]`` from the child payload.
4. Resolve path-like values to stable paths.
5. Merge each variant overlay.
6. Write one child TOML under ``<output_root>/_generated_configs/``.
7. Persist a dry evidence set.
8. If ``execute = true``, run each child sequentially.
9. Rewrite cases, metrics, manifest, and report after each child outcome.

This means ``execute = false`` is not a no-op. It is a planning mode that
materializes the experiment and lets a user audit generated children before
spending solver time.

Evidence Model
--------------

.. figure:: /_static/workflows/testbed/testbed_outputs.svg
   :alt: Testbed output evidence tree
   :align: center

   The output directory is designed for auditability: child configs first,
   status and metrics next, manifest and report last.

The evidence files have stable roles:

- ``testbed_plan.json``: planned variants and generated config paths;
- ``testbed_cases.csv``: status and artifacts per variant;
- ``testbed_metrics.csv``: configured metrics, or flattened numeric summaries;
- ``testbed_manifest.json``: machine-readable whole-run contract;
- ``testbed_report.md``: compact human summary.

Flow Metric Extraction
----------------------

For ``subject = "flow"``, the testbed does not parse solver files directly.
It delegates to ``workflow = "simulation"``, then reopens the completed run
through the result catalog. The catalog summary is flattened into
``flow_metrics`` keys that can be referenced by ``[[testbed.metric]]``.

Confirmed metric examples from the repository starter are:

- ``flow_metrics.duration_s``;
- ``flow_metrics.n_cells``;
- ``flow_metrics.param_K``;
- ``flow_metrics.max_abs_mass_balance_percent_error``;
- ``flow_metrics.head_range_m``;
- ``flow_metrics.budget_chd_total_out`` for prescribed-head exchanges;
- ``flow_metrics.budget_rcha_total_in`` for recharge.

The full ``flow_k_sensitivity`` matrix was executed locally with three MODFLOW
6 children. All three completed successfully with 547 cells and zero
mass-balance percent error in the extracted catalog metrics. The observed
``head_range_m`` decreased from the low-K case to the high-K case, which is
the expected direction for this controlled hydraulic-conductivity sensitivity
test.

Extension Point
---------------

Adding a new subject such as transport should follow the existing contract
instead of introducing a one-off runner convention.

The minimum changes are:

1. Add the subject name to ``SUPPORTED_SUBJECTS``.
2. Add allowed runner pairs to ``SUPPORTED_SUBJECT_RUNNERS``.
3. Add runner-to-child-workflow mapping in ``RUNNER_WORKFLOWS``.
4. Add one launcher branch in ``TestbedLauncher._run_case``.
5. Add metric extraction only through runner summaries or persisted result
   stores.
6. Add dry-plan tests, execution tests with fake runners, and one documented
   example.

The main invariant should stay intact: testbed remains an evidence layer, not
a physics layer.

Failure Semantics
-----------------

Metric declarations can set ``required = true``. A missing required metric
turns the child outcome into an explicit failure and writes that error into
the manifest. With ``continue_on_error = false``, the launcher re-raises after
persisting the failed case.

This is useful for robustness studies because silent metric loss is worse than
a failed variant: a matrix is only comparable if each declared evidence column
has the intended meaning across variants.
