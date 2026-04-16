Boussinesq Mathematical Notes
=============================

This page gives a mathematical reading of the Boussinesq backend implemented
in ``hydromodpy/solver/boussinesq``. It is not a full research-paper style
derivation. Its role is more practical:

- define the unknowns and the sign conventions used by the code,
- show how the finite-volume residual is assembled,
- explain the groundwater/surface interaction closures currently present in
  the implementation,
- connect the equations to the main Python modules.

The intended audience is a developer or modeller who wants to understand what
the backend solves and how that solve is encoded.

This note now belongs to the scientific documentation rather than the software
architecture section because its purpose is to describe the mathematical model
and numerical formulation.

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

Recharge, Wells, Drainage And Surface Interaction
-------------------------------------------------

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

Regularized Saturation Excess Closure
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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
It is a smooth release mechanism used by the head-only formulation close to
full saturation.

Mixed Complementarity Surface Closure
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The PETSc mixed formulation uses a different surface interaction model. It
introduces one explicit cellwise surface-excess unknown
:math:`q_i^{\text{ex}} \ge 0` and replaces the regularized law by the
complementarity condition

.. math::

   0 \le q_i^{\text{ex}} \perp z_i^{\text{top}} - h_i \ge 0

which reads:

- if :math:`h_i < z_i^{\text{top}}`, then :math:`q_i^{\text{ex}} = 0`,
- if :math:`q_i^{\text{ex}} > 0`, then :math:`h_i = z_i^{\text{top}}`.

The implementation enforces this relation with a Fischer-Burmeister residual
on scaled variables in ``petsc_runtime.py``. In that formulation the surface
flux is not prescribed by a local partition law; it is solved together with
the head field so that the finite-volume balance and the unilateral surface
constraint are satisfied simultaneously.

Head-Only Steady Residual
-------------------------

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

Head-Only Transient Residual
----------------------------

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

This is the transient residual solved by the ``local``, ``scipy``,
``scipy_sparse`` and PETSc regularized-partition runtimes.

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
small validation slices, but it is not the preferred path for larger meshes.

SciPy Runtime
^^^^^^^^^^^^^

The SciPy runtime keeps the same residual and the same finite-difference
Jacobian, but delegates the nonlinear solve to ``scipy.optimize.root``. The
important point is that the physics does not change; only the nonlinear driver
changes.

SciPy Sparse Runtime
^^^^^^^^^^^^^^^^^^^^

The SciPy sparse runtime still solves the head-only regularized-partition
residual, but it changes the linear algebra and Jacobian assembly strategy:

#. smooth residual terms are differentiated analytically,
#. the remaining nonlinear saturation terms are completed by sparse
   finite-difference corrections,
#. the Newton step is solved with SciPy sparse matrices and ``spsolve``.

This is the current non-PETSc reference path for larger Boussinesq meshes on
all platforms.

PETSc Regularized-Partition Runtime
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Linux-only PETSc regularized-partition backend keeps the same head-only
residual as above,

.. math::

   R_i^{\text{steady}}(h) = 0
   \qquad \text{or} \qquad
   R_i^{\text{transient}}(h^{n+1}) = 0,

but solves it with PETSc SNES on a sparse Jacobian assembled from the same
semi-analytic ingredients as the SciPy sparse runtime. This path is the PETSc
counterpart of the historical head-only overflow regularization.

PETSc Mixed Complementarity Runtime
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Linux-only PETSc backend introduces one algebraic saturation-excess
unknown :math:`q^{\text{ex}}_i` per cell and solves a mixed semi-explicit DAE
at each backward-Euler step:

.. math::

   R_i^{\text{flow}}(h, q^{\text{ex}}) = 0

with the same finite-volume flow balance as above, except that the
regularized overflow term is replaced by the explicit unknown
:math:`q^{\text{ex}}_i`, and one nonlinear complementarity relation:

.. math::

   0 \le q^{\text{ex}}_i \perp z_i^{\text{top}} - h_i \ge 0

The implementation encodes this complementarity through a
Fischer-Burmeister residual on scaled variables and lets PETSc SNES solve the
full mixed nonlinear system.

In transient mode the current implementation uses a hybrid warm start for
:math:`q^{\text{ex}}`:

- under explicit positive loading (for example recharge or injection), the
  initial guess is taken from the historical regularized-partition predictor,
- during dry-down periods without positive loading, the initial guess is the
  dry state :math:`q^{\text{ex}} = 0`.

That choice is numerical rather than physical. It improves robustness when
overflow turns off after a wet period without changing the converged zero set
of the mixed complementarity system.

On the committed ``headwater_100km2_outlet_2`` real-basin cycling case, this
mixed closure also captures repeated activation/deactivation windows of the
surface threshold, whereas the regularized-partition closures keep one
low-amplitude seepage set active through the whole sequence under the same
forcing. That difference is one practical reason to keep both surface
interaction models explicit in the documentation. Complementarity diagnostics
in the runtime summary are evaluated on accepted solver snapshots, excluding
the raw transient initial condition.

The same pattern remains visible on the stronger heterogeneous cycling variant
where :math:`K` and :math:`S_y` are mapped from generated concentric
hydrofacies over the committed basin mesh. In that case the regularized
partition path still keeps one persistent seepage window active, while the
mixed complementarity path converges with repeated on/off threshold windows and
returns to a dry terminal state.

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
     - ``boundary_head_edge_flux_from_head()``
   * - :math:`q_i^{\text{drain}}`
     - ``drainage_outflow_from_head()``
   * - :math:`s_i(h)`
     - ``saturation_excess_rate_from_balance()``
   * - :math:`R_i^{\text{steady}}`
     - ``assemble_steady_residual()``
   * - :math:`R_i^{\text{transient}}`
     - ``assemble_transient_residual()``
   * - :math:`R_i^{\text{flow}}(h, q^{\text{ex}})`
     - ``assemble_steady_residual_with_saturation_excess()`` /
       ``assemble_transient_residual_with_saturation_excess()``
   * - Fischer-Burmeister complementarity residual
     - ``_fischer_burmeister_residual_and_derivatives()`` in ``petsc_runtime.py``
   * - runtime solve
     - ``local_runtime.py`` / ``scipy_runtime.py`` /
       ``scipy_sparse_runtime.py`` / ``petsc_partition_runtime.py`` /
       ``petsc_runtime.py``
   * - problem orchestration
     - ``boussinesq.py``

Interpretation And Current Limits
---------------------------------

The current backend is still best viewed as a finite-volume Boussinesq solver
under active validation rather than as a finished production groundwater
platform. The important point, however, is that the implementation is no
longer limited to one dense prototype path.

Today:

- dense prototype runtimes still exist (``local`` and ``scipy``),
- a cross-platform sparse Newton path exists in ``scipy_sparse``,
- two Linux/PETSc sparse paths exist:

  - head-only regularized partition,
  - mixed complementarity with explicit :math:`q^{\text{ex}}`,

- committed real unstructured meshes are now exercised in addition to the
  small analytical and numerical validation strips.
- committed mesh bundles can receive explicit launcher-side overrides of
  :math:`K` and :math:`S_y`, including heterogeneous mappings through domain
  supports, without requiring a separate remeshing workflow.

The main current limits are elsewhere:

- the regularized-partition closure is still a pragmatic groundwater/surface
  release law, not a full coupled overland-flow model,
- the PETSc runtimes currently run on ``PETSc.COMM_SELF`` rather than a
  distributed MPI decomposition,
- the mixed complementarity path is validated on targeted overflow and real
  cases, but its benchmark envelope is still smaller than that of the
  head-only regularized-partition path.

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
