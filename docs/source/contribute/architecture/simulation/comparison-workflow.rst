Comparison workflow architecture
================================

This page documents the contract of ``[workflow].mode = "comparison"``. The goal is
to compare several HydroModPy simulations without adding logic to the simulation
workflow itself. Its keys are in :doc:`/reference/parameters/analysis/comparison`.

Positioning
-----------

- The comparison workflow is an external layer. The code is in
  ``hydromodpy/analysis/comparison/``.
- Each candidate is a real HydroModPy simulation, launched through ``hmp run`` in a
  subprocess.
- The layer generates child TOML files, runs the simulations, reads the persisted
  results, then produces the audit, the metrics, the exports and the figures.
- The ``simulation`` core never shares an in-memory cache, a Python mesh or a forcing
  object with the comparison layer.

This split accepts a recompute or reload cost in exchange for a clean boundary:
simulations stay self-contained and the comparison stays post hoc.

Input files
-----------

The usual setup has two TOML levels: a comparison file with
``[workflow].mode = "comparison"``, and a base simulation file named by
``base_simulation_config``. The comparison file declares what to compare:

.. code-block:: toml

   # not checked: check_page loads a block on top of a simulation file, and a
   # comparison file is read by the comparison launcher, not as a simulation
   [workflow]
   mode = "comparison"

   [comparison]
   comparison_id = "dupuit_mf6_vs_bouss"
   base_simulation_config = "base_dupuit_shared_mesh.toml"
   output_root = "outputs/dupuit_mf6_vs_bouss"
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

The section is ``[comparison]``, at the root of the file. The launcher reads it from
the raw TOML, with its ``base_config`` chain: ``dispatch.py`` requires
``[comparison]`` with ``[[comparison.simulation]]``. The same model is also declared
as the optional ``[analysis.comparison]`` block of ``HydroModPyConfig``. The model is
``ComparisonSection`` in ``hydromodpy/analysis/comparison/experiment_config.py``, and
its keys are in the generated :doc:`TOML reference </reference/parameters/index>`.

The launcher writes one child TOML per simulation:

.. code-block:: text

   <output_root>/_generated_configs/<simulation_id>.toml

A child is self-contained: relative paths of the base file are resolved before it is
written, so a change of output folder cannot shift the meaning of a path.

Allowed overlays
----------------

The physics of the case must not drift by accident, so a child may overlay only some
sections of the base file. The lists are in
``hydromodpy/analysis/comparison/child_materialization.py``:

- top-level sections: ``simulation``, ``workspace``, ``solver``, ``mesh_catchment``,
  ``mesh_input``, ``modflow6``, ``modflownwt``, ``display``, ``flow``, ``calibration``
  and ``workflow``;
- under ``simulation``: ``name``, ``tags``, ``description``, ``if_exists``,
  ``process`` and ``results``;
- under ``flow``: ``bc``, ``ic``, ``param``, ``runtime_backend`` and the Boussinesq
  surface-interaction and variational-inequality options.

Two keys put the shared case in one place. ``comparison.base_simulation_overlay`` is
applied to the base file for every child, and is the place for what must be identical
(outlet, recharge forcing, mesh settings, data paths). ``overlay`` on a
``[[comparison.simulation]]`` entry is merged after it, for what differs between
children. A section that is not in the lists is refused.

Guard rails
-----------

``ComparisonSection`` and ``SimulationComparisonConfig.from_toml`` refuse an ambiguous
setup before any simulation starts:

- ``base_simulation_config`` must exist, and is required when a child is generated;
- ``comparison.simulation`` ids are unique identifiers, and at least one is enabled;
- ``reference_simulation``, when present, is an enabled simulation;
- ``observable`` names are unique, and ``observable.simulations`` names only enabled
  simulations;
- ``comparison.execution.max_parallel_runs`` is 1: children run one after the other.

These checks live in the comparison layer. They add no constraint on the simulation
workflow.

Execution cycle
---------------

1. Load the comparison TOML and the base simulation TOML.
2. Generate the child TOMLs with their overlays.
3. Run each child through ``hmp run <child.toml>`` (``comparison.execution.backend =
   "subprocess_hmp_run"``).
4. Resolve the resulting ``sim_id`` and read the catalog.
5. Extract the declared observables.
6. Compare them with the reference simulation.
7. Write the exports and the figures.
8. Audit the persisted metadata after the fact (``comparison.audit``).

Outputs
-------

A comparison writes, among others:

- ``comparison_manifest.json``, the index of the outputs, and ``comparison_report.md``;
- ``comparison_audit.json`` and ``comparison_audit.md``, the consistency check;
- ``observables.csv``, ``comparison_metrics.csv`` (bias, MAE, RMSE, maximum error) and
  ``comparison_differences.csv``;
- ``hydrographic_network_metrics.csv``, the length-based comparison of the ``reference``
  and ``generated`` networks (coverage, precision, F1, Hausdorff distance, with a
  default tolerance), written when both are persisted;
- ``simulated_active_network_metrics.csv``, ``..._overlap_metrics.csv`` and
  ``..._distance_metrics.csv``, the occupancy, overlap and distance of the simulated
  active network (:doc:`../spatial_support/hydrographic-network-simulated-active-inventory`);
- for each of these, a ``..._skipped.json`` that says why a simulation was left out,
  such as a missing network role or a missing ``accumulation_flux`` field;
- ``comparison_figures/``: ``case_configuration.png`` (the case under test, with the
  support, the boundary conditions, the observation points and the recharge chronicle),
  then maps, differences, triptychs, budgets and computation time.

Read ``case_configuration.png`` first, then the ``*triptych*.png`` figures: reference
field, candidate field, candidate minus reference.

The canonical names of the hydrographic networks, and the historical file names that
are not aliases, are in :doc:`../mental-model`. If a run holds only one of the two
networks, ``hydrographic_network_metrics.csv`` is not written for it, and the ``Run``
methods ``available_hydrographic_network_roles()`` and ``has_hydrographic_network()``
tell which one is missing.

Disk cleanup
------------

Child simulations persist their own outputs like any run, and the comparison layer
never deletes them. It can drop only the generated TOMLs:

.. code-block:: toml

   # not checked: comparison files are read by the comparison launcher
   [comparison.execution]
   keep_generated_configs = false

They are kept by default, to ease debugging and reproduction.

Limits
------

- Children run one at a time.
- The audit reads persisted metadata, not shared in-memory objects.
- Comparisons across different meshes go through observables and fine rasters
  (``comparison.fine_raster``), not a general cell-to-cell mapping.

Where to look
-------------

``examples/projects/09_comparison_workflow/`` holds working comparison files and a
helper script, ``run_comparison_example.py``. The folder is not one of the maintained
examples: use it to read a complete file, and expect to adapt it.
