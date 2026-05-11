Boussinesq PETSc Validation Results
===================================

This page records the current analytical-validation status after routing the
``solver = "boussinesq"`` analytical cases through the PETSc Boussinesq runtime.

The public validation label remains ``boussinesq``. Internally, steady
analytical Boussinesq cases now use a pure steady PETSc SNESVI solve with
``flow.runtime_backend = "petsc"`` and
``flow.surface_interaction_model = "vi_obstacle"``. Transient analytical
Boussinesq cases now use PETSc TS with SNESVI through
``flow.surface_interaction_model = "ts_vi_obstacle"``.

Latest Automated Results
------------------------

The following commands were run on 2026-05-06 in the WSL PETSc environment
through ``install/enter_wsl_dev.sh --headless``.

.. list-table::
   :header-rows: 1
   :widths: 28 28 24 20

   * - Check
     - Command
     - Result
     - Duration
   * - Pytest PETSc analytical validation suite
     - ``python -m pytest tests/validation/analytical -m petsc -q --tb=short``
     - ``26 passed, 66 deselected``
     - ``158.92 s``
   * - Documentation validation batch for ``solver=boussinesq``
     - ``python -m validation_cases.run_cases --solver boussinesq --regime both --no-show --stop-on-error --report-json validation_cases/reports/latest/boussinesq_both.json --timeout 1800``
     - ``21/21 cases passed``
     - ``659.8 s``

The committed report consumed by the validation gallery is:
``validation_cases/reports/latest/boussinesq_both.json``. It was generated at
``2026-05-06T07:41:24.118686+00:00`` and records ``failed_case_count = 0``.

Validation Gallery Pages
------------------------

Open these pages first in the generated HTML build:

- :doc:`Validation Benchmarks </capability_gallery/validation>` shows the
  refreshed Boussinesq batch line: ``21/21 cases passed``.
- :doc:`Boussinesq Hillslope Interception 1D </capability_gallery/cases/boussinesq_hillslope_interception_1d>`
  is the main PETSc VI obstacle diagnostic page.
- :doc:`Capability Gallery </capability_gallery/index>` is the gallery entry
  point.

The hillslope interception figure was regenerated with the PETSc method line in
the plot footer.

.. figure:: /_static/capability_gallery/validation/boussinesq_hillslope_interception_1d__boussinesq.png
   :alt: Boussinesq hillslope interception validation with PETSc VI method annotation.
   :width: 100%

   Boussinesq hillslope interception validation, rendered for the documentation
   gallery with the PETSc VI obstacle method annotation.

Case Coverage
-------------

These 21 analytical validation cases use the PETSc-backed Boussinesq route in
the latest batch report.

.. list-table::
   :header-rows: 1
   :widths: 18 50 32

   * - Regime
     - Documentation page
     - Method
   * - Steady
     - :doc:`Boussinesq Circular-Island Piecewise-K 2D </capability_gallery/cases/boussinesq_circular_island_piecewise_k_2d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Boussinesq Divide-Fixed-Head Piecewise-K 1D </capability_gallery/cases/boussinesq_divide_fixed_head_piecewise_k_1d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Boussinesq Fixed-Head Piecewise-K 1D </capability_gallery/cases/boussinesq_fixed_head_piecewise_k_1d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Boussinesq Hillslope Interception 1D </capability_gallery/cases/boussinesq_hillslope_interception_1d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Boussinesq Sloping-Substratum Constant-Thickness 1D </capability_gallery/cases/boussinesq_sloping_substratum_constant_thickness_1d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Boussinesq Sloping-Substratum Fixed-Head 1D </capability_gallery/cases/boussinesq_sloping_substratum_fixed_head_1d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Boussinesq Sloping-Substratum Uniform-Recharge 1D </capability_gallery/cases/boussinesq_sloping_substratum_uniform_recharge_1d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Boussinesq Uniform-Recharge Piecewise-K 1D </capability_gallery/cases/boussinesq_uniform_recharge_piecewise_k_1d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Dupuit Circular-Island Ocean 2D </capability_gallery/cases/dupuit_circular_island_ocean_2d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Dupuit Divide-River 1D </capability_gallery/cases/dupuit_divide_river_1d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Dupuit Fixed-Head 1D </capability_gallery/cases/dupuit_fixed_head_1d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Steady
     - :doc:`Dupuit Uniform-Recharge 1D </capability_gallery/cases/dupuit_uniform_recharge_1d>`
     - PETSc SNESVI, pure steady, ``vi_obstacle``
   * - Transient
     - :doc:`Boussinesq Hillslope Recharge-Step Interception 1D </capability_gallery/cases/boussinesq_hillslope_recharge_step_interception_1d>`
     - PETSc TS + SNESVI, ``ts_vi_obstacle``
   * - Transient
     - :doc:`Brutsaert Recession Boussinesq Thin 1D </capability_gallery/cases/brutsaert_recession_boussinesq_thin_1d>`
     - PETSc TS + SNESVI, ``ts_vi_obstacle``
   * - Transient
     - :doc:`Brutsaert Recession Linearized Deep 1D </capability_gallery/cases/brutsaert_recession_linearized_deep_1d>`
     - PETSc TS + SNESVI, ``ts_vi_obstacle``
   * - Transient
     - :doc:`Late-Time Unconfined Pumping 2D </capability_gallery/cases/late_time_unconfined_pumping_2d>`
     - PETSc TS + SNESVI, ``ts_vi_obstacle``
   * - Transient
     - :doc:`Linearized Unconfined Boundary Piecewise 1D </capability_gallery/cases/linearized_unconfined_boundary_piecewise_1d>`
     - PETSc TS + SNESVI, ``ts_vi_obstacle``
   * - Transient
     - :doc:`Linearized Unconfined Boundary Step 1D </capability_gallery/cases/linearized_unconfined_boundary_step_1d>`
     - PETSc TS + SNESVI, ``ts_vi_obstacle``
   * - Transient
     - :doc:`Linearized Unconfined Recharge Periodic 1D </capability_gallery/cases/linearized_unconfined_recharge_periodic_1d>`
     - PETSc TS + SNESVI, ``ts_vi_obstacle``
   * - Transient
     - :doc:`Linearized Unconfined Recharge Step 1D </capability_gallery/cases/linearized_unconfined_recharge_step_1d>`
     - PETSc TS + SNESVI, ``ts_vi_obstacle``
   * - Transient
     - :doc:`Linearized Unconfined Recharge Step Deep 1D </capability_gallery/cases/linearized_unconfined_recharge_step_deep_1d>`
     - PETSc TS + SNESVI, ``ts_vi_obstacle``

Hillslope Interception Diagnostic
---------------------------------

The migration is mostly a runtime substitution. The main exception remains the
steady hillslope interception case. The PETSc VI solve is numerically clean, but
the interception position differs from the historical no-drain analytical
intersection.

.. list-table::
   :header-rows: 1
   :widths: 36 24 40

   * - Quantity
     - Current value
     - Interpretation
   * - Analytical interception x
     - ``244.776 m``
     - Historical no-drain Boussinesq profile intersected with topography.
   * - PETSc VI numerical interception x
     - ``285.000 m``
     - Contact front from the hard obstacle solve.
   * - Interception x error
     - ``40.224 m``
     - Below the current ``45 m`` acceptance threshold.
   * - Cross-row head spread
     - ``8.88e-16 m``
     - Quasi-1D uniformity is preserved.
   * - Topography overshoot
     - ``0.0 m`` in the PETSc diagnostic run
     - The obstacle constraint is respected.

This offset is not interpreted as a nonlinear convergence failure. The
analytical reference solves a no-drain profile and then intersects it with the
topography, while the PETSc VI method solves a constrained obstacle problem
with an active surface-contact zone and surface reaction.

Related Developer Notes
-----------------------

- ``docs/developers/boussinesq_petsc_vi_hillslope_interception_analysis.md``
  documents the detailed hillslope interpretation.
- ``docs/developers/boussinesq_petsc_complementarity_nancon_diagnostic.md``
  documents earlier PETSc complementarity diagnostics on a larger numerical
  scenario.
