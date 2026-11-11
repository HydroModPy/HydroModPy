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
| Mesh | DISV for every engine of {toml}`mesh.engine` | the `regular` engine only (DIS) | the `triangle` engine only |
| Time | backward Euler, equal steps in a period | backward Euler, equal steps in a period | one backward Euler step per period |
| Transport | GWT and particle tracking | MODPATH and MT3DMS | refused |

The names in the first row are the values read by {toml}`simulation.process.solvers`. The
traits of each solver, generated from the code, are on {doc}`../reference/solvers`.

::::{dropdown} Notation of this page
Lengths are in meters and time is in seconds: the run is written in seconds whatever the
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
{toml}`flow.first_period_steady` is true. With {toml}`solver.modflow6.runtime.mf6_ats`, MODFLOW 6
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

- The keys that set the tests are {toml}`solver.modflow6.runtime.mf6_outer_dvclose`,
  {toml}`solver.modflow6.runtime.mf6_inner_dvclose` and {toml}`solver.modflow6.runtime.mf6_inner_rclose`
  for MODFLOW 6, and {toml}`solver.modflow_nwt.runtime.nwt.headtol` and
  {toml}`solver.modflow_nwt.runtime.nwt.fluxtol` for MODFLOW-NWT. Heads are in m, flows in m³/s.
  HydroModPy writes `inner_rclose` with no option, which keeps the absolute largest
  residual of a cell. When the key is unset, the value of the complexity preset applies.
- The run metrics keep the percent discrepancy of the last step and the worst one of the
  run, both read from the volume budget of the entire model and not from a package budget.
  A calibration rejects a trial whose worst step is above
  {toml}`calibration.reject_water_budget_above` (one per cent unless the file says
  otherwise). The auxiliary steady solve of a `steady_state` start accepts its result only
  within 0.1 per cent.
  In the code: `model_percent_discrepancies`.

## MODFLOW 6, package by package

`run_pre_processing` assembles the FloPy simulation in this order. A package marked "if"
is written only when the file asks for it. Each package name links its input-guide page.

| Package | Written |
|---|---|
| [TDIS](https://modflow6.readthedocs.io/en/latest/_mf6io/sim-tdis.html), [IMS](https://modflow6.readthedocs.io/en/latest/_mf6io/sln-ims.html), GWF (the Newton options), [DISV](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-disv.html), [IC](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-ic.html), [NPF](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-npf.html), [STO](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-sto.html), [RCHA](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-rcha.html), [OC](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-oc.html) | always |
| [ATS](https://modflow6.readthedocs.io/en/latest/_mf6io/utl-ats.html) | if {toml}`solver.modflow6.runtime.mf6_ats` is true |
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
  auxiliary variable, which transport uses ({ref}`solvers-transport-coupling`). When the
  layers hold a pass-through cell ({ref}`mesh-layer-surfaces`), RCHA also writes the layer
  array `IRCH`, set to the top active layer of each column, because MODFLOW 6 drops the flux
  of a pass-through top cell instead of moving it down. Without such a cell the files are the
  same as before. In the code: `mask_recharge_on_lake_cells`, `areal_layer_index`.
- **Output.** OC saves the head at the last step of every stress period and the budget at
  every step, and prints the budget of every step. The catalog keeps one record per stress
  period: the head at its end, each flux as the mean of its steps weighted by their length
  ({ref}`alignment-steps`).

### The grid

MODFLOW 6 reads the cells of every mesh engine as a DISV grid: one code path covers the three.
A `regular` model is a DISV grid whose cells are the DEM pixels. The cells of the `voronoi`
engine are orthogonal to their connections, and the triangles of the `triangle` engine are not,
which turns XT3D on. The engine is {toml}`mesh.engine` and the number of layers is
{toml}`domain.layers.nlay`, read from the table `[domain.layers]` that MODFLOW-NWT reads too.
The mesh is the subject of {doc}`mesh`.

**The active cell of a column.** `idomain` is 1 for an active cell, 0 for an inactive one and
-1 for a vertical pass-through cell, and every test of activity reads it as above 0. The
packages that act on the surface of a column act on its top active cell, and not on the first
layer: the drains, the supports of the constant heads, the surface of the evapotranspiration,
the computational top below, the filling of the closed depressions, the lake footprint and the
saturated thickness the calibration reads. The footprint of a lake stays closed to them.
A constant head is written on active cells only.

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
that is the same everywhere gives $z_\mathrm{top}$ back, so no file changes then. The top moves
only on the columns whose top active cell is in the top layer: a column with a pinched
first layer keeps its interfaces, since its active cell joins cells of the second layer, which
cannot be raised. This is a
numerical device of HydroModPy, not a USGS practice. Every package elevation (drains, EVT,
streambeds, lake banks, barriers, the ocean), the initial heads and the run store keep the
ground. Water above the ground stays in the aquifer up to $z'_\mathrm{top}$, with its
specific yield, where a cell topped at the ground would turn confined; the drains at the
ground keep that rise to a few centimeters. Two limits. A lake column keeps its ground, since a raised top would
reach into the lake, so the thickness still changes at the banks. Only the top of the top
layer moves: a lower layer whose saturated part changes from cell to cell keeps the bias.
Anyone who opens the native MODFLOW 6 files (flopy, ModelMuse) sees a top above the ground
wherever the thickness varies. That is intended; the ground is `topography` in the run
store. In the code: `disv_grid_kwargs`.

### Flow between cells, and XT3D

NPF receives $K$, $K_z = K/\beta$ and the convertible flag, and `K22` and the three angles when
the flow sets them ({ref}`gwf-tensor`). With the two-point conductance
{eq}`eq-conductance`, the flux between two cells is exact only when the line between the
centers is perpendicular to the shared face and the conductivity is isotropic. XT3D adds
the missing terms {cite:p}`provost2017`. HydroModPy decides about it once per run; the
rule and its trigger are on {doc}`solvers/xt3d-on-irregular-disv-meshes`. XT3D makes the
matrix non-symmetric, so the IMS preset is promoted when needed
({ref}`solvers-newton-ims`). Two tensors need XT3D for a consistent result, so HydroModPy
turns it on and raises a `RuntimeWarning` on its cost. The first is a tilted tensor
(`angle2` or `angle3` not zero), because MODFLOW 6 reads these two angles only under XT3D. A
tilt writes the three angles, the missing ones as zero, since MODFLOW 6 refuses
`ANGLE2` without `ANGLE3`. The second is a `K22` different from $K$ on a cell whose `angle1` is
not a multiple of 90 degrees, or on any cell of an unstructured mesh. The axes of the tensor
then leave the connections and the two-point flux drops the cross terms
{cite:p}`provost2017`, so the head error does not shrink with refinement. For a steady well
with $K_{22} = K/10$ and `angle1` at 30 degrees on a structured grid, the head RMSE stayed at
2.2 m for a 7 m drawdown with cells of 40 m then 20 m, and fell to 0.04 then 0.01 m under
XT3D. XT3D costs time. On a steady benchmark of 120 by 120 cells and 10 layers, a run took 115
to 136 s with it, against 12 s without. A written {toml}`solver.modflow6.runtime.mf6_enable_xt3d` is
still obeyed, `true` without a warning and `false` with a `RuntimeWarning` when one of these
two tensors is set. In the code: `resolve_xt3d_decision`, `k_tensor_is_tilted`,
`k_tensor_is_off_axis`.

### Evaporation, drains, lakes and streams

The laws, conductances and worked cells of these exits are on {doc}`exits`.

- **Evaporation.** Under MODFLOW 6, EVTA receives a routed negative recharge
  ({toml}`flow.sinks_sources.recharge.negative_to_evt`) or, in soil mode, the ETP the soil
  could not meet, with the layer array `IEVT` when the layers hold a pass-through cell. The
  loaded ETP is ignored outside soil mode, with a warning ({doc}`exits/drains-and-et`).
- **Drains.** One drain in the top active layer of every column that is not an ocean or
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
{toml}`solver.modflow6.runtime.mf6_newton_under_relaxation` is true. Newton is on by default,
because every layer is convertible. The `UNDER_RELAXATION` of the Newton option damps the
head of a cell that Newton would push below its bottom. It is not the under-relaxation of
IMS, which adjusts the update factor of the outer iteration.

The code passes the closure criteria, the iteration limits and the optional
{toml}`solver.modflow6.runtime.mf6_linear_acceleration`,
{toml}`solver.modflow6.runtime.mf6_under_relaxation` and {toml}`solver.modflow6.runtime.mf6_inner_rclose`
to the IMS package, with the optional {toml}`solver.modflow6.runtime.mf6_reordering_method`. The
IMS can renumber the cells before it factorises, with reverse Cuthill-McKee (`rcm`) or minimum
degree (`md`) {cite:p}`hughes2017framework`. The default, `none`, keeps the numbering of the
mesh and writes nothing. The cases measured on 2026-10-26 gave no gain: on Voronoi meshes of
14 400 to 144 000 cells, in a shuffled or a row-sorted numbering, and on the steady Flume
solve of 73 400 cells, `rcm` and `md` added 3 to 73 per cent of inner iterations and did not
cut the wall time. The option reaches the IMS of the flow and the one of the transport. The
complexity, {toml}`solver.modflow6.runtime.mf6_ims_complexity`, defaults
to `COMPLEX`. A configured `SIMPLE` complexity
is promoted to `COMPLEX` when XT3D is on, and to at least `MODERATE` under Newton, because
`SIMPLE` assumes a symmetric, well-conditioned matrix. Two combinations are refused:

- {toml}`solver.modflow6.runtime.mf6_newton` and {toml}`solver.modflow6.runtime.mf6_enable_rewet`
  together stop the run with `[HMPY.E405]` when the NPF package is built, because MODFLOW 6
  forbids rewetting under the Newton formulation.
- Conjugate-gradient acceleration under Newton stops with `[HMPY.E406]`, because the
  Newton Jacobian is not symmetric and CG cannot solve it. The check runs before any grid
  is built. Use `BICGSTAB`, or leave {toml}`solver.modflow6.runtime.mf6_linear_acceleration`
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
| LMT: the link file of MT3DMS | when a transport follows |

The static ocean and side boundaries are not CHD rows. They are cells with a negative
`ibound` in BAS, which imposes the starting head on them. Four things differ from
MODFLOW 6.

- **The mesh must be the `regular` engine.** A file whose {toml}`mesh.engine` is another engine
  is refused when it is read. NWT builds the grid of the DEM pixels, or a coarser one given by
  {toml}`mesh.cell_size`.
- **The unconfined law is the upstream-weighted UPW package** {cite:p}`niswonger2011`,
  with a smoothing of the saturated thickness set by
  {toml}`solver.modflow_nwt.runtime.nwt.thickfact`.
- **EVT uses the topography.** The code sets the EVT surface to the top lowered by
  {toml}`flow.sinks_sources.etp.surface_offset` and the extinction depth to
  {toml}`flow.sinks_sources.etp.extinction_depth`, with `nevtop` from
  {toml}`solver.modflow_nwt.runtime.evt.nevtop`. The field
  {toml}`solver.modflow_nwt.process_specific.exdp` is declared but nothing in the code reads it.
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
{toml}`thickfact|solver.modflow_nwt.runtime.nwt.thickfact` {cite:p}`niswonger2011`. The smoothing
keeps the Newton step defined. It does not move the water table. The solvers differ in what
they do next.

| Case | What happens | Set by |
|---|---|---|
| MODFLOW 6, Newton | The cell stays in the equations. Conductance and storage go to zero smoothly, and `UNDER_RELAXATION` damps the head of a cell that Newton would push below its bottom. | {toml}`solver.modflow6.runtime.mf6_newton`, {toml}`solver.modflow6.runtime.mf6_newton_under_relaxation` |
| MODFLOW 6, standard formulation with rewet | The cell is rewetted by the NPF rewet test. Newton must be off. | {toml}`solver.modflow6.runtime.mf6_enable_rewet` and the four `mf6_rewet_*` keys |
| MODFLOW-NWT | The cell stays in the equations. A dry cell is written with the dry-head value, and the reader of the results turns that value into a missing value. | {toml}`solver.modflow_nwt.runtime.upw.iphdry`, {toml}`solver.modflow_nwt.runtime.upw.hdry` |
| Boussinesq | The saturated thickness is bounded between zero and the cell thickness, without smoothing ({eq}`eq-saturated-thickness`). | the runtime, see {doc}`boussinesq` |

Rewetting is off unless {toml}`solver.modflow6.runtime.mf6_enable_rewet` is true. When it is on,
the NPF package gets `WETFCT`, `IWETIT` and `IHDWET` from the `mf6_rewet_*` keys, and an
array `WETDRY` that is zero on inactive cells and the absolute value of
{toml}`solver.modflow6.runtime.mf6_rewet_wetdry` elsewhere. In the code: `resolve_rewet_npf_options`.

(solvers-mf6-vs-nwt)=
## MODFLOW 6 against MODFLOW-NWT

The same project file can run on either. The solver that runs is the first name in
{toml}`simulation.process.solvers` of the `flow` process. {toml}`solver.backend` is the
fallback when no process names one, and the key the compatibility checks of a file are run
against. Write the same name in both. {toml}`solver.backend` is a plain string, the name of a registered flow solver, and an unknown name
is refused with the names this installation serves. The settings of each solver are a table under
its name, `[solver.modflow_nwt]` and `[solver.modflow6]`. This page ranks neither solver.

| Topic | MODFLOW-NWT | MODFLOW 6 |
|---|---|---|
| Newton | always | {toml}`solver.modflow6.runtime.mf6_newton` |
| Dry cells | no rewetting (`laywet = 0`) | rewetting off, refused with Newton |
| Layering | `[domain.layers]`, shares or surfaces with `keep_min_thickness` | `[domain.layers]`, shares or surfaces, with `pass_through` cells |
| Non-orthogonal flux | not available | `XT3D`, automatic on irregular meshes and off-axis tensors |
| Conductivity tensor | refused | `K22` and the angles |
| Output | head and budget at every step, stored per period | head at the last step, budget at every step, stored per period |
| Loaded ETP | drives `EVT` | ignored outside soil mode |
| Streams, lakes, barriers | refused | `SFR`, `LAK`, `HFB` |
| Restart, cyclic spin-up | refused | supported |

The vertical conductivity is a ratio on both, $K_z = K / \beta$. The key is
{toml}`solver.modflow_nwt.process_specific.vka` for MODFLOW-NWT, with `layvka` set so that `vka`
is read as a ratio, and {toml}`solver.modflow6.process_specific.vka` for MODFLOW 6. A `Kv` of the flow
replaces the ratio on both. MODFLOW-NWT then writes `layvka = 0` and `vka = Kv`, so `UPW` reads
a conductivity, and a `vka` other than 1 beside a `Kv` is refused.

**Sources and sinks.** Recharge, wells, drains and constant heads are the same quantities
in both. Two points differ.

- **The loaded ETP** is a sink in MODFLOW-NWT, with its surface at the top minus
  {toml}`flow.sinks_sources.etp.surface_offset` and the extinction depth
  {toml}`flow.sinks_sources.etp.extinction_depth`. MODFLOW 6 draws none outside soil mode,
  and says so. In soil mode it writes the ETP the soil left unmet ({doc}`soil-reservoir`).
- **A negative recharge** sent to `EVT` by {toml}`flow.sinks_sources.recharge.negative_to_evt`
  follows the same rule in both ({doc}`forcing`), with a different geometry: the model top
  and {toml}`solver.modflow6.process_specific.evt_extinction_depth` in MODFLOW 6, the two `etp`
  keys above or fixed constants in MODFLOW-NWT.

**Comparing the two.** To compare the solvers, set the head test to the same value on both
sides ({toml}`solver.modflow_nwt.runtime.nwt.headtol` against the two `dvclose` keys): the residual
tests do not measure the same thing. {doc}`validation` lists the cases that run both solvers
against the same closed-form solution, and runs both on the catchment of example 04, where
their heads differ by less than a millimeter. Where the cell thickness changes from one
cell to the next, the two conductances differ, and the
{ref}`computational top <solvers-computational-top>` brings MODFLOW 6 back to
MODFLOW-NWT: on the circular-island cases, whose top follows the ground over a flat
bottom, both sit at the same distance from the closed form. {doc}`validation` gives the thresholds and the reason
for each. A threshold is a bound a test accepts, not a measured error, so it ranks nothing.

## The Boussinesq solver

The in-house solver writes one residual per triangle of the `triangle` engine. It solves each stress
period in {toml}`simulation.time.substeps_per_period` backward Euler steps.
{toml}`solver.boussinesq.backend` picks the nonlinear solver, `auto` by default: the dense `local`
engine up to 400 cells and the sparse `scipy_sparse` above; a dense engine asked by name
stops on a larger mesh. {toml}`solver.boussinesq.surface_interaction_model` picks the closure for the
water that reaches the surface. It builds recharge, wells, the side, stream and ocean
imposed heads, and top drainage, and refuses the rest. Its flux between two cells uses the
two cell centers only: on triangles far from equilateral it is not consistent, and the
patch test of {doc}`validation` shows the error that refinement does not remove. Its
equations and closures are on {doc}`boussinesq`.

## The linear reservoir

The sixth solver replaces the grid of the aquifer with one state: the depth of water on
the cell. It integrates `ds/dt = R - s/tau` exactly on every piece of constant rate the
run carries, where `R` is the recharge of the run and `tau` the time constant of
`[solver.linear_reservoir]`. One discharge and one reservoir storage leave the solve for
every period, at the station of the whole catchment, and the budget rows of the terms
recharge, drain and storage close it on the mass by construction.

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

The adapter of a transport receives four objects from the runner. `model` is the frozen
`Model` the flow was built from, the only `Model` a transport works from. `options` is the
validated table of its solver, `[transport.modflow6]` for the GWT of MODFLOW 6. The folder
it works in is the folder of the flow run itself, and `upstream[0]` is the `SolverRun` of
that flow.

What a transport declares as its `reads` is `face_flow`: the flux across each connection
between two cells, at every time step, in the format the solver files of the flow carry.
The name is the one of the field registry, where `connection_cells` sits beside it and
names the two cells of each connection, the smaller flat index first. The run store keeps
the pair only when {toml}`simulation.results.keep_face_flows` is true, in m3/s, one value
per connection at each stored stamp, the mean of the steps of the stamp weighted by their
length. A run of the default keeps no inter-cell flow, and the diagonal of `FLOW-JA-FACE`,
the residual of each cell, is never kept, because the per-cell budget already carries it.
MODFLOW 6 writes it as `FLOW-JA-FACE` in the cell-by-cell budget file of every step;
MODFLOW-NWT writes its face flows in the same file, and the link file of MT3DMS reads
from it. The flow solver writes what `reads` needs: a file that pairs a transport with a
flow solver that writes none of it is refused when the file is read, with the flow
solvers that write it. A transport of the family of its flow reaches what it reads
through that flow run, and none of them reads the run store during the solve. A
concentration transport stores its answer under the name of the solute,
`concentration/<spc_name>` in the run store, and a store written by a 2.0.0 run still
reads from the bare path.

### MODFLOW 6 GWT

`Modflow6Transport` adds a [GWT](https://modflow6.readthedocs.io/en/latest/_mf6io/gwt-nam.html)
model to the MODFLOW 6 simulation of the flow run {cite:p}`langevin2022gwt`. It reuses the
DISV grid and the `idomain` of the flow model, couples the two models with a `GWF6-GWT6`
exchange, writes the whole simulation again and solves it: the flow is then solved twice,
in the same folder. It gives GWT its own IMS with
`BICGSTAB`, because advection makes the matrix
non-symmetric. The transport solve is linear, so it uses the configured complexity and no
Newton promotion. What HydroModPy sets in the GWT model:

- advection with the scheme of {toml}`transport.modflow6.scheme`;
- dispersion only when {toml}`transport.modflow6.disp_long` or
  {toml}`transport.modflow6.diffu_coeff` is above zero;
- the mobile storage with {toml}`transport.modflow6.porosity`. Without it,
  the code falls back on the specific yield and warns that this underestimates the pore
  volume, because the pore velocity is the Darcy flux divided by the porosity;
- decay of order zero or one, from {toml}`transport.modflow6.react_order`
  and {toml}`transport.modflow6.rate_decay`.

Recharge is the only source of solute. Its concentration travels as the `CONCENTRATION`
auxiliary variable of RCHA, and the source and sink mixing package reads it. Constant-head
cells and wells bring water in at concentration zero.

### MODFLOW 6 particle tracking

`modflow6_prt` builds a [PRT](https://modflow6.readthedocs.io/en/latest/_mf6io/prt-nam.html)
model on the same flow model. It needs the cell-by-cell velocity that
{toml}`solver.modflow6.runtime.save_specific_discharge` writes. Its keys are in
{doc}`[transport] <../reference/parameters/transport>`.

### MODFLOW-NWT: MODPATH and MT3DMS

MODPATH builds a MODPATH 6 input from the NWT run and stops if the flow model is not
MODFLOW-NWT. MT3DMS reads the link file that the LMT package writes, and NWT adds LMT
when a transport run follows it: the run declares `face_flow` through its `reads`, which
the runner collects into the `hand_off` member of the slot of the flow run. The file name is
{toml}`solver.modflow_nwt.runtime.lmt.output_file_name`. In the code: `hand_off`, filled
by `slot_for` of the runner.

MODPATH releases its particles from the seepage areas of the flow run when
{toml}`transport.modpath.zone_partic` is `"seepage_clip"`. The mask is built from the
heads of the flow run itself, the water table of the first stored step against the
topography at half a drain band depth, exactly the rule the run store derives for its
`seepage_mask`, and the store is never read during the solve.

## Assumptions

- Flow is saturated, in one phase, and the head is the only unknown. Water above the water
  table is not modeled: the code writes no UZF package, and the soil reservoir of
  {doc}`soil-reservoir` is a separate daily model that hands a recharge to the solver.
- Every layer is convertible: it can be confined or unconfined from one step to the next.
- The horizontal conductivity is isotropic, unless the flow sets `K22` or the angles under
  MODFLOW 6. The vertical one is the horizontal one divided by one ratio for the whole model,
  or a per-cell $K_z$ field.

## Limits

The matrix of what each solver declares is generated on {doc}`../reference/solvers`. One rule gives
most of the refusals. Each flow solver lists in `supports` the traits of the model it honours, and a
file is refused when it is read if it uses a trait that the solver of the run leaves out. The message
gives the key the file wrote, the solver chosen and the solvers that honour the trait, for example
`solver.backend = 'modflow_nwt' does not honor flow.sinks_sources.lakes: it would be ignored without a word. Remove it, or run a flow solver that honors it (modflow6).`
A solver added by a plugin is checked by the same rule. A run sealed on disk is read back with a
warning instead of a refusal. The refusals are these.

- **Mesh.** MODFLOW 6 reads every engine, MODFLOW-NWT the `regular` engine and Boussinesq the
  `triangle` engine. A file that pairs a solver with another engine is refused when it is read:
  the message starts `solver 'modflow_nwt' reads the meshes of the engines`. A dense Boussinesq
  runtime asked by name stops on a mesh of more than 400 cells.
- **Boundaries.** Lakes, reservoirs, SFR and barriers need MODFLOW 6. The `stream` boundary
  needs MODFLOW 6 or Boussinesq. With {toml}`solver.backend` at `modflow_nwt`, the file is
  refused when it is read if it declares a stream network, a lake or a `stream` boundary, flow
  barriers or a dam cutoff wall. The message names the table the file wrote, for instance
  {toml}`flow.sinks_sources.sfr` for a stream network.
- **Layers and tensor.** MODFLOW-NWT has no pass-through cell: `pinch_out = "pass_through"` is
  refused when the file is read, and the build refuses a grid that holds one. `K22` and the
  angles need MODFLOW 6, and the file is refused with MODFLOW-NWT or Boussinesq. An `angle2` outside
  $[-90, 90]$ degrees and an angle with a vertical profile are refused. Boussinesq solves one
  layer and reads no {toml}`domain.layers`, so it refuses more than one layer and the
  `surfaces` mode. A vertical profile of K under a solver that lists no layers only warns, since
  the solver reads one K per column.
- **Soil reservoir.** `[flow.sinks_sources.recharge.soil]` is refused with every solver that
  does not list `soil`, which is MODFLOW 6 alone today.
- **ETP.** MODFLOW 6 draws no ETP outside soil mode, and only logs a warning.
  Boussinesq lists no `etp` and refuses it when the file is read.
- **Options of `[solver]`.** {toml}`solver.sink_fill`, {toml}`solver.drain_band_depth_m` and
  {toml}`solver.drain_conductance_floor_m2_s`, set away from their defaults, are refused under
  Boussinesq. It reads none of them, and a value it ignores would still move the seepage mask
  that a figure derives from the stored band.
- **Transport.** A transport solver follows the flow solvers its `requires` names. It is refused
  when {toml}`solver.backend` names another flow solver, with the flow solvers it follows.
  It is refused too when the flow solver of the file writes none of what the transport
  reads, `face_flow`, with the flow solvers that write it.
- **Hotstart and cyclic spin-up.** {toml}`flow.restart_from` and a cyclic spin-up need
  MODFLOW 6, the only solver that lists the two traits in `supports`. A restart beside a
  steady or a cyclic start is refused for every solver, because the computed start would
  overwrite the restart.
- **Lake and cyclic spin-up.** A lake with a `spinup_cyclic` start runs on MODFLOW 6. Each cycle
  starts from the final lake stages of the cycle before, the main run starts from those of the
  last cycle, and the loop settles only when the heads and the lake stages have both settled.
- **Windows.** {toml}`simulation.time.window_length` is refused under a steady run, a transport,
  a calibration, and, for a chain of more than one window, a flow solver that does not read an
  earlier state, because window 2 starts from the final state of window 1.
- **A steady start that did not converge.** The convergence of the auxiliary steady solve is
  known only at the solve. A transport run behind a steady start whose heads did not converge
  stops with `SolverDivergedError`, and says how to tighten the closure in
  {toml}`solver.modflow6.runtime.mf6_outer_dvclose` or to start from another state. Replaying a
  sealed run only warns.
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
solver.modflow6.runtime.mf6_ats
solver.modflow6.runtime.mf6_newton
solver.modflow6.runtime.mf6_newton_under_relaxation
solver.modflow6.runtime.mf6_ims_complexity
solver.modflow6.runtime.mf6_outer_dvclose
solver.modflow6.runtime.mf6_inner_dvclose
solver.modflow6.runtime.mf6_inner_rclose
solver.modflow6.runtime.mf6_preconditioner_levels
solver.modflow6.runtime.mf6_preconditioner_drop_tolerance
solver.modflow6.runtime.mf6_reordering_method
solver.modflow6.runtime.mf6_linear_acceleration
solver.modflow6.runtime.mf6_under_relaxation
solver.modflow6.runtime.mf6_enable_rewet
solver.modflow6.runtime.mf6_rewet_wetdry
solver.modflow_nwt.runtime.nwt.headtol
solver.modflow_nwt.runtime.nwt.fluxtol
solver.modflow_nwt.runtime.nwt.thickfact
solver.modflow_nwt.runtime.upw.iphdry
solver.modflow_nwt.runtime.upw.hdry
solver.modflow_nwt.process_specific.vka
solver.modflow6.process_specific.vka
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
| XT3D decision, IMS complexity | `hydromodpy/solver/modflow6/builders/solver_options.py` (`resolve_xt3d_decision`, `k_tensor_is_tilted`, `k_tensor_is_off_axis`, `resolve_ims_complexity`) |
| Newton options, guards, IMS options, ATS | `hydromodpy/solver/modflow6/builders/solver_options.py` (`newton_options`, `guard_newton_rewet`, `guard_newton_linear_acceleration`, `optional_ims_kwargs`, `build_ats_perioddata`) |
| Rewet options, starting heads | `hydromodpy/solver/modflow6/builders/initial_conditions.py` (`resolve_rewet_npf_options`, `build_start_heads`) |
| Recharge, EVT, drains, constant heads, wells | `hydromodpy/solver/modflow6/builders/` (`recharge.py`: `recharge_to_spd`, `build_soil_evta_payload`, `mask_recharge_on_lake_cells`; `boundary_conditions.py`: `build_drain_stress_period_data`, `assemble_constant_head_stress_period_data`; `wells.py`), `hydromodpy/solver/base/drain_conductance.py` |
| Lakes, streams, barriers, movers | `hydromodpy/solver/modflow6/builders/` (`lake.py`, `sfr.py`, `flow_barrier.py`, `mvr.py`) |
| Budget discrepancy | `hydromodpy/solver/modflow_common/listing.py` (`model_percent_discrepancies`), `hydromodpy/calibration/runners/verdict.py` (`water_budget_verdict`) |
| MODFLOW-NWT: solver and packages | `hydromodpy/solver/modflow_nwt/nwt/nwt_solver.py` (`_build_dis_package`, `_initialize_solver_packages`), `hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py` (`assemble_flopy_packages`) |
| Boussinesq: time loop and size limit | `hydromodpy/solver/boussinesq/drivers/transient.py`, `hydromodpy/solver/boussinesq/boussinesq.py` |
| Transport solvers | the four files that each hold an engine model and its adapter: `hydromodpy/solver/modflow6/transport.py`, `hydromodpy/solver/modflow6/prt.py`, `hydromodpy/solver/modflow_nwt/mt3dms/mt3dms.py`, `hydromodpy/solver/modflow_nwt/modpath/modpath.py` |
| Which transport follows which flow | the `requires` of each adapter, in the file of its engine under `hydromodpy/solver/<backend>/`, and `hydromodpy/solver/base/planner.py` |
| Solver names, what each backend declares, refusals at read time | `hydromodpy/solver/base/registry.py`, `hydromodpy/model/supports.py`, `hydromodpy/config/hydromodpy_config.py`, `hydromodpy/model/boundaries/boundary_condition_registry.py` |

## See also

- {doc}`groundwater-flow`: the balance of a cell.
- {doc}`boussinesq`: the full Boussinesq theory.
- {doc}`exits`: drains, streams and lakes as exits of the aquifer.
- {doc}`validation`: the checks against reference solutions.
- {doc}`../reference/solvers`: the solvers and what each supports.
