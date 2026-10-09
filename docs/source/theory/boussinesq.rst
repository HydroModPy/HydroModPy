Boussinesq theory
=================

This page gives the equations of the in-house Boussinesq solver, in the order the
code applies them, with what they assume and where they stop being true. It does not
say how to set up a run: the solvers and what each supports are in :doc:`../reference/solvers`.

The solver is not a MODFLOW wrapper. It writes one mass balance per triangular cell
of a 2D mesh, with the hydraulic head as the unknown. The shallow-groundwater
equation it solves descends from :cite:`boussinesq1877` and :cite:`boussinesq1904`,
which build on the Dupuit assumptions :cite:`dupuit1863`. A textbook treatment is
:cite:`brutsaert2005`. The full list of references is on :doc:`bibliography`.

.. note::

   **Scope.** The solver is chosen with
   :toml:`solvers|simulation.process.solvers` in a flow process. It runs one layer
   on a triangular mesh. It reads the conductivity and the specific yield, and
   nothing else about the ground. It builds recharge, wells, imposed heads on the
   sides, on the streams and on the ocean, and a top drain. A file that asks for
   another term is refused (see `Limits`_). Set :toml:`solver.backend` to
   ``boussinesq`` as well as the process: only then is the file checked against this
   solver when it is read.

The page follows the code. The notation comes first. Then the residual of one cell
is built term by term, then the three ways the solver treats water that reaches the
land surface or the bottom of the aquifer, then the engines that solve the
resulting nonlinear system. The assumptions, the limits and the map from each
equation to its function close the page.

Notation
--------

Every quantity is per cell :math:`i`, or per edge :math:`e` between two cells, unless
the table says otherwise. Lengths are in metres, times in seconds, rates in m/s.
Every symbol of the site is on :doc:`notation`.

.. dropdown:: Notation of this page

   .. hmp-notation::

The residual of a cell is in m\ :sup:`3`/s. The recharge and the two surface rates
are in m/s, so they enter the balance multiplied by the area :math:`a_i`.

From the continuous equation to one residual per cell
-----------------------------------------------------

The continuous problem is the Boussinesq equation for the water table of an
unconfined aquifer under the Dupuit assumptions. The flow is horizontal, the head
is the same over the whole saturated thickness, and the gradient that drives the
flow is the slope of the water table:

.. math::

   S_y\,\frac{\partial h}{\partial t}
   = \nabla\cdot\bigl(K\,B(h)\,\nabla h\bigr) + N + \ldots

where :math:`B(h)` is the saturated thickness and the dots stand for the wells, the
drain and the release at the surface, which the next sections add. The solver does
not discretize this form. It integrates the balance over each triangle and writes
the flux through each edge with a two-point formula between the centroids: a
cell-centered finite-volume scheme with one head per cell. The space scheme is the
descriptor ``FV_TRI_CELL_CENTERED`` in ``discretization/space.py``.

The sign convention is the one of the code. A residual term that is positive removes
water from the cell. Recharge and injection therefore enter with a minus sign. A
converged solution satisfies :math:`R_i \approx 0` in every cell that is not
constrained.

1. Saturated thickness and transmissivity
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The nonlinear solver may try a head below the bottom of the aquifer or above the
land surface. The physical operators read it through a thickness that is always
admissible (``saturated_thickness_from_head`` and ``transmissivity_from_head`` in
``assembly/fluxes.py``):

.. math::

   B_i(h) = \min\bigl(\max(h_i - z_{\mathrm{bot},i},\ 0),\ H_i\bigr),
   \qquad
   T_i(h) = K_i\,B_i(h)

The thickness is zero for a head at or below the bottom, and :math:`H_i` for a head
at or above the land surface. A head above the land surface does not add
transmissivity. The mesh builder refuses a cell whose top is below its bottom: the
message says ``z_top_centroid must be >= z_bottom_centroid.``

2. Flow between two cells
~~~~~~~~~~~~~~~~~~~~~~~~~

Take an internal edge :math:`e` shared by cells :math:`a` and :math:`b`.
``internal_edge_flux_from_head`` defines one oriented flux, positive when water
leaves :math:`a` and enters :math:`b`:

.. math::
   :label: eq-bq-edge-flux

   q_e = -\tau_e\,(h_b - h_a),
   \qquad
   \tau_e = K^{H}_e\,\bar{B}_e\,\frac{L_e}{d_e}

where :math:`K^{H}_e = 2 / (1/K_a + 1/K_b)` is the harmonic mean of the two
conductivities, and zero if either is not positive. :math:`\bar{B}_e =
(B_a + B_b)/2` is the mean of the two saturated thicknesses. The distance
:math:`d_e` is floored at a tiny positive value so that a degenerate edge does not
divide by zero.

The flux enters the two cells with opposite signs, so water is conserved across
every edge (``accumulate_internal_flux_residual``):

.. math::

   R^{\mathrm{int}}_a \mathrel{+}= q_e,
   \qquad
   R^{\mathrm{int}}_b \mathrel{-}= q_e

The thickness of the edge is the arithmetic mean, not the thickness of the donor
cell. The flux therefore does not fall to zero when the cell that gives water is
dry. On a sloping substratum a dry cell can sit higher than its wet neighbour and
be asked to give water it does not hold. That is the case the lower obstacle
handles (see `The lower obstacle`_).

.. plot:: theory/figures/bq_stencil.py
   :alt: Two triangles with their centroids and shared edge, and the flow between them against the saturated thickness of the upper one.
   :caption: Left: the two cells of :eq:`eq-bq-edge-flux`, the shared edge of length
      :math:`L_e` and the distance :math:`d_e` between the centroids. Right: cell
      :math:`b` sits 6 m higher on the substratum and drains into :math:`a`, whose
      saturated thickness stays 5 m; the flow comes from ``internal_edge_flux_from_head``.
      Look at :math:`B_b = 0`: with the mean thickness the dry cell :math:`b` still gives
      water, where a donor thickness would give none.

3. Cells with an imposed head
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The solver imposes a head on cells, not on edges. Three kinds of boundary resolve
to a set of constrained cells :math:`j`, each with a head :math:`H^D_j` per stress
period (``forcing/dirichlet_support_resolution.py``):

- a side of the mesh (north, south, east, west): the owner cells of the boundary
  edges on that side;
- the streams: the owner cells of the edges the mesh tags as river;
- the ocean: the owner cells of boundary edges that are not river edges and whose
  land surface is at or below the ocean stage of the period.

A boundary can also name a support of the mesh with
:toml:`flow.bc.<name>.support_label`. The cells of that support are constrained
instead of the default ones.

Two boundaries that give different heads to the same cell are refused (the message
says ``overlaps another prescribed-head BC on cell``). An outer edge that carries
no boundary is a no-flow edge: no term couples it to anything.

On a constrained cell the head is overwritten by :math:`H^D_j` before any flux is
computed, and the row of the nonlinear system is replaced by the constraint itself
(``resolve_boundary_head_inputs`` and ``finalize_boundary_constrained_residual`` in
``assembly/inputs.py``):

.. math::

   h_j = H^D_j,
   \qquad
   \text{solver row of } j:\ h_j - H^D_j = 0,
   \qquad
   \Phi^D_j = -R_j

:math:`R_j` is the balance the cell would have had if it were free. The constraint
supplies :math:`\Phi^D_j = -R_j`, which is positive when water enters the model
through that cell. A constrained cell keeps its own storage, drain, recharge and
wells in :math:`R_j`, so these terms end up in the flux it exchanges with the
boundary.

Because the head is pinned at the centroid of the cell and not on the edge, the
solution at the boundary cell differs from the value on the edge by about the
gradient times half a cell. The note at the top of ``runtime_contract.py`` records
this choice and its size on the Dupuit test case.

The edge form of the same exchange exists in the code, for diagnostics only.
``boundary_head_edge_flux_from_head`` writes the flux between an edge at stage
:math:`H_e` and its owner cell :math:`a`:

.. math::

   q^{D}_{a,e} = -\tau_{a,e}\,(H_e - h_a),
   \qquad
   \tau_{a,e} = K_a\,B_a\,\frac{L_e}{d_{a,e}}

with :math:`d_{a,e}` the distance from the centroid to the middle of the edge. The
solve never uses it: the two ways of imposing a head are mutually exclusive in
``assembly/inputs.py``, and the facades in ``assembly/residual_facade.py`` pass
none. The driver rebuilds this flux afterwards to export the exchange by edge
(``assembly/boundary_flux_reconstruction.py``).

4. Recharge and wells
~~~~~~~~~~~~~~~~~~~~~

The recharge :math:`N_i` is a rate per unit of area. It is constant over a stress
period. It is either one number per period, the same on every cell, or one value
per cell when the file loads a recharge field. The volume rate that enters the cell
is :math:`a_i N_i`. A negative recharge is refused: the message says
``must be non-negative.`` In a transient run every period keeps its own value; in
a steady run the period takes :toml:`flow.sinks_sources.recharge.first_clim`
(:doc:`forcing`).

A well is a volume rate :math:`\Phi^{\mathrm{well}}_i`, positive for injection and
negative for pumping. It is placed on the triangle that contains its x and y
coordinates, in the one layer of the model. A well outside the mesh is refused. A
well in a layer other than the first, or addressed by a grid cell, is refused too.
Wells that fall in the same triangle add up.

5. The top drain
~~~~~~~~~~~~~~~~

The drain removes water only where the head is above the land surface
(``drainage_outflow_from_head``):

.. math::

   q^{\mathrm{drain}}_i = C_i\,\max\bigl(h_i - z_{\mathrm{top},i},\ 0\bigr)

It is an outflow, and enters the residual with a plus sign. The conductance
:math:`C_i` is the value of :toml:`flow.bc.drainage.value`, the same for every cell
in a given period. When that value is not positive, the code uses
:math:`C_i = K_i\,a_i` instead, which is the derivation :math:`K\,a/b` with a drain
bed of :math:`b = 1` m. The solver does not read
:toml:`solver.drain_bed_thickness_m`.

Two consequences follow from the code.

- The drain is never off. A run with no drainage boundary passes a conductance of
  zero, which selects the derivation. A cell whose head rises above the land
  surface always loses water through :math:`K_i a_i`.
- On a cell supported by the ocean, the driver sets the conductance to zero to
  silence the drain (``apply_ocean_drainage_mask`` in ``drivers/forcing.py``).
  Zero selects the derivation, so these cells drain with :math:`K_i a_i` instead of
  with the configured value.

The discharge that a calibration reads from this solver is the sum over the cells
of this drain flow (``extract_discharge_history`` in ``calibration_extractors.py``).
It does not include the release at the surface of the next section.

6. Storage and the time step
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A transient run adds a storage term, with a backward Euler time scheme. The volume
held by a cell is lower-bounded and not capped (``_stored_saturated_volume_m3`` in
``assembly/residuals.py``):

.. math::
   :label: eq-bq-storage

   M_i(h) = a_i\,S_{y,i}\,\max\bigl(h_i - z_{\mathrm{bot},i},\ 0\bigr)

and the term that enters the residual is

.. math::

   \frac{M_i(h^{\mathrm{new}}) - M_i(h^{\mathrm{old}})}{\Delta t}

Transmissivity uses the capped thickness :math:`B_i`; storage does not. Two reasons
explain the difference. A head below the bottom must not give a negative volume.
A head above the land surface, which the head-only closures allow, must keep the
memory of the previous step: with a capped volume, the change of storage over the
step would be lost.

Each stress period is one backward Euler step of length :math:`\Delta t`. The
forcing is constant over the period and is evaluated at the end of the step. The
solver does not read :toml:`simulation.time.substeps_per_period`. To integrate a
period in several steps, shorten the period, or use the substeps of the experimental
obstacle runtimes (see :doc:`/contribute/architecture/solver/boussinesq-engines`).

7. The residual of the steady and of the transient problem
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The steady problem has no storage term
(``_steady_raw_residual_from_spatial_terms``). For every free cell:

.. math::

   R_i^{\mathrm{steady}}(h)
   = R^{\mathrm{int}}_i(h)
   + q^{\mathrm{drain}}_i(h)
   + a_i\,s_i(h)
   - a_i\,N_i
   - \Phi^{\mathrm{well}}_i
   = 0

The transient problem adds the storage term at the new time level
(``_transient_raw_residual_from_spatial_terms``):

.. math::
   :label: eq-bq-transient-residual

   R_i^{\mathrm{transient}}(h^{\mathrm{new}})
   = \frac{M_i(h^{\mathrm{new}}) - M_i(h^{\mathrm{old}})}{\Delta t}
   + R^{\mathrm{int}}_i(h^{\mathrm{new}})
   + q^{\mathrm{drain}}_i(h^{\mathrm{new}})
   + a_i\,s_i(h^{\mathrm{new}})
   - a_i\,N_i
   - \Phi^{\mathrm{well}}_i
   = 0

:math:`s_i` is the release of water at the surface, which the next part defines.
The functions ``assemble_steady_residual`` and ``assemble_transient_residual`` in
``assembly/residual_facade.py`` build these two residuals. The variants with
``_with_saturation_excess`` take :math:`s_i` as an input instead of computing it,
which the mixed closure needs.

When the head stays above the bottom, the storage term is
:math:`a_i S_{y,i} (h_i^{\mathrm{new}} - h_i^{\mathrm{old}}) / \Delta t`. The two forms differ only when
a head crosses the bottom, which is where the lower bound matters.

8. The balance closes
~~~~~~~~~~~~~~~~~~~~~

The internal fluxes cancel in pairs. Summed over all cells, with
:math:`\Phi^D_j = -R_j` on the constrained cells and zero elsewhere, the solution
satisfies

.. math::

   \sum_i \Bigl[
   \frac{M_i(h^{\mathrm{new}}) - M_i(h^{\mathrm{old}})}{\Delta t}
   + q^{\mathrm{drain}}_i
   + a_i\,s_i
   - a_i\,N_i
   - \Phi^{\mathrm{well}}_i
   + \Phi^{D}_i
   \Bigr] = 0

The water that enters through recharge, wells and the constraints equals what
leaves through the drain and the surface release, plus the change of storage. In
the mixed closure the term :math:`-a_i q^{\mathrm{dry}}_i` joins the bracket (see
`The lower obstacle`_), and the comparison budget reads it as water that is
available (``_closure_residual`` in ``analysis/comparison/numerical_closure.py``).

What happens at the surface and at the bottom
---------------------------------------------

A cell can be full to the land surface, or empty down to the bottom. The head-only
residual above needs a rule for the water that cannot be stored. The solver offers
three families of rules. With the value ``auto``, every runtime except PETSc uses
the first.

The regularized partition
~~~~~~~~~~~~~~~~~~~~~~~~~

The ``regularized_partition`` closure keeps the head as the only unknown. It
releases water at the surface by a smooth function of the saturation, so that there
is no sharp on and off at the moment the cell is full
(``regularized_partition_surface_rate_from_balance`` in ``assembly/surface.py``).
The saturation ratio is

.. math::

   \sigma_i(h) = \frac{B_i(h)}{H_i},

and zero for a cell of zero thickness. The sum of the fluxes through the edges of the
cell is :math:`R^{\mathrm{int}}_i` (step 2). The water that arrives at the cell, per
unit of area, is the lateral inflow plus the recharge when this is positive:

.. math::

   \gamma_i = \max\!\left(-\frac{R^{\mathrm{int}}_i}{a_i} + \max(N_i, 0),\ 0\right)

and the release is

.. math::
   :label: eq-bq-partition

   s_i(h) = \exp\!\left(-\frac{1 - \sigma_i(h)}{\varepsilon_r}\right)\gamma_i

The radius :math:`\varepsilon_r` is a constant of the code, 0.05, set in
``boussinesq.py``. No key changes it. The code and the card of
:toml:`flow.surface_interaction_model` call this law a Marcais-style regularized
partition: it follows the regularized partition of seepage and subsurface flow of
:cite:t:`marcais2017`. The wells and the storage are not in :math:`\gamma_i`. The factor
in front of :math:`\gamma_i`:

.. plot:: theory/figures/bq_partition.py
   :alt: The release factor against the saturation of the cell, on a linear and a log scale, for three radii.
   :caption: The factor of :eq:`eq-bq-partition`, from
      ``regularized_partition_surface_rate_from_balance``. The dots are the saturations
      1, 0.95, 0.9, 0.8 and 0.5. Look at the left panel: the factor is 0.37 at 0.95 and
      0.14 at 0.9, so the release starts well before the cell is full. The right panel
      shows that it never reaches zero. The dotted and dash-dotted curves are the radii
      0.02 and 0.1, which no key sets.

A full cell releases the whole of what arrives. A cell that is nine tenths full
releases about one seventh of it. The factor is never exactly zero, so a cell that
is half full still releases a tiny share. This is a pragmatic law and not a model of
overland flow. It can keep a low-amplitude release active where a threshold law
would turn it off. The four runtimes of this method use the same law.

The complementarity closure
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``complementarity`` closure turns the surface into an exact threshold. It adds
one unknown per cell, the saturation excess :math:`q^{\mathrm{ex}}_i`, and replaces
:math:`s_i` by it. The head cannot rise above the land surface, and water is
released only when the head is at the surface:

.. math::

   0 \leq q^{\mathrm{ex}}_i \;\perp\; z_{\mathrm{top},i} - h_i \geq 0

that is, :math:`q^{\mathrm{ex}}_i \geq 0`, :math:`z_{\mathrm{top},i} - h_i \geq 0`, and
their product is zero. If the head is below the surface, nothing is released. If
something is released, the head is at the surface. The release is solved together
with the heads, so the balance and the threshold hold at the same time.

The code does not solve the inequalities. It turns each pair into one equation with
the Fischer-Burmeister function. For two scaled variables :math:`u` and :math:`v`,

.. math::

   \phi_\mathrm{FB}(u, v) = \sqrt{u^2 + v^2} - u - v

which is zero exactly when :math:`u \geq 0`, :math:`v \geq 0` and :math:`u v = 0`. The
rate is scaled by a rate :math:`q_s` and the gap by a length :math:`h_s`, so that
both arguments are of order one (``_complementarity_scales`` and
``_fischer_burmeister_residual_and_derivatives`` in
``runtimes/petsc_mixed_common.py``):

.. math::

   \phi_\mathrm{FB}\!\left(\frac{q^{\mathrm{ex}}_i}{q_s},\ \frac{z_{\mathrm{top},i} - h_i}{h_s}\right) = 0

The length :math:`h_s` is the thickest cell of the mesh, and at least 1 m. The rate
:math:`q_s` is the largest of the recharge, the well rate per unit of area, the
conductivity, and in a transient run :math:`S_y h_s / \Delta t`, with a floor of
:math:`10^{-12}` m/s. These scales are numerical. They change the conditioning of
the system and not its solution.

.. plot:: theory/figures/bq_fischer_burmeister.py
   :alt: Map of the Fischer-Burmeister function over the scaled release and the scaled gap, zero on the two positive half-axes.
   :caption: :math:`\phi_\mathrm{FB}` over the two scaled arguments, from
      ``_fischer_burmeister_residual_and_derivatives``. Look at the thick line, the only
      place where the function is zero: either no release and a head below the surface,
      or a release and a head at the surface. A negative release or a head above the
      surface gives a positive value (red), and a release with a head below the surface
      a negative one (blue).

A constrained cell does not release: its unknown :math:`q^{\mathrm{ex}}` is held at
zero.

.. _bq-lower-obstacle:

The lower obstacle
~~~~~~~~~~~~~~~~~~

The head must also stay at or above the bottom of the aquifer:

.. math::

   z_{\mathrm{bot},i} \leq h_i \leq z_{\mathrm{top},i}

The mixed closure enforces the lower bound with a second unknown per cell,
:math:`q^{\mathrm{dry}}_i`, and a second complementarity:

.. math::

   0 \leq q^{\mathrm{dry}}_i \;\perp\; h_i - z_{\mathrm{bot},i} \geq 0

with the same Fischer-Burmeister form in the scaled variables. The three unknowns
per cell are :math:`(h_i, q^{\mathrm{ex}}_i, q^{\mathrm{dry}}_i)`: the system has
three times as many unknowns as there are cells.

:math:`q^{\mathrm{dry}}_i` is not a leak through the substratum. It is a numerical
unmet demand. When a cell is empty, its balance may ask to remove more water than
the aquifer holds. :math:`q^{\mathrm{dry}}_i` cancels that excess so that the
storage cannot go below zero. It enters the balance of the cell with the sign
opposite to a removal (``_assembly_with_dry_deficit`` in
``runtimes/petsc_mixed.py``):

.. math::

   R_i \leftarrow R_i - a_i\,q^{\mathrm{dry}}_i

If a cell sits at :math:`h_i = z_{\mathrm{bot},i}`, the term offsets the remaining
demand and does not add water through a physical boundary. It is not a flux of the
water budget of the catchment. The comparison budget counts it as available water
only to close the balance of the cells.

The head-only closures have no explicit lower constraint. Their transmissivity
uses the capped thickness, their storage is lower-bounded, and the run reports
whether the accepted heads went below the bottom (the diagnostics are listed on
:doc:`/contribute/architecture/solver/boussinesq-engines`).

One cell, by hand
~~~~~~~~~~~~~~~~~

The test ``test_single_cell_pumping_activates_lower_obstacle`` in
``tests/validation/numerical/transient/test_boussinesq_drying_petsc.py`` runs one
isolated cell. Its area is 1 m\ :sup:`2`, the bottom is at 0 m, the top at 2 m,
:math:`S_y = 0.2`. It starts at :math:`h = 0.1` m, with no recharge, and a well
pumps :math:`0.01` m\ :sup:`3`/s for one step of :math:`\Delta t = 10` s.

For a head above the bottom, the residual is

.. math::

   R(h) = \frac{0.2\,h - 0.2 \times 0.1}{10} + 0.01 = 0.02\,h + 0.008

It reaches zero at :math:`h = -0.4` m, which is below the bottom: no admissible head
balances the cell. At the bottom the storage term is :math:`-0.002` m\ :sup:`3`/s and
the residual is :math:`R = 0.008` m\ :sup:`3`/s. The second complementarity gives
:math:`h = 0` and :math:`a\,q^{\mathrm{dry}} = 0.008`, so

.. math::

   q^{\mathrm{dry}} = 0.008\ \text{m/s}

which is the value the test asserts. The well asked for 0.01 m\ :sup:`3`/s, the
aquifer could give 0.002 m\ :sup:`3`/s from storage, and the other 0.008 is the
unmet demand.

.. plot:: theory/figures/bq_lower_obstacle.py
   :alt: Residual of the one cell against its head, and the split of the pumped rate between storage and unmet demand.
   :caption: The cell of the test. Left: its residual against the head, from the assembly of
      the code. Without a floor on the storage (dotted), the balance reaches zero at
      :math:`h = -0.4` m (cross), below the bottom. The code's storage stops at the
      bottom, so :math:`R` stays at 0.008 there and has no root. The obstacle subtracts
      :math:`a\,q^\mathrm{dry}` (dashed) and puts the solution at :math:`h = 0` (dot).
      Right: of the 0.01 m\ :sup:`3`/s pumped, 0.002 comes from storage and 0.008 is
      unmet. :math:`q^\mathrm{dry}` is the value the test asserts, since the PETSc
      solve does not run at build time.

.. _bq-methods-engines:

Methods and engines
-------------------

Two choices are independent. The method is the physics: the unknowns and the closure
of the surface. The engine is the numerics: the nonlinear solver, the Jacobian and the
linear solver. :toml:`flow.surface_interaction_model` picks the closure and
:toml:`flow.runtime_backend` the engine; the pair resolves to one method:

.. list-table::
   :header-rows: 1
   :widths: 30 24 22 24

   * - Method
     - Unknowns
     - Closure
     - Runtime backends
   * - ``head_only_regularized_partition``
     - :math:`h`
     - ``regularized_partition``
     - ``local``, ``scipy``, ``scipy_sparse``, ``petsc``
   * - ``mixed_complementarity``
     - :math:`h, q^{\mathrm{ex}}, q^{\mathrm{dry}}`
     - ``complementarity``
     - ``petsc``
   * - ``head_only_vi_obstacle``
     - :math:`h`
     - ``vi_obstacle``, experimental
     - ``petsc``
   * - ``head_only_ts_vi_obstacle``
     - :math:`h`
     - ``ts_vi_obstacle``, experimental
     - ``petsc``

With ``auto``, the closure is ``complementarity`` on PETSc and
``regularized_partition`` on every other backend. A closure that the backend does not
implement is refused when the solve starts. Every engine stops when the largest entry
of the solver residual is below :toml:`flow.runtime_tol_residual_inf`; a step that does
not converge ends the run.

- ``local`` is a damped Newton loop with a dense Jacobian by finite differences,
  written to be read. It refuses a mesh of more than 400 cells.
- ``scipy`` hands the same residual and a dense semi-analytic Jacobian to
  ``scipy.optimize.root``. It has the same limit of 400 cells.
- ``scipy_sparse`` runs the Newton loop of ``local`` on a sparse Jacobian. It is the
  reference engine for larger meshes on every system.
- ``petsc`` solves with PETSc SNES on a sparse Jacobian, on Linux only and in serial. It
  is the only engine of the mixed closure and of the two experimental obstacle
  closures.

Each engine step by step, the experimental closures and the diagnostics a run writes
are on :doc:`/contribute/architecture/solver/boussinesq-engines`.

.. code-block:: toml
   :caption: The two keys that choose the method and the engine

   base_config = "step4_transient.toml"

   [solver]
   backend = { backend = "boussinesq" }

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["boussinesq"]

   # The rivers the mesh follows: every cell that drains more than 0.5 km2.
   [geographic.river_network]
   enabled = true
   threshold_area_km2 = 0.5

   [mesh_catchment]
   constraints_mode = "rivers_only"
   cache = true

   [flow]
   runtime_backend = "scipy_sparse"
   surface_interaction_model = "regularized_partition"

The mesh section is the one the solver needs: it reads a triangular mesh, from
:toml:`mesh_catchment` or from :toml:`mesh_input`. For the mixed closure, write
``runtime_backend = "petsc"`` and ``surface_interaction_model = "complementarity"``.

The starting state and the time loop
------------------------------------

The transient driver loops over the stress periods. At each period it takes the
forcing of the period, the heads of the previous period as the previous state and as
the initial guess, and solves one step. The first period is a transient step like the
others: the solver does not read :toml:`flow.first_period_steady`.

The initial heads come from :toml:`flow.ic.h.type`. With ``steady_state``, the solver
first runs one steady solve with the same method, under the time-mean recharge or
under the rate of :toml:`flow.ic.h.rate`, with the boundary heads of the first period.
It starts the transient from the result. Cyclic spin-up and :toml:`flow.restart_from`
are not implemented for this solver and the file is refused when it asks for them.
In the code: ``run_transient_runtime``.

Assumptions
-----------

- **Dupuit.** The flow is horizontal. The head is uniform over the saturated
  thickness and the gradient is that of the water table. There is no vertical
  resistance.
- **One layer.** The aquifer is one cell thick. Its top and bottom are the values
  sampled at the centroid of the triangle and are flat inside the cell.
- **One conductivity and one specific yield per cell**, isotropic in the plane. The
  solver reads no specific storage, no anisotropy and no porosity.
- **Two-point flux.** The flux through an edge depends on the two heads next to it.
  The formula is consistent where the line between the two centroids is
  perpendicular to the edge, and loses accuracy where it is not. The solver has no
  correction for skewed cells.
- **Arithmetic mean of the thickness** on an edge, harmonic mean of the
  conductivity.
- **Forcing constant over a stress period**, evaluated at the end of the step.
- **Backward Euler**, one step per stress period, with no substeps in the head-only
  methods.
- **A closure for the surface that is a model choice.** The regularized partition is
  a smooth release law. The complementarity closure is an exact threshold. Neither
  routes the water over the land.
- **Constant radius of the regularization**, 0.05.
- **Imposed heads on cell centres.**

Limits
------

- **Triangles only.** A mesh with another cell shape is refused: the message says
  ``Boussinesq V1 currently supports only triangular cells``.
- **Supported terms.** Recharge, wells, side, stream and ocean imposed heads, and
  the top drain. A file that activates anything else in
  :toml:`flow.active_sinks_sources` or :toml:`flow.active_bc` is refused: ETP, lakes
  and reservoirs, stream routing, flow barriers. The soil reservoir is wired to
  MODFLOW 6 only. A file with a ``[transport]`` section and this solver is refused
  when it is read.
- **Wells by coordinates.** A well addressed by a cell of a structured grid, or in a
  layer other than the first, is refused.
- **Recharge is non-negative.** A series with a negative value is refused.
- **Boundary bias.** A constrained cell is pinned at its centroid. Near a boundary
  with a strong gradient, the head differs from the edge value by the gradient times
  half a cell. Refine the mesh near the boundary to reduce it.
- **The drain cannot be switched off**, and the ocean mask on the drain does not
  silence it (see `5. The top drain`_). A calibration of the discharge reads the
  drain and not the release at the surface.
- **Dense engines are limited to 400 cells**, ``local`` and ``scipy``.
- **PETSc is Linux only, serial**, and needs ``petsc4py``.
- **One step per period.** A stress period that does not converge ends the run. The
  solver reads no substeps per period. The experimental obstacle runtimes can
  substep.
- **No restart, no cyclic spin-up.** The starting state is the top, an offset below
  it, the bottom, a custom level, or a steady solve of the same solver.
- **What can be read back.** The solver serves the head at a cell, the discharge
  over the domain, and the release per cell. It has no lake stage and no routed
  discharge, because it has no lake package and no stream reaches.
- **Experimental.** The cards of :toml:`flow.runtime_backend` and
  :toml:`flow.surface_interaction_model` are marked experimental, and the
  description of the obstacle closures says so too.
- **Not a model of overland flow.** The water released at the surface leaves the
  model. It is not routed downhill.

The status of the solver against the analytic cases is on :doc:`validation`. How it
compares with MODFLOW 6 and MODFLOW-NWT is on :doc:`solvers`.

Parameters of this page
-----------------------

The keys below set the terms of the equations and the choice of the method and of
the engine. Open a row for its card.

.. hmp-params::

   simulation.process.solvers
   flow.flow_regime
   flow.runtime_backend
   flow.surface_interaction_model
   flow.runtime_max_iterations
   flow.runtime_tol_residual_inf
   flow.runtime_tol_state_update_inf
   flow.param.K.field.value
   flow.param.Sy.field.value
   flow.sinks_sources.recharge.values
   flow.sinks_sources.recharge.first_clim
   flow.sinks_sources.wells.<name>.flux
   flow.bc.drainage.value
   flow.bc.stream.value
   flow.ic.h.type
   flow.ic.h.source
   flow.ic.h.rate
   flow.bc.<name>.support_label
   flow.sinks_sources.recharge.heterogeneous_source

A drain with a stated conductance, and a starting state that is a steady solve of the
same solver:

.. code-block:: toml

   base_config = "step4_transient.toml"

   [solver]
   backend = { backend = "boussinesq" }

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["boussinesq"]

   # The rivers the mesh follows: every cell that drains more than 0.5 km2.
   [geographic.river_network]
   enabled = true
   threshold_area_km2 = 0.5

   [mesh_catchment]
   constraints_mode = "rivers_only"
   cache = true

   [flow]
   active_bc = ["drainage"]

   [flow.bc.drainage]
   value = 1e-3

   [flow.ic.h]
   type = "steady_state"

Checked by
----------

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

.. hmp-tested-by::

   hydromodpy.solver.boussinesq.assembly
   hydromodpy.solver.boussinesq.methods
   hydromodpy.solver.boussinesq.engines
   hydromodpy.solver.boussinesq.runtimes
   hydromodpy.solver.boussinesq.forcing
   hydromodpy.solver.boussinesq.drivers
   hydromodpy.solver.boussinesq.boussinesq

In the code
-----------

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - What
     - Where
   * - Thickness, transmissivity, internal fluxes, drain
     - ``hydromodpy/solver/boussinesq/assembly/fluxes.py`` (``saturated_thickness_from_head``, ``transmissivity_from_head``, ``harmonic_conductivity``, ``internal_edge_flux_from_head``, ``accumulate_internal_flux_residual``, ``drainage_outflow_from_head``)
   * - Constrained cells and the solver row
     - ``hydromodpy/solver/boussinesq/assembly/inputs.py`` (``resolve_boundary_head_inputs``, ``finalize_boundary_constrained_residual``)
   * - Edge exchange, for diagnostics
     - ``hydromodpy/solver/boussinesq/assembly/fluxes.py`` (``edge_to_stage_tau_from_head``, ``boundary_head_edge_flux_from_head``), ``assembly/boundary_flux_reconstruction.py``
   * - Steady and transient residual
     - ``hydromodpy/solver/boussinesq/assembly/residuals.py`` (``assemble_spatial_terms``, ``_stored_saturated_volume_m3``), facades in ``assembly/residual_facade.py``
   * - Regularized partition
     - ``hydromodpy/solver/boussinesq/assembly/surface.py`` (``regularized_partition_surface_rate_from_balance``, ``resolve_saturation_excess_rate``)
   * - Fischer-Burmeister function and scales
     - ``hydromodpy/solver/boussinesq/runtimes/petsc_mixed_common.py`` (``_fischer_burmeister_residual_and_derivatives``, ``_complementarity_scales``)
   * - Mixed system, dry deficit
     - ``hydromodpy/solver/boussinesq/runtimes/petsc_mixed.py`` (``_solve_mixed_problem``, ``_assembly_with_dry_deficit``)
   * - Method and engine choice
     - ``hydromodpy/solver/boussinesq/methods/catalog.py`` (``resolve_method_spec``), ``engines/catalog.py`` (``resolve_engine_spec``), ``runtime_selection.py``
   * - Time loop
     - ``hydromodpy/solver/boussinesq/drivers/transient.py`` (``run_transient_runtime``), ``drivers/steady.py`` (``run_steady_runtime``)
   * - Forcing, wells, imposed heads, drain
     - ``hydromodpy/solver/boussinesq/forcing/`` (``recharge_resolution.py``, ``well_resolution.py``, ``dirichlet_support_resolution.py``, ``drainage_resolution.py``), ``drivers/forcing.py``
   * - Mesh and properties
     - ``hydromodpy/solver/boussinesq/mesh.py``, ``_mesh_builders.py``, ``property_mapping.py``
   * - Supported subset, options
     - ``hydromodpy/solver/boussinesq/solver_contract.py`` (``assert_supported_runtime_subset``, ``build_runtime_options``)
   * - Diagnostics, export, calibration reader
     - ``hydromodpy/solver/boussinesq/runtime_summary.py``, ``export_payload.py``, ``calibration_extractors.py``
   * - Earlier derivation notes, in LaTeX, not built into the site
     - ``hydromodpy/solver/boussinesq/boussinesq_math_notes.tex``

See also
--------

- :doc:`../reference/solvers`: the solvers and what each supports.
- :doc:`groundwater-flow`: the discrete problem of the three solvers side by side.
- :doc:`solvers`: what each solver does with the same file.
- :doc:`mf6-vs-nwt`: the two MODFLOW solvers against each other.
- :doc:`validation`: the checks against closed-form solutions.
- :doc:`notation`: the symbols used on every theory page.
- :doc:`/contribute/architecture/solver/boussinesq-engines`: the engines step by step,
  the experimental closures and the diagnostics of a run.
- :doc:`/contribute/architecture/solver/boussinesq-uml-diagrams`: the module
  diagrams of the solver.
- :doc:`bibliography`: the references.
