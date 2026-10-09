# The solvers of the aquifer

HydroModPy integrates the groundwater flow equation with one of three solvers: MODFLOW 6,
MODFLOW-NWT or the in-house Boussinesq solver. This page says what each of them does with
the model you describe in the file: the packages it writes, how it solves the nonlinear
balance and when it stops, what happens to a cell that dries, and how a transport run
hooks onto a flow run. What each solver supports is listed in {doc}`../reference/solvers`.

:::{note}
**Scope.** The continuous equation and the balance of a cell, {eq}`eq-cell-balance`, are
on {doc}`groundwater-flow`. The Boussinesq solver is on {doc}`boussinesq`, the XT3D terms
on {doc}`solvers/xt3d-on-irregular-disv-meshes`, and the two MODFLOW solvers side by side
on {doc}`mf6-vs-nwt`.
:::

(modflow-governing-equation)=
## Sources

The MODFLOW pages of this site build on the USGS documentation and do not replace it:

- MODFLOW 6, the groundwater flow model, its control-volume formulation, storage and
  stress packages {cite:p}`langevin2017`;
- the XT3D option of the `NPF` package {cite:p}`provost2017`;
- MODFLOW-NWT, the Newton formulation of MODFLOW-2005 {cite:p}`niswonger2011`, on the
  MODFLOW-2005 groundwater flow process {cite:p}`harbaugh2005`;
- the [MODFLOW 6 input guide](https://modflow6.readthedocs.io/en/latest/mf6io.html), for
  the definition of each package.

What these sources leave open, and this page says, is which options HydroModPy writes.

## The three solvers side by side

| | MODFLOW 6 | MODFLOW-NWT | Boussinesq |
|---|---|---|---|
| Name in `solvers` | `modflow6` | `modflow_nwt` | `boussinesq` |
| Unknown | head in every cell | head in every cell | head in every cell |
| Grid | DISV for every grid, structured or not | structured grid only (DIS) | triangular cells of a Gmsh mesh |
| Nonlinear scheme | Newton-Raphson, on by default | Newton-Raphson (NWT) | Newton-type, per runtime |
| Time | backward Euler, equal steps in a period | backward Euler, equal steps in a period | one backward Euler step per period |
| A cell that dries | stays in the equations (Newton) or is rewetted (rewet) | stays in the equations | thickness is bounded, never negative |
| Transport | GWT and particle tracking | MODPATH and MT3DMS | refused |

The names in the first row are the values read by {toml}`simulation.process.solvers`.
The capabilities of each solver, generated from the code, are on {doc}`../reference/solvers`.

::::{dropdown} Notation of this page
Cells are numbered $n$, and $m$ runs over the cells that share a face with $n$. Lengths
are in metres and time is in seconds: the run is written in seconds whatever the calendar
of the file.

```{hmp-notation}
```
::::

(solvers-time)=
## Time steps

The three solvers read the same time grid, built from {toml}`simulation.time`. Each
stress period has a length $\Delta t$ and holds every forcing constant. The two MODFLOW
solvers cut it into $n_\mathrm{sub}$ equal steps, $\delta t = \Delta t / n_\mathrm{sub}$,
with a step multiplier of 1: MODFLOW 6 in its `TDIS` package, MODFLOW-NWT in `DIS`, where
HydroModPy leaves the multiplier at the FloPy value, 1.

The choice of equal steps rests on the linear problem. For a balance whose coefficients do
not depend on the head, backward Euler over one period is a product of one factor per
step, and the factors commute: the state at the end of the period depends on the set of
step sizes and not on their order. On a confined column against a closed-form solution,
the validation case `test_stress_period_substepping` finds equal steps more accurate than
a geometric growth of the steps, in either direction, and one step per period about ten
times less accurate than ten steps ({doc}`validation`). The unconfined problem is
nonlinear, through $B(h)$ and the switch of storage, so these statements hold there only
approximately. The same case reports that one step per period moves the monthly discharge
of a drained hillslope by tens of per cent against a refined run. One step per period is
therefore not a neutral choice.

```{eval-rst}
.. plot:: theory/figures/solvers_substeps.py
   :alt: Head error at the end of a period against the number of steps, with two geometric partitions of ten steps.
   :caption: The confined column of ``test_stress_period_substepping``: 200 cells of 5 m, a
      head step of 1 m held for 31 days. The steps are the backward Euler equations
      MODFLOW 6 solves for this linear case, computed at build time; their error matches
      the one of a MODFLOW 6 run within :math:`10^{-7}` m. Look at 1 against 10 steps, then at
      the two triangles: ten steps that grow or shrink by 2 give the same error, about
      four times that of ten equal steps. Past about 10 steps the error of the 5 m cells
      dominates.
```

A period is steady or transient. With {toml}`flow.flow_regime` set to `"steady"`, every
period is steady. With `"transient"`, only the first period is steady, and only when
{toml}`flow.first_period_steady` is true. With {toml}`modflow6.runtime.mf6_ats`, MODFLOW 6
adds adaptive time stepping to the transient periods: each period starts at the step
above, ATS subdivides it only where the solver cannot converge, and it never grows past
that step. Steady periods are left out. The starting heads are on {ref}`gwf-start`. In the
code: `build_temporal_discretization_from_time_grid`.

(solvers-newton)=
## The nonlinear solve

Both MODFLOW solvers write {eq}`eq-cell-balance` for every active cell and every step.
Call $R_n$ the difference between its two sides, the water that enters minus the change of
storage, and $\mathbf J$ the Jacobian $J_{nm} = \partial R_n / \partial h_m$. The balance
depends on the head through the saturated thickness, in the conductance and in the
storage, so the system $\mathbf R(\mathbf h) = 0$ is nonlinear. Outer iteration $\nu$
solves

$$
\mathbf J\bigl(\mathbf h^{(\nu)}\bigr)\,\delta\mathbf h = -\mathbf R\bigl(\mathbf h^{(\nu)}\bigr),
\qquad
\mathbf h^{(\nu+1)} = \mathbf h^{(\nu)} + \omega\,\delta\mathbf h ,
\qquad 0 < \omega \le 1 ,
$$ (eq-newton)

with $\omega$ the factor the solver applies to the update {cite:p}`niswonger2011`. The
Newton form keeps a cell in the system when its head crosses the bottom: the conductance
and the storage go smoothly to zero instead of switching off ({doc}`mf6-vs-nwt` gives the
smoothing). Because the conductance follows the upstream head, $\mathbf J$ is not
symmetric.

**When the iteration stops.** The two solvers test different quantities. With
$\nu$ the outer iteration and $k$ the inner (linear) iteration inside it:

$$
\begin{aligned}
&\text{MODFLOW 6, outer:} && \max_n \bigl|h_n^{(\nu+1)} - h_n^{(\nu)}\bigr| \le \text{outer\_dvclose},\\
&\text{MODFLOW 6, inner:} && \max_n \bigl|h_n^{(k+1)} - h_n^{(k)}\bigr| \le \text{inner\_dvclose}
\ \text{ and }\ \max_n \bigl|r_n^{(k)}\bigr| \le \text{inner\_rclose},\\
&\text{MODFLOW-NWT:} && \max_n \bigl|h_n^{(\nu+1)} - h_n^{(\nu)}\bigr| < \text{headtol}
\ \text{ and }\ \Bigl(\textstyle\sum_n R_n^2\Bigr)^{1/2} < \text{fluxtol},
\end{aligned}
$$ (eq-closure)

where $r_n^{(k)}$ is the residual of the linear system of the outer iteration. The keys
are {toml}`modflow6.runtime.mf6_outer_dvclose`, {toml}`modflow6.runtime.mf6_inner_dvclose`
and {toml}`modflow6.runtime.mf6_inner_rclose`, in m and m³/s, and
{toml}`modflownwt.runtime.nwt.headtol` and {toml}`modflownwt.runtime.nwt.fluxtol`, in m
and m³/s. HydroModPy writes `inner_rclose` with no option, which keeps the absolute
largest residual of a cell in MODFLOW 6; when the key is unset, the value of the
complexity preset applies. The residual test of MODFLOW-NWT is a norm over every cell, of
the nonlinear balance; the one of MODFLOW 6 is a maximum over the cells, of the linear
solve. A closure value of the same number is therefore not the same test on the two
solvers.

**The budget of a step.** A converged step still carries a small imbalance. MODFLOW writes
it in the listing file as a percent discrepancy,

$$
E_\% = 100\,\frac{V_\mathrm{in} - V_\mathrm{out}}{\bigl(V_\mathrm{in} + V_\mathrm{out}\bigr)/2} ,
$$ (eq-discrepancy)

with $V_\mathrm{in}$ and $V_\mathrm{out}$ the volumes that enter and leave over the step,
storage included. HydroModPy reads the value of the last step and the worst one of the run
into the metrics of the run. A calibration rejects a trial whose last value is above
{toml}`calibration.reject_water_budget_above`. The auxiliary steady solve of a
`steady_state` start accepts its result only within 0.1 per cent. In the code:
`percent_discrepancies`.

## MODFLOW 6, package by package

`run_pre_processing` assembles the FloPy simulation in this order. A package marked "if"
is written only when the file asks for it.

| Package | What it adds to the balance | Written |
|---|---|---|
| TDIS (and ATS) | the steps of {ref}`solvers-time` | always |
| IMS | the nonlinear and linear solver | always |
| GWF | the Newton options | always |
| DISV | the cells, their tops and bottoms, $a_n$, the geometry of $G_{nm}$ | always |
| IC | $h_0$ | always |
| NPF | $K$, $K_z$, convertible flag, XT3D | always |
| STO | $S_y$, $S_s$, steady or transient flag per period | always |
| RCHA | $N\,a_n$ | always |
| EVTA (or EVT) | evapotranspiration drawn from the water table | if |
| DRN | drainage at the ground surface | if the `drainage` boundary is active |
| CHD | head imposed on ocean, stream and side cells | if one is active |
| WEL | the rate of each well | if a well exists |
| LAK | lake and reservoir exchange | if a lake is active |
| HFB | horizontal flow barrier on a shared face | if a barrier exists |
| SFR | stream network | if `sfr` is active |
| MVR | transfers between LAK, SFR and DRN | if one transfer exists |
| OC | what is written to disk | always |

HydroModPy writes no UZF, GHB or RIV package.

### The grid

MODFLOW 6 reads every grid as a DISV grid, structured or not: one code path covers both.
A structured model is a DISV grid whose cells are the DEM pixels. A mesh built from Gmsh
is, by default, the Voronoi dual of its triangles, which is orthogonal to its connections.
{toml}`modflow6.sgrid.grid_dual` keeps the triangles as cells instead. The number of
layers is {toml}`modflow6.sgrid.vertical.nlay`. The mesh is the subject of {doc}`mesh`.

### Flow between cells, and XT3D

NPF receives $K$, $K_z = K/\beta$ and the convertible flag. The first layer of the model
also carries the drains. With the two-point conductance {eq}`eq-conductance`, the flux
between two cells is exact only when the line between the centres is perpendicular to
the shared face and the conductivity is isotropic. XT3D adds the missing terms. The code
decides about it once per run, and the rule, its trigger and the equation are on
{doc}`solvers/xt3d-on-irregular-disv-meshes`. XT3D makes the matrix non-symmetric, so the
IMS preset is promoted when needed ({ref}`solvers-newton-ims`). In the code:
`resolve_xt3d_decision`.

### Storage

STO receives $S_y$ and $S_s$ and a steady or transient flag for each period. The flags
are written only where they change. $S_s$ matters only where the aquifer is confined, but
MODFLOW 6 asks for a value. In the code: `sto_period_settings`.

### Recharge and evaporation

RCHA gets one rate per column and per period. The rate is the value of
{toml}`flow.sinks_sources.recharge.values`, or the recharge the soil reservoir computes
(see {doc}`soil-reservoir`). The cells of a lake that the model makes inactive receive
none, because LAK handles the rain on the lake. The package also carries a
`CONCENTRATION` auxiliary variable, which transport uses
({ref}`solvers-transport-coupling`).

EVTA draws evapotranspiration from the water table, with the law of the MODFLOW EVT
package {cite:p}`harbaugh2005`: a full rate at and above a surface, falling linearly to
zero at an extinction depth below it. Under MODFLOW 6 it receives a routed negative
recharge ({toml}`flow.sinks_sources.recharge.negative_to_evt`) or, in soil mode, the ETP
the soil could not meet. The loaded ETP is ignored outside soil mode, with a warning. The
surface and the depth of each case, and the cells left without EVT, are on {doc}`exits`.
In the code: `mask_recharge_on_lake_cells`.

### Drains

The `drainage` boundary lets the water table leave at the ground surface. HydroModPy
writes one drain in the first layer of every active cell that is not an ocean or stream
constant-head cell. The conductance is declared or derived from $K$, it has a floor, and
an optional discharge band lowers the drain and scales its conductance.
{toml}`solver.sink_fill` sets it to zero in closed depressions. The law, the conductance,
the band and a worked cell are on {doc}`exits`. In the code:
`build_drain_stress_period_data`.

### Imposed heads and wells

CHD imposes the head of the ocean, stream and lateral boundaries on their cells. MODFLOW 6
takes one CHD package, so the three supports are merged, and a cell claimed twice keeps
the head written last. WEL adds the rate of each well. Under the Newton formulation the
code sets `auto_flow_reduce` to 0.1 on WEL, so that a well that dewaters its cell tapers
its extraction instead of making the head oscillate across the threshold. In the code:
`assemble_constant_head_stress_period_data`.

### Lakes, streams and barriers

LAK, SFR, MVR and HFB exist under MODFLOW 6 only. LAK and SFR are built after the drains,
so that the drains that coincide with a stream reach can be removed and the drainage of
the hillslope can be handed to the stream or lake it flows to. MVR is built last, because
it names the packages it moves water between. The equations of these exits are on
{doc}`exits`, and their keys are in
{doc}`[flow.sinks_sources] <../reference/parameters/flow/sinks_sources/index>`.

(solvers-newton-ims)=
### The solution: Newton and IMS

The code writes `NEWTON`, and adds `UNDER_RELAXATION` when
{toml}`modflow6.runtime.mf6_newton_under_relaxation` is true. Newton is on by default,
because every cell is convertible. That option is a rule about one cell: it damps the head
of a cell whose head is above the bottom while the Newton head is below it.

IMS runs the outer iteration of {eq}`eq-newton` and, inside it, the inner linear solve,
with the tests of {eq}`eq-closure`. The code passes the closure criteria, the iteration
limits and the optional {toml}`modflow6.runtime.mf6_linear_acceleration`,
{toml}`modflow6.runtime.mf6_under_relaxation` and {toml}`modflow6.runtime.mf6_inner_rclose`
to the IMS package. The under-relaxation of IMS adjusts $\omega$ of the outer iteration.
It is not the Newton option of the previous paragraph.

A configured `SIMPLE` complexity is promoted to `COMPLEX` when XT3D is on, and to at least
`MODERATE` under Newton, because `SIMPLE` assumes a symmetric, well-conditioned matrix.
The promotion matters only when you set `SIMPLE`. Two combinations are refused:

- {toml}`modflow6.runtime.mf6_newton` and {toml}`modflow6.runtime.mf6_enable_rewet`
  together stop the run with `[HMPY.E405]` when the NPF package is built, because MODFLOW 6
  forbids rewetting under the Newton formulation.
- Conjugate-gradient acceleration under Newton stops with `[HMPY.E406]`, because the
  Newton Jacobian is not symmetric and CG cannot solve it. The check runs before any grid
  is built. Use `BICGSTAB`, or leave {toml}`modflow6.runtime.mf6_linear_acceleration`
  unset.

In the code: `resolve_ims_complexity`.

### Output

OC saves the head and the budget at the end of every stress period, not at every step.
The catalog keeps one record per stress period.

## MODFLOW-NWT, package by package

`ModflowNwt` builds the FloPy model in this order, and `assemble_flopy_packages` adds the
stress packages.

| Package | What it adds to the balance | Written |
|---|---|---|
| NWT | the Newton solver and its closure | always |
| DIS | the structured grid and the steps of {ref}`solvers-time` | always |
| CHD | head imposed on the transient ocean and side cells | if a transient boundary is active |
| BAS | active cells (`ibound`), starting heads, the no-flow sentinel | always |
| UPW | $K$, $K_z$, $S_y$, $S_s$ with upstream weighting | always |
| EVT | evapotranspiration drawn from the water table | if an ETP or a negative recharge exists |
| RCH | $N\,a_n$ | if a recharge exists |
| DRN | drainage at the ground surface, the law of {doc}`exits` | if the `drainage` boundary is active |
| WEL | the rate of each well | if a well exists |
| OC | head and budget at every step | always |
| LMT | the link file for MT3DMS | only when an MT3DMS process follows |

The static ocean and side boundaries are not CHD rows. They are cells with a negative
`ibound` in BAS, which imposes the starting head on them. Four things differ from
MODFLOW 6.

- **The grid must be structured.** NWT stops with `MODFLOW NWT requires a structured grid`.
  A `[mesh_catchment]` section does not change that: the solver keeps the grid it builds
  from the DEM.
- **The unconfined law is the upstream-weighted UPW package**, with its own smoothing of
  the saturated thickness, set by {toml}`modflownwt.runtime.nwt.thickfact`
  ({doc}`mf6-vs-nwt`). The closure is the third line of {eq}`eq-closure`.
- **EVT uses the topography.** The code sets the EVT surface to the top lowered by
  {toml}`flow.sinks_sources.etp.surface_offset` and the extinction depth to
  {toml}`flow.sinks_sources.etp.extinction_depth`, with `nevtop` from
  {toml}`modflownwt.runtime.evt.nevtop`. The field
  {toml}`modflownwt.process_specific.exdp` is declared but nothing in the code reads it.
  When no ETP is active, a routed negative recharge uses an offset of 2 m and a depth of
  1 m.
- **No soil reservoir, lakes, streams or barriers.** The checks listed under Limits stop
  the file.

In the code: `assemble_flopy_packages`.

(solvers-wetting-drying)=
## Wetting and drying

A cell dries when the head falls to its bottom. The solvers differ in what they do next.

| Case | What happens | Set by |
|---|---|---|
| MODFLOW 6, Newton | The cell stays in the equations. Conductance and storage go to zero smoothly, and `UNDER_RELAXATION` damps the head of a cell that Newton would push below its bottom. | {toml}`modflow6.runtime.mf6_newton`, {toml}`modflow6.runtime.mf6_newton_under_relaxation` |
| MODFLOW 6, standard formulation with rewet | The cell is rewetted by the NPF rewet test. Newton must be off. | {toml}`modflow6.runtime.mf6_enable_rewet` and the four `mf6_rewet_*` keys |
| MODFLOW-NWT | The cell stays in the equations. A dry cell is written with the dry-head value. | {toml}`modflownwt.runtime.upw.iphdry`, {toml}`modflownwt.runtime.upw.hdry` |
| Boussinesq | The saturated thickness is bounded between zero and the cell thickness, so the head can go below the bottom without a negative thickness. | the runtime, see {doc}`boussinesq` |

Rewetting is off unless {toml}`modflow6.runtime.mf6_enable_rewet` is true. When it is on,
the NPF package gets `WETFCT`, `IWETIT` and `IHDWET` from the `mf6_rewet_*` keys, and an
array `WETDRY` that is zero on inactive cells and the absolute value of
{toml}`modflow6.runtime.mf6_rewet_wetdry` elsewhere. To use it you set Newton off:

```toml
base_config = "step4_transient.toml"

[modflow6.runtime]
mf6_newton = false
mf6_enable_rewet = true
```

In the code: `resolve_rewet_npf_options`.

## The Boussinesq solver

The in-house solver writes one residual per triangle of a Gmsh mesh, with the head as the
unknown, and counts a loss of water as positive. It solves each stress period in one
backward Euler step and does not read {toml}`simulation.time.substeps_per_period`. A
runtime is chosen by name, with {toml}`flow.runtime_backend` for the nonlinear solver and
{toml}`flow.surface_interaction_model` for the water that reaches the surface; a runtime
that assembles a dense Jacobian stops on a mesh of more than 400 cells. It builds
recharge, wells, the side, stream and ocean imposed heads, and top drainage, and refuses
the rest. Its equations, its closures and its limits are on {doc}`boussinesq`.

(solvers-transport-coupling)=
## Transport coupling

A transport process attaches to the flow process that came before it. The planner binds
each transport run to an earlier flow run of the right solver, in the order written in the
file, and stops with `requires an earlier process using flow/<solver>` when there is none.
The pairs are declared by each adapter as its `requires` attribute.

| Transport process | Needs the flow solver | What it does |
|---|---|---|
| `modflow6` (GWT) | `modflow6` | concentration in the flow field |
| `modflow6_prt` | `modflow6` | particle tracking, MODFLOW 6 PRT |
| `modpath` | `modflow_nwt` | particle tracking, MODPATH 6 |
| `mt3dms` | `modflow_nwt` | concentration, MT3DMS |

### MODFLOW 6 GWT

`Modflow6Transport` adds a GWT model to the MODFLOW 6 simulation of the flow run. It
reuses the DISV grid and the `idomain` of the flow model, couples the two models with a
`GWF6-GWT6` exchange, and gives GWT its own IMS with `BICGSTAB`, because advection makes
the matrix non-symmetric. The transport solve is linear, so it uses the configured
complexity and no Newton promotion. What HydroModPy sets in the GWT model:

- advection with the scheme of {toml}`transport.modflow6gwt.parameters.scheme`;
- dispersion only when {toml}`transport.modflow6gwt.parameters.disp_long` or
  {toml}`transport.modflow6gwt.parameters.diffu_coeff` is above zero;
- the mobile storage with {toml}`transport.modflow6gwt.parameters.porosity`. Without it,
  the code falls back on the specific yield and warns that this underestimates the pore
  volume, because the pore velocity is the Darcy flux divided by the porosity;
- decay of order zero or one, from {toml}`transport.modflow6gwt.parameters.react_order`
  and {toml}`transport.modflow6gwt.parameters.rate_decay`.

Recharge is the only source of solute. Its concentration travels as the `CONCENTRATION`
auxiliary variable of RCHA, and the source and sink mixing package reads it. Constant-head
cells and wells bring water in at concentration zero.

### MODFLOW 6 particle tracking

`modflow6_prt` builds a PRT model on the same flow model. It needs the cell-by-cell
velocity that {toml}`modflow6.runtime.save_specific_discharge` writes. Its keys are in
{doc}`[transport] <../reference/parameters/transport>`.

### MODFLOW-NWT: MODPATH and MT3DMS

MODPATH builds a MODPATH 6 input from the NWT run and stops if the flow model is not
MODFLOW-NWT. MT3DMS needs the link file that the LMT package writes. NWT adds LMT only when
an MT3DMS process is planned after it. The file name is
{toml}`modflownwt.runtime.lmt.output_file_name`. In the code: `_requires_mt3dms_link`.

Before you compare transport results, check the flow run they stand on: the head
convention, the active cells and their volumes, the budget of each period, and the
storage and drainage terms of the sections above.

## Assumptions

- Flow is saturated, in one phase, and the head is the only unknown. Water above the water
  table is not modelled: the code writes no UZF package, and the soil reservoir of
  {doc}`soil-reservoir` is a separate daily model that hands a recharge to the solver.
- Every layer is convertible: it can be confined or unconfined from one step to the next.
- A stress period holds its forcings constant. The recharge and the ETP of one period are
  one rate per column.
- Time stepping is backward Euler, with equal steps in a period, in the two MODFLOW
  solvers. For the linear problem the end state of a period does not depend on the order
  of its steps; for the unconfined problem this holds only approximately.
- The horizontal conductivity is isotropic. The vertical one is the horizontal one divided
  by one ratio for the whole model, or a per-cell $K_z$ field.
- The drains sit in the first layer, at the ground surface, or half a band depth below it.
- The model has no feedback from the solver to the soil reservoir.

## Limits

- **Grid.** MODFLOW-NWT works on the structured grid only. The Boussinesq solver works on
  Gmsh triangles only, and a dense runtime on a mesh of more than 400 cells.
- **Boundaries.** Lakes, reservoirs, SFR and barriers need MODFLOW 6. The `stream` boundary
  needs MODFLOW 6 or Boussinesq. The file is refused otherwise, when
  {toml}`solver.backend` names the solver: `does not support the 'sfr' boundary` is the
  start of the message for the first case, and
  `does not support flow barriers / dam cutoff walls (HFB); they require the 'modflow6' backend.`
  is the whole message for barriers.
- **Soil reservoir.** `[flow.sinks_sources.recharge.soil] is wired to MODFLOW 6 only`
  stops a file that asks for it with another solver.
- **ETP.** MODFLOW 6 draws no ETP outside soil mode, and only logs a warning.
  Boussinesq rejects it.
- **Hotstart and cyclic spin-up.** `flow.restart_from` and a cyclic spin-up need MODFLOW 6,
  the only solver that declares the two capabilities.
- **Newton.** Newton with rewet, and Newton with conjugate gradients, are refused.
- **Transport.** Concentration and particle tracking depend on the solver of the flow run,
  as in {ref}`solvers-transport-coupling`. Boussinesq has no transport.
- **Not represented.** The code writes no unsaturated-zone package (UZF), no
  variable-density package (BUY), no subsidence package (CSUB), and no GHB or RIV
  package.

## Parameters of this page

The keys of the equations and of the solver options of this page. The keys of each
transport process are on its reference card.

```{hmp-params}
simulation.time.substeps_per_period
flow.flow_regime
flow.first_period_steady
modflow6.runtime.mf6_ats
modflow6.runtime.mf6_newton
modflow6.runtime.mf6_newton_under_relaxation
modflow6.runtime.mf6_ims_complexity
modflow6.runtime.mf6_outer_dvclose
modflow6.runtime.mf6_inner_dvclose
modflow6.runtime.mf6_inner_rclose
modflow6.runtime.mf6_outer_maximum
modflow6.runtime.mf6_inner_maximum
modflow6.runtime.mf6_linear_acceleration
modflow6.runtime.mf6_under_relaxation
modflow6.runtime.mf6_enable_rewet
modflow6.runtime.mf6_rewet_wetdry
modflownwt.runtime.nwt.headtol
modflownwt.runtime.nwt.fluxtol
modflownwt.runtime.nwt.maxiterout
modflownwt.runtime.nwt.thickfact
modflownwt.runtime.nwt.backflag
modflownwt.runtime.upw.iphdry
modflownwt.runtime.upw.hdry
calibration.reject_water_budget_above
```

## Checked by

The tests that import the code of this page. The box is generated: a new test appears
here on the next build.

```{hmp-tested-by}
hydromodpy.solver.modflow6
hydromodpy.solver.modflow_nwt
hydromodpy.solver.modflow_common
hydromodpy.solver.modflow_grid
hydromodpy.solver.boussinesq
```

## In the code

| What | Where |
|---|---|
| Steps, steady flags, the first period | `hydromodpy/solver/modflow_grid/discretization_temporal.py` (`build_temporal_discretization_from_time_grid`, `resolve_first_period_steady`) |
| MODFLOW 6: every package, in order | `hydromodpy/solver/modflow6/build.py` (`run_pre_processing`) |
| XT3D decision, IMS complexity | `hydromodpy/solver/modflow6/builders/solver_options.py` (`resolve_xt3d_decision`, `resolve_ims_complexity`) |
| Newton options, guards, IMS options, ATS | `hydromodpy/solver/modflow6/build.py` (`newton_options`, `guard_newton_rewet`, `guard_newton_linear_acceleration`, `optional_ims_kwargs`, `build_ats_perioddata`) |
| Rewet options, starting heads | `hydromodpy/solver/modflow6/builders/initial_conditions.py` (`resolve_rewet_npf_options`, `build_start_heads`) |
| Recharge and EVT | `hydromodpy/solver/modflow6/builders/recharge.py` (`recharge_to_spd`, `build_soil_evta_payload`, `mask_recharge_on_lake_cells`) |
| Drains | `hydromodpy/solver/modflow6/builders/boundary_conditions.py` (`build_drain_stress_period_data`), `hydromodpy/solver/modflow_common/drain_conductance.py` |
| Constant heads and wells | `boundary_conditions.py` (`assemble_constant_head_stress_period_data`), `hydromodpy/solver/modflow6/builders/wells.py` |
| Lakes, streams, barriers, movers | `hydromodpy/solver/modflow6/builders/` (`lake.py`, `sfr.py`, `flow_barrier.py`, `mvr.py`) |
| Budget discrepancy | `hydromodpy/solver/modflow_common/flow_adapter_helpers.py` (`percent_discrepancies`), `hydromodpy/calibration/runners/verdict.py` (`water_budget_verdict`) |
| MODFLOW-NWT: solver and packages | `hydromodpy/solver/modflow_nwt/nwt/nwt_solver.py`, `hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py` (`assemble_flopy_packages`) |
| Boussinesq: time loop and size limit | `hydromodpy/solver/boussinesq/drivers/transient.py`, `hydromodpy/solver/boussinesq/boussinesq.py` |
| Transport solvers | `hydromodpy/solver/modflow6/transport.py`, `hydromodpy/solver/modflow6/prt.py`, `hydromodpy/solver/modflow_nwt/mt3dms/mt3dms.py`, `hydromodpy/solver/modflow_nwt/modpath/modpath.py` |
| Which transport follows which flow | `requires` of each adapter in `hydromodpy/solver/*/adapters/`, `hydromodpy/simulation/planning/planner.py` |
| Solver names and capabilities | `hydromodpy/solver/base/registry.py` |

## See also

- {doc}`groundwater-flow`: the continuous equation and the balance of a cell.
- {doc}`mf6-vs-nwt`: the two MODFLOW solvers compared.
- {doc}`boussinesq`: the full Boussinesq theory.
- {doc}`exits`: drains, streams and lakes as exits of the aquifer.
- {doc}`validation`: the checks against reference solutions.
