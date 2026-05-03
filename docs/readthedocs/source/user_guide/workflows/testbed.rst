Testbed Workflow
================

Use this workflow when the goal is not to run one model, but to organize a
controlled method testbed.

A testbed expands variants, delegates each variant to a child runner, then
collects evidence artifacts such as generated configs, metrics, manifests, and
reports.

The first supported subjects are:

- ``mesh`` through the ``mesh_catchment`` runner;
- ``flow`` through the ``simulation`` runner.

This keeps the testbed detached from simulation internals. A mesh testbed can
evaluate discretization choices without running a flow solver. A flow testbed
delegates to ordinary generated ``workflow = "simulation"`` children, but the
testbed itself only expands variants and gathers evidence.

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

Each generated child is an ordinary ``workflow = "mesh"`` TOML. The testbed
does not call the simulation planner and does not persist solver runs.

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

Runnable Example Files
----------------------

The repository contains two starter testbeds:

- ``examples/projects/10_testbed_workflow/mesh_resolution_testbed.toml``;
- ``examples/projects/10_testbed_workflow/flow_k_sensitivity_testbed.toml``.

Both use ``execute = false`` so they first materialize generated child configs
without spending solver time. Change that flag to ``true`` when the matrix has
the intended variants.

How It Differs From Mesh
------------------------

``workflow = "mesh"`` answers:
"Build this one reusable mesh artifact."

``workflow = "testbed"`` answers:
"Run this controlled set of method variants and collect evidence."

For mesh work, this means:

- ``mesh`` remains the simple mono-case entry point;
- ``testbed`` becomes the place for resolution ladders, constraint sensitivity,
  conformity studies, and robustness checks;
- ``flow`` testbeds can vary solver settings, flow parameters, forcing choices,
  or boundary-condition alternatives by producing ordinary simulation children;
- the same testbed contract can later support transport subjects without
  turning those subjects into special workflow names.

Output Files
------------

A testbed writes:

- ``testbed_plan.json``: planned variants and generated child configs;
- ``testbed_cases.csv``: one row per variant with status and artifacts;
- ``testbed_metrics.csv``: configured metrics, or flattened numeric summary
  values when no metrics are declared;
- ``testbed_manifest.json``: machine-readable run manifest;
- ``testbed_report.md``: compact human-readable summary.

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
