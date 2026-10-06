Boussinesq theory
=================

This page gives the equations of the in-house Boussinesq solver, in the order the
code applies them, with what they assume and where they stop being true. It does not
say how to set up a run: for that, see :doc:`../guides/choose-a-solver`.

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
The symbols follow :doc:`notation`.

.. list-table::
   :header-rows: 1
   :widths: 16 44 12 28

   * - Symbol
     - Meaning
     - Unit
     - Read from
   * - :math:`h_i`
     - hydraulic head of the cell, the unknown
     - m
     - state, not a field
   * - :math:`a_i`
     - area of the triangle
     - m\ :sup:`2`
     - the mesh, not a field
   * - :math:`z^{\mathrm{top}}_i`, :math:`z^{\mathrm{bot}}_i`
     - land surface and bottom of the aquifer, sampled at the centroid of the cell
     - m
     - :toml:`data.dem` and :toml:`domain.depth_model`
   * - :math:`H_i`
     - thickness of the cell, :math:`z^{\mathrm{top}}_i - z^{\mathrm{bot}}_i`
     - m
     - derived
   * - :math:`K_i`
     - hydraulic conductivity
     - m/s
     - :toml:`K|flow.param.K.field.value`
   * - :math:`S_{y,i}`
     - specific yield, the storage coefficient of the solver
     - \-
     - :toml:`Sy|flow.param.Sy.field.value`
   * - :math:`B_i`
     - saturated thickness, clipped to the cell
     - m
     - derived
   * - :math:`T_i`
     - transmissivity, :math:`K_i B_i`
     - m\ :sup:`2`/s
     - derived
   * - :math:`L_e`, :math:`d_e`
     - length of the edge, distance between the two centroids
     - m
     - the mesh, not a field
   * - :math:`\tau_e`
     - transmissive factor of the edge
     - m\ :sup:`2`/s
     - derived
   * - :math:`q_e`
     - flux through an internal edge, positive from cell :math:`a` to cell :math:`b`
     - m\ :sup:`3`/s
     - derived
   * - :math:`H^D_j`
     - imposed head of a constrained cell :math:`j`
     - m
     - :toml:`flow.bc.stream.value`, and the side and ocean boundaries
   * - :math:`\Phi^D_j`
     - flux the constraint supplies to cell :math:`j`, positive into the cell
     - m\ :sup:`3`/s
     - derived
   * - :math:`N_i`
     - recharge rate, positive into the aquifer
     - m/s
     - :toml:`flow.sinks_sources.recharge.values`
   * - :math:`\Phi^{\mathrm{well}}_i`
     - well rate, positive for injection
     - m\ :sup:`3`/s
     - :toml:`flux|flow.sinks_sources.wells.<name>.flux`
   * - :math:`C_i`
     - conductance of the top drain
     - m\ :sup:`2`/s
     - :toml:`flow.bc.drainage.value`
   * - :math:`q^{\mathrm{drain}}_i`
     - flow leaving through the top drain
     - m\ :sup:`3`/s
     - derived
   * - :math:`\Delta t`
     - length of a stress period, one time step of the solver
     - s
     - :toml:`simulation.time.step_value`
   * - :math:`M_i`
     - drainable volume held by the cell
     - m\ :sup:`3`
     - derived
   * - :math:`R_i`
     - residual of the balance, positive when the cell loses water
     - m\ :sup:`3`/s
     - derived
   * - :math:`s_i`
     - release of water at the surface, regularized closure
     - m/s
     - derived
   * - :math:`\sigma_i`
     - saturation ratio, :math:`B_i / H_i`
     - \-
     - derived
   * - :math:`\varepsilon`
     - radius of the regularization
     - \-
     - constant of the code, not a field (see `The regularized partition`_)
   * - :math:`q^{\mathrm{ex}}_i`
     - saturation excess released at the surface, an unknown of the mixed closure
     - m/s
     - state, not a field
   * - :math:`q^{\mathrm{dry}}_i`
     - unmet demand at the bottom of the aquifer, an unknown of the mixed closure
     - m/s
     - state, not a field

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

   B_i(h) = \min\bigl(\max(h_i - z^{\mathrm{bot}}_i,\ 0),\ H_i\bigr),
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
``must be non-negative.`` When the series has one value per period, the first stress period does not take its
own value. It takes the policy of :toml:`flow.sinks_sources.recharge.first_clim`,
whatever that policy is.

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

   q^{\mathrm{drain}}_i = C_i\,\max\bigl(h_i - z^{\mathrm{top}}_i,\ 0\bigr)

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

   M_i(h) = a_i\,S_{y,i}\,\max\bigl(h_i - z^{\mathrm{bot}}_i,\ 0\bigr)

and the term that enters the residual is

.. math::

   \frac{M_i(h^{n+1}) - M_i(h^{n})}{\Delta t}

Transmissivity uses the capped thickness :math:`B_i`; storage does not. Two reasons
explain the difference. A head below the bottom must not give a negative volume.
A head above the land surface, which the head-only closures allow, must keep the
memory of the previous step: with a capped volume, the change of storage over the
step would be lost.

Each stress period is one backward Euler step of length :math:`\Delta t`. The
forcing is constant over the period and is evaluated at the end of the step. The
solver does not read :toml:`simulation.time.substeps_per_period`. To integrate a
period in several steps, shorten the period, or use the substeps of the experimental
obstacle runtimes (see `The experimental obstacle closures`_).

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

   R_i^{\mathrm{transient}}(h^{n+1})
   = \frac{M_i(h^{n+1}) - M_i(h^{n})}{\Delta t}
   + R^{\mathrm{int}}_i(h^{n+1})
   + q^{\mathrm{drain}}_i(h^{n+1})
   + a_i\,s_i(h^{n+1})
   - a_i\,N_i^{\,n+1}
   - \Phi^{\mathrm{well},\,n+1}_i
   = 0

:math:`s_i` is the release of water at the surface, which the next part defines.
The functions ``assemble_steady_residual`` and ``assemble_transient_residual`` in
``assembly/residual_facade.py`` build these two residuals. The variants with
``_with_saturation_excess`` take :math:`s_i` as an input instead of computing it,
which the mixed closure needs.

When the head stays above the bottom, the storage term is
:math:`a_i S_{y,i} (h_i^{n+1} - h_i^{n}) / \Delta t`. The two forms differ only when
a head crosses the bottom, which is where the lower bound matters.

8. The balance closes
~~~~~~~~~~~~~~~~~~~~~

The internal fluxes cancel in pairs. Summed over all cells, with
:math:`\Phi^D_j = -R_j` on the constrained cells and zero elsewhere, the solution
satisfies

.. math::

   \sum_i \Bigl[
   \frac{M_i(h^{n+1}) - M_i(h^{n})}{\Delta t}
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

   \beta_i = \max\!\left(-\frac{R^{\mathrm{int}}_i}{a_i} + \max(N_i, 0),\ 0\right)

and the release is

.. math::

   s_i(h) = \exp\!\left(-\frac{1 - \sigma_i(h)}{\varepsilon}\right)\beta_i

The radius :math:`\varepsilon` is a constant of the code, 0.05, set in
``boussinesq.py``. No key changes it. The code and the card of
:toml:`flow.surface_interaction_model` call this law a Marcais-style regularized
partition. The wells and the storage are not in :math:`\beta_i`. The factor
in front of :math:`\beta_i` takes these values:

.. list-table::
   :header-rows: 1
   :widths: 30 30

   * - Saturation :math:`\sigma_i`
     - Factor :math:`\exp(-(1-\sigma_i)/\varepsilon)`
   * - 1.0
     - 1
   * - 0.95
     - 0.37
   * - 0.9
     - 0.14
   * - 0.8
     - 0.018
   * - 0.5
     - 4.5e-5

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

   0 \leq q^{\mathrm{ex}}_i \;\perp\; z^{\mathrm{top}}_i - h_i \geq 0

that is, :math:`q^{\mathrm{ex}}_i \geq 0`, :math:`z^{\mathrm{top}}_i - h_i \geq 0`, and
their product is zero. If the head is below the surface, nothing is released. If
something is released, the head is at the surface. The release is solved together
with the heads, so the balance and the threshold hold at the same time.

The code does not solve the inequalities. It turns each pair into one equation with
the Fischer-Burmeister function. For two scaled variables :math:`u` and :math:`v`,

.. math::

   \phi(u, v) = \sqrt{u^2 + v^2} - u - v

which is zero exactly when :math:`u \geq 0`, :math:`v \geq 0` and :math:`u v = 0`. The
rate is scaled by a rate :math:`q_s` and the gap by a length :math:`h_s`, so that
both arguments are of order one (``_complementarity_scales`` and
``_fischer_burmeister_residual_and_derivatives`` in
``runtimes/petsc_mixed_common.py``):

.. math::

   \phi\!\left(\frac{q^{\mathrm{ex}}_i}{q_s},\ \frac{z^{\mathrm{top}}_i - h_i}{h_s}\right) = 0

The length :math:`h_s` is the thickest cell of the mesh, and at least 1 m. The rate
:math:`q_s` is the largest of the recharge, the well rate per unit of area, the
conductivity, and in a transient run :math:`S_y h_s / \Delta t`, with a floor of
:math:`10^{-12}` m/s. These scales are numerical. They change the conditioning of
the system and not its solution.

A constrained cell does not release: its unknown :math:`q^{\mathrm{ex}}` is held at
zero.

The lower obstacle
~~~~~~~~~~~~~~~~~~

The head must also stay at or above the bottom of the aquifer:

.. math::

   z^{\mathrm{bot}}_i \leq h_i \leq z^{\mathrm{top}}_i

The mixed closure enforces the lower bound with a second unknown per cell,
:math:`q^{\mathrm{dry}}_i`, and a second complementarity:

.. math::

   0 \leq q^{\mathrm{dry}}_i \;\perp\; h_i - z^{\mathrm{bot}}_i \geq 0

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

If a cell sits at :math:`h_i = z^{\mathrm{bot}}_i`, the term offsets the remaining
demand and does not add water through a physical boundary. It is not a flux of the
water budget of the catchment. The comparison budget counts it as available water
only to close the balance of the cells.

The head-only closures have no explicit lower constraint. Their transmissivity
uses the capped thickness, their storage is lower-bounded, and the run reports
whether the accepted heads went below the bottom (see `What the run reports`_).

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

The experimental obstacle closures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Two more closures exist and are marked experimental on their cards. Both run on
PETSc only, and both keep the head as the only unknown.

- ``vi_obstacle`` solves the balance with the head bounded between the bottom and
  the land surface, as a variational inequality (PETSc SNESVI). The release is not
  in the system: :math:`s_i = 0` while the solver iterates. After convergence, the
  balance left on a cell at its upper bound is read as the saturation excess, and
  on a cell at its lower bound as the unmet demand (``reconstruct_obstacle_reactions``
  in ``runtimes/petsc_vi/obstacle.py``):

  .. math::

     q^{\mathrm{ex}}_i = \frac{\max(-R_i,\ 0)}{a_i},
     \qquad
     q^{\mathrm{dry}}_i = \frac{\max(R_i,\ 0)}{a_i}

  The first expression is used on a cell at its upper bound and the second on a cell
  at its lower bound. The upper bound is relaxed when a positive drain conductance
  is declared, so that the drain carries the exchange at the surface
  (``runtimes/vi_bounds.py``). The stress period can be cut into substeps, with
  :toml:`flow.vi_substeps_per_period`, and a failed period can be retried with more
  substeps.
- ``ts_vi_obstacle`` hands the time stepping to PETSc TS with a backward Euler
  scheme, inside each stress period, and keeps the same bounds. The storage term is
  :math:`a_i S_{y,i}\,\dot h_i`, because the head is bounded. The number of steps and
  the adaptivity are set by the ``ts_vi_*`` keys listed at the end of the page.

A steady solve for the initial state of a ``ts_vi_obstacle`` run uses the regularized
partition (``steady_state_initialization_surface_interaction_model`` in
``solver/steady_initial_conditions.py``).

What the run reports
~~~~~~~~~~~~~~~~~~~~

The run writes ``_boussinesq_state_history.npz`` and ``_boussinesq_summary.json`` in
the solver folder. The summary carries diagnostics of the surface and of the bottom,
computed on the accepted snapshots (``runtime_summary.py``):

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Key family
     - Meaning
   * - ``surface_threshold_*``
     - Cells where the surface release is active, the number of windows in which it
       turns on and off, the peak rate and the peak head above the surface.
   * - ``bottom_threshold_*``
     - Accepted heads below the bottom of the aquifer, and the negative storage
       volume they would imply.
   * - ``bottom_constraint_*``
     - Cells where the dry deficit is active, its peak rate and its integrated
       volume.
   * - ``dry_deficit_history_m_s``
     - The state history of :math:`q^{\mathrm{dry}}`, in the npz file.

Read the dry deficit apart from the discharge terms. It says where the bottom
constraint was active and how much demand the storage could not meet.

From closure to solver: methods and engines
-------------------------------------------

Two choices are independent. The method is the physics: the unknowns, the closure,
the space scheme and the time scheme. The engine is the numerics: the nonlinear
solver, the matrix layout, the Jacobian and the linear solver. Two runs can share a
method and differ by the engine. The keys are
:toml:`flow.surface_interaction_model` for the closure and
:toml:`flow.runtime_backend` for the engine.

The method
~~~~~~~~~~

The closure and the runtime backend resolve to one method
(``resolve_method_spec`` in ``methods/catalog.py``):

.. list-table::
   :header-rows: 1
   :widths: 28 18 18 18 18

   * - Method
     - Unknowns
     - Closure
     - Time scheme
     - Runtime backends
   * - ``head_only_regularized_partition``
     - :math:`h`
     - ``regularized_partition``
     - steady, backward Euler
     - ``local``, ``scipy``, ``scipy_sparse``, ``petsc``
   * - ``mixed_complementarity``
     - :math:`h, q^{\mathrm{ex}}, q^{\mathrm{dry}}`
     - ``complementarity``
     - steady, backward Euler
     - ``petsc``
   * - ``head_only_vi_obstacle``
     - :math:`h`
     - ``vi_obstacle``
     - steady, backward Euler
     - ``petsc``
   * - ``head_only_ts_vi_obstacle``
     - :math:`h`
     - ``ts_vi_obstacle``
     - backward Euler
     - ``petsc``

With ``auto``, the closure is ``complementarity`` on PETSc and
``regularized_partition`` on every other backend. A closure that the backend does
not implement is refused when the solve starts: the message says
``The requested Boussinesq surface-interaction model is not implemented``. The
space scheme is the same for all four methods.

.. code-block:: toml
   :caption: The two keys that choose the method and the engine

   base_config = "step4_transient.toml"

   [solver]
   backend = { backend = "boussinesq" }

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["boussinesq"]

   [mesh_catchment]
   constraints_mode = "rivers_only"
   cache = true

   [flow]
   runtime_backend = "scipy_sparse"
   surface_interaction_model = "regularized_partition"

The block selects the solver and the closure. The mesh section is the one the
solver needs: it reads a triangular mesh, from :toml:`mesh_catchment` or from
:toml:`mesh_input`. Example 04 as shipped runs on MODFLOW 6.

The same file with the mixed closure:

.. code-block:: toml

   base_config = "step4_transient.toml"

   [solver]
   backend = { backend = "boussinesq" }

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["boussinesq"]

   [mesh_catchment]
   constraints_mode = "rivers_only"
   cache = true

   [flow]
   runtime_backend = "petsc"
   surface_interaction_model = "complementarity"

The pair below loads, and the run then refuses it, because the complementarity
closure is implemented only on PETSc:

.. code-block:: toml

   # not checked: shows a pair that loads and that the run refuses
   base_config = "step4_transient.toml"

   [solver]
   backend = { backend = "boussinesq" }

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["boussinesq"]

   [flow]
   runtime_backend = "scipy_sparse"
   surface_interaction_model = "complementarity"

The engine
~~~~~~~~~~

The runtime backends are numerical engines for one method. They are not separate
hydrological models. The rows are the pairs of the engine catalog
(``engines/catalog.py``):

.. list-table::
   :header-rows: 1
   :widths: 14 22 22 22 20

   * - Backend
     - Method
     - Nonlinear solver
     - Jacobian
     - Linear solver
   * - ``local``
     - head-only partition
     - damped Newton, dense
     - forward finite differences
     - NumPy dense solve
   * - ``scipy``
     - head-only partition
     - SciPy ``root``, method ``hybr``
     - semi-analytic, dense
     - MINPACK ``hybr``
   * - ``scipy_sparse``
     - head-only partition
     - damped Newton, sparse
     - semi-analytic, plus colored finite differences for the release
     - SciPy ``spsolve``
   * - ``petsc``
     - head-only partition
     - PETSc SNES ``newtonls``
     - semi-analytic, sparse
     - direct LU
   * - ``petsc``
     - mixed complementarity
     - PETSc SNES ``newtonls`` on the three unknowns
     - semi-analytic, sparse blocks
     - direct LU
   * - ``petsc``
     - ``vi_obstacle``
     - PETSc SNESVI ``vinewtonrsls``
     - semi-analytic, sparse
     - direct LU
   * - ``petsc``
     - ``ts_vi_obstacle``
     - PETSc TS backward Euler with SNESVI
     - semi-analytic, sparse
     - direct LU, with a shift

The PETSc engines run only on Linux and need ``petsc4py``: on another system the run
stops with a message that starts ``Boussinesq runtime_backend='petsc' is only
supported on Linux.`` They run in serial, on ``PETSc.COMM_SELF``.

The nonlinear solve
-------------------

Every engine looks for a head :math:`h` such that the residual vector is zero. The
vector it tests is the solver residual: the balance in m\ :sup:`3`/s on a free cell,
and :math:`h_j - H^D_j` in metres on a constrained cell. The tolerance
:toml:`flow.runtime_tol_residual_inf` applies to the largest absolute entry. The
iteration budget is :toml:`flow.runtime_max_iterations`; when the key is not set,
the runtime has its own budget, larger on ``scipy_sparse`` than on the others
(``build_runtime_options`` in ``solver_contract.py``). A step that does not converge
ends the run.

The local engine
~~~~~~~~~~~~~~~~

The ``local`` engine is a damped Newton loop (``_newton_loop_template`` in
``runtimes/newton_common.py``), written to be read:

#. start from the initial guess and assemble the residual;
#. build a dense Jacobian by forward finite differences, with a step of
   :math:`10^{-7}\max(1, \lvert h \rvert)` on each head in turn
   (``build_dense_fd_jacobian``);
#. solve :math:`J\,\delta = -R` with a dense solve;
#. halve the step, from 1 down to a minimum factor, until the largest residual entry
   falls; if it never does, the solve stops and is not converged;
#. stop when the largest residual entry is below the tolerance.

The method is transparent and fit for small validation meshes. A dense engine assembles
a dense Jacobian, so it refuses a mesh of more than 400 cells
(``_assert_runtime_mesh_size_supported`` in ``boussinesq.py``).

The SciPy engine
~~~~~~~~~~~~~~~~

The ``scipy`` engine keeps the same residual. It gives SciPy a semi-analytic dense
Jacobian and lets ``scipy.optimize.root`` with the ``hybr`` method drive the solve
(``runtimes/scipy_dense.py``). SciPy stops on its own criterion on the step, set
from :toml:`flow.runtime_tol_state_update_inf`, and the run then checks the residual
against the tolerance: a solve that SciPy calls successful but whose residual is
above the tolerance is reported as not converged. It has the same limit of 400
cells.

The SciPy sparse engine
~~~~~~~~~~~~~~~~~~~~~~~

The ``scipy_sparse`` engine runs the same Newton loop as ``local`` with a sparse
Jacobian (``runtimes/scipy_sparse.py``):

#. the smooth terms, which are the internal fluxes, the storage, the drain and the
   constraints, are differentiated analytically;
#. the release :math:`s_i` is completed by finite differences, with columns of the
   matrix that do not share a row perturbed together (graph coloring);
#. the Newton step is solved with ``spsolve``.

If the matrix is singular, the step is solved again with a diagonal shift that grows
by a factor of ten at each of up to six tries. For a steady solve the initial guess
is moved to the middle of the cell wherever the head sits exactly on the top or the
bottom, because the partition Jacobian can be singular there
(``interiorize_regularized_partition_initial_guess``). This is the reference engine
for larger meshes on every system.

The PETSc engines
~~~~~~~~~~~~~~~~~

The PETSc partition engine solves the same head-only residual with PETSc SNES, a
Newton method with a backtracking line search, on a sparse semi-analytic Jacobian
(``runtimes/petsc_partition.py``). The linear systems are solved by a direct LU
factorization with a small shift of the diagonal against zero pivots
(``_configure_default_snes`` in ``runtimes/petsc_common.py``). The absolute
tolerance of SNES is the residual tolerance, and its relative and step tolerances
are off. The Jacobian also receives a diagonal shift that decays with the residual,
a light pseudo-transient regularization for large meshes:

.. math::

   \mathrm{shift} = \max\Bigl(10^{-8},\ 0.2\;\mathrm{median}_{J_{ii} \neq 0}\,
   \lvert J_{ii}\rvert\ \min\bigl(1,\ \lVert R\rVert_\infty / \lVert R_0\rVert_\infty\bigr)\Bigr)

where :math:`R_0` is the residual of the first iterate. The shift vanishes as the
solve converges. The residual does not contain it, so the solution is the one of the
unshifted system (``regularized_partition_jacobian_shift`` in
``runtimes/partition_utils.py``).

The mixed engine solves the system of :math:`3n` unknowns of
`The lower obstacle`_, with the rates scaled by :math:`q_s`
(``_solve_mixed_problem`` in ``runtimes/petsc_mixed.py``). The residual has three
blocks: the balance with :math:`-a_i q^{\mathrm{dry}}_i`, the Fischer-Burmeister
equation of the surface, and the Fischer-Burmeister equation of the bottom. The run
converges when SNES reports a convergence and the largest entry of the full residual
is below the tolerance.

The starting point of the mixed solve is a numerical choice, not a physical one. The
head is clipped between the bottom and the top. A free cell whose balance at the
bottom still asks to lose water starts at the bottom. In a transient run, the first
guess of :math:`q^{\mathrm{ex}}` is the release the regularized partition would
give when the recharge is positive or a well flux is negative, and zero otherwise
(``_initial_transient_q_ex_guess``). The choice changes the path to the solution,
not the equations.

The VI engines solve the bounded system of `The experimental obstacle closures`_.

The starting state and the time loop
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The transient driver loops over the stress periods (``run_transient_runtime`` in
``drivers/transient.py``). At each period it takes the forcing of the period, the
heads of the previous period as the previous state and as the initial guess, and
solves one step. The first period is a transient step like the others: the solver
does not read :toml:`flow.first_period_steady`.

The initial heads come from :toml:`flow.ic.h.type`. With ``steady_state``, the
solver first runs one steady solve with the same method, under the time-mean
recharge or under the rate of :toml:`flow.ic.h.rate`, with the boundary heads of the
first period. It starts the transient from the result. Cyclic spin-up and
:toml:`flow.restart_from` are not implemented for this solver and the file is
refused when it asks for them. How to choose the starting state is in
:doc:`../guides/time-and-initial-state`.

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

The keys of the experimental obstacle runtimes:

.. hmp-params::

   flow.vi_substeps_per_period
   flow.vi_substep_on_failure
   flow.vi_max_adaptive_substeps
   flow.ts_vi_steps_per_period
   flow.ts_vi_adapt
   flow.ts_vi_dt_min_fraction
   flow.ts_vi_dt_max_fraction
   flow.ts_vi_type
   flow.ts_vi_snes_type

A file that chooses the experimental closure and cuts each period into substeps:

.. code-block:: toml

   base_config = "step4_transient.toml"

   [solver]
   backend = { backend = "boussinesq" }

   [[simulation.process]]
   id = "flow_main"
   type = "flow"
   solvers = ["boussinesq"]

   [mesh_catchment]
   constraints_mode = "rivers_only"
   cache = true

   [flow]
   runtime_backend = "petsc"
   surface_interaction_model = "vi_obstacle"
   vi_substeps_per_period = 4
   vi_substep_on_failure = true

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
   * - Experimental obstacle closures
     - ``hydromodpy/solver/boussinesq/runtimes/petsc_vi_obstacle.py``, ``runtimes/petsc_ts_vi_obstacle.py``, ``runtimes/petsc_vi/obstacle.py``, ``runtimes/vi_bounds.py``
   * - Method and engine choice
     - ``hydromodpy/solver/boussinesq/methods/catalog.py`` (``resolve_method_spec``), ``engines/catalog.py`` (``resolve_engine_spec``), ``runtime_selection.py``
   * - Newton loop and the engines
     - ``hydromodpy/solver/boussinesq/runtimes/newton_common.py``, ``local.py``, ``scipy_dense.py``, ``scipy_sparse.py``, ``petsc_partition.py``, ``petsc_common.py``
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
   * - Notes in LaTeX
     - ``hydromodpy/solver/boussinesq/boussinesq_math_notes.tex``

See also
--------

- :doc:`../guides/choose-a-solver`: how to choose a solver and set its runtime keys.
- :doc:`groundwater-flow`: the discrete problem of the three solvers side by side.
- :doc:`solvers`: what each solver does with the same file.
- :doc:`mf6-vs-nwt`: the two MODFLOW solvers against each other.
- :doc:`validation`: the checks against closed-form solutions.
- :doc:`notation`: the symbols used on every theory page.
- :doc:`/contribute/architecture/solver/boussinesq-uml-diagrams`: the module
  diagrams of the solver.
- :doc:`bibliography`: the references.
