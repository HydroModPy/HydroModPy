Boussinesq Formulation Comparison
=================================

This page is the Boussinesq-local entry point for comparing alternative
``flow/boussinesq`` formulations.

The comparison outputs should still be produced by the standard comparison
workflow. What changes here is the reading location: Boussinesq formulation
comparisons belong close to the Boussinesq equations, methods, and surface
closures, not only in the transversal capability gallery.

What Is Being Compared
----------------------

The current in-house Boussinesq backend has two distinct modelling axes:

.. list-table::
   :header-rows: 1
   :widths: 24 32 44

   * - Axis
     - Choices
     - Interpretation
   * - Surface closure
     - ``regularized_partition`` or ``complementarity``
     - Changes how near-surface release and saturation excess are represented.
   * - Unknown layout
     - ``head_only`` or ``head_plus_qex_qdry``
     - Changes whether saturation excess is reconstructed from head or solved
       together with the lower drying obstacle as explicit cellwise unknowns.
   * - Runtime backend
     - ``local``, ``scipy``, ``scipy_sparse``, ``petsc``
     - Changes nonlinear and linear algebra execution. This is not by itself a
       different hydrological formulation.
   * - Flow regime
     - ``steady`` or ``transient``
     - Adds or removes storage and time-step history.
   * - Support
     - Shared triangular mesh, different mesh, or structured MODFLOW support
     - Controls whether differences can be interpreted as formulation effects
       or as mixed formulation/support effects.

The cleanest formulation comparison keeps the runtime backend and support
fixed as much as possible. For example, comparing:

- ``petsc`` + ``regularized_partition``;
- ``petsc`` + ``complementarity``;

is a cleaner surface-closure comparison than comparing
``scipy_sparse`` + ``regularized_partition`` against
``petsc`` + ``complementarity``, because the latter changes the runtime engine
and the surface closure at the same time.

Recommended Comparison Questions
--------------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Question
     - Recommended variants
     - How to read the result
   * - Does the surface closure matter?
     - Same mesh, same forcing, ``petsc`` partition versus ``petsc``
       complementarity.
     - Read head maps together with saturation-excess and budget diagnostics.
   * - Does the sparse backend change the head-only result?
     - ``scipy_sparse`` versus ``petsc`` with
       ``regularized_partition``.
     - Runtime sensitivity, not a hydrological formulation comparison.
   * - How far is Boussinesq from a MODFLOW representation?
     - MODFLOW 6 versus Boussinesq on a shared support when possible.
     - Solver-family comparison; document vertical representation, boundary
       semantics, property transfer, and surface closure explicitly.
   * - Does a validation case still match its analytical reference?
     - One solver variant against the committed validation reference.
     - Validation evidence, not solver-to-solver comparison.

Implementation Pattern
----------------------

Use the external comparison workflow as the producer:

.. code-block:: toml

   workflow = "comparison"

   [comparison]
   comparison_id = "boussinesq_surface_closure_comparison"
   base_simulation_config = "base_boussinesq_shared_case.toml"
   output_root = "outputs/boussinesq_surface_closure_comparison"
   reference_simulation = "partition"

   [comparison.execution]
   backend = "subprocess_hmp_run"
   run_simulations = true
   keep_generated_configs = true

   [comparison.audit]
   mode = "strict_same_case"
   on_mismatch = "warn"

   [[comparison.simulation]]
   id = "partition"
   label = "Head-only regularized partition"
   solver = "boussinesq"
   mesh_mode = "mesh_input"

   [comparison.simulation.overlay.flow]
   runtime_backend = "petsc"
   surface_interaction_model = "regularized_partition"

   [[comparison.simulation]]
   id = "complementarity"
   label = "Mixed complementarity"
   solver = "boussinesq"
   mesh_mode = "mesh_input"

   [comparison.simulation.overlay.flow]
   runtime_backend = "petsc"
   surface_interaction_model = "complementarity"

   [[comparison.observable]]
   name = "head_map_last"
   variable = "watertable_elevation"
   support = "map"
   time = "last"
   unit = "m"

   [[comparison.observable]]
   name = "surface_excess_last"
   variable = "surface_excess_rate"
   support = "map"
   time = "last"
   unit = "m/s"

This keeps the implementation centralized:

- child simulations are normal ``hmp run`` simulations;
- generated child TOMLs are kept for auditability;
- observables, metrics, reports, budgets, and figures are produced by one
  workflow instead of custom plotting scripts;
- the Boussinesq documentation only reads committed outputs and explains how
  to interpret them.

Where To Store The Evidence
---------------------------

For a committed Boussinesq-local comparison page, use this layout:

.. code-block:: text

   examples/projects/09_comparison_workflow/
     compare_boussinesq_surface_closures.toml
     base_boussinesq_surface_closure_case.toml

   docs/source/_static/solvers/boussinesq/formulation_comparison/
     case_configuration.png
     head_triptych.png
     surface_excess_triptych.png
     comparison_metrics.json
     comparison_manifest.json

   docs/source/scientific/solvers/flow/boussinesq/
     formulation-comparison.rst

The important rule is that the page should not contain one-off code. If a
figure or metric is needed repeatedly, it belongs in the comparison workflow or
in a small gallery adapter, not in a bespoke documentation script.

Existing Transient Evidence
---------------------------

The closest committed example is the recharge-ramp surface-interaction
comparison. It is not a pure Boussinesq formulation comparison: it mixes
MODFLOW-family solvers and Boussinesq variants. It is still the best current
visual reference for the transient case where the surface closure controls
storage release, overflow, and total outflow.

.. figure:: /_static/capability_gallery/code_comparison/ramp_reference_k.png
   :alt: Recharge-ramp transient comparison across MODFLOW and Boussinesq variants
   :width: 100%

   Reference-conductivity transient ramp benchmark. The committed gallery
   version compares MODFLOW-NWT, MODFLOW 6, MODFLOW 6 on irregular triangles,
   the local Boussinesq partition route, PETSc partition, and PETSc
   complementarity.

Read this figure as mixed evidence:

- differences between the three Boussinesq curves can inform formulation and
  runtime sensitivity;
- differences between MODFLOW and Boussinesq curves also include vertical
  representation, support, boundary semantics, and budget-reconstruction
  effects;
- the page belongs in the cross-code gallery, but this Boussinesq-local page
  should point to it because it is where the scientific formulation question
  arises.

Reference Configuration
~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Item
     - Value
   * - Geometry
     - 400 m by 30 m synthetic strip aquifer.
   * - Topography
     - Linear 5 m rise from the east outlet to the west divide.
   * - Boundary conditions
     - West no-flow divide, east fixed head, top drainage / surface
       interaction.
   * - East fixed head
     - 5.0625 m.
   * - Transient forcing
     - Progressive recharge ramp, followed by dry recovery.
   * - Time step
     - 15 days.
   * - Storage
     - Specific yield 0.10.
   * - Conductivity scale
     - 0.2 times the baseline strip conductivity for the reference-K figure;
       1.6 times for the high-K companion gallery tab.
   * - Drainage conductance
     - 1e-4 m2/s.
   * - Reference-K methods
     - MODFLOW-NWT, MODFLOW 6, MODFLOW 6 on irregular triangles, Boussinesq
       local partition, Boussinesq PETSc partition, and Boussinesq PETSc
       complementarity.

Execution Times
~~~~~~~~~~~~~~~

The transient investigation tools write calculation times into
``execution_times.csv`` and into the richer ``summary_metrics.csv`` table. The
compact gallery JSON is now set up to preserve ``wall_time_seconds`` whenever
``execution_times.csv`` exists next to the source ``timeseries.csv``.

Use the timing values as run metadata, not as hydrological evidence. They
depend on the machine, Linux/WSL setup, PETSc build, executable availability,
and whether previous workspaces are still warm in the filesystem cache.

The richer diagnostic run that isolates the remembered MODFLOW-NWT and
Boussinesq PETSc variants is still an investigation script:

.. code-block:: bash

   python -m tools.investigate_linux_nwt_boussinesq_transient \
     --output-root out/linux_nwt_bouss_4m4m6m_local

It compares:

- ``modflownwt``: MODFLOW-NWT through the launcher path;
- ``petsc_partition``: Boussinesq PETSc with regularized partition;
- ``petsc``: Boussinesq PETSc with complementarity.

The run writes ``timeseries.csv``, ``summary_metrics.csv``,
``execution_times.csv``, ``head_point_timeseries.csv``, ``summary.md``, and a
``figures`` directory with head snapshots, head-point series, flux time
series, total-outflow overlay, complete flux budget, and execution-time
diagnostics. This is the right source to promote when the documentation needs
the full transient MODFLOW-NWT versus Boussinesq story.

Documentation Refresh Contract
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The figures embedded by this page are not regenerated by Sphinx alone. The
update chain is:

.. code-block:: bash

   python -m tools.investigate_surface_interaction_hillslope_transient \
     --output-root out/sih_tx_6cmp_linux_ramp_dirichlet_cell_20260416

   python tools/doc_gallery/generate_code_comparison_assets.py
   python -m tools.doc_gallery
   python -m sphinx -b html -j auto docs/source docs/build/html

The first command refreshes the source run under ``out``. The generator then
rebuilds the committed gallery PNG/JSON files under
``examples/projects/09_capability_gallery/code_comparison``. The doc-gallery
step mirrors those committed assets into
``docs/source/_static/capability_gallery/code_comparison`` and
refreshes the generated gallery pages. The final Sphinx build only renders the
documentation from those already-updated source files.

Promotion Rule
--------------

When this transient benchmark is promoted from investigation to documentation,
keep the same separation of concerns:

1. use the investigation script, or a small wrapper around it, as the producer
   of numerical outputs;
2. republish only stable summary assets under
   ``examples/projects/09_capability_gallery/code_comparison`` or under
   ``docs/source/_static/solvers/boussinesq``;
3. have the Boussinesq page read committed PNG/JSON artifacts only;
4. keep any pure ``workflow = "comparison"`` example separate from the
   MODFLOW-NWT bridge, because MODFLOW-NWT is a cross-code comparison rather
   than a Boussinesq-only formulation test.

Pure Boussinesq Starting Point
-------------------------------

For a Boussinesq-only transient comparison, the current validation case is:

.. code-block:: bash

   python -m validation_cases.numerical.transient.boussinesq_hillslope_recharge_pulse_overflow_1d.run_multi_solver_case \
     --solvers boussinesq petsc_partition petsc \
     --context-preset windows_surface_transient \
     --output-root out/boussinesq_hillslope_overflow_multi_local

This route compares the local head-only partition path, PETSc partition, and
PETSc complementarity without adding MODFLOW-family effects. It is therefore
better for a strict Boussinesq formulation page, while the MODFLOW-NWT bridge
is better for explaining how far the Boussinesq closures sit from a mature
external code. The same command writes an ``execution_times.csv`` file and an
``execution_times.png`` figure under its ``figures`` directory, so formulation
and runtime questions can be read from one run directory without adding a
separate timing script.

Current Comparison-Workflow Template
------------------------------------

The shipped comparison workflow also demonstrates the clean producer side with
a MODFLOW 6 versus Boussinesq case:

.. figure:: /_static/workflows/comparison/dupuit_head_triptych.png
   :alt: Dupuit MODFLOW 6 versus Boussinesq head-map triptych
   :width: 100%

   This is a solver-family comparison, not a Boussinesq formulation
   comparison. It is still useful as the reference pattern for producing
   stable comparison artifacts through ``workflow = "comparison"``.

Use it as a template for the mechanics, then narrow the variants to
Boussinesq-only surface closures when the goal is formulation choice. Use the
transient MODFLOW-NWT bridge when the goal is cross-code interpretation.

Reading Rules
-------------

Before interpreting differences as formulation effects, check:

- same mesh source and resolution;
- same top and bottom surfaces;
- same hydraulic conductivity and storage mapping;
- same recharge, wells, and imposed-head supports;
- same flow regime and time stepping;
- same runtime backend, unless the question is explicitly runtime sensitivity;
- explicit surface-interaction model for every child run.

If any of these differ, report the comparison as mixed. That does not make it
invalid, but it changes the scientific claim.

Related Pages
-------------

- :doc:`boussinesq-method`
- :doc:`surface-interaction`
- :doc:`solver-engines`
- :doc:`possibility-map`
- :doc:`../../../../getting_started/comparison-workflow`
- :doc:`../../../../capability_gallery/simulation_comparison`
- :doc:`../../../../capability_gallery/cases/surface_interaction_ramp_code_comparison`
- :doc:`../../../../capability_gallery/cases/surface_interaction_no_seepage_code_comparison`
