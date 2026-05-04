Testbed Workflow
================

Use this workflow when the goal is not to run one model, but to organize a
controlled method testbed.

A testbed expands variants, delegates each variant to a child runner, then
collects evidence artifacts such as generated configs, metrics, manifests, and
reports.

.. figure:: /_static/workflows/testbed/testbed_orchestration.svg
   :alt: Testbed orchestration model
   :align: center

   ``testbed`` owns the variant matrix and evidence contract. Mesh, flow, and
   future transport runners keep ownership of their own domain execution.

The first supported subjects are:

- ``mesh`` through the ``mesh_catchment`` runner;
- ``flow`` through the ``simulation`` runner.

This keeps the testbed detached from simulation internals. A mesh testbed can
evaluate discretization choices without running a flow solver. A flow testbed
delegates to ordinary generated ``workflow = "simulation"`` children, but the
testbed itself only expands variants and gathers evidence.

The implementation lives near the analysis workflows in
``hydromodpy/analysis/testbed/``. The package README documents the internal
contract for maintainers; this page documents the user-facing behavior.

What This Workflow Is
---------------------

Declare a testbed with:

.. code-block:: toml

   workflow = "testbed"

   [testbed]
   id = "mesh_resolution_testbed"
   subject = "mesh"
   purpose = "robustness"
   base_config = "mesh_base.toml"
   output_root = "outputs/mesh_resolution_testbed"

   [testbed.runner]
   type = "mesh_catchment"

   [[testbed.variant]]
   id = "coarse"
   axis = "resolution"

   [testbed.variant.overlay.mesh_catchment.zone_meshing]
   global_size = 400.0

   [[testbed.variant]]
   id = "fine"
   axis = "resolution"

   [testbed.variant.overlay.mesh_catchment.zone_meshing]
   global_size = 100.0

   [[testbed.metric]]
   name = "n_cells"

The launcher writes one child TOML per variant under:

.. code-block:: text

   <output_root>/_generated_configs/

For mesh subjects, each generated child is delegated to the
``mesh_catchment`` runner. The testbed does not call the simulation planner
and does not persist solver runs.

Flow Example
------------

A flow testbed uses the same orchestration contract, but delegates each child
variant to the simulation workflow:

.. code-block:: toml

   workflow = "testbed"

   [testbed]
   id = "flow_k_sensitivity"
   subject = "flow"
   purpose = "robustness"
   base_config = "flow_base.toml"
   output_root = "outputs/flow_k_sensitivity"

   [testbed.runner]
   type = "simulation"

   [[testbed.variant]]
   id = "low_k"
   axis = "hydraulic_conductivity"

   [testbed.variant.overlay.simulation]
   name = "flow_low_k"

   [testbed.variant.overlay.flow.param.K.field_homogeneous]
   value = "5e-6 m/s"

   [[testbed.variant]]
   id = "high_k"
   axis = "hydraulic_conductivity"

   [testbed.variant.overlay.simulation]
   name = "flow_high_k"

   [testbed.variant.overlay.flow.param.K.field_homogeneous]
   value = "2e-5 m/s"

   [[testbed.metric]]
   name = "duration_s"
   source = "flow_metrics.duration_s"

   [[testbed.metric]]
   name = "max_abs_balance_error"
   source = "flow_metrics.max_abs_mass_balance_percent_error"

   [[testbed.metric]]
   name = "head_range_m"
   source = "flow_metrics.head_range_m"

Here ``flow_base.toml`` is a normal ``workflow = "simulation"`` TOML. The
testbed declaration stays outside that base file, so the generated child
configs remain valid simulation configs. This is the important boundary:
``testbed`` owns the experimental matrix; ``simulation`` owns physical
execution.

For flow children, the launcher tries to reopen the generated run through the
``SimulationCatalog`` and enriches the child summary with:

- ``catalog``: run metadata such as solver, status, duration, cell count, and
  time-step count;
- ``parameters``: scalar persisted parameters;
- ``budget``: component-wise total inflow, outflow, and net flow;
- ``mass_balance`` indicators under ``flow_metrics``;
- ``field_summary`` and flat ``flow_metrics`` entries for persisted fields such
  as ``head``, ``watertable_depth``, ``outflow_drain``, and
  ``accumulation_flux`` when they are available.

Metric sources use dot paths into that summary. For example:
``flow_metrics.param_K``, ``flow_metrics.budget_<component>_total_out``, or
``flow_metrics.head_range_m``. The exact budget component name comes from the
solver result catalog, for example ``chd`` for prescribed-head exchanges.

The repository flow starter in
``examples/projects/10_testbed_workflow/flow_k_sensitivity_testbed.toml`` has
been smoke-tested with one executed MODFLOW 6 child. In that case, prescribed
heads are exposed as ``flow_metrics.budget_chd_total_out`` and recharge as
``flow_metrics.budget_rcha_total_in``. The example marks its key metrics as
``required = true`` so switching from ``execute = false`` to ``execute = true``
fails loudly if the catalog cannot provide the expected evidence.

The full three-variant matrix was also executed locally with ``execute = true``.
All children completed successfully with 547 cells and zero mass-balance
percent error:

.. list-table::
   :header-rows: 1
   :widths: 18 18 18 22 24

   * - Variant
     - ``param_K``
     - ``n_cells``
     - ``head_range_m``
     - ``prescribed_head_out``
   * - ``low_k``
     - ``5e-06``
     - ``547``
     - ``61.95``
     - ``0.05158187``
   * - ``reference_k``
     - ``1e-05``
     - ``547``
     - ``47.55``
     - ``0.05158152``
   * - ``high_k``
     - ``2e-05``
     - ``547``
     - ``40.91``
     - ``0.05158121``

These values are not committed as generated outputs; they document the current
smoke-tested behavior of the starter configuration.

Runnable Example Files
----------------------

The repository contains two starter testbeds:

- ``examples/projects/10_testbed_workflow/mesh_resolution_testbed.toml``;
- ``examples/projects/10_testbed_workflow/flow_k_sensitivity_testbed.toml``.

Both use ``execute = false`` so they first materialize generated child configs
without spending solver time. Change that flag to ``true`` when the matrix has
the intended variants.

Mesh As A Testbed Subject
-------------------------

Mesh work is documented here rather than as a separate top-level user guide
workflow. The user-facing question is usually not "build one mesh", but "how
stable is the discretization choice?"

For mesh studies, ``testbed`` answers:
"Run this controlled set of mesh variants and collect evidence."

This means:

- use ``subject = "mesh"`` with ``runner.type = "mesh_catchment"`` for
  resolution ladders, constraint sensitivity, conformity studies, and
  robustness checks;
- keep mono-case mesh artifacts as generated evidence inside the testbed output
  tree;
- use ``flow`` testbeds when the varied axis is solver settings, flow
  parameters, forcing choices, or boundary-condition alternatives;
- keep future transport subjects inside the same testbed contract instead of
  creating a new workflow name for each method family.

Output Files
------------

A testbed writes:

- ``testbed_plan.json``: planned variants and generated child configs;
- ``testbed_cases.csv``: one row per variant with status and artifacts;
- ``testbed_metrics.csv``: configured metrics, or flattened numeric summary
  values when no metrics are declared;
- ``testbed_manifest.json``: machine-readable run manifest;
- ``testbed_report.md``: compact human-readable summary.

.. figure:: /_static/workflows/testbed/testbed_outputs.svg
   :alt: Testbed evidence output tree
   :align: center

   A testbed output folder is designed to be read as evidence: generated
   child configs first, then status, metrics, manifest, and report.

Reading The Evidence
--------------------

Use this order when reviewing a testbed run:

1. Open ``_generated_configs/`` to verify what each child actually received
   after base-config loading and overlay merging.
2. Read ``testbed_cases.csv`` to check which variants were planned, skipped,
   completed, or failed.
3. Read ``testbed_metrics.csv`` to compare the declared indicators across
   variants.
4. Read ``testbed_manifest.json`` when another tool needs the full
   machine-readable contract.
5. Read ``testbed_report.md`` for the compact human summary.

This order matters because metrics only make sense after confirming that the
generated child configs isolate the intended method axis.

Dry Planning
------------

Set ``execute = false`` to materialize the child configs without running them:

.. code-block:: toml

   [testbed]
   id = "mesh_resolution_plan"
   execute = false

This is useful when checking that overlays really isolate the intended method
axis before spending runtime on the variants.

Vocabulary
----------

The canonical terms are:

- ``testbed``: reproducible evidence layer;
- ``subject``: method domain under test, currently ``mesh`` or ``flow``;
- ``axis``: dimension varied by a variant, such as ``resolution`` or
  ``constraints``;
- ``variant``: one concrete child case;
- ``runner``: child launcher used to execute a variant;
- ``metric``: value extracted from the child summary.

Current Limits
--------------

The current implementation deliberately supports only:

- ``subject = "mesh"`` with ``runner.type = "mesh_catchment"``;
- ``subject = "flow"`` with ``runner.type = "simulation"``;
- sequential execution.

This is intentional. The workflow establishes the orchestration contract while
keeping comparison and future transport runners as separate extensions.

Implementation Notes
--------------------

The code is intentionally split into two small modules:

- ``hydromodpy.analysis.testbed.config`` validates the TOML contract, supported
  subject/runner pairs, variants, metrics, and path resolution;
- ``hydromodpy.analysis.testbed.runtime`` materializes child TOMLs, delegates
  execution, extracts metrics, and writes evidence files.

Adding a new subject should extend that contract rather than special-case the
runner in user configuration. In practice, a new subject needs:

- a subject name and allowed runner pair;
- a mapping from runner to generated child workflow;
- a runner branch in the launcher;
- tests for dry planning, execution, and metric extraction;
- a small documented example.

The testbed layer should remain a thin evidence layer. Solver-specific logic
belongs in child runners or result stores; the testbed can consume their
summaries, but should not duplicate their physics.
