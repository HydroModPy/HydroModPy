Simulation Comparison Workflow
==============================

Use this page when you want to compare two or more HydroModPy simulations while
keeping one shared physical case as constant as possible.

This is the right workflow for questions such as:

- how different are MODFLOW 6 and Boussinesq on the same saved mesh?
- what changes when I switch from NWT to MF6?
- what is the effect of one numerical option, such as XT3D, on the same case?

What This Workflow Is
---------------------

The comparison workflow is an external orchestration layer declared through:

.. code-block:: toml

   workflow = "comparison"

It does not replace the standard ``simulation`` workflow. Instead, it:

1. reads one comparison TOML,
2. reads one shared base simulation TOML,
3. generates child simulation TOMLs,
4. runs those children through the public HydroModPy entry point,
5. extracts observables from persisted results,
6. computes metrics, audits, and figures.

Execution Map
-------------

.. uml:: diagrams/comparison_workflow_execution.wsd

This is the most important structural point to keep in mind: the workflow does
not bypass standard simulations. It builds ordinary child simulation configs,
runs them through the public entry point, then compares persisted outputs.

Why It Exists As A Separate Workflow
------------------------------------

Keeping comparison separate from standard simulation is a good scientific and
architectural choice.

It means:

- each child run remains a real HydroModPy simulation,
- solver-to-solver comparison stays explicit instead of becoming a hidden side
  effect inside ``simulation``,
- comparison outputs are clearly post-hoc evidence products rather than raw
  simulation artifacts.

This also prevents one important confusion:

- a comparison workflow is not a validation workflow.

Comparison asks:
"How different are these runs on the same declared case?"

Validation asks:
"Does this run match an analytical or trusted reference within stated
tolerances?"

Two-Level Input Structure
-------------------------

The recommended structure uses:

- one comparison TOML with ``workflow = "comparison"``,
- one base simulation TOML referenced by
  ``[comparison].base_simulation_config``.

Minimal example:

.. code-block:: toml

   workflow = "comparison"

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

The comparison workflow then writes one self-contained child TOML per
simulation under:

.. code-block:: text

   <output_root>/_generated_configs/

Method Notes Before You Interpret Results
-----------------------------------------

The comparison workflow keeps one physical case as constant as possible, but it
does not remove the need to interpret method choices explicitly.

Before reading the output figures as "solver differences", confirm at least the
following:

- whether the child runs use the exact same support,
- whether the comparison is backend-only or also changes mesh family,
- whether XT3D is active for irregular MODFLOW 6 cases,
- whether the comparison mixes a layered MODFLOW representation with a reduced
  shallow-flow Boussinesq representation,
- whether heterogeneous properties are being transferred to cells in the same
  way for both runs.

The key scientific notes are:

- :doc:`../scientific/solvers/modflow6-vs-modflownwt-scientific-comparison`
- :doc:`../scientific/solvers/modflow-governing-equation-and-cvfd-formulation`
- :doc:`../scientific/solvers/modflow-package-semantics-and-boundary-conditions`
- :doc:`../scientific/solvers/field-to-cell-parameter-transfer`
- :doc:`../scientific/solvers/vertical-representation-and-storage-assumptions`
- :doc:`../scientific/solvers/mesh-quality-and-acceptance-criteria`
- :doc:`../scientific/solvers/xt3d-on-irregular-disv-meshes`
- :doc:`../scientific/solvers/boussinesq-mathematical-notes`
- :doc:`../scientific/hydrology/forcing-time-aggregation-and-first-clim`
- :doc:`../scientific/hydrology/simulated-active-network`

Recommended First Cases
-----------------------

The public example set already contains several useful starting points.

.. list-table::
   :header-rows: 1
   :widths: 30 28 42

   * - Example
     - Main comparison
     - Why start here
   * - ``compare_dupuit_mf6_bouss.toml``
     - MODFLOW 6 versus Boussinesq on a synthetic shared mesh
     - Smallest conceptual jump; best first case for understanding the workflow
   * - ``compare_vire_natural_mf6_nwt.toml``
     - MODFLOW 6 versus MODFLOW-NWT on a natural structured case
     - Useful when the question is backend migration without changing mesh
       family
   * - ``compare_10km2_natural_mesh_mf6_bouss.toml``
     - MODFLOW 6 versus Boussinesq on a natural saved triangular mesh
     - Best entry point for shared-support comparison on an irregular mesh
   * - ``compare_10km2_natural_mesh_recharge_mf6_bouss.toml``
     - Same natural shared mesh, but with diffuse recharge activated
     - Best next case when the question moves from geometry alone to forcing
       semantics
   * - ``compare_10km2_natural_mesh_transient_pulse_mf6_bouss.toml``
     - Same natural shared mesh with one controlled transient recharge pulse
     - Best first transient comparison when you want differences that stay
       interpretable
   * - ``compare_nancon_transient_seasonal_mf6_bouss.toml``
     - MODFLOW 6 versus Boussinesq on a Nancon catchment setup with a
       synthetic weekly seasonal recharge chronicle
     - More realistic transient stress test; the child runs regenerate their
       support from the same base TOML and the comparison audits the outputs

How To Run It
-------------

Run one public example directly through the example helper:

.. code-block:: powershell

   python examples/projects/09_comparison_workflow/run_comparison_example.py --case synthetic --show

or through the public CLI:

.. code-block:: powershell

   hmp run examples/projects/09_comparison_workflow/compare_dupuit_mf6_bouss.toml

The same pattern applies to the other shipped examples:

- ``compare_vire_natural_mf6_nwt.toml``
- ``compare_10km2_natural_mesh_mf6_bouss.toml``
- ``compare_10km2_natural_mesh_recharge_mf6_bouss.toml``
- ``compare_10km2_natural_mesh_transient_pulse_mf6_bouss.toml``
- ``compare_nancon_transient_seasonal_mf6_bouss.toml``

Representative results
----------------------

.. figure:: /_static/workflows/comparison/dupuit_case_configuration.png
   :alt: Configuration figure for the Dupuit MODFLOW 6 versus Boussinesq comparison workflow
   :width: 100%

   The configuration figure is the orientation panel for a comparison run: it
   tells you which shared case, support, observables, and forcing layout are
   being compared before you read any differences.

.. figure:: /_static/workflows/comparison/dupuit_head_triptych.png
   :alt: Head-map triptych for the Dupuit MODFLOW 6 versus Boussinesq comparison workflow
   :width: 100%

   The triptych places the reference field, the candidate field, and the
   candidate-minus-reference difference in one compact visual sequence.

What You Should Inspect First
-----------------------------

The first files worth opening are usually:

- ``comparison_report.md``
- ``comparison_metrics.csv``
- ``comparison_figures/case_configuration.png``
- ``comparison_figures/*triptych*.png``

``case_configuration.png`` is the orientation figure. It shows the physical
support used by the reference case before looking at the numerical results:

- mesh cells or cell centroids,
- topography when the mesh bundle exposes it,
- detected fixed-head side boundaries,
- point/outlet observables,
- the recharge forcing chronicle when it is declared in the case TOML.

The triptych figures are especially useful because they place:

1. the reference field,
2. the candidate field,
3. the candidate-minus-reference difference

in one visual sequence.

When the runs expose both canonical hydrographic networks, also inspect:

- ``hydrographic_network_metrics.csv``

because it adds a geometric comparison beyond scalar field metrics.

When one or more variants do not expose both required roles, also inspect:

- ``hydrographic_network_metrics_skipped.json``

because it records which variants were skipped and why, instead of silently
leaving the hydrographic-network export incomplete.

For the simulated active drainage signal, inspect:

- ``simulated_active_network_metrics.csv``
- ``simulated_active_network_metrics_skipped.json``
- ``simulated_active_network_overlap_metrics.csv``
- ``simulated_active_network_overlap_metrics_skipped.json``

The first pair summarizes active-network occupancy from ``accumulation_flux``.
The second pair compares that simulated active occupancy against the observed
``reference`` network after rasterizing the vector network onto the simulation
mesh. These files do not mean that a stored vector feature
``hydrographic_network_simulated_active`` exists yet.

For a single run with ``accumulation_flux`` and a plottable mesh, the display
layer can also render:

- ``simulated_active_network``
- ``simulated_active_network_reference_overlay``

The first is a computed cell-map figure. The second overlays the simulated
active cells with the observed ``reference`` network and is the preferred
validation figure when both are available. These figures are useful before
deciding whether a canonical vectorized ``simulated_active`` network should be
persisted.

For terminology, ``steady`` is the representative steady-flow concept, while
``persistent`` and ``always_active`` are transient occupancy rules.
``always_active`` means active at every timestep of the analysed transient
window. A steady simulated active network should be based on a representative
``flow_regime = "steady"`` run, then compared against ``reference``. When no
active-network ``mode`` is supplied, HydroModPy resolves the default from the
run regime: ``steady`` uses the steady-state active field, while ``transient``
uses ``persistent`` for backward compatibility.

For a programmatic diagnostic against an existing vector role, use:

- ``run.simulated_active_network_overlap_metrics(network_role="reference")``

This compares cell occupancy after rasterizing the selected vector network onto
the simulation mesh. This is the primary validation comparison for the
simulated active network. If ``reference`` is not available, the validation
comparison is skipped. It should not silently fall back to ``generated``,
because that would no longer be an observation-vs-simulation validation.

For a single run that carries both networks, HydroModPy also exposes dedicated
figures such as:

- ``hydrographic_network_comparison``
- ``hydrographic_network_reference_missing_only``
- ``hydrographic_network_generated_extra_only``

The canonical feature names behind those views are
``hydrographic_network_reference`` and ``hydrographic_network_generated``.
Older names such as ``river_network`` are kept only as legacy aliases.

If only one of the two canonical roles is present, HydroModPy behaves
conservatively:

- the standalone figure for the existing role remains available,
- the comparison figures do not appear in ``run.display_capabilities``,
- ``run.hydrographic_network_comparison()`` raises an explicit error saying
  which role is missing,
- comparison exports such as ``hydrographic_network_metrics.csv`` are skipped,
- ``hydrographic_network_metrics_skipped.json`` records the skipped variants
  and the missing-role reason.

If you want a strict reading order once the run is finished, continue with
:doc:`comparison-output-reading-order`.

For transient MODFLOW 6 versus Boussinesq examples, inspect the budget
diagnostics before interpreting head metrics alone. The same physical case can
still expose solver-specific accounting semantics, for example whether recharge
is applied on fixed-head cells or exported as prescribed-head outflow.

Allowed Variant Overlays
------------------------

The current public contract intentionally limits what can change between child
simulations.

The main allowed overlay families are:

- generic simulation metadata,
- solver selection and solver-specific options,
- display options,
- a narrow ``flow`` overlay used for runtime-backend selection.

The workflow is deliberately conservative here. If the physical case changes
too much between children, the result is no longer a clear method comparison.

When To Use This Workflow
-------------------------

Use it when the goal is:

- backend comparison on one shared support,
- structured-versus-irregular discretization comparison,
- numerical-option sensitivity on one fixed physical case,
- production of stable difference figures and metrics.

Do not use it as a substitute for:

- a first learning walkthrough,
- analytical validation,
- or a fully free-form multi-physics experiment where every child case changes
  physically.

Current Limits
--------------

The current comparison workflow still has explicit limits.

- Execution is sequential.
- The strongest comparisons are those that share one saved support.
- Cross-mesh comparisons rely on observables and derived products, not on a
  universal cell-to-cell correspondence.
- The natural Boussinesq cases remain intentionally reduced and controlled.

Related Reading
---------------

- :doc:`comparison-output-reading-order`
- :doc:`reading-results-pages`
- :doc:`workflow-families`
- :doc:`../scientific/solvers/modflow6-vs-modflownwt-scientific-comparison`
- :doc:`../scientific/solvers/modflow-governing-equation-and-cvfd-formulation`
- :doc:`../scientific/solvers/modflow-package-semantics-and-boundary-conditions`
- :doc:`../scientific/solvers/field-to-cell-parameter-transfer`
- :doc:`../scientific/solvers/meshes-and-numerical-methods`
- :doc:`../scientific/solvers/mesh-quality-and-acceptance-criteria`
- :doc:`../scientific/solvers/xt3d-on-irregular-disv-meshes`
- :doc:`../scientific/solvers/boussinesq-mathematical-notes`
- :doc:`../scientific/hydrology/forcing-time-aggregation-and-first-clim`
