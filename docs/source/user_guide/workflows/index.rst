Workflow Reference
==================

HydroModPy workflows answer the question:
"What user-facing operation should this TOML run?"

They are selected by the mandatory top-level field:

.. code-block:: toml

   [workflow]
   mode = "simulation"

The same workflow can be driven from different usage modes. For example, a
``simulation`` can be launched from the CLI, from Python, or from a notebook.
The workflow describes the operation. The usage mode describes the entry
interface.

.. list-table::
   :header-rows: 1
   :widths: 14 30 28 28

   * - Workflow
     - Use it to
     - Main TOML sections
     - Detailed page
   * - ``overview``
     - Inspect a watershed and available data before solving.
     - ``[workspace]``, ``[geographic]``, ``[domain]``, ``[data]``,
       ``[overview]``
     - :doc:`overview`
   * - ``simulation``
     - Run one forward model and persist one run.
     - ``[simulation]``, ``[[simulation.process]]``, ``[flow]``,
       ``[solver]``, backend sections
     - :doc:`simulation`
   * - ``testbed``
     - Expand controlled method variants and collect evidence, including mesh
       resolution or constraint studies.
     - ``[testbed]``, ``[testbed.runner]``, ``[[testbed.variant]]``,
       child-runner sections such as ``[mesh_catchment]`` or
       ``[simulation]``
     - :doc:`testbed`
   * - ``calibration``
     - Estimate parameters by running repeated candidate simulations.
     - ``[calibration]``, ``[calibration.parameters.*]``, simulation
       sections
     - :doc:`calibration`
   * - ``batch``
     - Expand recipes over many sites or clusters.
     - ``[regional_lab]``, ``[regional_lab.catalog]``,
       ``[[regional_lab.recipe]]``
     - :doc:`batch`
   * - ``comparison``
     - Generate several child simulations from one shared base case and
       compare observables.
     - ``[comparison]``, ``[[comparison.simulation]]``,
       ``[[comparison.observable]]``
     - :doc:`comparison`

Workflow flowchart
------------------

Click any node to jump to its detailed page.

.. mermaid::

   flowchart TD
       config[hmp run config.toml] --> dispatch{workflow = ...}
       dispatch -->|overview| ov[Overview]
       dispatch -->|simulation| sim[Simulation]
       dispatch -->|testbed| tb[Testbed]
       dispatch -->|calibration| cal[Calibration]
       dispatch -->|batch| bat[Batch]
       dispatch -->|comparison| cmp[Comparison]
       click ov "overview.html" "Open overview workflow"
       click sim "simulation.html" "Open simulation workflow"
       click tb "testbed.html" "Open testbed workflow"
       click cal "calibration.html" "Open calibration workflow"
       click bat "batch.html" "Open batch workflow"
       click cmp "comparison.html" "Open comparison workflow"

Dispatch Model
--------------

The CLI dispatch is intentionally simple:

.. code-block:: text

   hmp run <config.toml>
        |
        +-- read [workflow].mode = "..."
        |
        +-- dispatch to one launcher
              simulation  -> Project(config).run()
              overview    -> DataOverviewLauncher
              testbed     -> TestbedLauncher
              calibration -> calibration ask/tell loop
              batch       -> RegionalLabLauncher
              comparison  -> SimulationComparisonLauncher

This split avoids mixing three concepts:

- a workflow is the operation requested by the user;
- a solver is one numerical backend used by some workflows;
- a usage mode is the interface used to drive the operation.

Choosing A Workflow
-------------------

Use ``overview`` when the model domain itself is still uncertain. It is the
best workflow for data availability, watershed identity cards, observation
inventories, and pre-solver QA.

Use ``simulation`` when the physical setup is clear and you want one forward
run with persisted model outputs.

Use ``testbed`` when the question is about robustness across method variants,
for example mesh resolution, mesh constraints, hydraulic-parameter sensitivity,
or future transport method axes. Mesh work is now documented through
``testbed`` with ``subject = "mesh"`` and ``runner.type = "mesh_catchment"``;
the mesh runner remains an implementation detail rather than a separate user
guide workflow.

Use ``calibration`` when parameters are uncertain and the goal is to optimize
or sample them against observations or synthetic targets.

Use ``batch`` when the same recipe must be expanded across many catchments,
clusters, or regional sites.

Use ``comparison`` when several child simulations must stay tied to one shared
physical base case so that solver, mesh, or option differences remain
controlled.

.. toctree::
   :maxdepth: 2

   overview
   simulation
   testbed
   calibration
   batch
   comparison
