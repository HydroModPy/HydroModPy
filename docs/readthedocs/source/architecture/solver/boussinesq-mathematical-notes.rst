Boussinesq Mathematical Notes
=============================

This page gives a mathematical reading of the Boussinesq backend implemented
in ``hydromodpy/solver/boussinesq``. It is not a full research-paper style
derivation. Its role is more practical:

- define the unknowns and the sign conventions used by the code,
- show how the finite-volume residual is assembled,
- explain the additional regularized source terms currently present in the
  implementation,
- connect the equations to the main Python modules.

The intended audience is a developer or modeller who wants to understand what
the backend solves and how that solve is encoded.

Purpose Of This Note
--------------------

This note complements the architecture documentation by making the solver-side
physics and residual assembly explicit.

Geometric Setting And Unknowns
------------------------------

The solver works on a 2D triangular mesh of aquifer cells. Each cell
:math:`i` has:

- area :math:`A_i`,
- top elevation :math:`z^{\text{top}}_i`,
- bottom elevation :math:`z^{\text{bot}}_i`,
- hydraulic conductivity :math:`K_i`,
- storage coefficient :math:`S_i`.

The primary unknown is the cell-centered hydraulic head.

.. math::

   h_i

From :math:`h_i`, the code reconstructs the saturated thickness.

.. math::

   b_i(h) = \min\!\left(
       \max\!\left(h_i - z^{\text{bot}}_i, 0\right),
       z^{\text{top}}_i - z^{\text{bot}}_i
   \right)

This clipping is important. It means the nonlinear iterate is always
interpreted through a physically admissible thickness, even if the head
temporarily overshoots during Newton iterations.

The cell transmissivity is then

.. math::

   T_i(h) = K_i\,b_i(h)

Cell Balance And Sign Convention
--------------------------------

The solver is built around a residual balance written per cell. The convention
used by the code is:

- positive residual contributions tend to remove water from the cell,
- recharge and positive well injection add water and therefore appear with a
  minus sign in the residual,
- a converged solution satisfies :math:`R_i \approx 0` for every cell
  :math:`i`.

This convention is the one implemented in ``assemble_steady_residual()`` and
``assemble_transient_residual()``.

Internal Edge Fluxes
--------------------

Consider an internal edge :math:`e` shared by cells :math:`a` and :math:`b`.
The code defines one oriented flux :math:`q^{\text{int}}_e` that is positive
when water leaves cell :math:`a` and enters cell :math:`b`:

.. math::

   q^{\text{int}}_e = -\tau_e(h_b - h_a)

The edge transmissive factor is

.. math::

   \tau_e
   =
   K^{H}_e\,\bar{b}_e\,\frac{L_e}{d_e}

where:

- :math:`K^{H}_e` is the harmonic mean of :math:`K_a` and :math:`K_b`,
- :math:`\bar{b}_e = \frac{1}{2}(b_a + b_b)` is the averaged saturated
  thickness,
- :math:`L_e` is the edge length,
- :math:`d_e` is the centroid-to-centroid distance between the two cells.

The residual contribution of internal fluxes is conservative:

.. math::

   R^{\text{int}}_a \mathrel{+}= q^{\text{int}}_e,
   \qquad
   R^{\text{int}}_b \mathrel{-}= q^{\text{int}}_e

This part is implemented by:

- ``internal_edge_flux_from_head()``,
- ``accumulate_internal_flux_residual()``.

Imposed-Head Exchanges
----------------------

Some edges carry an imposed stage :math:`H_e`, for example:

- side Dirichlet conditions,
- stream supports,
- ocean supports.

For such edges, the code builds cell-to-edge transmissive coefficients

.. math::

   \tau_{a,e} = K_a\,b_a\,\frac{L_e}{d_{a,e}}

and similarly for :math:`\tau_{b,e}` when a second owner cell exists.

The corresponding exchange fluxes are

.. math::

   q^{D}_{a,e} = -\tau_{a,e}(H_e - h_a),
   \qquad
   q^{D}_{b,e} = -\tau_{b,e}(H_e - h_b)

Those fluxes are accumulated directly into the owner-cell residuals. In the
current mesh usage, imposed-head support is mainly used on boundary edges, but
the implementation is slightly more general and can also account for an edge
with two owner cells.

Recharge, Wells, Drainage And Saturation Excess
-----------------------------------------------

Recharge
^^^^^^^^

Recharge is represented as a surface rate :math:`r_i` in ``m/s``. In the
current first slice of the backend, recharge is homogeneous in space for a
given stress period. Its volumetric contribution in cell :math:`i` is

.. math::

   A_i r_i

Wells
^^^^^

Wells are converted to cell-based volumetric rates
:math:`Q^{\text{well}}_i` in ``m^3/s``. The sign convention is:

- positive value: injection into the aquifer,
- negative value: pumping from the aquifer.

Since injection adds water, the residual contains :math:`-Q^{\text{well}}_i`.

Drainage
^^^^^^^^

Drainage is a simple top leakage law that activates only when the head exceeds
the cell top elevation:

.. math::

   q^{\text{drain}}_i = C_i^{\text{drain}}
   \max(h_i - z^{\text{top}}_i, 0)

This term is always treated as an outflow from the aquifer and therefore
enters the residual with a positive sign.

Regularized Saturation Excess
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The current backend includes a regularized saturation-excess source term. Its
goal is pragmatic: avoid a sharp on/off overflow law exactly at full saturation
while still allowing near-surface water release when the cell is almost full.

Define the saturation ratio

.. math::

   \sigma_i(h) =
   \frac{b_i(h)}{z^{\text{top}}_i - z^{\text{bot}}_i}

Let :math:`R^{\text{lat}}_i` be the lateral balance rate converted back to a
surface flux by division through :math:`A_i`. The code forms

.. math::

   \beta_i
   =
   \max\!\left(
       -\frac{R^{\text{lat}}_i}{A_i} + \max(r_i, 0),
       0
   \right)

and then applies the regularization

.. math::

   s_i(h)
   =
   \exp\!\left(
       -\frac{1 - \sigma_i(h)}{\varepsilon}
   \right)
   \beta_i

where :math:`\varepsilon > 0` is the regularization radius.

This term is not meant to be a final physically complete overland-flow model.
It is a smooth release mechanism used by the current backend close to full
saturation.

Steady Residual
---------------

The steady residual assembled by the code is

.. math::

   R_i^{\text{steady}}(h)
   =
   R_i^{\text{int}}(h)
   +
   R_i^{D}(h)
   +
   q_i^{\text{drain}}(h)
   +
   A_i s_i(h)
   -
   A_i r_i
   -
   Q_i^{\text{well}}

The steady solve therefore searches for

.. math::

   R_i^{\text{steady}}(h) = 0
   \qquad \text{for all cells } i

Transient Residual
------------------

For one fully implicit backward-Euler time step from :math:`t^n` to
:math:`t^{n+1}`, the additional storage term is

.. math::

   R_i^{\text{storage}}
   =
   A_i S_i \frac{h_i^{n+1} - h_i^n}{\Delta t}

The transient residual is then

.. math::

   R_i^{\text{transient}}(h^{n+1})
   =
   A_i S_i \frac{h_i^{n+1} - h_i^n}{\Delta t}
   +
   R_i^{\text{int}}(h^{n+1})
   +
   R_i^{D}(h^{n+1})
   +
   q_i^{\text{drain}}(h^{n+1})
   +
   A_i s_i(h^{n+1})
   -
   A_i r_i^{n+1}
   -
   Q_{i}^{\text{well},\,n+1}

The backend solves

.. math::

   R_i^{\text{transient}}(h^{n+1}) = 0
   \qquad \text{for all cells } i

Nonlinear Solution Strategy
---------------------------

Local Runtime
^^^^^^^^^^^^^

The local runtime uses a dense damped Newton loop:

#. start from an initial head guess,
#. assemble the residual,
#. build a dense Jacobian by forward finite differences,
#. solve the linearized Newton system,
#. backtrack the Newton update until the residual decreases,
#. stop when the infinity norm of the residual is below tolerance.

This strategy is transparent and easy to debug, which is why it is useful in
an early implementation slice.

SciPy Runtime
^^^^^^^^^^^^^

The SciPy runtime keeps the same residual and the same finite-difference
Jacobian, but delegates the nonlinear solve to ``scipy.optimize.root``. The
important point is that the physics does not change; only the nonlinear driver
changes.

Mapping Between Equations And Code
----------------------------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Mathematical object
     - Main implementation point
   * - :math:`b_i(h)`
     - ``saturated_thickness_from_head()``
   * - :math:`T_i(h)`
     - ``transmissivity_from_head()``
   * - :math:`q^{\text{int}}_e`
     - ``internal_edge_flux_from_head()``
   * - :math:`q^{D}_e`
     - ``imposed_head_edge_flux_from_head()``
   * - :math:`q_i^{\text{drain}}`
     - ``drainage_outflow_from_head()``
   * - :math:`s_i(h)`
     - ``saturation_excess_rate_from_balance()``
   * - :math:`R_i^{\text{steady}}`
     - ``assemble_steady_residual()``
   * - :math:`R_i^{\text{transient}}`
     - ``assemble_transient_residual()``
   * - runtime solve
     - ``local_runtime.py`` / ``scipy_runtime.py``
   * - problem orchestration
     - ``boussinesq.py``

Interpretation And Current Limits
---------------------------------

The current backend is best viewed as a clear and auditable first
finite-volume Boussinesq implementation, not yet as the final production
solver. In particular:

- the Jacobian is still dense,
- the overflow-related term is regularized rather than derived from a full
  coupled surface-flow model,
- the current slice focuses on small validation meshes and controlled test
  cases.

That is acceptable at this stage because the code is optimized for
interpretability, validation, and iterative refinement of the physics.

Original LaTeX Source
---------------------

If a LaTeX distribution is installed, the original note in
``hydromodpy/solver/boussinesq/boussinesq_math_notes.tex`` can still be
compiled from the package directory with either:

.. code-block:: bash

   pdflatex -interaction=nonstopmode boussinesq_math_notes.tex

or:

.. code-block:: bash

   latexmk -pdf boussinesq_math_notes.tex
