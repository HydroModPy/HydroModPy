# The groundwater flow problem

What head does the aquifer hold, in every cell and at every time? This page gives
the equation HydroModPy solves for that head, the geometry it is solved on, the
properties that enter it and the state it starts from. It does not say how to set
up a run: for that, see {doc}`../guides/choose-a-solver`. For the same subject in
plain words, see {doc}`../understand/what-it-computes`.

:::{note}
**Scope.** Three solvers read the same `[flow]` section: MODFLOW 6 (the default),
MODFLOW-NWT and the in-house Boussinesq solver. They solve the same physical
problem and not the same discrete equations. The problem is written once here.
Section 5 gives the discrete form of the two MODFLOW solvers and section 6 the
one of the Boussinesq solver. What enters and leaves the aquifer (recharge,
drains, streams, lakes, wells) has its own pages: {doc}`forcing`,
{doc}`soil-reservoir` and {doc}`exits`.
:::

## Notation

Lengths are in metres, time in seconds, and elevation is positive up. A key
accepts a value with its unit ("30 m", "5 m/day"); the code converts it to the
unit below before it builds the solver input. The symbols shared with the other
theory pages are those of {doc}`notation`.

| Symbol | Meaning | Unit | Set by |
|---|---|---|---|
| $h$ | hydraulic head, one value per cell | m | state, not a field |
| $h_0$ | head at the start of the run | m | {toml}`type\|flow.ic.h.type` |
| $z_\mathrm{top}$ | model top, the land surface | m | {toml}`data.dem` |
| $z_\mathrm{bot}$ | bottom of the aquifer | m | {toml}`kind\|domain.depth_model.kind` |
| $H$ | aquifer thickness, $H = z_\mathrm{top} - z_\mathrm{bot}$ | m | derived |
| $B$ | saturated thickness | m | state, not a field |
| $H_c$ | thickness of the constant-thickness model | m | {toml}`thickness\|domain.depth_model.thickness` |
| $z_s$ | elevation of the flat substratum | m | {toml}`substratum_elevation\|domain.depth_model.substratum_elevation` |
| $R$ | value of the substratum raster in a cell | m | {toml}`path\|data.substratum.sources.path` |
| $\omega$ | vertical shift of the raster substratum | m | {toml}`offset\|domain.depth_model.offset` |
| $\lambda$ | factor applied to the thickness raster | - | {toml}`scale\|domain.depth_model.scale` |
| $H_\mathrm{min}$ | smallest aquifer thickness kept under the top | m | {toml}`min_thickness\|domain.depth_model.min_thickness` |
| $j$, $J$ | layer index, number of layers | - | {toml}`nlay\|modflow6.sgrid.vertical.nlay` |
| $p_j$ | cumulative share of the thickness reached at the bottom of layer $j$ | - | {toml}`genmtd_lay\|modflow6.sgrid.vertical.genmtd_lay` |
| $K$ | horizontal hydraulic conductivity | m/s | {toml}`flow.param.K.field.value` |
| $K_z$ | vertical hydraulic conductivity | m/s | {toml}`vka\|modflow6.process_specific.vka` |
| $\beta$ | ratio $K / K_z$ | - | {toml}`vka\|modflow6.process_specific.vka` |
| $S_y$ | specific yield | - | {toml}`flow.param.Sy.field.value` |
| $S_s$ | specific storage | 1/m | {toml}`flow.param.Ss.field.value` |
| $f(d)$ | factor that scales a property with the depth $d$ below the top | - | {toml}`mode\|flow.param.K.field_vertical_profile.mode` |
| $d_c$, $f_\mathrm{min}$ | characteristic depth and floor of the exponential factor | m, - | {toml}`characteristic_depth\|flow.param.K.field_vertical_profile.characteristic_depth`, {toml}`min_factor\|flow.param.K.field_vertical_profile.min_factor` |
| $n$, $m$ | cell indices; $\mathcal{N}(n)$ is the set of cells that share a face with $n$ | - | the grid ({doc}`mesh`) |
| $a_n$ | plan area of cell $n$ | m² | the grid |
| $G_{nm}$ | conductance between cells $n$ and $m$ | m²/s | derived |
| $\Phi_{n,p}$ | flow into cell $n$ from the stress package $p$, positive into the aquifer | m³/s | {toml}`flow.active_bc`, {toml}`flow.active_sinks_sources` |
| $N$ | recharge, positive into the aquifer | m/s | {toml}`flow.sinks_sources.recharge` |
| $\Delta t$ | stress period, the stretch of time that gets one forcing value | s | {toml}`step_value\|simulation.time.step_value` |
| $\delta t$ | solver time step, $\delta t = \Delta t / n_\mathrm{sub}$ | s | {toml}`substeps_per_period\|simulation.time.substeps_per_period` |

## 1. The domain

The code builds the geometry in `Domain._build_surfaces`
(`hydromodpy/spatial/domain/domain.py`). Two surfaces bound the aquifer.

**The top** $z_\mathrm{top}$ is the digital elevation model of the catchment,
read from {toml}`data.dem`. By default the grid takes the value of the DEM at the
centre of each cell, and nothing else moves the top.
{toml}`modflow6.sgrid.top_sampling.mode` can ask for a statistic over the pixels
of the cell instead, with a lower value for the cells that hold a channel.

**The bottom** $z_\mathrm{bot}$ comes from a depth model, chosen by
{toml}`domain.depth_model.kind`. Four kinds exist:

| Kind | Bottom | Reads |
|---|---|---|
| `constant_thickness` | $z_\mathrm{bot} = z_\mathrm{top} - H_c$ | {toml}`domain.depth_model.thickness` |
| `flat_substratum` | $z_\mathrm{bot} = z_s$ | {toml}`domain.depth_model.substratum_elevation` |
| `raster_substratum` | $z_\mathrm{bot} = \min\bigl(R + \omega,\ z_\mathrm{top} - H_\mathrm{min}\bigr)$ | the raster of {toml}`data.substratum`, in metres, on the datum of the DEM |
| `raster_thickness` | $z_\mathrm{bot} = \min\bigl(z_\mathrm{top} - \lambda R + \omega,\ z_\mathrm{top} - H_\mathrm{min}\bigr)$ | the raster of {toml}`data.substratum`, in metres below the top |

The first two kinds follow `ConstantThicknessDepthModel` and
`FlatSubstratumDepthModel`. A flat substratum is an elevation, not a depth: where
the land surface drops under it, no aquifer is left. The last two kinds follow
`RasterSubstratumDepthModel` and `RasterThicknessDepthModel`, and the raster
goes through `Domain._substratum_from_raster`. That function:

1. reprojects the raster onto the grid of the top;
2. refuses the run if one cell of the domain has no raster value, so the raster
   must cover the whole extent of the domain, buffer included when
   {toml}`geographic.domain_extent` is `"box"`;
3. applies $\lambda$ and $\omega$;
4. lowers the bottom to $z_\mathrm{top} - H_\mathrm{min}$ wherever it would
   come closer to the top than that, and logs a warning that counts the cells;
5. refuses the run if every cell needs that correction, since no aquifer would
   remain.

Take a top of 120 m everywhere and a raster that holds 40 m, or 85 m for the
elevation kind, in every cell but one. The table gives the bottom of that cell, as
`build_domain` returns it (the check ran the function).

| Depth model | Raster value | $\omega$, $\lambda$ | Bottom |
|---|---|---|---|
| `raster_thickness` | 40 m | 5 m, 1 | 85 m |
| `raster_thickness` | 40 m | 0 m, 2 | 40 m |
| `raster_thickness` | 0.5 m, with $H_\mathrm{min} = 1$ m | 0 m, 1 | 119 m, with a warning |
| `raster_substratum` | 85 m | -5 m | 80 m |

A raster kind needs the raster. {toml}`data.substratum` takes exactly one source.
Example 04 sets a constant thickness, so a block that switches to a raster removes
the inherited thickness with `thickness__delete` (see {doc}`../guides/inheritance`).

```toml
base_config = "step4_transient.toml"

[domain.depth_model]
thickness__delete = true
kind = "raster_thickness"
min_thickness = "2 m"

[[data.substratum.sources]]
source = "custom"
path = "substratum/thickness.tif"
```

Example 04 gives the constant thickness a value:

```{hmp-resolved} domain.depth_model.thickness
:config: project.toml
```

The thickness of an aquifer is an assumption in this model, not a result. No
equation below estimates it. The field of the constant thickness declares itself
calibrable, in log space.

## 2. The solver grid and its layers

The grid samples $z_\mathrm{top}$ and $z_\mathrm{bot}$ at the centre of each cell.
`build_spatial_discretization` (`hydromodpy/solver/modflow_grid/discretization_spatial.py`)
then does three things.

- A cell with no finite value in either surface becomes inactive in every layer.
- It refuses the grid when $z_\mathrm{bot} \ge z_\mathrm{top}$ on a valid cell,
  with the message "Bottom surface must be strictly below top surface on valid cells".
- On a runtime mesh, it logs a warning when a column is thicker than 500 m and
  thicker than 10 times the median. A raster nodata value read as an elevation
  produces such columns. A structured grid does not emit it ({doc}`mesh`, section 8).

The thickness is then cut into $J$ layers. The bottom of layer $j$ is

$$
z_{\mathrm{bot},j} = z_\mathrm{top} - H\,p_j ,
\qquad p_J = 1 .
$$

The shares $p_j$ are the same for every cell, so the layers follow the relief and
the substratum and never pinch out. `_compute_layer_proportions` builds them from
{toml}`modflow6.sgrid.vertical.genmtd_lay`:

| `genmtd_lay` | $p_j$ |
|---|---|
| `constant` | $j / J$ |
| `decay`, with a decay $\rho$ read from {toml}`modflow6.sgrid.vertical.lay_decay` | $(1 - \rho^{j}) / (1 - \rho^{J})$ |
| `list` | the running sum of {toml}`modflow6.sgrid.vertical.lay_proportions` |

With one layer, $p_1 = 1$ and the column is one cell. MODFLOW-NWT
reads the same keys under `modflownwt.sgrid.vertical`. A model with four layers
that thicken with depth (with $\rho = 2$ the layers hold 1, 2, 4 and 8 fifteenths of the
column, from the top down):

```toml
base_config = "step4_transient.toml"

[modflow6.sgrid.vertical]
genmtd_lay = "decay"
nlay = 4
lay_decay = 2.0
```

MODFLOW 6 builds every grid, structured or not, as a vertex grid (`DISV`), and a
gmsh mesh is turned into Voronoi cells by default. The Boussinesq solver has no
layers: it works on one triangle per column. See {doc}`mesh`.

## 3. The properties

Each property is a field: one value for the whole domain, or one value per zone
({doc}`../guides/k-per-zone`). The code evaluates it per cell and per layer
(`hydromodpy/solver/modflow6/support/property_mapping.py`).

| Property | Needed by a steady run | Needed by a transient run |
|---|---|---|
| MODFLOW 6 and MODFLOW-NWT | $K$ | $K$, $S_y$, $S_s$ |
| Boussinesq | $K$ | $K$, $S_y$ |

The Boussinesq solver reads no $S_s$. The rule is in `resolve_required_flow_properties`,
once in `solver/modflow_common/property_mapping.py` and once in
`solver/boussinesq/property_mapping.py`. In a steady MODFLOW run, a missing
$S_y$ or $S_s$ is filled with zero. In a transient run, a missing one stops the run.
Example 04 gives the three values, one for the whole catchment:

```{hmp-resolved} flow.param.K.field.value
:config: step4_transient.toml
```

```{hmp-resolved} flow.param.Sy.field.value
:config: step4_transient.toml
```

```{hmp-resolved} flow.param.Ss.field.value
:config: step4_transient.toml
```

**A depth factor.** A property can carry a `field_vertical_profile`. The value
of the layer $j$ in a column is the value of the field times $f(d_j)$, where
$d_j$ is the depth of the middle of the layer below $z_\mathrm{top}$
(`SolverMesh.layer_center_depths`). The factor is, for `mode = "exponential"`
(`FieldParam.vertical_factor` in `hydromodpy/spatial/field/core/field_param.py`):

$$
f(d) = \max\!\bigl(e^{-d/d_c},\ f_\mathrm{min}\bigr) ,
$$

and for `mode = "tabulated"` a linear or stepwise interpolation of the table you
give, equal to the first and last factor outside the table. With one layer, $d_j$
is half the thickness: the profile then gives one factor per cell and no
variation with depth.

**Vertical conductivity.** MODFLOW 6 reads $K_z = K / \beta$, with $\beta$ the
{toml}`modflow6.process_specific.vka`, layer by layer, so a depth factor on $K$
reaches $K_z$. A parameter with the id `Kv` replaces it with a conductivity per
cell, and a file that gives `Kv` and a `vka` other than 1 is refused
(`resolve_k33_field`).

```toml
base_config = "step4_transient.toml"

[modflow6.process_specific]
vka = 10.0

[flow.param.K.field_vertical_profile]
mode = "exponential"
characteristic_depth = "20 m"
min_factor = 0.05
```

The code refuses a $K$ that is zero, negative or not finite on an active cell
(`require_positive_conductivity`). A heterogeneous $K$ whose zones do not cover the
whole domain produces exactly that.

## 4. The flow equation

Water is incompressible and its density is constant. Darcy's law gives the
specific discharge $\mathbf{q} = -\mathbf{K}\,\nabla h$. Mass conservation in a
porous medium gives the equation of the three-dimensional problem, written for
the head $h$ (the form of the MODFLOW documentation, {cite}`harbaugh2005`,
{cite}`langevin2017`):

$$
S_s\,\frac{\partial h}{\partial t}
= \frac{\partial}{\partial x}\!\left(K\,\frac{\partial h}{\partial x}\right)
+ \frac{\partial}{\partial y}\!\left(K\,\frac{\partial h}{\partial y}\right)
+ \frac{\partial}{\partial z}\!\left(K_z\,\frac{\partial h}{\partial z}\right)
+ W ,
$$

where $W$ is the net volume of water that stress packages add per unit volume
and time. The conductivity is the same along $x$ and $y$.

In a catchment the aquifer is mostly unconfined. The head can sit below the top
of a cell, and then the thickness that carries flow is the saturated thickness

$$
B(h) = \min\bigl(\max(h - z_\mathrm{bot},\ 0),\ H\bigr) .
$$

Every cell of the model is declared convertible: it can be full or partly
dry (`icelltype = 1` in the MODFLOW 6 `NPF` package, `iconvert = 1` in `STO`,
`laytyp = 1` in the MODFLOW-NWT `UPW` package). Two things then depend on
the head. The flow depends on it through $B$. The storage depends on it
because a falling water table releases water from the pores, which the specific
yield $S_y$ measures, and a head above the top of a full cell only
decompresses water and the matrix, which $S_s$ measures. For a column that is
one layer thick, integrating the equation over the thickness gives the
Boussinesq equation {cite}`boussinesq1877,boussinesq1904`, with the Dupuit
assumption that the head does not vary with depth {cite}`dupuit1863,brutsaert2005`:

$$
\bigl(S_s\,B + S_y\,\chi\bigr)\,\frac{\partial h}{\partial t}
= \nabla\!\cdot\!\bigl(K\,B\,\nabla h\bigr) + q ,
\qquad
\chi = \begin{cases} 1 & z_\mathrm{bot} < h < z_\mathrm{top},\\ 0 & \text{otherwise.}\end{cases}
$$

Here $q$ is the net flux per unit of plan area from the stress packages, in m/s.
The product $K\,B$ is the transmissivity $T$. When the water table is inside the
cell, the $S_s B$ term is small against $S_y$: in example 04, $S_y = 0.05$ and
$S_s B \le 3 \times 10^{-4}$, a ratio of about 170. The steady problem drops the
left-hand side.

## 5. The discrete problem in MODFLOW 6 and MODFLOW-NWT

Both solvers integrate the equation by control volumes, with one head per cell
at its centre. For a cell $n$, the balance of one time step is

$$
\sum_{m \in \mathcal{N}(n)} G_{nm}\,(h_m - h_n)
+ \sum_{p} \Phi_{n,p}
= \frac{1}{\delta t}\Bigl[\,S_s\,a_n\,B_n\,(h_n - h_n^\mathrm{old})
+ S_y\,a_n\,(B_n - B_n^\mathrm{old})\Bigr] .
$$

The left side is the water that enters the cell during the step: the exchange with
the neighbours and the stress packages. The right side is the change of the
volume stored. $h^\mathrm{old}$ is the head at the start of the step. The exact
weight of the saturation inside the step is the one of {cite}`langevin2017`.
The code builds this balance in `hydromodpy/solver/modflow6/build.py`:
`ModflowGwfnpf` for $G_{nm}$, `ModflowGwfsto` for the storage and `ModflowGwfic`
for the start.

**Conductance.** Between two cells of a layer, MODFLOW 6 keeps its default cell
averaging (HydroModPy sets no `CELL_AVERAGING` option in `ModflowGwfnpf`), which
joins the two half-cell conductances in series. Without Newton, each half cell
carries its own saturated thickness:

$$
\frac{1}{G_{nm}}
= \frac{c_{nm}}{K_n\,B_n\,w_{nm}}
+ \frac{c_{mn}}{K_m\,B_m\,w_{nm}} ,
$$

with $w_{nm}$ the width of the shared face and $c_{nm}$ the distance from the
centre of $n$ to that face. Under the Newton formulation, the default here, the
series is built with the full cell thicknesses and then multiplied by the
saturated fraction of the upstream cell, the one with the higher head
(upstream weighting, {cite}`langevin2017`; the code comment of `guard_newton_rewet`
in `build.py` says the same). Between two layers, the series applies with $K_z$
and the area of the shared face. On Voronoi cells the face is the perpendicular
bisector of the two centres, which is the case the formula needs. The extended
conductance of the XT3D option applies when the mesh is not orthogonal or
the conductivity is anisotropic ({doc}`solvers/xt3d-on-irregular-disv-meshes`). A cell with
$B_n = 0$ carries no flow out of it.

**Newton.** The balance is nonlinear in $h$, through $B$ and through the switch
$\chi$. MODFLOW 6 solves it with the Newton-Raphson formulation by default,
with under-relaxation, since every cell is convertible:

```{hmp-params}
modflow6.runtime.mf6_newton
modflow6.runtime.mf6_newton_under_relaxation
```

Newton and cell rewetting exclude each other: the code refuses a file that asks
for both. MODFLOW-NWT is the Newton formulation of MODFLOW-2005
{cite}`niswonger2011,harbaugh2005`. HydroModPy gives it the same convertible
layers on a structured grid.

**A cell by hand.** Take one layer, $a_n = 2500$ m², $z_\mathrm{bot} = 70$ m,
$z_\mathrm{top} = 100$ m, $S_y = 0.05$ and $S_s = 10^{-5}$ m⁻¹. Over one step of
30 days the head falls from 95 m to 94 m, and $B$ from 25 m to 24 m.

| Term | Value |
|---|---|
| $S_y\,a_n\,(B_n - B_n^\mathrm{old})$ | $0.05 \times 2500 \times (-1) = -125$ m³ |
| $S_s\,a_n\,B_n\,(h_n - h_n^\mathrm{old})$ | $10^{-5} \times 2500 \times 24 \times (-1) = -0.6$ m³ |
| Release over the step | $-125.6$ m³, or $-4.8 \times 10^{-5}$ m³/s |

The cell loses 125.6 m³ of water, and the specific storage accounts for 0.5 per
cent of it. The first row is the value of `_stored_saturated_volume_m3`
(`solver/boussinesq/assembly/residuals.py`) for these numbers; the second row is the
formula above, not a run of MODFLOW 6.

## 6. The discrete problem in the Boussinesq solver

The Boussinesq solver is not a MODFLOW wrapper. It writes one residual per
triangular cell $i$. Its equation, its closures and its engines are in
{doc}`boussinesq`. Three points matter here, because they differ from section 5.

- The thickness is $B_i = \min(\max(h_i - z_{\mathrm{bot},i}, 0), H_i)$ and the
  edge flux between two cells $a$ and $b$ is $q_e = -\tau_e\,(h_b - h_a)$, with
  $\tau_e = K^H_e\,\bar B_e\,L_e / d_e$. $K^H_e$ is the harmonic mean of the two
  conductivities, $\bar B_e$ the mean of the two thicknesses, $L_e$ the edge length
  and $d_e$ the distance between the two centres
  (`internal_edge_flux_from_head` in `solver/boussinesq/assembly/fluxes.py`).
  MODFLOW takes $K\,B$ per half cell; here the mean of $B$ goes with the mean of $K$.
- The storage is $a_i\,S_y\,\max(h_i - z_{\mathrm{bot},i},\ 0)$, with no $S_s$ and
  no cap at the top, so that a head above the land surface keeps its memory.
- The residual counts water that leaves the cell as positive. Recharge and
  injection enter with a minus sign:

$$
\frac{M_i(h^{k+1}) - M_i(h^{k})}{\delta t}
+ \sum_{e} q_e + R^{D}_i + q^\mathrm{drain}_i + a_i\,s_i
- a_i\,N_i - \Phi^\mathrm{well}_i = 0 ,
$$

with $M_i = a_i S_y \max(h_i - z_{\mathrm{bot},i}, 0)$, $R^{D}_i$ the exchange
through edges at an imposed head (zero in the solve, which pins the imposed head
on its cells instead; see {doc}`boussinesq`), $q^\mathrm{drain}_i$ the top drainage and $s_i$ the
surface-interaction term of the solver
(`_transient_raw_residual_from_spatial_terms`).

## 7. Time

The run is cut into stress periods of length $\Delta t$, one per forcing value
({doc}`forcing`). Within a period the forcing is constant. Each period is cut into
$n_\mathrm{sub}$ equal time steps and the time integration is the backward Euler
scheme: the balance of section 5 is written with the stress and the conductances
at the end of the step. The code sets a time-step multiplier of 1
(`ModflowTdis` in `solver/modflow6/build.py`), so the steps of a period are equal.
The one exception is {toml}`modflow6.runtime.mf6_ats`: with it, MODFLOW 6 may cut
a transient step further where the solver does not converge, never above the
step asked for.

```{hmp-params}
simulation.time.step_value
simulation.time.substeps_per_period
```

{toml}`flow.flow_regime` picks the regime. In a `steady` run, every period is
steady. In a `transient` run, {toml}`flow.first_period_steady` marks the first
period as steady (`_build_solver_steady_array`) in the two MODFLOW solvers; the
Boussinesq solver does not read it and solves every period as a transient step. In a steady period the right side
of the balance is zero, the storage plays no part, and the heads settle where the
forcing of that period puts them. Example 04 states the regime:

```{hmp-resolved} flow.flow_regime
:config: step4_transient.toml
```

The sequence of steady and transient periods goes to MODFLOW 6 as change points
(`sto_period_settings` in `solver/modflow6/builders/period_forcing.py`). The
solver time step is a numerical choice: a period solved in one step differs from
the same period in several, by an amount that depends on the case.

## 8. The starting heads

The head at the start of the run, $h_0$, is declared in the flat table `[flow.ic]`
and read by `build_head_initial_condition_array`
(`hydromodpy/solver/initial_conditions.py`). Its value is the same in every layer
of a column. `bottom` is the bottom of the deepest layer.

| `type` | $h_0$ |
|---|---|
| `top` | $z_\mathrm{top}$ |
| `top_offset` | $z_\mathrm{top} - v$, with $v$ the `value` |
| `bottom` | $z_{\mathrm{bot},J}$ |
| `custom` | $v$ |
| `steady_state` | the solution $h^\star$ of the steady problem under a constant recharge, see below |
| `spinup_cyclic` | the state a cyclic run settles at, see below |

In every case, a cell on an imposed head (an ocean, a stream or a side boundary)
starts at that head (`build_start_heads` in `solver/modflow6/builders/initial_conditions.py`).
`top` is a full aquifer; the card of {toml}`flow.ic.h.type` gives the default.

**The equilibrium.** For `steady_state`, the code first solves an auxiliary
steady problem with the same solver, the same grid and the same properties.
Its recharge is a constant, set by {toml}`flow.ic.h.source`: the mean of the whole
record, or the rate that you state. The result is $h_0$:

$$
\nabla\!\cdot\!\bigl(K\,B(h^\star)\,\nabla h^\star\bigr) + \bar N + q_\mathrm{bc}(h^\star) = 0 ,
\qquad h_0 = h^\star ,
$$

where $\bar N$ is the constant recharge and $q_\mathrm{bc}$ the exchanges with
the boundaries, held at the value of the first period
({toml}`flow.ic.h.boundary_condition_policy`).

**The settled cycle.** For `spinup_cyclic`, the run repeats its own period. Cycle
$c + 1$ starts from the heads where cycle $c$ ended, $h_\mathrm{end}^{(c)}$, and
the first cycle starts from {toml}`flow.ic.h.first_cycle_from`. The loop stops when

$$
\max_n \bigl|\,h^{(c+1)}_{\mathrm{end},n} - h^{(c)}_{\mathrm{end},n}\,\bigr| \le \varepsilon ,
$$

with $\varepsilon$ the {toml}`flow.ic.h.tol_head`, or after
{toml}`flow.ic.h.max_cycles` cycles. The maximum counts every cell, not the mean
(`cycles_have_settled` in `solver/steady_initial_conditions.py`).

**When the first period is steady.** With {toml}`flow.first_period_steady` at its
default, period 0 is solved as a steady state, and the heads above are only the
first guess of that solve. They change the convergence and not the state
reached. To make the run start from a state you choose, write `first_period_steady = false`
(see {doc}`../guides/time-and-initial-state`).

```toml
base_config = "step4_transient.toml"

[flow]
first_period_steady = false

[flow.ic]
type = "steady_state"
```

A run can also restart from the last time step of an earlier run
({toml}`flow.restart_from`). That state replaces $h_0$.

## 9. What enters and leaves

The stress terms $\Phi_{n,p}$ and the source $W$ of the equations above come from
packages. The code builds them in `solver/modflow6/build.py`, and each one has its
page.

| Term | MODFLOW 6 package | Page |
|---|---|---|
| Recharge $N$ | `RCHA` | {doc}`forcing`, {doc}`soil-reservoir` |
| Evapotranspiration that the soil did not meet, or a negative recharge routed to evaporation | `EVTA` | {doc}`soil-reservoir`, {doc}`forcing` |
| Drainage at the land surface | `DRN` | {doc}`exits` |
| Imposed heads: ocean, stream, sides | `CHD` | {doc}`exits` |
| Wells | `WEL` | {doc}`exits` |
| Stream reaches, lakes, flow barriers, water transfers | `SFR`, `LAK`, `HFB`, `MVR` | {doc}`exits` |

Recharge and injection are positive when water enters the aquifer, and a well with a
negative rate pumps. Where no boundary is activated, the edge of the domain carries no flow. The two
keys that activate them are {toml}`flow.active_bc` and
{toml}`flow.active_sinks_sources`. A boundary prescribes a head and lets the flow
emerge. Drainage is a head-dependent exchange. Recharge and evapotranspiration are
areal rates. A well is a volume per unit of time.

## Assumptions

- The water is incompressible and its density is constant. The conductivity does
  not change with time or with the head.
- The conductivity is the same along the two horizontal axes. Only the vertical
  one differs, by the ratio $\beta$ or by the parameter `Kv`.
- Each cell holds one head, at its centre. The flow between two cells is a
  conductance times a head difference.
- With one layer, the flow is horizontal and the head does not vary with depth (the
  Dupuit assumption).
- The specific yield releases its water at once when the water table falls. There
  is no delayed yield.
- The thickness of each cell does not change in time: no compaction.
- The layers share one plan grid and one rule of proportions, so geology varies
  through properties and never through surfaces.
- The forcing is constant over a stress period.
- The bottom and the sides of the domain are impervious, except where a
  boundary is activated.
- The thickness of the aquifer is chosen, not computed.

## Limits

- **Shallow and unconfined.** Every cell is convertible. The code is built for
  the saturated zone of a catchment, from the surface down to a substratum that
  you place. On a runtime mesh it warns when a column is thicker than 500 m and
  thicker than 10 times the median.
- **No unsaturated flow.** The code builds no `UZF` package. The water that reaches
  the water table is a recharge, given or computed by the daily soil store of
  {doc}`soil-reservoir`.
- **No density-dependent flow, no compaction.** The code builds neither a `BUY`
  nor a `CSUB` package.
- **A bottom above the top is refused.** So is a bottom that equals it, and a
  raster that leaves one cell without a value.
- **Layers cannot pinch out.** The same proportions apply in every column, and
  the thickness cannot fall below $H_\mathrm{min}$ with a raster kind.
- **Boussinesq has one layer and no $S_s$.** It reads $K$ and $S_y$ only.
- **Newton and rewetting exclude each other** in MODFLOW 6.
- **A steady first period is refused with the soil reservoir.** The reservoir
  sends a daily recharge that is zero after a dry day, and a one-period
  steady state would start the run from a drained aquifer.
- **Each solver has its own boundaries.** {doc}`../guides/choose-a-solver` gives the
  table, and the file is refused when the solver cannot carry a boundary it asks for.

## Parameters of this page

The fields below are the ones that appear in the equations. Open a row for its
card.

```{hmp-params}
domain.depth_model.kind
domain.depth_model.thickness
domain.depth_model.substratum_elevation
domain.depth_model.offset
domain.depth_model.min_thickness
domain.depth_model.scale
data.substratum.sources.path
data.substratum.sources.default_crs
modflow6.sgrid.vertical.nlay
modflow6.sgrid.vertical.genmtd_lay
modflow6.sgrid.vertical.lay_decay
modflow6.sgrid.vertical.lay_proportions
flow.param_list
flow.param.K.field.value
flow.param.Sy.field.value
flow.param.Ss.field.value
flow.param.K.field_vertical_profile.mode
flow.param.K.field_vertical_profile.characteristic_depth
flow.param.K.field_vertical_profile.min_factor
modflow6.process_specific.vka
flow.flow_regime
flow.first_period_steady
flow.ic.h.type
flow.ic.h.value
flow.ic.h.source
flow.ic.h.rate
flow.ic.h.boundary_condition_policy
flow.ic.h.max_cycles
flow.ic.h.tol_head
flow.ic.h.first_cycle_from
flow.restart_from
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.physics.flow
hydromodpy.spatial.domain
hydromodpy.spatial.field.core.field_param
hydromodpy.solver.field_property_mapping
hydromodpy.solver.modflow_grid
hydromodpy.solver.initial_conditions
hydromodpy.solver.steady_initial_conditions
hydromodpy.solver.modflow6.build
hydromodpy.solver.modflow_nwt.nwt
hydromodpy.solver.boussinesq.assembly
```

## In the code

| What | Where |
|---|---|
| The top, the bottom and the raster depth models | `hydromodpy/spatial/domain/domain.py` (`Domain._build_surfaces`, `Domain._substratum_from_raster`), `hydromodpy/spatial/domain/depth_model_config.py` |
| Reading the substratum raster | `hydromodpy/spatial/domain/build.py` (`read_substratum_source`) |
| Layers, the check bottom below top | `hydromodpy/solver/modflow_grid/discretization_spatial.py` (`_compute_layer_proportions`, `_assert_bottom_below_top`, `build_spatial_discretization`) |
| The properties, per cell and per layer | `hydromodpy/solver/modflow6/support/property_mapping.py`, `hydromodpy/solver/field_property_mapping.py` |
| The depth factor | `hydromodpy/spatial/field/core/field_param.py` (`FieldParam.vertical_factor`) |
| The MODFLOW 6 balance: `NPF`, `STO`, `IC`, Newton | `hydromodpy/solver/modflow6/build.py` (`newton_options`) |
| The MODFLOW-NWT balance: `UPW` | `hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py` |
| The Boussinesq residual | `hydromodpy/solver/boussinesq/assembly/residuals.py`, `hydromodpy/solver/boussinesq/assembly/fluxes.py` |
| Steady and transient periods | `hydromodpy/solver/modflow_grid/discretization_temporal.py`, `hydromodpy/solver/modflow6/builders/period_forcing.py` |
| The starting heads | `hydromodpy/solver/initial_conditions.py`, `hydromodpy/solver/steady_initial_conditions.py`, `hydromodpy/physics/flow/initial_conditions.py` |

## See also

- {doc}`solvers`: what each solver adds to this problem.
- {doc}`mf6-vs-nwt`: where MODFLOW 6 and MODFLOW-NWT differ.
- {doc}`boussinesq`: the in-house solver in full.
- {doc}`../guides/time-and-initial-state`: how to set the window and the starting state.
- {doc}`index`: the other theory pages.
