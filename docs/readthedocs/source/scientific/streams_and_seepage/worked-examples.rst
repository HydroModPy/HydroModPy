Worked Examples
===============

Purpose
-------

This page collects the examples that make the streams, seepage, and simulated
active-network concepts operational.

An example is useful here only if it answers four questions:

1. What modelling decision does it test?
2. Which command or committed page reproduces the evidence?
3. Which files or figures should be opened first?
4. What conclusion can be defended from those artifacts?

The examples below are therefore not a gallery. They are reading paths from a
scientific question to concrete outputs.

For the current implementation status and known non-contracts, read
:doc:`status-and-limitations` before treating any example as validation
evidence.

Example 1 - Choose The Method Before Running
--------------------------------------------

Use this first when the question is still conceptual.

Question
   Should the model prescribe exchange against a known stream head, let
   groundwater emerge at the surface, or only post-process active drainage?

Where to read
   :doc:`conceptual-model`

What to open
   The three method sketches:

   - ``method_stream_stage_boundary.svg``
   - ``method_seepage_drainage_operator.svg``
   - ``method_simulated_active_postprocess.svg``

What it proves
   The three methods are different modelling decisions. A stream boundary
   prescribes a hydraulic level on a zero-thickness support. A seepage or
   drainage operator releases water only where ``h_i > z_s,i``. A simulated
   active network is a post-solve diagnostic derived from positive seepage or
   drainage outflow.

Use this example to prevent the common shortcut "there is a river, therefore
use a stream package". The better question is what is known before the solve
and what should be computed by the solve.

Example 2 - MODFLOW 6 Active-Network Ladder
-------------------------------------------

Use this when the question is whether the MODFLOW 6 path carries enough result
information to interpret simulated seepage activity.

Where to read
   :doc:`../hydrology/simulated-active-network`

What to open
   In the validation section, inspect the four-panel figure first, then the
   individual panels:

   - ``modflow6_piezometric_map.png``
   - ``modflow6_outflow_drain_last.png``
   - ``modflow6_accumulation_flux_last.png``
   - ``modflow6_simulated_active_network.png``

What it proves
   The MODFLOW 6 workflow can expose a readable chain:

   1. solved head field;
   2. positive local ``outflow_drain``;
   3. routed ``accumulation_flux``;
   4. thresholded ``simulated_active_network`` display.

This is the key example for the modern MODFLOW 6 implementation path. It does
not prove that one hydraulic parameter set is calibrated. It proves that the
result contract needed for active-network interpretation is present.

Example 3 - Nancon Wide-K MODFLOW 6 Sweep
-----------------------------------------

Use this when the question is how hydraulic conductivity changes the simulated
active network on a real basin support.

Run command
   From the repository root:

.. code-block:: powershell

   python examples/projects/09_comparison_workflow/run_comparison_example.py --case nancon-seasonal-hydrography-k-sweep-mf6

Output folder
   The run writes:

.. code-block:: text

   examples/projects/09_comparison_workflow/outputs/nancon_transient_seasonal_hydrography_wide_k_sweep_mf6/

What to open first
   Start with the comparison-level files:

   - ``comparison_audit.md``
   - ``comparison_report.md``
   - ``simulated_active_network_metrics.csv``
   - ``simulated_active_network_overlap_metrics.csv``
   - ``run_figures/<variant>/simulated_active_network_reference_overlay.png``

Where the committed result is explained
   :doc:`nancon-k-sweep-results`

What it proves
   Increasing ``K`` contracts the persistent simulated-active extent in this
   current setup. The example also shows why overlap against ``reference`` is a
   validation diagnostic and not just a display choice: missing reference cells,
   extra active cells, coverage, precision, and F1 react differently.

What it does not prove
   It is not a calibration result. The page is a development and reading
   example. A calibration-grade protocol would need a frozen common mesh,
   explicit parameter search, and a stronger distance metric.

Example 4 - Nancon MODFLOW-NWT Basin Baseline
---------------------------------------------

Use this when the question is whether the older MODFLOW-NWT route already has
a concrete real-basin example that can be used as a reference point.

Run command
   From the repository root:

.. code-block:: powershell

   python -m hydromodpy run examples/projects/02_nancon_watershed/run_transient_nwt.toml

Committed documentation case
   :doc:`/capability_gallery/cases/nancon_transient_nwt`

What to open
   Read the figures in this order:

   1. ``nancon_transient_nwt_hydrographic_network_comparison.png``
   2. ``nancon_transient_nwt_simulated_active_network_reference_overlay.png``
   3. ``nancon_transient_nwt_piezometric_map.png``
   4. ``nancon_transient_nwt_hydrograph.png``
   5. ``nancon_transient_nwt_water_budget.png``

What it proves
   MODFLOW-NWT already has a stable real-basin diagnostic page that combines
   observed hydrography, simulated active-network overlay, groundwater state,
   hydrograph, and water budget. This is the best legacy baseline to use when
   checking that the MODFLOW 6 path is not merely producing files, but
   producing files that can be interpreted in the same scientific order.

What to copy into MODFLOW 6 work
   Copy the reading discipline, not the backend assumptions: start with
   network roles, then active-network overlay, then groundwater state, then
   hydrograph and budget.

Example 5 - Comparison Output Reading Order
-------------------------------------------

Use this after any comparison run, including the Nancon sweeps.

Where to read
   :doc:`../../getting_started/comparison-output-reading-order`

What to open first
   Use this order:

   1. ``comparison_audit.md``
   2. ``comparison_report.md``
   3. ``comparison_figures/case_configuration.png``
   4. ``comparison_metrics.csv``
   5. field triptychs
   6. ``simulated_active_network_metrics.csv``
   7. ``simulated_active_network_overlap_metrics.csv``
   8. ``*_skipped.json`` files when an expected export is missing

What it proves
   This order keeps evidence and interpretation separate. It avoids reading an
   attractive active-network figure before checking whether the compared runs
   have the same support, reference role, forcing, and diagnostics.

Acceptance Checklist
--------------------

For streams, seepage, and simulated active-network documentation, an example
"does the job" only when the following checks are explicit:

- the method role is stated: stream boundary, seepage/drainage operator, or
  simulated-active diagnostic;
- the support is named: observed ``reference``, DEM-derived ``generated``,
  solver support, or routed post-processing graph;
- the groundwater quantity is named: ``h``, ``outflow_drain``, or
  ``accumulation_flux``;
- the validation target is ``reference`` when the question is
  observation-versus-simulation;
- skipped comparisons are recorded with ``*_skipped.json`` rather than hidden;
- figures are read after the audit and configuration files, not before.

If one of those items is missing, the example may still be visually useful,
but it is not yet strong enough to carry the scientific explanation.

Related Reading
---------------

- :doc:`conceptual-model`
- :doc:`status-and-limitations`
- :doc:`nancon-k-sweep-results`
- :doc:`../hydrology/simulated-active-network`
- :doc:`../../getting_started/comparison-output-reading-order`
