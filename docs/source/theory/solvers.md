# The solvers of the aquifer

HydroModPy integrates the groundwater flow equation with one of three solvers: MODFLOW 6,
MODFLOW-NWT or the in-house Boussinesq solver. This page says what each of them does with
the model you describe in the file: the packages it writes, the numerical options the code
sets, what happens to a cell that dries, and how a transport run hooks onto a flow run.
It does not say how to pick a solver (see {doc}`../guides/choose-a-solver`), nor how to
make a run converge (see {doc}`../guides/non-convergence`).

:::{note}
**Scope.** The continuous equation is on {doc}`groundwater-flow`. Its control-volume
form is on {doc}`solvers/modflow-governing-equation-and-cvfd-formulation`. The full
Boussinesq theory is on {doc}`boussinesq`, and the extra terms XT3D adds on irregular
meshes are on {doc}`solvers/xt3d-on-irregular-disv-meshes`. What the two MODFLOW solvers
do differently, side by side, is on {doc}`mf6-vs-nwt`. This page follows the code of
`hydromodpy/solver/`, in the order it writes things.
:::

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

The rows are developed in the sections below. The names in the first row are the values
read by {toml}`simulation.process.solvers`.

## Notation

Cells are numbered $n$, and $m$ runs over the cells that share a face with $n$. All
quantities are per cell. Lengths are in metres and time is in seconds: the run is
written in seconds whatever the calendar of the file (`SIMULATION_TIME_UNIT` in
`hydromodpy/core/time/window.py`).

| Symbol | Meaning | Unit | Read from |
|---|---|---|---|
| $h_n$ | head of cell $n$ at the end of a step | m | state, not a field |
| $z^t_n$, $z^b_n$ | top and bottom of cell $n$ | m | state: the top comes from the DEM, the bottom from {toml}`domain.depth_model` |
| $A_n$ | plan area of cell $n$ | m$^2$ | state, set by the mesh |
| $K_n$ | horizontal hydraulic conductivity | m/s | {toml}`K\|flow.param.K` |
| $K^{v}_n$ | vertical conductivity, $K_n / \mathrm{vka}$ | m/s | {toml}`vka\|modflow6.process_specific.vka` |
| $S_y$, $S_s$ | specific yield, specific storage | -, 1/m | {toml}`Sy\|flow.param.Sy` and {toml}`Ss\|flow.param.Ss` |
| $C_{nm}$ | conductance between cells $n$ and $m$ | m$^2$/s | state, built from $K$, the geometry and the heads |
| $V_n(h)$ | volume of water held by cell $n$ at head $h$ | m$^3$ | state, not a field |
| $L_k$ | length of stress period $k$ | s | {toml}`step_value\|simulation.time.step_value` |
| $n_k$ | number of steps in period $k$ | - | {toml}`substeps_per_period\|simulation.time.substeps_per_period` |
| $\Delta t$ | length of one step, $L_k / n_k$ | s | state, not a field |
| $r_n$ | recharge rate | m/s | {toml}`values\|flow.sinks_sources.recharge.values` |
| $H_n(t)$ | imposed head of a constant-head cell | m | the boundaries in {toml}`flow.active_bc` |
| $Q^w_n$ | well rate, negative when pumping | m$^3$/s | {toml}`flux\|flow.sinks_sources.wells.<name>.flux` |

## 1. Time and starting heads

The three solvers read the same time grid, built from {toml}`simulation.time`. Each
stress period $k$ has a length $L_k$ and holds every forcing constant. The code cuts it
into $n_k$ equal steps:

$$
\Delta t = \frac{L_k}{n_k}, \qquad n_k = \text{substeps\_per\_period} .
$$

The function is `build_temporal_discretization_from_time_grid` in
`hydromodpy/solver/modflow_grid/discretization_temporal.py`. MODFLOW 6 receives the
lengths and step counts in its TDIS package, with a step multiplier of 1
(`hydromodpy/solver/modflow6/build.py:942`). MODFLOW-NWT receives them in DIS
(`hydromodpy/solver/modflow_nwt/nwt/nwt_solver.py:388`) and HydroModPy leaves the
multiplier at the FloPy value, 1. Equal steps are deliberate: inside one period the forcing
does not change, so the backward Euler state at the end of the period depends on the set
of step sizes and not on their order, and equal steps give the smallest error. One step
per period is not a neutral choice. The card of
{toml}`simulation.time.substeps_per_period` gives the size of the error it makes.

A period is steady or transient. With {toml}`flow.flow_regime` set to `"steady"`, every
period is steady. With `"transient"`, only the first period is steady, and only when
{toml}`flow.first_period_steady` is true. The steady first period gives the heads from
which the transient periods start.

Example 04 writes its regime in `step4_transient.toml`:

```{hmp-resolved} flow.flow_regime
:config: step4_transient.toml
```

The starting heads of the first period come from {toml}`flow.ic.h`, or from a previous run
when {toml}`flow.restart_from` is set. MODFLOW 6 then overwrites the starting head of every
ocean, stream and side constant-head cell with its imposed value
(`build_start_heads` in `hydromodpy/solver/modflow6/builders/initial_conditions.py`). The
other initial conditions, which run an auxiliary steady model or repeat the first period,
are described in {doc}`../guides/time-and-initial-state`.

## 2. The balance both MODFLOW solvers write

For every active cell $n$ and every step, MODFLOW 6 and MODFLOW-NWT write one balance.
What flows in from the neighbours and from the stress packages equals what the cell
stores {cite}`harbaugh2005,langevin2017`:

$$
\sum_{m} C_{nm}\,(h_m - h_n)\;+\;\sum_{p} Q^{p}_n(h_n)
\;=\;\frac{V_n(h_n) - V_n(h_n^{\,\mathrm{old}})}{\Delta t},
$$

where $p$ runs over the stress packages of the next sections and $h_n^{\mathrm{old}}$ is
the head at the start of the step. In a steady period the right-hand side is zero.

Two terms of this balance depend on the head, and that is what makes the problem
nonlinear. The first is the conductance. Schematically,

$$
C_{nm} = K_{nm}\,\bar b_{nm}\,\frac{w_{nm}}{d_{nm}},
$$

with $K_{nm}$ the harmonic mean of the two conductivities, $w_{nm}$ the width of the shared
face, $d_{nm}$ the distance between the two cell centres and $\bar b_{nm}$ the saturated
thickness at the face. That thickness is a function of $h_n$ and $h_m$. The exact
weighting is in the manuals and in
{doc}`solvers/modflow-governing-equation-and-cvfd-formulation`.

The second is the storage. Every layer is convertible: the code writes the convertible
flag for all layers, `icelltype = 1` in NPF and `iconvert = 1` in STO for MODFLOW 6
(`build.py:1159` and `build.py:1175`), and `laytyp = 1` in UPW for MODFLOW-NWT
(`hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py:61` and `:73`). The change of stored volume
with the head is, to first order,

$$
\frac{\partial V_n}{\partial h_n} =
\begin{cases}
S_y\,A_n & z^b_n < h_n \le z^t_n \quad \text{(the water table moves inside the cell)},\\[0.5ex]
S_s\,A_n\,(z^t_n - z^b_n) & h_n > z^t_n \quad \text{(the cell is confined)}.
\end{cases}
$$

The manuals give the complete form, which also lets $S_s$ act on the saturated thickness.
A steady period never reads $S_y$ or $S_s$.

Both solvers then solve the nonlinear system with a Newton step. Call $R_n$ the
difference between the two sides of the balance, and $J_{nm} = \partial R_n / \partial h_m$.
Iteration $j$ solves

$$
\mathbf J\bigl(\mathbf h^{(j)}\bigr)\,\delta\mathbf h = -\mathbf R\bigl(\mathbf h^{(j)}\bigr),
\qquad
\mathbf h^{(j+1)} = \mathbf h^{(j)} + \omega_j\,\delta\mathbf h ,
$$

with $0 < \omega_j \le 1$ the relaxation factor of the iteration {cite}`niswonger2011`.
The Newton form keeps a cell in the system when its head crosses the bottom: the
conductance and the storage go smoothly to zero instead of switching off. That is how
both solvers handle a drying cell without an inactive/active switch (see
{ref}`Wetting and drying <solvers-wetting-drying>`).

## 3. MODFLOW 6, package by package

`run_pre_processing` in `hydromodpy/solver/modflow6/build.py` assembles the FloPy
simulation in this order. A package marked "if" is written only when the file asks for it.

| Package | What it adds to the balance | Written | `build.py` |
|---|---|---|---|
| TDIS (and ATS) | the steps of section 1 | always | 942 |
| IMS | the nonlinear and linear solver | always | 968 |
| GWF | the Newton options | always | 981 |
| DISV | the cells, their tops and bottoms, $A_n$, $C_{nm}$ geometry | always | 1143 |
| IC | $h^{(0)}$ | always | 1154 |
| NPF | $K$, $K^{v}$, convertible flag, XT3D | always | 1159 |
| STO | $S_y$, $S_s$, steady or transient flag per period | always | 1175 |
| RCHA | $+r_n A_n$ | always | 1200 |
| EVTA (or EVT) | $-$ evapotranspiration drawn from the water table | if | 1258 to 1297 |
| DRN | $-$ drainage at the ground surface | if the `drainage` boundary is active | 1360 |
| CHD | head imposed on ocean, stream and side cells | if one is active | 1383 |
| WEL | $Q^w_n$ | if a well exists | 1396 |
| LAK | lake and reservoir exchange | if a lake is active | 1423 |
| HFB | horizontal flow barrier on a shared face | if a barrier exists | 1470 |
| SFR | stream network | if `sfr` is active | 1505 |
| MVR | transfers between LAK, SFR and DRN | if one transfer exists | 1529 |
| OC | what is written to disk | always | 1543 |

HydroModPy writes no UZF, GHB or RIV package.

### The grid

MODFLOW 6 reads every grid as a DISV grid, structured or not: one code path covers both
(`build.py:1143`). A structured model is a DISV grid whose cells are the DEM pixels. A mesh
built from Gmsh is, by default, the Voronoi dual of its triangles, which is orthogonal to
its connections. {toml}`modflow6.sgrid.grid_dual` keeps the triangles as cells instead.
The number of layers is {toml}`modflow6.sgrid.vertical.nlay`. The mesh itself is the
subject of {doc}`mesh`.

### Flow between cells, and XT3D

NPF receives $K$ (the first layer of the model sets the drains, every layer sets the flow),
$K^v = K/\mathrm{vka}$ and the convertible flag. With the two-point conductance of the
section above, the flux between two cells is exact only when the line between the centres
is perpendicular to the shared face. On a mesh that departs from that, XT3D adds the
missing terms.

The code decides about XT3D once per run (`resolve_xt3d_decision` in
`hydromodpy/solver/modflow6/builders/solver_options.py`):

1. A value in {toml}`modflow6.runtime.mf6_enable_xt3d` wins. If it disagrees with the
   checks below, the code logs a warning and keeps your value.
2. On a structured grid, XT3D is off.
3. If the horizontal conductivity is anisotropic or angled, XT3D is on. The code writes
   no such input today, so this branch does not fire.
4. Otherwise the code measures, on every connection, the angle between the line that
   joins the two centres and the normal of the shared face. XT3D is on when more than 5 %
   of the connections are above 30 degrees, or when the 95th percentile is above 30
   degrees (the constants `_NONORTH_FRAC_GT30_TRIGGER` and `_NONORTH_P95_TRIGGER_DEG`,
   `solver_options.py:16` and `:17`). Otherwise it is off.

XT3D makes the matrix non-symmetric, so the IMS preset is promoted when needed (see
{ref}`The solution: Newton and IMS <solvers-newton-ims>`).

### Storage

STO receives $S_y$ and $S_s$ and a steady or transient flag for each period
(`sto_period_settings` in `hydromodpy/solver/modflow6/builders/period_forcing.py`). The
flags are written only where they change. Example 04 sets $S_s$ by hand in
`step4_transient.toml`, and a comment there says that it only matters where the aquifer is
confined, but MODFLOW 6 asks for a value.

### Recharge and evaporation

RCHA gets one rate per column and per period. The rate is the value of
{toml}`flow.sinks_sources.recharge.values`, or the recharge the soil reservoir computes
(see {doc}`soil-reservoir`). The cells of a lake that the model makes inactive receive none, because LAK handles the
rain on the lake (`mask_recharge_on_lake_cells` in
`hydromodpy/solver/modflow6/builders/recharge.py`). The package also carries a
`CONCENTRATION` auxiliary variable, which transport uses (see
{ref}`Transport coupling <solvers-transport-coupling>`).

EVTA draws evapotranspiration from the water table, with the law of the MODFLOW EVT
package {cite}`harbaugh2005`: a full rate at and above a surface, falling linearly to zero
at an extinction depth below it. Under MODFLOW 6 it receives a routed negative recharge
({toml}`flow.sinks_sources.recharge.negative_to_evt`) or, in soil mode, the ETP the soil
could not meet. The loaded ETP is ignored outside soil mode, with a warning
(`ETP_IGNORED_OUTSIDE_SOIL_MODE`, `recharge.py`). The surface and the depth of each case,
and the cells left without EVT, are on {doc}`exits`.

### Drains

The `drainage` boundary lets the water table leave at the ground surface. HydroModPy
writes one drain in the first layer of every active cell that is not an ocean or stream
constant-head cell (`build_drain_stress_period_data`,
`hydromodpy/solver/modflow6/builders/boundary_conditions.py:369`). The conductance is
declared or derived from $K$, it has a floor, and an optional discharge band lowers the
drain and scales its conductance (`hydromodpy/solver/modflow_common/drain_conductance.py`).
{toml}`solver.sink_fill` sets it to zero in closed depressions. The law, the conductance,
the band and a worked cell are on {doc}`exits`, with the routing of the drained water to
streams and lakes.

### Imposed heads and wells

CHD imposes $h_n = H_n(t)$ on the cells of the ocean, stream and lateral boundaries.
MODFLOW 6 takes one CHD package, so the three supports are merged, and a cell claimed
twice keeps the head written last (`assemble_constant_head_stress_period_data`,
`boundary_conditions.py:455`). WEL adds the rate $Q^w_n$. Under the Newton formulation the
code sets `auto_flow_reduce` to 0.1 on WEL, so that a well that dewaters its cell tapers
its extraction instead of making the head oscillate across the threshold
(`build.py:1395`).

### Lakes, streams and barriers

LAK, SFR, MVR and HFB exist under MODFLOW 6 only. LAK and SFR are built after the
drains, so that the drains that coincide with a stream reach can be removed and the
drainage of the hillslope can be handed to the stream or lake it flows to. MVR is built
last, because it names the packages it moves water between. The equations of these
exits are on {doc}`exits`, and the task guides are {doc}`../guides/lakes-and-reservoirs`,
{doc}`../guides/route-streams-with-sfr` and {doc}`../guides/add-a-flow-barrier`.

(solvers-newton-ims)=
### The solution: Newton and IMS

The Newton options come from `newton_options` (`build.py:614`): the code writes `NEWTON`,
and adds `UNDER_RELAXATION` when {toml}`modflow6.runtime.mf6_newton_under_relaxation`
is true. Newton is on by default, because every cell is convertible. That option is a
rule about one cell: it damps the head of a cell whose head is above the bottom while the
Newton head is below it.

IMS runs the outer (nonlinear) iteration of the formula in section 2 and, inside it, an
inner linear solve. The code passes the closure criteria, the iteration limits and the
optional {toml}`modflow6.runtime.mf6_linear_acceleration`,
{toml}`modflow6.runtime.mf6_under_relaxation` and
{toml}`modflow6.runtime.mf6_inner_rclose` of `[modflow6.runtime]` to the IMS package
(`build.py:968` and `optional_ims_kwargs`, `build.py:649`). The under-relaxation of IMS
adjusts $\omega_j$ of the outer iteration. It is not the Newton option of the previous
paragraph.

A configured `SIMPLE` complexity is promoted by `resolve_ims_complexity`
(`solver_options.py:126`): to `COMPLEX` when XT3D is on, and to at least `MODERATE` under
Newton. The reason is that `SIMPLE` assumes a symmetric, well-conditioned matrix. The
promotion matters only when you set `SIMPLE`.

Two combinations are refused:

- {toml}`modflow6.runtime.mf6_newton` and {toml}`modflow6.runtime.mf6_enable_rewet`
  together stop the run with `[HMPY.E405]` when the NPF package is built, because MODFLOW 6
  forbids rewetting under the Newton formulation (`build.py:625`).
- Conjugate-gradient acceleration under Newton stops with `[HMPY.E406]`, because the
  Newton Jacobian is not symmetric and CG cannot solve it. The check runs before any grid
  is built. Use `BICGSTAB`, or leave {toml}`modflow6.runtime.mf6_linear_acceleration`
  unset (`build.py:636`).

With {toml}`modflow6.runtime.mf6_ats` the code adds adaptive time stepping to the
transient periods. Each period starts at the step of section 1, ATS subdivides it only
where the solver cannot converge, and it never grows past that step
(`build_ats_perioddata`, `build.py:123`). Steady periods are left out.

### Output

OC saves the head and the budget at the end of every stress period, not at every step
(`saverecord=[("HEAD", "LAST"), ("BUDGET", "LAST")]`, `build.py:1547`). The catalog keeps
one record per stress period.

## 4. MODFLOW-NWT, package by package

`ModflowNwt` in `hydromodpy/solver/modflow_nwt/nwt/nwt_solver.py` builds the FloPy model in
this order, and `assemble_flopy_packages` in `_pre_processing.py` adds the stress
packages.

| Package | What it adds to the balance | Written |
|---|---|---|
| NWT | the Newton solver and its closure | always (`nwt_solver.py:245`) |
| DIS | the structured grid and the steps of section 1 | always (`nwt_solver.py:388`) |
| CHD | head imposed on the transient ocean and side cells | if a transient boundary is active |
| BAS | active cells (`ibound`), starting heads, the no-flow sentinel | always (`_pre_processing.py:53`) |
| UPW | $K$, $K^v$, $S_y$, $S_s$ with upstream weighting | always (`_pre_processing.py:71`) |
| EVT | evapotranspiration drawn from the water table | if an ETP or a negative recharge exists |
| RCH | $+r_n A_n$ | if a recharge exists |
| DRN | drainage at the ground surface, the law of {doc}`exits` | if the `drainage` boundary is active |
| WEL | $Q^w_n$ | if a well exists |
| OC | head and budget at every step | always |
| LMT | the link file for MT3DMS | only when an MT3DMS process follows |

The static ocean and side boundaries are not CHD rows. They are cells with a negative
`ibound` in BAS, which imposes the starting head on them.

Four things differ from MODFLOW 6.

- **The grid must be structured.** NWT stops with `MODFLOW NWT requires a structured grid`
  (`nwt_solver.py:289`). A `[mesh_catchment]` section does not change that: the solver
  keeps the grid it builds from the DEM.
- **The unconfined law is the upstream-weighted UPW package.** The closure of the Newton
  loop is set by {toml}`modflownwt.runtime.nwt.headtol`,
  {toml}`modflownwt.runtime.nwt.fluxtol` and
  {toml}`modflownwt.runtime.nwt.maxiterout`. The smoothing of the saturated thickness near
  the cell bottom is {toml}`modflownwt.runtime.nwt.thickfact`
  {cite}`niswonger2011`.
- **EVT uses the topography.** The code sets the EVT surface to the top lowered by
  {toml}`flow.sinks_sources.etp.surface_offset` and the extinction depth to
  {toml}`flow.sinks_sources.etp.extinction_depth`, with `nevtop` from
  {toml}`modflownwt.runtime.evt.nevtop` (`_pre_processing.py:99`). The field
  {toml}`modflownwt.process_specific.exdp` is declared but nothing in the code reads it.
  When no ETP is active, a routed negative recharge uses an offset of 2 m and a depth of
  1 m (`build_etp_payload`, `payloads/recharge_etp.py`).
- **No soil reservoir, lakes, streams or barriers.** The checks listed under Limits stop the file.

(solvers-wetting-drying)=
## 5. Wetting and drying

A cell dries when the head falls to its bottom. The solvers differ in what they do next.

| Case | What happens | Set by |
|---|---|---|
| MODFLOW 6, Newton | The cell stays in the equations. Conductance and storage go to zero smoothly, and `UNDER_RELAXATION` damps the head of a cell that Newton would push below its bottom. | {toml}`modflow6.runtime.mf6_newton`, {toml}`modflow6.runtime.mf6_newton_under_relaxation` |
| MODFLOW 6, standard formulation with rewet | The cell is rewetted by the NPF rewet test. Newton must be off. | {toml}`modflow6.runtime.mf6_enable_rewet` and the four `mf6_rewet_*` keys |
| MODFLOW-NWT | The cell stays in the equations. A dry cell is written with the dry-head value. | {toml}`modflownwt.runtime.upw.iphdry`, {toml}`modflownwt.runtime.upw.hdry` |
| Boussinesq | The saturated thickness is bounded between zero and the cell thickness, so the head can go below the bottom without a negative thickness. | the runtime, see section 6 |

Rewetting is off unless {toml}`modflow6.runtime.mf6_enable_rewet` is true
(`rewet_is_enabled`, `hydromodpy/solver/modflow6/builders/initial_conditions.py:22`). When
it is on, the NPF package gets `WETFCT`, `IWETIT` and `IHDWET` from the `mf6_rewet_*` keys,
and an array `WETDRY` that is zero on inactive cells and the absolute value of
{toml}`modflow6.runtime.mf6_rewet_wetdry` elsewhere (`resolve_rewet_npf_options`, same
file). To use it you set Newton off:

```toml
base_config = "step4_transient.toml"

[modflow6.runtime]
mf6_newton = false
mf6_enable_rewet = true
```

The file below loads, and the run then stops at `[HMPY.E405]`:

```toml
# not checked: this file loads, and the run stops when the package is built
base_config = "step4_transient.toml"

[modflow6.runtime]
mf6_newton = true
mf6_enable_rewet = true
```

## 6. The Boussinesq solver, in short

The in-house solver is not a MODFLOW wrapper. It writes one residual per triangular cell of
a Gmsh mesh, with the head as the unknown. The full derivation is on {doc}`boussinesq`.
This page keeps what bears on how the solvers compare.

The saturated thickness is clipped to the cell, and the transmissivity follows it:

$$
b_n(h) = \min\!\bigl(\max(h_n - z^b_n,\ 0),\ z^t_n - z^b_n\bigr), \qquad T_n = K_n\,b_n(h).
$$

A transient period adds a backward Euler storage term with a lower-bounded thickness,
$M_n(h) = A_n S_n \max(h_n - z^b_n, 0)$, so that

$$
R_n(h^{\mathrm{new}}) = \frac{M_n(h^{\mathrm{new}}) - M_n(h^{\mathrm{old}})}{\Delta t}
+ \sum_e q_e + (\text{drainage, wells, recharge, surface terms}) = 0,
$$

with $q_e$ the flux through an edge, which uses the harmonic mean of $K$ and the average
thickness of the two cells. The shallow-groundwater equation descends from
{cite}`boussinesq1877,dupuit1863`, and {cite}`brutsaert2005` is a textbook treatment. Each
cell residual is written with the sign that removes water from the cell. The solver
differs from the two MODFLOW solvers in four ways.

- **One step per period.** `run_transient_runtime`
  (`hydromodpy/solver/boussinesq/drivers/transient.py:73`) solves each stress period in
  one backward Euler step. {toml}`simulation.time.substeps_per_period` is not read. The
  PETSc obstacle runtimes can substep with {toml}`flow.vi_substeps_per_period`. A period
  that does not converge ends the run.
- **A runtime is chosen by name.** {toml}`flow.runtime_backend` selects the nonlinear
  solver and {toml}`flow.surface_interaction_model` selects the closure for the water
  that reaches the surface.
- **A size limit for the dense runtimes.** A runtime that assembles a dense Jacobian stops
  on a mesh of more than 400 cells (`_assert_runtime_mesh_size_supported`,
  `boussinesq.py:487`).
- **Fewer boundaries.** It builds recharge, wells, the side, stream and ocean imposed heads,
  and top drainage. It has no lakes, SFR, barriers or soil reservoir, it refuses an ETP,
  and it refuses a `[transport]` section.

(solvers-transport-coupling)=
## 7. Transport coupling

A transport process attaches to the flow process that came before it. The planner binds
each transport run to an earlier flow run of the right solver, in the order written in the
file, and stops with `requires an earlier process using flow/<solver>` when there is none
(`hydromodpy/simulation/planning/planner.py:108`). The pairs are declared by each adapter
as its `requires` attribute.

| Transport process | Needs the flow solver | What it does |
|---|---|---|
| `modflow6` (GWT) | `modflow6` | concentration in the flow field |
| `modflow6_prt` | `modflow6` | particle tracking, MODFLOW 6 PRT |
| `modpath` | `modflow_nwt` | particle tracking, MODPATH 6 |
| `mt3dms` | `modflow_nwt` | concentration, MT3DMS |

### MODFLOW 6 GWT

`Modflow6Transport` (`hydromodpy/solver/modflow6/transport.py`) adds a GWT model to the
MODFLOW 6 simulation of the flow run. It reuses the DISV grid and the `idomain` of the
flow model, couples the two models with a `GWF6-GWT6` exchange, and gives GWT its own IMS
with `BICGSTAB`, because advection makes the matrix non-symmetric. The transport solve is
linear, so it uses the configured complexity and no Newton promotion.

What HydroModPy sets in the GWT model:

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
velocity that {toml}`modflow6.runtime.save_specific_discharge` writes. The task guide is
{doc}`../guides/track-particles`.

### MODFLOW-NWT: MODPATH and MT3DMS

MODPATH builds a MODPATH 6 input from the NWT run and stops if the flow model is not
MODFLOW-NWT (`hydromodpy/solver/modflow_nwt/modpath/modpath.py`). MT3DMS needs the link
file that the LMT package writes. NWT adds LMT only when an MT3DMS process is planned
after it (`nwt_solver.py:482` and `_requires_mt3dms_link` in
`hydromodpy/solver/modflow_common/flow_adapter_helpers.py`). The file name is
{toml}`modflownwt.runtime.lmt.output_file_name`.

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
  solvers. The solution at the end of a step does not depend on the order of the steps of
  a period.
- The horizontal conductivity is isotropic. The vertical one is the horizontal one divided
  by one ratio for the whole model, or a per-cell $K^v$ field.
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
  is the whole message for barriers (`hydromodpy/config/hydromodpy_config.py:600` and
  `:660`).
- **Soil reservoir.** `[flow.sinks_sources.recharge.soil] is wired to MODFLOW 6 only`
  stops a file that asks for it with another solver (`hydromodpy_config.py:709`).
- **ETP.** MODFLOW 6 draws no ETP outside soil mode, and only logs a warning.
  Boussinesq rejects it.
- **Hotstart and cyclic spin-up.** `flow.restart_from` and a cyclic spin-up need MODFLOW 6,
  the only solver that declares the two capabilities (`hydromodpy/solver/base/registry.py`).
- **Newton.** Newton with rewet, and Newton with conjugate gradients, are refused.
- **Transport.** Concentration and particle tracking depend on the solver of the flow run,
  as in section 7. Boussinesq has no transport.
- **Not represented.** The code writes no unsaturated-zone package (UZF), no
  variable-density package (BUY), no subsidence package (CSUB), and no GHB or RIV
  package.

## Parameters of this page

Time and starting state.

```{hmp-params}
simulation.time.substeps_per_period
flow.flow_regime
flow.first_period_steady
flow.ic.h.type
```

MODFLOW 6: the grid, the flow law and the stress terms.

```{hmp-params}
modflow6.sgrid.grid_dual
modflow6.sgrid.vertical.nlay
modflow6.process_specific.vka
modflow6.process_specific.evt_extinction_depth
modflow6.runtime.mf6_enable_xt3d
flow.sinks_sources.recharge.negative_to_evt
flow.sinks_sources.etp.surface_offset
flow.sinks_sources.etp.extinction_depth
solver.drain_bed_thickness_m
solver.drain_band_depth_m
solver.drain_conductance_floor_m2_s
solver.sink_fill
```

MODFLOW 6: the nonlinear and linear solution, and the dry cells.

```{hmp-params}
modflow6.runtime.mf6_newton
modflow6.runtime.mf6_newton_under_relaxation
modflow6.runtime.mf6_ims_complexity
modflow6.runtime.mf6_outer_dvclose
modflow6.runtime.mf6_inner_dvclose
modflow6.runtime.mf6_outer_maximum
modflow6.runtime.mf6_inner_maximum
modflow6.runtime.mf6_inner_rclose
modflow6.runtime.mf6_linear_acceleration
modflow6.runtime.mf6_under_relaxation
modflow6.runtime.mf6_ats
modflow6.runtime.mf6_ats_dtmin_s
modflow6.runtime.mf6_enable_rewet
modflow6.runtime.mf6_rewet_wetfct
modflow6.runtime.mf6_rewet_iwetit
modflow6.runtime.mf6_rewet_ihdwet
modflow6.runtime.mf6_rewet_wetdry
```

MODFLOW-NWT.

```{hmp-params}
modflownwt.runtime.nwt.headtol
modflownwt.runtime.nwt.fluxtol
modflownwt.runtime.nwt.maxiterout
modflownwt.runtime.nwt.thickfact
modflownwt.runtime.nwt.linmeth
modflownwt.runtime.nwt.options
modflownwt.runtime.nwt.ibotav
modflownwt.runtime.nwt.backflag
modflownwt.runtime.nwt.stoptol
modflownwt.runtime.nwt.continue_run
modflownwt.runtime.upw.iphdry
modflownwt.runtime.upw.hdry
modflownwt.runtime.evt.nevtop
modflownwt.process_specific.vka
```

Boussinesq.

```{hmp-params}
flow.runtime_backend
flow.surface_interaction_model
flow.vi_substeps_per_period
```

Transport.

```{hmp-params}
transport.modflow6gwt.parameters.scheme
transport.modflow6gwt.parameters.porosity
transport.modflow6gwt.parameters.disp_long
transport.modflow6gwt.parameters.diffu_coeff
transport.modflow6gwt.parameters.react_order
transport.modflow6gwt.parameters.rate_decay
modflow6.runtime.save_specific_discharge
modflownwt.runtime.lmt.output_file_name
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
| Newton options, guards, ATS | `hydromodpy/solver/modflow6/build.py` (`newton_options`, `guard_newton_rewet`, `guard_newton_linear_acceleration`, `build_ats_perioddata`) |
| Rewet options, starting heads | `hydromodpy/solver/modflow6/builders/initial_conditions.py` (`resolve_rewet_npf_options`, `build_start_heads`) |
| Recharge and EVT | `hydromodpy/solver/modflow6/builders/recharge.py` (`recharge_to_spd`, `build_soil_evta_payload`, `build_evt_array_stress_period_data`) |
| Drains | `hydromodpy/solver/modflow6/builders/boundary_conditions.py` (`build_drain_stress_period_data`), `hydromodpy/solver/modflow_common/drain_conductance.py` |
| Constant heads and wells | `boundary_conditions.py` (`assemble_constant_head_stress_period_data`), `hydromodpy/solver/modflow6/builders/wells.py` |
| Lakes, streams, barriers, movers | `hydromodpy/solver/modflow6/builders/` (`lake.py`, `sfr.py`, `flow_barrier.py`, `mvr.py`) |
| MODFLOW-NWT: solver and packages | `hydromodpy/solver/modflow_nwt/nwt/nwt_solver.py`, `hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py` (`assemble_flopy_packages`) |
| MODFLOW-NWT: what the flow object becomes | `hydromodpy/solver/modflow_nwt/nwt/flow_to_modflow_adapter.py` and `payloads/` |
| Boussinesq: time loop and size limit | `hydromodpy/solver/boussinesq/drivers/transient.py`, `hydromodpy/solver/boussinesq/boussinesq.py` |
| Transport solvers | `hydromodpy/solver/modflow6/transport.py`, `hydromodpy/solver/modflow6/prt.py`, `hydromodpy/solver/modflow_nwt/mt3dms/mt3dms.py`, `hydromodpy/solver/modflow_nwt/modpath/modpath.py` |
| Which transport follows which flow | `requires` of each adapter in `hydromodpy/solver/*/adapters/`, `hydromodpy/simulation/planning/planner.py` |
| Solver names and capabilities | `hydromodpy/solver/base/registry.py` |

## See also

- {doc}`groundwater-flow`: the continuous equation.
- {doc}`solvers/modflow-governing-equation-and-cvfd-formulation`: the control-volume form.
- {doc}`solvers/xt3d-on-irregular-disv-meshes`: the XT3D terms.
- {doc}`boussinesq`: the full Boussinesq theory.
- {doc}`mf6-vs-nwt`: the two MODFLOW solvers compared.
- {doc}`exits`: drains, streams and lakes as exits of the aquifer.
- {doc}`validation`: the checks against reference solutions.
- {doc}`../guides/choose-a-solver` and {doc}`../guides/non-convergence`: the task guides.
- {doc}`bibliography`: the references cited here.
