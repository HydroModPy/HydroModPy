Comparison Workflow
===================

``[workflow].mode = "comparison"`` creates several child simulations from one shared
base configuration and compares declared observables.

Use it when the question is:
"If the physical case stays fixed, how do solver, mesh, or option choices
change the outputs?"

Functional Role
---------------

The comparison workflow is an external orchestration layer. It does not ask you
to duplicate whole TOML files manually. Instead it:

.. code-block:: text

   base simulation TOML
       -> child simulation overlays
       -> generated child TOMLs
       -> child hmp run executions
       -> equivalence audit
       -> observable extraction
       -> metrics and differences
       -> comparison figures and report

It is appropriate for:

- MODFLOW 6 versus MODFLOW-NWT comparison;
- MODFLOW 6 versus Boussinesq comparison;
- structured versus irregular mesh experiments;
- sensitivity to numerical options while keeping the base case stable;
- producing stable comparison pages for documentation and teaching.

Typical Command
---------------

.. code-block:: bash

   hmp run examples/projects/09_comparison_workflow/compare_dupuit_mf6_bouss.toml

Reference examples:

- ``examples/projects/09_comparison_workflow/compare_dupuit_mf6_bouss.toml``
- ``examples/projects/09_comparison_workflow/compare_10km2_natural_mesh_mf6_bouss.toml``
- ``examples/projects/09_comparison_workflow/compare_vire_natural_mf6_nwt.toml``

Representative Results
----------------------

.. figure:: /_static/workflows/comparison/dupuit_case_configuration.png
   :alt: Comparison workflow configuration figure
   :width: 100%

   The configuration panel shows the shared physical case before any
   difference metric is interpreted as a solver effect.

.. figure:: /_static/workflows/comparison/dupuit_head_triptych.png
   :alt: Comparison workflow head-map triptych
   :width: 100%

   The triptych is the core comparison visual: reference, candidate, and
   difference are kept in one read order instead of split across separate
   files.

Minimal Shape
-------------

.. code-block:: toml

   [workflow]
   mode = "comparison"

   [comparison]
   comparison_id = "dupuit_mf6_vs_bouss"
   base_simulation_config = "base_dupuit_shared_mesh.toml"
   output_root = "outputs/dupuit_mf6_vs_bouss"
   reference_simulation = "mf6_ref"
   continue_on_error = false

   [comparison.execution]
   backend = "subprocess_hmp_run"
   max_parallel_runs = 1
   run_simulations = true
   keep_generated_configs = true

   [[comparison.simulation]]
   id = "mf6_ref"
   label = "MODFLOW 6 reference"
   solver = "modflow6"
   mesh_mode = "mesh_input"

   [[comparison.simulation]]
   id = "bouss_candidate"
   label = "Boussinesq candidate"
   solver = "boussinesq"
   mesh_mode = "mesh_input"

   [[comparison.observable]]
   name = "head_map_last"
   variable = "watertable_elevation"
   support = "map"
   time = "last"
   unit = "m"

Important Parameters
--------------------

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Section / field
     - Role
     - Practical guidance
   * - ``workflow``
     - Selects the comparison launcher.
     - Must be ``"comparison"``.
   * - ``[comparison].comparison_id``
     - Names the experiment.
     - Used in reports, output paths, generated child names, and metrics.
   * - ``base_simulation_config``
     - Shared physical base case.
     - Keep all common geometry, forcing, time, and physical assumptions here.
   * - ``output_root``
     - Stores comparison artifacts.
     - Use a dedicated folder, not a child simulation folder.
   * - ``reference_simulation``
     - Defines the baseline for differences.
     - Pick the most trusted or conventional variant.
   * - ``continue_on_error``
     - Controls failure policy.
     - Keep ``false`` for strict studies; use ``true`` for exploratory grids.
   * - ``[comparison.execution]``
     - Controls child execution.
     - ``subprocess_hmp_run`` keeps child runs close to normal CLI behavior.
   * - ``keep_generated_configs``
     - Keeps generated child TOMLs.
     - Keep enabled while debugging overlays and audit mismatches.
   * - ``[comparison.audit]``
     - Checks same-case consistency.
     - Use ``strict_same_case`` to catch accidental physical differences.
   * - ``[[comparison.simulation]]``
     - Declares one child variant.
     - Use overlays for solver-specific changes only.
   * - ``[[comparison.observable]]``
     - Declares what to compare.
     - Prefer a small set of maps, points, and budgets before expanding.
   * - ``[comparison.fine_raster]``
     - Optional common rasterization for map comparisons.
     - Use it when comparing maps from different supports.

Overlay Example
---------------

Each child simulation can override a small part of the base TOML:

.. code-block:: toml

   [comparison.simulation.overlay.modflow6.runtime]
   mf6_ims_complexity = "SIMPLE"
   mf_verbose = false

   [comparison.simulation.overlay.modflow6.process_specific]
   vka = 1.0

Keep overlays narrow. If two child simulations differ in geometry, forcing,
time window, and solver at once, the comparison will be hard to interpret.

Observable Example
------------------

.. code-block:: toml

   [[comparison.observable]]
   name = "head_middle_last"
   variable = "watertable_elevation"
   support = "point"
   cell_index = 88
   time = "last"
   unit = "m"

Point observables are cheap and clear. Map observables are richer but usually
need careful support alignment, especially when meshes differ.

Outputs To Inspect
------------------

Read comparison outputs in this order:

1. ``comparison_manifest.json``;
2. generated child configs, if kept;
3. audit JSON or Markdown report;
4. ``observables.csv``;
5. ``comparison_metrics.csv`` and ``comparison_differences.csv``;
6. comparison figures;
7. child run outputs only if a metric needs explanation.

Next Pages
----------

- :doc:`../concepts/comparison-workflow`
- :doc:`../concepts/comparison-output-reading-order`
- :doc:`../comparison`
- :doc:`../../capability_gallery/simulation_comparison`
- :doc:`../../theory/solvers/modflow6-vs-modflownwt-scientific-comparison`
