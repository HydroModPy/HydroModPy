# The solvers of the aquifer

HydroModPy integrates the groundwater flow equation with one of three solvers: MODFLOW 6,
MODFLOW-NWT or the in-house Boussinesq solver. This page says which packages and options
HydroModPy writes for each of them, how it sets the time steps, what happens to a cell that
dries, how the two MODFLOW solvers differ, and how a transport run hooks onto a flow run.
What each solver supports is listed in {doc}`../reference/solvers`.

:::{note}
**Scope.** The balance of a cell, {eq}`eq-cell-balance`, is on {doc}`groundwater-flow`. The
Boussinesq solver is on {doc}`boussinesq` and the XT3D terms on
{doc}`solvers/xt3d-on-irregular-disv-meshes`.
:::

(modflow-governing-equation)=
## Sources

The MODFLOW equations, packages and numerical methods are documented by the USGS. This page
does not repeat them. It says which options HydroModPy writes.

- MODFLOW 6 groundwater flow model: control-volume formulation, Newton-Raphson, storage and
  stress packages {cite:p}`langevin2017`.
- MODFLOW 6 framework and the IMS linear solver {cite:p}`hughes2017framework`.
- XT3D option of the `NPF` package {cite:p}`provost2017`.
- MODFLOW-NWT, the Newton formulation of MODFLOW-2005 {cite:p}`niswonger2011`, on the
  MODFLOW-2005 groundwater flow process {cite:p}`harbaugh2005`.
- MODFLOW 6 groundwater transport model {cite:p}`langevin2022gwt` and water mover package
  {cite:p}`morway2021mvr`.
- The [MODFLOW 6 input guide](https://modflow6.readthedocs.io/en/latest/mf6io.html) and the
  [MODFLOW-NWT guide](https://water.usgs.gov/ogw/modflow-nwt/MODFLOW-NWT-Guide/), for the
  definition of each package and option.

## The three solvers side by side

| | MODFLOW 6 | MODFLOW-NWT | Boussinesq |
|---|---|---|---|
| Name in `solvers` | `modflow6` | `modflow_nwt` | `boussinesq` |
| Grid | DISV for every grid, structured or not | structured grid only (DIS) | triangular cells of a Gmsh mesh |
| Time | backward Euler, equal steps in a period | backward Euler, equal steps in a period | one backward Euler step per period |
| Transport | GWT and particle tracking | MODPATH and MT3DMS | refused |

The names in the first row are the values read by {toml}`simulation.process.solvers`. The
capabilities of each solver, generated from the code, are on {doc}`../reference/solvers`.

::::{dropdown} Notation of this page
Lengths are in metres and time is in seconds: the run is written in seconds whatever the
calendar of the file.

```{hmp-notation}
```
::::

(solvers-time)=
## Time steps

The three solvers read the same time grid, built from {toml}`simulation.time`. Each
stress period has a length $\Delta t$ and holds every forcing constant. The two MODFLOW
solvers cut it into $n_\mathrm{sub}$ equal steps, $\delta t = \Delta t / n_\mathrm{sub}$,
with a step multiplier of 1: MODFLOW 6 in its [`TDIS`](https://modflow6.readthedocs.io/en/latest/_mf6io/sim-tdis.html)
package, MODFLOW-NWT in `DIS`.

Equal steps are a choice with a test behind it. On a confined column against a closed-form
solution, `test_stress_period_substepping` finds equal steps more accurate than a geometric
growth of the steps, in either direction, and one step per period about ten times less
accurate than ten steps ({doc}`validation`). The unconfined problem is nonlinear, so this
holds there only approximately. The same case reports that one step per period moves the
monthly discharge of a drained hillslope by tens of per cent against a refined run. One
step per period is therefore not a neutral choice.

```{eval-rst}
.. plot:: theory/figures/solvers_substeps.py
   :alt: Head error at the end of a period against the number of steps, with two geometric partitions of ten steps.
   :caption: The confined column of ``test_stress_period_substepping``: 200 cells of 5 m, a
      head step of 1 m held for 31 days, with the backward Euler equations MODFLOW 6 solves
      for this linear case. Ten steps that grow or shrink by 2 give the same error, about
      four times that of ten equal steps.
```

A period is steady or transient. With {toml}`flow.flow_regime` set to `"steady"`, every
period is steady. With `"transient"`, only the first period is steady, and only when
{toml}`flow.first_period_steady` is true. With {toml}`modflow6.runtime.mf6_ats`, MODFLOW 6
adds [adaptive time stepping](https://modflow6.readthedocs.io/en/latest/_mf6io/utl-ats.html)
to the transient periods: each period starts at the step above, ATS subdivides it only where
the solver cannot converge, and it never grows past that step. Steady periods are left out.
The starting heads are on {ref}`gwf-start`. In the code:
`build_temporal_discretization_from_time_grid`.

## The nonlinear solve

MODFLOW 6 and MODFLOW-NWT both write the balance {eq}`eq-cell-balance` for every active
cell and every step, and solve the nonlinear system by Newton-Raphson outer iterations, with
a linear solve inside each one {cite:p}`hughes2017framework,niswonger2011`. The tests that
stop the iteration and the percent discrepancy of the budget are the ones of the listing
file, defined in the sources above. They do not measure the same thing on the two solvers:
MODFLOW-NWT tests a norm of the residual over all cells, MODFLOW 6 a maximum over the cells
of the linear solve. What HydroModPy adds:

- The keys that set the tests are {toml}`modflow6.runtime.mf6_outer_dvclose`,
  {toml}`modflow6.runtime.mf6_inner_dvclose` and {toml}`modflow6.runtime.mf6_inner_rclose`
  for MODFLOW 6, and {toml}`modflownwt.runtime.nwt.headtol` and
  {toml}`modflownwt.runtime.nwt.fluxtol` for MODFLOW-NWT. Heads are in m, flows in m³/s.
  HydroModPy writes `inner_rclose` with no option, which keeps the absolute largest
  residual of a cell. When the key is unset, the value of the complexity preset applies.
- The run metrics keep the percent discrepancy of the last step and the worst one of the
  run. A calibration rejects a trial whose last value is above
  {toml}`calibration.reject_water_budget_above`. The auxiliary steady solve of a
  `steady_state` start accepts its result only within 0.1 per cent.
  In the code: `percent_discrepancies`.

## MODFLOW 6, package by package

`run_pre_processing` assembles the FloPy simulation in this order. A package marked "if"
is written only when the file asks for it. Each package name links its input-guide page.

| Package | Written |
|---|---|
| [TDIS](https://modflow6.readthedocs.io/en/latest/_mf6io/sim-tdis.html), [IMS](https://modflow6.readthedocs.io/en/latest/_mf6io/sln-ims.html), GWF (the Newton options), [DISV](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-disv.html), [IC](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-ic.html), [NPF](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-npf.html), [STO](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-sto.html), [RCHA](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-rcha.html), [OC](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-oc.html) | always |
| [ATS](https://modflow6.readthedocs.io/en/latest/_mf6io/utl-ats.html) | if {toml}`modflow6.runtime.mf6_ats` is true |
| [EVTA](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-evta.html) (or [EVT](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-evt.html)) | if |
| [DRN](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-drn.html) | if the `drainage` boundary is active |
| [CHD](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-chd.html) | if one is active |
| [WEL](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-wel.html) | if a well exists |
| [LAK](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-lak.html) | if a lake is active |
| [HFB](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-hfb.html) | if a barrier exists |
| [SFR](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-sfr.html) | if `sfr` is active |
| [MVR](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-mvr.html) | if one transfer exists |

HydroModPy writes no UZF, GHB or RIV package. Three notes on the table.

- **Storage.** STO receives $S_y$ and $S_s$ and a steady or transient flag per period. The
  flags are written only where they change. $S_s$ matters only where the aquifer is
  confined, but MODFLOW 6 asks for a value. In the code: `sto_period_settings`.
- **Recharge.** RCHA gets one rate per column and per period: the value of
  {toml}`flow.sinks_sources.recharge.values`, or the recharge the soil reservoir computes
  ({doc}`soil-reservoir`). The cells of a lake that the model makes inactive receive none,
  because LAK handles the rain on the lake. The package also carries a `CONCENTRATION`
  auxiliary variable, which transport uses ({ref}`solvers-transport-coupling`). In the
  code: `mask_recharge_on_lake_cells`.
- **Output.** OC saves the head at the last step of every stress period and the budget at
  every step, and prints the budget of every step. The catalog keeps one record per stress
  period: the head at its end, each flux as the mean of its steps weighted by their length
  ({ref}`alignment-steps`).

### The grid

MODFLOW 6 reads every grid as a DISV grid, structured or not: one code path covers both.
A structured model is a DISV grid whose cells are the DEM pixels. A mesh built from Gmsh
is, by default, the Voronoi dual of its triangles, which is orthogonal to its connections.
{toml}`modflow6.sgrid.grid_dual` keeps the triangles as cells instead. The number of
layers is {toml}`modflow6.sgrid.vertical.nlay`. The mesh is the subject of {doc}`mesh`.

(solvers-computational-top)=
**The computational top.** Under Newton, MODFLOW 6 builds the horizontal conductance from
the full thickness of the two cells times the saturation of the upstream cell, where
MODFLOW-NWT and MODFLOW-USG use the saturated thickness
([`GwfConductanceUtils.f90`](https://github.com/MODFLOW-ORG/modflow6/blob/6.6.3/src/Model/ModelUtilities/GwfConductanceUtils.f90),
[NPF](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-npf.html)) {cite:p}`langevin2017`.
Where the thickness $H$ changes from one cell to the next, the transmissivity is then too
low by about $\Delta H / (2H)$. The grid MODFLOW 6 reads therefore has a computational top
$z'_\mathrm{top} = z_\mathrm{top} + \max H_1 - H_1$, with $H_1$ the thickness of the top
layer under the ground: every cell of the top layer gets the same thickness. A thickness
that is the same everywhere gives $z_\mathrm{top}$ back, so no file changes then. This is a
numerical device of HydroModPy, not a USGS practice. Every package elevation (drains, EVT,
streambeds, lake banks, barriers, the ocean), the initial heads and the run store keep the
ground. Water above the ground stays in the aquifer up to $z'_\mathrm{top}$, with its
specific yield, where a cell topped at the ground would turn confined; the drains at the
ground keep that rise to a few centimetres. Two limits. A lake column keeps its ground, since a raised top would
reach into the lake, so the thickness still changes at the banks. Only the top of the top
layer moves: a lower layer whose saturated part changes from cell to cell keeps the bias.
Anyone who opens the native MODFLOW 6 files (flopy, ModelMuse) sees a top above the ground
wherever the thickness varies. That is intended; the ground is `topography` in the run
store. In the code: `disv_grid_kwargs`.

### Flow between cells, and XT3D

NPF receives $K$, $K_z = K/\beta$ and the convertible flag. With the two-point conductance
{eq}`eq-conductance`, the flux between two cells is exact only when the line between the
centres is perpendicular to the shared face and the conductivity is isotropic. XT3D adds
the missing terms {cite:p}`provost2017`. HydroModPy decides about it once per run; the
rule and its trigger are on {doc}`solvers/xt3d-on-irregular-disv-meshes`. XT3D makes the
matrix non-symmetric, so the IMS preset is promoted when needed
({ref}`solvers-newton-ims`). In the code: `resolve_xt3d_decision`.

### Evaporation, drains, lakes and streams

The laws, conductances and worked cells of these exits are on {doc}`exits`.

- **Evaporation.** Under MODFLOW 6, EVTA receives a routed negative recharge
  ({toml}`flow.sinks_sources.recharge.negative_to_evt`) or, in soil mode, the ETP the soil
  could not meet. The loaded ETP is ignored outside soil mode, with a warning
  ({doc}`exits/drains-and-et`).
- **Drains.** One drain in the first layer of every active cell that is not an ocean or
  stream constant-head cell. It sits at the ground surface or half a band depth below it.
  {toml}`solver.sink_fill` sets it to zero in closed depressions
  ({doc}`exits/drains-and-et`). In the code: `build_drain_stress_period_data`.
- **Lakes, streams and barriers.** LAK, SFR, MVR and HFB exist under MODFLOW 6 only. LAK
  and SFR are built after the drains, so that the drains that coincide with a stream reach
  can be removed and the drainage of the hillslope can be handed to the stream or lake it
  flows to. MVR is built last, because it names the packages it moves water between
  ({doc}`exits/lakes`, {doc}`exits/streams-and-mover`).

### Imposed heads and wells

CHD imposes the head of the ocean, stream and lateral boundaries on their cells. MODFLOW 6
takes one CHD package, so the three supports are merged, and a cell claimed twice keeps
the head written last. WEL adds the rate of each well. Under the Newton formulation the
code sets `auto_flow_reduce` on WEL, so that a well that dewaters its cell tapers its
extraction instead of making the head oscillate across the threshold. MODFLOW 6 reads it as
a fraction of the cell height, and the option is one value per package: it is the
smallest fraction that keeps the interval within a tenth of the aquifer below the ground
in every well cell, 0.1 when the top is the ground. In the code:
`assemble_constant_head_stress_period_data`, `well_flow_reduce_fraction`.

(solvers-newton-ims)=
### The solution: Newton and IMS

The code writes `NEWTON`, and adds `UNDER_RELAXATION` when
{toml}`modflow6.runtime.mf6_newton_under_relaxation` is true. Newton is on by default,
because every layer is convertible. The `UNDER_RELAXATION` of the Newton option damps the
head of a cell that Newton would push below its bottom. It is not the under-relaxation of
IMS, which adjusts the update factor of the outer iteration.

The code passes the closure criteria, the iteration limits and the optional
{toml}`modflow6.runtime.mf6_linear_acceleration`,
{toml}`modflow6.runtime.mf6_under_relaxation` and {toml}`modflow6.runtime.mf6_inner_rclose`
to the IMS package. The complexity, {toml}`modflow6.runtime.mf6_ims_complexity`, defaults
to `COMPLEX`. A configured `SIMPLE` complexity
is promoted to `COMPLEX` when XT3D is on, and to at least `MODERATE` under Newton, because
`SIMPLE` assumes a symmetric, well-conditioned matrix. Two combinations are refused:

- {toml}`modflow6.runtime.mf6_newton` and {toml}`modflow6.runtime.mf6_enable_rewet`
  together stop the run with `[HMPY.E405]` when the NPF package is built, because MODFLOW 6
  forbids rewetting under the Newton formulation.
- Conjugate-gradient acceleration under Newton stops with `[HMPY.E406]`, because the
  Newton Jacobian is not symmetric and CG cannot solve it. The check runs before any grid
  is built. Use `BICGSTAB`, or leave {toml}`modflow6.runtime.mf6_linear_acceleration`
  unset.

In the code: `resolve_ims_complexity`.

## MODFLOW-NWT, package by package

`ModflowNwt` builds the FloPy model in this order, and `assemble_flopy_packages` adds the
stress packages.

| Package | Written |
|---|---|
| NWT: the Newton solver and its closure | always |
| DIS: the structured grid and the steps of {ref}`solvers-time` | always |
| CHD: head imposed on the transient ocean and side cells | if a transient boundary is active |
| BAS: active cells (`ibound`), starting heads, the no-flow sentinel | always |
| UPW: $K$, $K_z$, $S_y$, $S_s$ with upstream weighting | always |
| EVT | if an ETP or a negative recharge exists |
| RCH | if a recharge exists |
| DRN | if the `drainage` boundary is active |
| WEL | if a well exists |
| OC: head and budget at every step | always |
| LMT: the link file for MT3DMS | only when an MT3DMS process follows |

The static ocean and side boundaries are not CHD rows. They are cells with a negative
`ibound` in BAS, which imposes the starting head on them. Four things differ from
MODFLOW 6.

- **The grid must be structured.** NWT stops with `MODFLOW NWT requires a structured grid`.
  A `[mesh_catchment]` section does not change that: the solver keeps the grid it builds
  from the DEM.
- **The unconfined law is the upstream-weighted UPW package** {cite:p}`niswonger2011`,
  with a smoothing of the saturated thickness set by
  {toml}`modflownwt.runtime.nwt.thickfact`.
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

A cell dries when the head falls to its bottom. Under Newton, MODFLOW 6 smooths the
saturated thickness near the bottom with a fraction of the thickness that it sets
internally, and HydroModPy has no key for it {cite:p}`langevin2017`. MODFLOW-NWT does the
same in its `SAT_THICK` function, with the fraction read from
{toml}`thickfact|modflownwt.runtime.nwt.thickfact` {cite:p}`niswonger2011`. The smoothing
keeps the Newton step defined. It does not move the water table. The solvers differ in what
they do next.

| Case | What happens | Set by |
|---|---|---|
| MODFLOW 6, Newton | The cell stays in the equations. Conductance and storage go to zero smoothly, and `UNDER_RELAXATION` damps the head of a cell that Newton would push below its bottom. | {toml}`modflow6.runtime.mf6_newton`, {toml}`modflow6.runtime.mf6_newton_under_relaxation` |
| MODFLOW 6, standard formulation with rewet | The cell is rewetted by the NPF rewet test. Newton must be off. | {toml}`modflow6.runtime.mf6_enable_rewet` and the four `mf6_rewet_*` keys |
| MODFLOW-NWT | The cell stays in the equations. A dry cell is written with the dry-head value, and the reader of the results turns that value into a missing value. | {toml}`modflownwt.runtime.upw.iphdry`, {toml}`modflownwt.runtime.upw.hdry` |
| Boussinesq | The saturated thickness is bounded between zero and the cell thickness, without smoothing ({eq}`eq-saturated-thickness`). | the runtime, see {doc}`boussinesq` |

Rewetting is off unless {toml}`modflow6.runtime.mf6_enable_rewet` is true. When it is on,
the NPF package gets `WETFCT`, `IWETIT` and `IHDWET` from the `mf6_rewet_*` keys, and an
array `WETDRY` that is zero on inactive cells and the absolute value of
{toml}`modflow6.runtime.mf6_rewet_wetdry` elsewhere. In the code: `resolve_rewet_npf_options`.

(solvers-mf6-vs-nwt)=
## MODFLOW 6 against MODFLOW-NWT

The same project file can run on either. The solver that runs is the first name in
{toml}`simulation.process.solvers` of the `flow` process. {toml}`solver.backend` is the
fallback when no process names one, and the key the compatibility checks of a file are run
against. Write the same name in both. The settings live in `[modflownwt]` and `[modflow6]`.
This page ranks neither solver.

| Topic | MODFLOW-NWT | MODFLOW 6 |
|---|---|---|
| Newton | always | on by default, can be switched off |
| Dry cells | no rewetting (`laywet = 0`) | rewetting off, refused with Newton |
| Non-orthogonal flux | not available | `XT3D`, automatic on irregular meshes |
| Output | head and budget at every step, stored per period | head at the last step, budget at every step, stored per period |
| Loaded ETP | drives `EVT` | ignored outside soil mode |
| Streams, lakes, barriers | refused | `SFR`, `LAK`, `HFB` |
| Restart, cyclic spin-up | refused | supported |

The vertical conductivity is a ratio on both, $K_z = K / \beta$. The key is
{toml}`modflownwt.process_specific.vka` for MODFLOW-NWT, with `layvka` set so that `vka`
is read as a ratio, and {toml}`modflow6.process_specific.vka` for MODFLOW 6.

**Sources and sinks.** Recharge, wells, drains and constant heads are the same quantities
in both. Two points differ.

- **The loaded ETP** is a sink in MODFLOW-NWT, with its surface at the top minus
  {toml}`flow.sinks_sources.etp.surface_offset` and the extinction depth
  {toml}`flow.sinks_sources.etp.extinction_depth`. MODFLOW 6 draws none outside soil mode,
  and says so. In soil mode it writes the ETP the soil left unmet ({doc}`soil-reservoir`).
- **A negative recharge** sent to `EVT` by {toml}`flow.sinks_sources.recharge.negative_to_evt`
  follows the same rule in both ({doc}`forcing`), with a different geometry: the model top
  and {toml}`modflow6.process_specific.evt_extinction_depth` in MODFLOW 6, the two `etp`
  keys above or fixed constants in MODFLOW-NWT.

**Comparing the two.** To compare the solvers, set the head test to the same value on both
sides ({toml}`modflownwt.runtime.nwt.headtol` against the two `dvclose` keys): the residual
tests do not measure the same thing. {doc}`validation` lists the cases that run both solvers
against the same closed-form solution, and runs both on the catchment of example 04, where
their heads differ by less than a millimetre. Where the cell thickness changes from one
cell to the next, the two conductances differ, and the
{ref}`computational top <solvers-computational-top>` brings MODFLOW 6 back to
MODFLOW-NWT: on the circular-island cases, whose top follows the ground over a flat
bottom, both sit at the same distance from the closed form. {doc}`validation` gives the thresholds and the reason
for each. A threshold is a bound a test accepts, not a measured error, so it ranks nothing.

## The Boussinesq solver

The in-house solver writes one residual per triangle of a Gmsh mesh. It solves each stress
period in {toml}`simulation.time.substeps_per_period` backward Euler steps.
{toml}`flow.runtime_backend` picks the nonlinear solver, `auto` by default: the dense `local`
engine up to 400 cells and the sparse `scipy_sparse` above; a dense engine asked by name
stops on a larger mesh. {toml}`flow.surface_interaction_model` picks the closure for the
water that reaches the surface. It builds recharge, wells, the side, stream and ocean
imposed heads, and top drainage, and refuses the rest. Its flux between two cells uses the
two cell centres only: on triangles far from equilateral it is not consistent, and the
patch test of {doc}`validation` shows the error that refinement does not remove. Its
equations and closures are on {doc}`boussinesq`.

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

`Modflow6Transport` adds a [GWT](https://modflow6.readthedocs.io/en/latest/_mf6io/gwt-nam.html)
model to the MODFLOW 6 simulation of the flow run {cite:p}`langevin2022gwt`. It reuses the
DISV grid and the `idomain` of the flow model, couples the two models with a `GWF6-GWT6`
exchange, and gives GWT its own IMS with `BICGSTAB`, because advection makes the matrix
non-symmetric. The transport solve is linear, so it uses the configured complexity and no
Newton promotion. What HydroModPy sets in the GWT model:

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

`modflow6_prt` builds a [PRT](https://modflow6.readthedocs.io/en/latest/_mf6io/prt-nam.html)
model on the same flow model. It needs the cell-by-cell velocity that
{toml}`modflow6.runtime.save_specific_discharge` writes. Its keys are in
{doc}`[transport] <../reference/parameters/transport>`.

### MODFLOW-NWT: MODPATH and MT3DMS

MODPATH builds a MODPATH 6 input from the NWT run and stops if the flow model is not
MODFLOW-NWT. MT3DMS needs the link file that the LMT package writes. NWT adds LMT only when
an MT3DMS process is planned after it. The file name is
{toml}`modflownwt.runtime.lmt.output_file_name`. In the code: `_requires_mt3dms_link`.

## Assumptions

- Flow is saturated, in one phase, and the head is the only unknown. Water above the water
  table is not modelled: the code writes no UZF package, and the soil reservoir of
  {doc}`soil-reservoir` is a separate daily model that hands a recharge to the solver.
- Every layer is convertible: it can be confined or unconfined from one step to the next.
- The horizontal conductivity is isotropic. The vertical one is the horizontal one divided
  by one ratio for the whole model, or a per-cell $K_z$ field.

## Limits

The capability matrix is generated on {doc}`../reference/solvers`. The refusals, with their
messages, are these.

- **Grid.** MODFLOW-NWT works on the structured grid only. The Boussinesq solver works on
  Gmsh triangles only, and a dense runtime asked by name on a mesh of more than 400 cells.
- **Boundaries.** Lakes, reservoirs, SFR and barriers need MODFLOW 6. The `stream` boundary
  needs MODFLOW 6 or Boussinesq. When {toml}`solver.backend` names `modflow_nwt`, the file
  is refused when it is read if it asks for {toml}`flow.active_bc` with `sfr`, `lake`,
  `reservoir` or `stream`, for flow barriers or a dam cutoff wall, or for a head initial
  condition of type `spinup_cyclic`. `does not support the 'sfr' boundary` is the start of
  the message for the first case, and
  `does not support flow barriers / dam cutoff walls (HFB); they require the 'modflow6' backend.`
  is the whole message for barriers. An unstructured mesh stops the build with
  `MODFLOW NWT requires a structured grid`.
- **Soil reservoir.** `[flow.sinks_sources.recharge.soil] is wired to MODFLOW 6 only`
  stops a file that asks for it with another solver.
- **ETP.** MODFLOW 6 draws no ETP outside soil mode, and only logs a warning.
  Boussinesq rejects it.
- **Hotstart and cyclic spin-up.** {toml}`flow.restart_from` and a cyclic spin-up need
  MODFLOW 6, the only solver that declares the two capabilities.
- **Newton.** Newton with rewet (`HMPY.E405`) and Newton with conjugate gradients
  (`HMPY.E406`) are refused ({ref}`solvers-newton-ims`).
- **Not represented.** The code writes no unsaturated-zone package (UZF), no
  variable-density package (BUY), no subsidence package (CSUB), and no GHB or RIV
  package.

## Parameters of this page

The keys of the solver options of this page. The keys of each transport process are on its
reference card.

```{hmp-params}
simulation.process.solvers
solver.backend
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
modflow6.runtime.mf6_linear_acceleration
modflow6.runtime.mf6_under_relaxation
modflow6.runtime.mf6_enable_rewet
modflow6.runtime.mf6_rewet_wetdry
modflownwt.runtime.nwt.headtol
modflownwt.runtime.nwt.fluxtol
modflownwt.runtime.nwt.thickfact
modflownwt.runtime.upw.iphdry
modflownwt.runtime.upw.hdry
modflownwt.process_specific.vka
modflow6.process_specific.vka
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
| Recharge, EVT, drains, constant heads, wells | `hydromodpy/solver/modflow6/builders/` (`recharge.py`: `recharge_to_spd`, `build_soil_evta_payload`, `mask_recharge_on_lake_cells`; `boundary_conditions.py`: `build_drain_stress_period_data`, `assemble_constant_head_stress_period_data`; `wells.py`), `hydromodpy/solver/modflow_common/` (`recharge_evt_routing.py`, `drain_conductance.py`) |
| Lakes, streams, barriers, movers | `hydromodpy/solver/modflow6/builders/` (`lake.py`, `sfr.py`, `flow_barrier.py`, `mvr.py`) |
| Budget discrepancy | `hydromodpy/solver/modflow_common/flow_adapter_helpers.py` (`percent_discrepancies`), `hydromodpy/calibration/runners/verdict.py` (`water_budget_verdict`) |
| MODFLOW-NWT: solver and packages | `hydromodpy/solver/modflow_nwt/nwt/nwt_solver.py` (`_build_dis_package`, `_initialize_solver_packages`), `hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py` (`assemble_flopy_packages`) |
| Boussinesq: time loop and size limit | `hydromodpy/solver/boussinesq/drivers/transient.py`, `hydromodpy/solver/boussinesq/boussinesq.py` |
| Transport solvers | `hydromodpy/solver/modflow6/transport.py`, `hydromodpy/solver/modflow6/prt.py`, `hydromodpy/solver/modflow_nwt/mt3dms/mt3dms.py`, `hydromodpy/solver/modflow_nwt/modpath/modpath.py` |
| Which transport follows which flow | `requires` of each adapter in `hydromodpy/solver/*/adapters/`, `hydromodpy/simulation/planning/planner.py` |
| Solver names, capabilities, refusals at read time | `hydromodpy/solver/base/registry.py`, `hydromodpy/config/hydromodpy_config.py`, `hydromodpy/physics/flow/boundary_condition_registry.py` |

## See also

- {doc}`groundwater-flow`: the balance of a cell.
- {doc}`boussinesq`: the full Boussinesq theory.
- {doc}`exits`: drains, streams and lakes as exits of the aquifer.
- {doc}`validation`: the checks against reference solutions.
- {doc}`../reference/solvers`: the solvers and what each supports.
