Lower Obstacle Drying
=====================

This page documents how the Boussinesq backend treats the physically required
lower bound on hydraulic head:

.. math::

   z_i^{bot} \le h_i \le z_i^{top}

The implementation still solves for hydraulic head. It does not switch the
primary unknown to water volume or saturated stock. The lower obstacle is
handled by using non-negative saturated thickness in the physical operators,
and by adding an explicit complementarity term in the PETSc mixed runtime.

Bounded Saturated Thickness
---------------------------

For every cell :math:`i`, the raw saturated thickness would be:

.. math::

   h_i - z_i^{bot}

The solver does not use this raw value directly in transmissivity. It
reconstructs the transmissive saturated thickness:

.. math::

   H_i^T(h) =
   \min\left(
      \max\left(h_i - z_i^{bot}, 0\right),
      z_i^{top} - z_i^{bot}
   \right)

The transmissivity is:

.. math::

   T_i(h) = K_i H_i^T(h)

The transient storage uses a lower-bounded drainable volume:

.. math::

   H_i^M(h) = \max\left(h_i - z_i^{bot}, 0\right)

.. math::

   M_i(h) = A_i S_i H_i^M(h)

The backward-Euler storage contribution is:

.. math::

   \frac{M_i(h^{n+1}) - M_i(h^n)}{\Delta t}

This avoids negative transmissivity and negative storage even if a nonlinear
iteration temporarily evaluates a head below the substratum. The upper surface
is deliberately not used to cap transient storage in the head-only routes: if
those routes allow a pressure-like head above :math:`z^{top}`, the time-step
history must still contain enough storage memory to avoid artificially frozen
transients.

Regularized Partition Route
---------------------------

The ``regularized_partition`` route is head-only. It uses the capped thickness
above in transmissivity and lower-bounded storage in the transient term, but it
does not solve an explicit lower complementarity constraint.

In practice:

- transmissivity remains non-negative;
- storage remains non-negative and keeps transient memory above the top
  surface when this head-only route permits such heads;
- diagnostics report whether the accepted head field went below
  :math:`z^{bot}`;
- no algebraic ``dry deficit`` unknown is solved in this route.

Use this route when the goal is a smooth head-only baseline or cross-platform
execution. Use the PETSc complementarity route when the lower obstacle itself
must be enforced by the nonlinear solve.

PETSc Double Obstacle Route
---------------------------

With ``runtime_backend = "petsc"`` and
``surface_interaction_model = "complementarity"``, the mixed unknown layout is:

.. math::

   (h_i,\ q_i^{ex},\ q_i^{dry})

The upper surface complementarity is:

.. math::

   q_i^{ex} \ge 0,\quad z_i^{top} - h_i \ge 0,\quad
   q_i^{ex}(z_i^{top} - h_i) = 0

The lower drying complementarity is:

.. math::

   q_i^{dry} \ge 0,\quad h_i - z_i^{bot} \ge 0,\quad
   q_i^{dry}(h_i - z_i^{bot}) = 0

The two algebraic rates have different interpretations:

- :math:`q_i^{ex}` is a saturation-excess release term at the upper surface;
- :math:`q_i^{dry}` is not a substratum leakage term. It is an unmet-demand
  correction that prevents the residual from removing more water than the
  available saturated storage.

With the HydroModPy residual sign convention, positive residual terms remove
water. The dry-deficit contribution therefore enters the balance with the
opposite sign:

.. math::

   R_i \leftarrow R_i - A_i q_i^{dry}

This sign is essential. If a cell is already at :math:`h_i=z_i^{bot}`, the
dry-deficit term offsets any remaining removal demand instead of adding water
through a physical boundary.

Diagnostics And Exports
-----------------------

Boussinesq runtime summaries now include lower-obstacle diagnostics:

.. list-table::
   :header-rows: 1
   :widths: 42 58

   * - Key family
     - Meaning
   * - ``bottom_threshold_*``
     - Reports accepted-head violations below :math:`z^{bot}` and the
       associated potential negative storage volume.
   * - ``bottom_constraint_*``
     - Reports active dry-deficit cells, peak rates and integrated dry-deficit
       volume.
   * - ``dry_deficit_history_m_s``
     - Exported state-history array for the cellwise :math:`q^{dry}` rate.
   * - ``dry_deficit_total_m3_s``
     - Comparison-budget component reconstructed from
       ``dry_deficit_history_m_s`` and cell areas.
   * - ``boussinesq_obstacle_diagnostics.csv``
     - Comparison export containing per-snapshot ``min(h-z_bot)``,
       potential negative storage volume, active dry-deficit cells, and
       surface-excess cells when Boussinesq state histories and mesh vertical
       bounds are available.

These diagnostics should be read separately from physical discharge terms.
They tell where the lower obstacle is active and how much extraction or
drainage demand could not be satisfied by saturated storage.

In budget closure diagnostics, ``dry_deficit_total_m3_s`` is treated with the
same sign as available water because it offsets an otherwise unsatisfied
removal demand. It is still not a physical recharge boundary.

Validation Case: Steep Hillslope Drying And Rewetting
-----------------------------------------------------

The committed PETSc validation test is:

.. code-block:: text

   tests/validation/numerical/transient/test_boussinesq_drying_petsc.py

It contains two checks:

- a single-cell pumping case that forces immediate lower-obstacle activation;
- a steep sloping hillslope that dries by natural lateral drainage under zero
  recharge, then rewets when recharge resumes.

The hillslope case uses:

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Item
     - Value
   * - Cells
     - 8 cell-centered finite-volume cells.
   * - Substratum
     - Linear drop from 20 m upstream to 0 m downstream.
   * - Saturable thickness
     - 1.5 m.
   * - Hydraulic conductivity
     - 1e-3 m/s.
   * - Storage coefficient
     - 0.2.
   * - Downstream boundary
     - Prescribed head equal to downstream substratum elevation.
   * - Drying phase
     - Two 30-day periods with zero recharge.
   * - Rewetting phase
     - One 10-day period with recharge 2e-6 m/s.

Expected behavior:

- during zero recharge, lateral drainage lowers the water table naturally;
- several cells reach :math:`h=z^{bot}` and activate :math:`q^{dry}`;
- the accepted head field remains above the lower obstacle within tolerance;
- after recharge resumes, head rises and :math:`q^{dry}` deactivates.

.. figure:: /_static/scientific/solvers/boussinesq/lower_obstacle_drying_rewetting.png
   :alt: Boussinesq lower-obstacle drying and rewetting diagnostic
   :width: 100%

   The diagnostic figure shows the same validation setup as a visual sequence:
   the initial water table drains toward the sloping substratum, the lower
   complementarity constraint activates during the dry phase, and recharge
   reactivates storage without leaving a persistent dry-deficit term.

Run the validation from Windows through the WSL development environment:

.. code-block:: powershell

   wsl.exe bash -lc "bash install/enter_wsl_dev.sh --headless -- python -m pytest tests/validation/numerical/transient/test_boussinesq_drying_petsc.py -q"

Regenerate the documentation asset from the same WSL environment:

.. code-block:: powershell

   wsl.exe bash -lc "cd /mnt/c/codes/HydroModPy && bash install/enter_wsl_dev.sh --headless -- python -m tools.doc_gallery.generate_boussinesq_drying_assets"

Or from an already activated Linux shell:

.. code-block:: bash

   python -m pytest tests/validation/numerical/transient/test_boussinesq_drying_petsc.py -q
   python -m tools.doc_gallery.generate_boussinesq_drying_assets

Design Interpretation
---------------------

This is a pragmatic intermediate formulation:

- the solved differential unknown remains hydraulic head;
- transmissive operators use capped saturated thickness;
- transient storage uses lower-bounded saturated thickness;
- the PETSc mixed runtime adds a lower algebraic obstacle only where needed;
- dry deficit is exposed as a diagnostic, not as a physical flux.

A future stock-based formulation could make stored water the primary unknown.
That would be a larger modelling change. The current design keeps the existing
head-based method while removing negative saturated thickness, negative
storage, and unconstrained dry heads in the PETSc complementarity route.

Related Pages
-------------

- :doc:`equation-and-unknowns`
- :doc:`boussinesq-method`
- :doc:`surface-interaction`
- :doc:`solver-engines`
