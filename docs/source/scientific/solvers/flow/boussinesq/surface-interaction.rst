Surface Interaction And Interception
====================================

This page separates the groundwater/surface-interaction choices from the rest
of the Boussinesq equation.

The important modelling point is that Boussinesq does not simply compute head.
It also needs a rule for what happens when the groundwater state approaches or
intercepts the topographic surface.

Surface Terms
-------------

The current documentation distinguishes three related mechanisms:

.. list-table::
   :header-rows: 1
   :widths: 26 34 40

   * - Mechanism
     - Role
     - Current status
   * - Recharge
     - Adds water as a surface rate projected to cells.
     - Supported as homogeneous or resolved cellwise forcing depending on the
       workflow input.
   * - Drainage
     - Removes water when head exceeds the cell top elevation.
     - Simple top leakage law.
   * - Saturation excess
     - Represents near-surface release when the aquifer reaches the surface
       constraint.
     - Implemented through two alternative closures.

Regularized Partition Closure
-----------------------------

The ``regularized_partition`` closure keeps hydraulic head as the only
unknown. The surface-excess term is reconstructed by a smooth law that becomes
active near full saturation.

This route is useful because it is:

- available with ``local``, ``scipy``, ``scipy_sparse``, and ``petsc``;
- smooth enough for dense and sparse Newton-style solves;
- the main cross-platform comparison baseline.

Its limit is scientific rather than technical: it is a pragmatic release law,
not a full coupled surface-flow model. It can keep a low-amplitude seepage set
active where a stricter threshold model would turn surface excess off.

Mixed Complementarity Closure
-----------------------------

The ``complementarity`` closure introduces explicit saturation excess:

.. math::

   q_i^{ex} \ge 0

and enforces:

.. math::

   0 \le q_i^{ex} \perp z_i^{top} - h_i \ge 0

This reads:

- if the head is below the topographic surface, surface excess is zero;
- if surface excess is positive, the head is on the surface threshold.

The implementation uses a Fischer-Burmeister residual in the PETSc mixed
runtime. This route is the most explicit way to represent surface interception
as an on/off threshold constraint.

Lower Drying Obstacle
---------------------

The same PETSc mixed route also enforces the lower head obstacle:

.. math::

   h_i - z_i^{bot} \ge 0

through a dry-deficit unknown :math:`q_i^{dry}`. This quantity is not a
physical leakage through the substratum. It is a numerical unmet-demand term:
when the cell is already dry, it prevents the balance from removing more water
than the saturated storage can provide.

The head-only ``regularized_partition`` route does not solve this explicit
lower complementarity constraint. It still uses bounded saturated thickness in
transmissivity, lower-bounded saturated thickness in transient storage, and it
reports diagnostics if the head itself drops below the lower obstacle.

Selection Rule
--------------

.. list-table::
   :header-rows: 1
   :widths: 36 32 32

   * - Question
     - Prefer ``regularized_partition``
     - Prefer ``complementarity``
   * - Need cross-platform execution?
     - Yes.
     - No, PETSc/Linux route.
   * - Need a smooth head-only residual?
     - Yes.
     - No.
   * - Need explicit on/off surface-threshold behavior?
     - Not primarily.
     - Yes.
   * - Comparing against existing head-only validation cases?
     - Usually yes.
     - Only if the comparison is about the closure itself.

Related Gallery Pages
---------------------

- :doc:`../../../../capability_gallery/cases/surface_interaction_ramp_code_comparison`
- :doc:`../../../../capability_gallery/cases/surface_interaction_no_seepage_code_comparison`

Related Pages
-------------

- :doc:`boussinesq-method`
- :doc:`lower-obstacle-drying`
- :doc:`solver-engines`
