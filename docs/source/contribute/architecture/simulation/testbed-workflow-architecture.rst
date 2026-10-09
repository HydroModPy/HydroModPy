Testbed workflow architecture
=============================

``[workflow].mode = "testbed"`` is an orchestration workflow for method robustness
studies. It deliberately sits above domain workflows such as mesh generation or
flow simulation.

The key design rule is:

.. code-block:: text

   testbed owns cases and evidence
   child runners own domain execution

This keeps method experiments reproducible without turning the testbed package
into another simulation engine. ``[testbed].profile`` selects the launcher:
``generic`` (the default) runs ``TestbedLauncher`` (``analysis/testbed/runtime.py``),
and ``regional_lab`` runs ``RegionalLabProfileLauncher``
(``analysis/testbed/regional_lab.py``). Any other value is refused.

.. figure:: /_static/workflows/testbed/testbed_orchestration.svg
   :alt: Testbed orchestration model
   :align: center

   The testbed layer expands cases into generated child configs, delegates
   execution, then collects evidence artifacts.

Package boundary
----------------

The implementation is intentionally narrow:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Module
     - Responsibility
   * - ``hydromodpy.analysis.testbed.config``
     - Validate the ``[testbed]`` contract, supported subject/runner pairs,
       cases, metrics, and path resolution.
   * - ``hydromodpy.analysis.testbed.runtime``
     - Load the base TOML, materialize generated child TOMLs, delegate child
       execution, extract metrics, and persist evidence files.
   * - ``hydromodpy.project.dispatch.workflow``
     - Expose ``run_testbed`` as the CLI adapter.
   * - Child runner packages
     - Keep ownership of mesh generation, simulation execution, solver
       persistence, and transport execution.

Supported runtime pairs
-----------------------

The contract accepts only explicit subject and runner pairs
(``SUPPORTED_SUBJECT_RUNNERS`` in ``hydromodpy/analysis/testbed/config.py``):

.. list-table::
   :header-rows: 1
   :widths: 20 24 28 28

   * - Subject
     - Runner
     - Generated workflow
     - Purpose
   * - ``mesh``
     - ``simulation``
     - ``[workflow].mode = "simulation"`` with ``[[simulation.process]]`` of
       ``type = "mesh"``
     - Resolution ladders, constraint sensitivity, conformity checks.
   * - ``flow``
     - ``simulation``
     - ``[workflow].mode = "simulation"``
     - Parameter sensitivity, boundary-condition cases, solver-option
       robustness.
   * - ``flow``
     - ``comparison``
     - ``[workflow].mode = "comparison"``
     - Pairwise comparison campaigns and method-comparison subsets.
   * - ``flow``
     - ``calibration``
     - ``[workflow].mode = "calibration"``
     - Calibration campaigns over a case matrix.
   * - ``transport``
     - ``simulation``
     - ``[workflow].mode = "simulation"``
     - Transport parameter sensitivity and method robustness.
   * - ``transport``
     - ``comparison``
     - ``[workflow].mode = "comparison"``
     - Pairwise transport-method comparison campaigns.

Generated children never contain ``[testbed]``. They are ordinary child
workflow TOMLs that can be opened, inspected, and in many cases run directly.

Data flow
---------

One testbed run follows this sequence:

1. Load the testbed TOML.
2. Load ``testbed.base_config`` when present.
3. Remove ``[testbed]`` from the child payload.
4. Resolve path-like values to stable paths.
5. Merge each case overlay.
6. Write one child TOML under ``<output_root>/_generated_configs/``.
7. Persist a dry evidence set.
8. If ``execute = true``, run each child sequentially.
9. Rewrite cases, metrics, manifest, and report after each child outcome.

This means ``execute = false`` is not a no-op. It is a planning mode that
materializes the experiment and lets a user audit generated children before
spending solver time.

Evidence model
--------------

.. figure:: /_static/workflows/testbed/testbed_outputs.svg
   :alt: Testbed output evidence tree
   :align: center

   The output directory is designed for auditability: child configs first,
   status and metrics next, manifest and report last.

The evidence files have stable roles:

- ``testbed_plan.json``: planned cases and generated config paths;
- ``testbed_cases.csv``: status and artifacts per case;
- ``testbed_metrics.csv``: configured metrics, or flattened numeric summaries;
- ``testbed_manifest.json``: machine-readable whole-run contract;
- ``testbed_report.md``: compact human summary.

Flow metric extraction
----------------------

For ``subject = "flow"``, the testbed does not parse solver files directly.
It delegates to ``[workflow].mode = "simulation"``, then reopens the completed run
through the result catalog. The catalog summary is flattened into
``flow_metrics`` keys that can be referenced by ``[[testbed.metrics]]``.

The keys are the flattened catalog summary of the child run, for example
``flow_metrics.duration_s``, ``flow_metrics.n_cells``,
``flow_metrics.max_abs_mass_balance_percent_error`` and
``flow_metrics.head_range_m``, plus one key per parameter (``flow_metrics.param_K``)
and per budget component (``flow_metrics.budget_chd_total_out`` for prescribed-head
exchanges, ``flow_metrics.budget_rcha_total_in`` for recharge).

Comparison children are deliberately thinner: the testbed consumes the summary
returned by the comparison runner and can expose those fields through
``[[testbed.metrics]]``. The comparison workflow keeps ownership of its HTML,
metrics, figures, and child simulation details.

Extension point
---------------

A new subject follows the existing contract, not a one-off runner convention.
The minimum changes are:

1. Add the subject name to ``SUPPORTED_SUBJECTS`` in ``analysis/testbed/config.py``.
2. Add the allowed runner pairs to ``SUPPORTED_SUBJECT_RUNNERS``.
3. Add the runner-to-child-workflow mapping in ``RUNNER_WORKFLOWS``
   (``analysis/testbed/pipeline.py``).
4. Add one launcher branch in ``TestbedLauncher._run_case``.
5. Add metric extraction only through runner summaries or persisted result
   stores.
6. Add dry-plan tests, execution tests with fake runners, and one documented
   example.

The main invariant should stay intact: testbed remains an evidence layer, not
a physics layer.

Failure semantics
-----------------

Metric declarations can set ``required = true``. A missing required metric
turns the child outcome into an explicit failure and writes that error into
the manifest. With ``continue_on_error = false``, the launcher re-raises after
persisting the failed case.

This is useful for robustness studies because silent metric loss is worse than
a failed case: a matrix is only comparable if each declared evidence column
has the intended meaning across cases.
