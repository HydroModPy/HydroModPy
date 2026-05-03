Boussinesq Equation And Unknowns
================================

This page isolates the equation-level view of ``flow/boussinesq``.

Primary Unknown
---------------

The primary solved variable is the cell-centered hydraulic head:

.. math::

   h_i

for each triangular aquifer cell :math:`i`.

From :math:`h_i`, the backend reconstructs the saturated thickness:

.. math::

   b_i(h) =
   \min\left(
      \max\left(h_i - z_i^{bot}, 0\right),
      z_i^{top} - z_i^{bot}
   \right)

and the transmissivity:

.. math::

   T_i(h) = K_i b_i(h)

The clipping is important. The nonlinear solver may test intermediate head
states, but the physical residual always interprets them through an admissible
saturated thickness.

Cell Balance
------------

The Boussinesq backend solves a cellwise mass balance. In words, each residual
balances:

- lateral exchange between neighboring triangular cells;
- imposed-head exchanges on side, stream, or ocean supports;
- recharge;
- wells;
- top drainage or surface-excess terms;
- storage in transient mode.

With HydroModPy's residual sign convention, positive residual contributions
tend to remove water from the cell. Recharge and injection therefore enter
with a negative sign.

Steady Equation
---------------

The steady problem searches for:

.. math::

   R_i^{steady}(h) = 0

for every active cell :math:`i`.

The head-only regularized formulation uses the residual shape:

.. math::

   R_i^{steady}(h)
   =
   R_i^{int}(h)
   +
   R_i^{D}(h)
   +
   q_i^{drain}(h)
   +
   A_i s_i(h)
   -
   A_i r_i
   -
   Q_i^{well}

where :math:`s_i(h)` is the selected surface-interaction contribution.

Transient Equation
------------------

Transient runs add a backward-Euler storage term:

.. math::

   A_i S_i \frac{h_i^{n+1} - h_i^n}{\Delta t}

so the transient residual is:

.. math::

   R_i^{transient}(h^{n+1}) = 0

with the same exchange, forcing, and surface terms evaluated at the new time
level.

What This Equation Does Not Claim
---------------------------------

The Boussinesq backend is not a full 3D groundwater model and not a full
overland-flow model. It is a shallow-groundwater reduction where the water
table, transmissivity, and surface-interaction behavior are represented inside
one cell-centered finite-volume balance.

Detailed Reference
------------------

- :doc:`../../boussinesq-mathematical-notes`
- :doc:`boussinesq-method`
- :doc:`surface-interaction`
