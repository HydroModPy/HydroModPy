Comparison Workflow Architecture
================================

This page documents the contract of the ``[workflow].mode = "comparison"``
layer. The goal is to compare several HydroModPy simulations without
adding logic to the ``simulation`` workflow itself.

For the user-facing entry point, see
:doc:`../../user_guide/workflows/comparison`. For the operational walkthrough, see
:doc:`../../user_guide/concepts/comparison-workflow`.

Positioning
-----------

- The comparison workflow is an external layer.
- Each candidate is still a real HydroModPy simulation launched through
  ``hmp run``.
- The comparison layer generates child TOML files, runs the simulations,
  reads the persisted results, then produces audit, metrics, exports,
  and figures.
- The ``simulation`` core never shares an in-memory cache, a Python
  mesh, or forcing objects with the comparison layer.

This split accepts a recompute or reload cost in exchange for a clean
boundary: simulations remain self-contained and the comparison stays
post-hoc.

Input files
-----------

The recommended setup uses two TOML levels:

- a comparison TOML, with ``[workflow].mode = "comparison"``;
- a base simulation TOML, referenced by
  ``[comparison].base_simulation_config``.

The comparison TOML declares the simulations to compare:

.. code-block:: toml

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

The layer then writes one child TOML per simulation under:

.. code-block:: text

   <output_root>/_generated_configs/<simulation_id>.toml

These child TOMLs are self-contained: relative paths from the base TOML
are resolved before writing, so changing the output folder cannot shift
the meaning of a path.

Allowed overlays
----------------

V1 intentionally limits overlays so that the physics of the case
cannot drift by accident. Allowed sections:

- ``simulation``: name, run id, collision policy, processes;
- ``solver``: generic solver parameters;
- ``modflow6``: MODFLOW 6 options;
- ``modflownwt``: MODFLOW-NWT options;
- ``flow``: ``runtime_backend`` and ``param`` for parameter sweeps;
- ``display``: graphical output.

Physical sections such as domain, recharge, hydraulic properties, and
boundary conditions cannot change between simulations in V1. If the
physics must change, write a different base simulation TOML or extend
the contract explicitly.

``flow.param`` is allowed for explicit sensitivity comparisons (for
example a hydraulic-conductivity sweep). All other physical sections
remain forbidden by default.

V1 guard rails
--------------

The comparison TOML loader rejects ambiguous setups before launching
any simulation:

- ``base_simulation_config`` must exist;
- ``comparison_id`` must not contain a path separator;
- each ``comparison.simulation.id`` must be unique and filename-safe;
- at least one simulation must be enabled;
- ``reference_simulation``, when present, must point to an enabled
  simulation;
- ``observable.simulations``, when present, can only reference enabled
  simulations.

These checks live entirely in the comparison layer. They add no
constraint on the ``simulation`` workflow.

Execution cycle
---------------

1. Load the comparison TOML.
2. Load the base simulation TOML.
3. Generate child TOMLs with the solver overlays.
4. Run each child via the public entry point:

.. code-block:: bash

   python -m hydromodpy run <child.toml>

5. Resolve the resulting ``sim_id`` and read the result catalog.
6. Extract the declared observables.
7. Compare the observables against the reference simulation.
8. Write exports and figures.
9. Audit the persisted metadata after the fact.

Outputs
-------

A comparison run produces, among others:

- ``comparison_manifest.json``: full output index;
- ``comparison_report.md``: readable report;
- ``comparison_audit.json`` and ``comparison_audit.md``: consistency
  check;
- ``observables.csv``: extracted values;
- ``comparison_metrics.csv``: bias, MAE, RMSE, max error;
- ``comparison_differences.csv``: element-wise differences;
- ``hydrographic_network_metrics.csv``: geometric ``reference`` vs
  ``generated`` comparison when both canonical hydrographic networks
  are persisted;
- ``hydrographic_network_metrics_skipped.json``: diagnostic for
  simulations skipped because a required hydrographic role is missing;
- ``simulated_active_network_metrics.csv``: occupancy metrics of the
  simulated active network, computed from ``accumulation_flux`` when
  the field exists;
- ``simulated_active_network_metrics_skipped.json``: diagnostic for
  simulations skipped because the simulated field is missing;
- ``simulated_active_network_overlap_metrics.csv``: cell-by-cell
  comparison between the simulated active network and the vector
  ``reference`` role when both supports exist;
- ``simulated_active_network_overlap_metrics_skipped.json``:
  diagnostic for that observation-vs-simulation comparison;
- ``simulated_active_network_distance_metrics.csv``: planar
  bidirectional distances between simulated active cell centroids and
  the ``reference`` vector role;
- ``simulated_active_network_distance_metrics_skipped.json``:
  diagnostic for that distance comparison;
- ``comparison_figures/case_configuration.png``: orientation figure for
  the compared case, with spatial support, detected boundary
  conditions, observable points, and the recharge chronicle when
  available;
- ``comparison_figures/*.png``: maps, differences, triptychs, budgets,
  computation time.

Default ``hydrographic_network_metrics.csv`` uses a 50 m tolerance and
exports:

- total reference and candidate lengths;
- missing and extra lengths;
- coverage / precision / F1 ratios on length;
- Hausdorff distance.

Canonical names used by the code:

- ``hydrographic_network_reference`` for the network loaded from
  ``data.hydrography``;
- ``hydrographic_network_generated`` for the network derived from the
  DEM through ``geographic.river_network``.

The feature-store contract uses those canonical names only. Historical
filenames may still exist on disk, but they are not feature aliases:

- ``river_network.shp`` for the generated network vector file;
- ``river_network_summary.json`` for generated-network metrics;
- ``streams.shp`` for the reference vector filename emitted by the
  manager;
- ``hydrography_streams`` for the reference forcing-raster name.

If a run only exposes one of the two canonical networks:

- ``hydrographic_network_metrics.csv`` is not produced for that run;
- hydrographic comparison figures should not be requested;
- the ``Run`` API exposes ``available_hydrographic_network_roles()``
  and ``has_hydrographic_network(...)`` to detect the case.

The canonical role ``simulated_active`` is not yet persisted as a
vector feature. The ``Run`` API does expose
``cell_field_active_mask()``,
``cell_field_active_metrics()``,
``cell_field_network_overlap_metrics()`` (cell-by-cell against
``reference``), and ``cell_field_network_distance_metrics()``.
The primary target is ``reference``, because the comparison is between
simulation and observation. ``generated`` remains useful as a
secondary diagnostic against the DEM-derived network, but it is not an
observation. When the run carries a usable mesh, the
``simulated_active_network`` figure renders that view, and
``simulated_active_network_reference_overlay`` overlays it with the
observed ``reference`` network.

Terminology to respect for these views:

- without an explicit ``mode``, ``flow_regime = "steady"`` uses the
  steady-state active field, while ``flow_regime = "transient"`` uses
  ``persistent`` for compatibility;
- ``persistent`` means active during at least a declared fraction of
  transient timesteps;
- ``always_active`` means active at every timestep of the analysed
  transient window;
- ``steady`` is the concept to use for a permanent reference state in
  the solver sense;
- ``perennial`` remains a legacy alias of ``always_active`` in the
  computed API;
- a simulated steady network should ideally come from a representative
  ``flow_regime = "steady"`` run, then be compared to ``reference``;
- the contract leaves room for several named simulated networks
  (``steady``, ``transient_persistent_50``, ``event_snapshot``).

Read ``case_configuration.png`` first to understand the case under
test, then the ``*triptych*.png`` figures to validate the fields:
reference field, candidate field, then candidate-minus-reference
difference.

Disk cleanup
------------

Child simulations persist their own outputs like any HydroModPy run.
The comparison layer can only clean up the generated TOMLs:

.. code-block:: toml

   [comparison.execution]
   keep_generated_configs = false

By default they are kept to ease debugging and reproducibility. Heavy
results stay in the simulations' own run folders; the comparison layer
must not delete simulation outputs.

Available examples
------------------

The folder ``examples/projects/09_comparison_workflow/`` provides:

- ``compare_dupuit_mf6_bouss.toml``: synthetic case, MODFLOW 6 vs
  Boussinesq, shared triangular mesh;
- ``compare_vire_natural_mf6_nwt.toml``: natural Vire basin, MODFLOW 6
  vs MODFLOW-NWT, structured 40 x 40 grid;
- ``compare_10km2_natural_mesh_mf6_bouss.toml``: pre-computed natural
  10 km2 mesh, simplified steady physics, MODFLOW 6 vs Boussinesq on
  the same triangular mesh;
- ``compare_10km2_natural_mesh_recharge_mf6_bouss.toml``: same natural
  10 km2 mesh with uniform low synthetic recharge;
- ``compare_10km2_natural_mesh_transient_pulse_mf6_bouss.toml``: same
  natural 10 km2 mesh, daily impulse recharge with Sy/Ss storage;
- ``compare_nancon_transient_seasonal_mf6_bouss.toml``: Nancon basin,
  support regenerated from the same base TOML, weekly synthetic
  recharge with seasonality and wet/dry episodes.

Run them through the helper script:

.. code-block:: bash

   python examples/projects/09_comparison_workflow/run_comparison_example.py --case synthetic --show
   python examples/projects/09_comparison_workflow/run_comparison_example.py --case all --show

Current limitations
-------------------

- Sequential execution only: ``max_parallel_runs = 1``.
- Strict audit based on persisted metadata, not on shared in-memory
  objects.
- Comparisons across different meshes go through observables and fine
  rasters, not a general cell-to-cell mapping.
- The reduced natural Boussinesq case keeps a natural mesh but uses an
  analytical topography and lateral fixed heads. The recharge case
  adds a synthetic diffuse forcing but not yet a complete basin
  physics with drainage and hydrographic network. The transient case
  adds Sy/Ss and a recharge pulse but stays short and controlled.
- ``nancon-seasonal`` raises the difficulty: natural basin topography,
  surface drainage, support regenerated per run, and non-trivial
  transient recharge. It serves as a robustness test rather than an
  analytical benchmark.

Next development direction
--------------------------

The natural reduced MODFLOW 6 vs Boussinesq case can be extended
toward basin-scale physics:

- compare boundary fluxes and budgets explicitly when both solvers
  expose them in compatible form;
- add a multi-month or multi-year seasonal simulation on the same
  mesh;
- test a full natural basin case with drainage and hydrographic
  network;
- document convergence criteria and expected differences per case
  family.

This work should stay in
``examples/projects/09_comparison_workflow/`` or
``validation_cases/`` and must not modify ``simulation``.

See also
--------

- :doc:`../../user_guide/workflows/comparison` for the user-facing hub.
- :doc:`../../user_guide/concepts/comparison-workflow` for the
  operational walkthrough.
- :doc:`../../user_guide/concepts/comparison-output-reading-order` for
  the output reading order.
- :doc:`index` for the simulation architecture root.
