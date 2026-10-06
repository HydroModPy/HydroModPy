# MODFLOW 6 and MODFLOW-NWT

The same project file can run on MODFLOW 6 or on MODFLOW-NWT. This page says what
changes between the two in the equations and the options HydroModPy uses, and what
each backend refuses. It does not rank them, and it gives no speed or accuracy claim
that the repository cannot show. To pick one for a model, see
{doc}`../guides/choose-a-solver`. For the equation both solve, see
{doc}`solvers/modflow-governing-equation-and-cvfd-formulation`.

The solver that runs is the first name in {toml}`simulation.process.solvers` of the
`flow` process; {toml}`solver.backend` is the fallback when no process names one, and
the key the compatibility checks of a file are run against. Write the same name in
both ({doc}`../guides/choose-a-solver`). The name of MODFLOW-NWT is `modflow_nwt`, and
the settings of that backend live in the section `[modflownwt]`. The settings of
MODFLOW 6 live in `[modflow6]`.

## What changes, in one table

| Topic | MODFLOW-NWT | MODFLOW 6 |
|---|---|---|
| Grid | `DIS`, structured only | `DISV` for every grid, structured or not |
| Flow package | `UPW`, upstream weighting | `NPF`, with Newton |
| Water table | Newton, smoothed thickness | Newton, smoothed saturation |
| Newton | always | on by default, can be switched off |
| Dry cells | no rewetting | rewetting off, refused with Newton |
| Non-orthogonal flux | not available | `XT3D`, automatic on irregular meshes |
| Time | `DIS`, equal steps in a period | `TDIS`, equal steps, optional adaptive stepping |
| Loaded ETP | drives `EVT` | ignored outside soil mode |
| Streams, lakes, barriers | refused | `SFR`, `LAK`, `HFB` |
| Restart, cyclic spin-up | refused | supported |
| Transport | MT3DMS, MODPATH | GWT, PRT |

The sections below follow the order in which the code applies each item.

## Notation

| Symbol | Meaning | Unit | Set by |
|---|---|---|---|
| $h_n$ | head of cell $n$ at the end of the step | m | state, not a field |
| $h_n^{t}$ | head of cell $n$ at the start of the step | m | state, not a field |
| $z_{b,n}$, $z_{t,n}$ | bottom and top of cell $n$ | m | state, not a field |
| $K$ | hydraulic conductivity | m/s | {toml}`K\|flow.param.K.field.value` |
| $S_y$ | specific yield | - | {toml}`Sy\|flow.param.Sy.field.value` |
| $S_s$ | specific storage | 1/m | {toml}`Ss\|flow.param.Ss.field.value` |
| $A_n$, $V_n$ | plan area and volume of cell $n$ | m$^2$, m$^3$ | state, not a field |
| $C_{nm}$ | conductance between cells $n$ and $m$ | m$^2$/s | state, not a field |
| $\theta_n$ | saturated share of the thickness of cell $n$ | - | state, not a field |
| $\Delta t$ | length of one time step | s | {toml}`substeps_per_period\|simulation.time.substeps_per_period` |
| $\omega$ | factor applied to a Newton update | - | state, not a field |
| $\varepsilon$ | thickness over which the smoothing acts | m | {toml}`thickfact\|modflownwt.runtime.nwt.thickfact` |

## 1. One file, two translations

Both backends read the same flow payload: head as the unknown, $K$, $S_y$, $S_s$,
recharge, wells, drains and constant heads. Each backend turns it into its own
packages. The registry
`hydromodpy/solver/base/registry.py` maps `modflow_nwt` and `modflow6` to their adapter.

The grid differs first. MODFLOW-NWT builds a `DIS` grid in `_build_dis_package` and
stops on a mesh that is not structured. MODFLOW 6 builds `DISV` in
`run_pre_processing`, also for a structured grid, so one code path covers both. A
MODFLOW 6 run on a structured grid and a MODFLOW-NWT run therefore have the same
cells, but they do not go through the same grid package. When a mesh is irregular,
only MODFLOW 6 can run it. The mesh itself is described in {doc}`mesh`.

## 2. The cell balance, the same in both

For each cell $n$ and each step, backward Euler in time, both backends solve the
balance of {cite}`harbaugh2005` and {cite}`langevin2017`:

$$
\sum_{m \in \mathcal{N}(n)} C_{nm}\,(h_m - h_n) \;+\; \sum_k Q^{k}_n
\;=\; \frac{\mathrm{SC}_n}{\Delta t}\,\bigl(h_n - h_n^{t}\bigr)
$$

$\mathcal{N}(n)$ is the set of cells that share a face with $n$. $Q^{k}_n$ is the flow
that package $k$ (recharge, wells, drains, evaporation, constant head) adds to the
cell. In a steady period the right side is zero.

Every layer is unconfined and convertible. The code sets `laytyp = 1` in
`assemble_flopy_packages` for MODFLOW-NWT, and `icelltype = 1` and `iconvert = 1` in
`run_pre_processing` for MODFLOW 6. The storage capacity $\mathrm{SC}_n$ has two
limits:

$$
\mathrm{SC}_n = S_y A_n \quad \text{(water table inside the cell)},
\qquad
\mathrm{SC}_n = S_s V_n \quad \text{(cell full)} .
$$

## 3. Flow between cells and the water table

The conductance is a two-point flux with the thickness of the water column in it:

$$
C_{nm} \;=\; \frac{K_{nm}\, w_{nm}\, \bar b_{nm}}{L_{nm}}
$$

$K_{nm}$ is the harmonic mean of the two cell values, $w_{nm}$ the width of the shared
face and $L_{nm}$ the distance between the two cell centres. The thickness
$\bar b_{nm}$ is where a water table that crosses cells makes the problem nonlinear.

Both backends make $\bar b_{nm}$ a continuous function of head instead of a wet or
dry switch, and both weight it by the upstream cell, the one with the higher head.
With $\theta_n$ the saturated share of the thickness of cell $n$, the thickness of
that cell is

$$
b_n = \theta_n\,(z_{t,n} - z_{b,n}),
\qquad
\theta_n = \begin{cases}
0 & h_n \le z_{b,n},\\
\text{smooth ramp} & z_{b,n} < h_n < z_{b,n} + \varepsilon,\\
\dfrac{\min(h_n, z_{t,n}) - z_{b,n}}{z_{t,n} - z_{b,n}} & \text{above.}
\end{cases}
$$

A cell then keeps a head below its bottom and a conductance that goes to zero,
instead of leaving the problem. The exact ramp is in {cite}`niswonger2011` for
`UPW` and in {cite}`langevin2017` for `NPF` with Newton.

- **MODFLOW-NWT.** `UPW` is required by the Newton formulation. The code writes
  `laywet = 0`, so the older wetting algorithm is off. The thickness range of the
  ramp is controlled by {toml}`thickfact|modflownwt.runtime.nwt.thickfact`. A cell whose head falls to
  its bottom is written with {toml}`hdry|modflownwt.runtime.upw.hdry` when
  {toml}`iphdry|modflownwt.runtime.upw.iphdry` is on. The reader of NWT results turns
  that value into a missing value (`extractors/flow.py`).
- **MODFLOW 6.** `NPF` carries the Newton option set by
  {toml}`modflow6.runtime.mf6_newton`. HydroModPy does not set the smoothing range, so
  the MODFLOW 6 default applies. Rewetting is off unless
  {toml}`modflow6.runtime.mf6_enable_rewet` is on, and `guard_newton_rewet` refuses
  rewetting together with Newton (error code `HMPY.E405`).

The vertical conductivity is given by a ratio in both: $K_v = K / \mathrm{vka}$. The
key is {toml}`modflownwt.process_specific.vka` for MODFLOW-NWT, with `layvka` set so
that `vka` is read as a ratio, and {toml}`modflow6.process_specific.vka` for MODFLOW 6.
Horizontally, $K$ is isotropic in both.

## 4. The nonlinear solve

With $b$ a function of head, the balance is a nonlinear system $\mathbf r(\mathbf h) = 0$.
Both backends iterate with the Newton method:

$$
\mathbf J\bigl(\mathbf h^{(k)}\bigr)\,\delta\mathbf h^{(k)} = -\,\mathbf r\bigl(\mathbf h^{(k)}\bigr),
\qquad
\mathbf h^{(k+1)} = \mathbf h^{(k)} + \omega^{(k)}\,\delta\mathbf h^{(k)},
\quad 0 < \omega^{(k)} \le 1 .
$$

Because $\bar b_{nm}$ depends on the upstream head, the Jacobian is not symmetric.
That fixes one rule on the linear solver: the conjugate gradient method needs a
symmetric matrix. MODFLOW 6 refuses `CG` with Newton in `guard_newton_linear_acceleration`
(error code `HMPY.E406`) and asks for `BICGSTAB`.

The two backends close the loop with different criteria and different keys.

| | MODFLOW-NWT | MODFLOW 6 |
|---|---|---|
| Head closure | {toml}`modflownwt.runtime.nwt.headtol` | {toml}`modflow6.runtime.mf6_outer_dvclose` on the outer loop, {toml}`modflow6.runtime.mf6_inner_dvclose` on the inner loop |
| Flow closure | {toml}`modflownwt.runtime.nwt.fluxtol`, on the nonlinear loop | {toml}`modflow6.runtime.mf6_inner_rclose`, on the residual of the inner linear loop |
| Iteration cap | {toml}`modflownwt.runtime.nwt.maxiterout` | {toml}`modflow6.runtime.mf6_outer_maximum`, {toml}`modflow6.runtime.mf6_inner_maximum` |
| Update factor $\omega$ | backtracking, {toml}`modflownwt.runtime.nwt.backflag` | {toml}`modflow6.runtime.mf6_under_relaxation`, and the Newton option {toml}`modflow6.runtime.mf6_newton_under_relaxation` |
| Linear solver | {toml}`modflownwt.runtime.nwt.linmeth`, with the tolerance {toml}`modflownwt.runtime.nwt.stoptol` of the `GMRES` solver | {toml}`modflow6.runtime.mf6_linear_acceleration` |
| Preset | {toml}`modflownwt.runtime.nwt.options` | {toml}`modflow6.runtime.mf6_ims_complexity` |

A closure value of the same number is not the same test. To compare the two backends,
set the head criterion on both sides:

```toml
base_config = "step4_transient.toml"

[modflownwt.runtime.nwt]
headtol = 1e-5

[modflow6.runtime]
mf6_outer_dvclose = 1e-5
mf6_inner_dvclose = 1e-5
```

`resolve_ims_complexity` raises a `SIMPLE` preset of MODFLOW 6 to `COMPLEX` under XT3D
and to at least `MODERATE` under Newton, because `SIMPLE` assumes a symmetric matrix.
For what to do when a run does not converge, see {doc}`../guides/non-convergence`.

## 5. Time

Both backends read one time grid, built in
`build_temporal_discretization_from_time_grid`. A period is cut into
{toml}`simulation.time.substeps_per_period` equal steps. The step is backward Euler
in both, and both run in metres and seconds. A period is steady when the flow regime
is steady, or for the first period when {toml}`flow.first_period_steady` is on.
MODFLOW 6 sets `tsmult = 1.0` on purpose, and the `DIS` call of MODFLOW-NWT leaves
`tsmult` at the FloPy default of 1.

```{hmp-resolved} flow.first_period_steady
:config: step6_soil_reservoir.toml
```

Only MODFLOW 6 has adaptive time stepping, through {toml}`modflow6.runtime.mf6_ats`.
It subdivides a step where the solver does not converge and never makes a step
longer than the one asked for.

## 6. Sources and sinks

Recharge, wells, drains and constant heads are the same quantities in both. Their
packages differ in name only: `RCH` and `EVT` in MODFLOW-NWT, `RCHA` and `EVTA` in
MODFLOW 6. Three points are not the same.

**Evaporation from the water table.** The loaded ETP is a sink in MODFLOW-NWT, and
it is not in MODFLOW 6.

- MODFLOW-NWT writes `EVT` with its surface at the top minus
  {toml}`flow.sinks_sources.etp.surface_offset`, and the extinction depth
  {toml}`flow.sinks_sources.etp.extinction_depth`, when `"etp"` is in
  {toml}`flow.active_sinks_sources`.
- MODFLOW 6 draws no ETP from the water table outside soil mode, and it says so.
  In soil mode it writes the ETP that the soil left unmet (`build_soil_evta_payload`),
  see {doc}`soil-reservoir`.

**Negative recharge.** With {toml}`flow.sinks_sources.recharge.negative_to_evt` on, both
backends clip the recharge to zero and send the deficit to `EVT`, by the same rule
(`route_negative_recharge_to_evt`; see {doc}`forcing`). The geometry of that `EVT` differs. In
MODFLOW 6 the surface is the model top and the depth is
{toml}`modflow6.process_specific.evt_extinction_depth`. In MODFLOW-NWT the depth and the
offset come from the two `etp` keys above, and the code uses its own constants when
`"etp"` is not active (`build_etp_payload`).

**Starting state.** Only MODFLOW 6 can start from a stored state
({toml}`flow.restart_from`) or repeat a cycle until it settles
({toml}`flow.ic.h.type` set to `spinup_cyclic`). A file that asks for either on
MODFLOW-NWT is refused.

## 7. XT3D, MODFLOW 6 only

On a mesh whose cell faces are not perpendicular to the line between the two centres,
the two-point flux of section 3 is wrong by an amount that grows with the angle. XT3D
replaces it with a flux that uses the heads of the cells around the face. It is the
`XT3D` option of `NPF`, documented in the USGS report TM 6-A56. MODFLOW-NWT has no
such option, and only runs on structured grids where the error does not arise.

{toml}`modflow6.runtime.mf6_enable_xt3d` left unset lets `resolve_xt3d_decision` decide:

- structured grid: off;
- a horizontal anisotropy present: on;
- more than 5 % of the connections more than 30 degrees from orthogonal, or a 95th
  percentile above 30 degrees: on;
- otherwise off.

A value written in the file wins, and the code logs a warning when it disagrees with
that check. The details of the mesh test are in
{doc}`solvers/xt3d-on-irregular-disv-meshes`.

## Assumptions

- Every layer is convertible. No layer is declared confined in either backend.
- There is no wetting and drying algorithm. The water table is followed by the smooth
  thickness of section 3, and a rewetting scheme is refused together with Newton.
- $K$ is isotropic in the horizontal plane. Vertical anisotropy is a constant ratio.
- Within a period the forcing is constant and the steps are equal.
- The two backends run on the same cells only when the mesh is structured and the
  planar and vertical grid keys are the same on both sides.

## Limits

**What MODFLOW-NWT refuses.** When {toml}`solver.backend` names `modflow_nwt`, the
file is refused when it is read if it asks for:

- {toml}`flow.active_bc` with `sfr`, `lake`, `reservoir` or `stream`;
- flow barriers or a dam cutoff wall;
- {toml}`flow.restart_from`;
- a head initial condition of type `spinup_cyclic`.

A soil reservoir ({toml}`flow.sinks_sources.recharge.soil`) is refused as soon as
either key names `modflow_nwt`, with the message
`[flow.sinks_sources.recharge.soil] is wired to MODFLOW 6 only`.

An unstructured mesh stops the build with the message
`MODFLOW NWT requires a structured grid`.

**What the two backends do differently without a refusal.** A loaded ETP changes a
MODFLOW-NWT run and not a MODFLOW 6 run outside soil mode.

**What MODFLOW 6 refuses.** Newton with rewetting (`HMPY.E405`), and Newton with the
`CG` linear solver (`HMPY.E406`).

**Transport.** MT3DMS and MODPATH read a MODFLOW-NWT run. GWT and PRT read a
MODFLOW 6 run. The registry lists them as separate adapters.

**What this page does not say.** It does not say that one backend is faster, or closer
to the truth on a catchment. The repository has no run that compares the two on a real
basin. The next section lists what exists.

## What the validation shows

{doc}`validation` lists every check. Each analytical case that runs both backends has
one reference solution and one configuration per solver: `config_modflownwt.toml`,
`config_modflow6.toml` and, for an irregular mesh, `config_modflow6_irregular_tri.toml`.
Both backends are scored against the same closed-form profile or flow, on the same
structured grid for the first two.

The thresholds are in the case folder. For the steady cases with a head profile,
MODFLOW-NWT reads the shared `tolerances.toml` and MODFLOW 6 reads
`tolerances_modflow6.toml`, which is tighter or equal in every such folder. A threshold
is a bound a test accepts, not an error that was measured, so this says how the
checks are set and nothing about which backend is more accurate.

Two cases carry a relaxed threshold that MODFLOW-NWT reads. In
`brutsaert_recession_linearized_deep_1d`, the file `tolerances_modflownwt.toml`
says "Temporary relaxation for the known MODFLOW-NWT regression on this case"
and keeps the variant as a smoke test. In `brutsaert_recession_boussinesq_thin_1d`, every
solver reads a threshold far above the one in the shared file.

## What a refused file looks like

```toml
# not checked: asks for a stream network, which MODFLOW-NWT does not build, so the file is refused
base_config = "step4_transient.toml"

[solver.backend]
backend = "modflow_nwt"

[flow]
active_bc = ["drainage", "sfr"]
```

The same project on MODFLOW-NWT, with nothing MODFLOW 6 specific. Example 04 names
`modflow6` in its `flow` process, so the block names the solver in both keys:

```toml
base_config = "step4_transient.toml"

[solver.backend]
backend = "modflow_nwt"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]
```

## Parameters of this page

The fields below are the ones that appear in the text. Open a row for its card.
The backend, and the keys both backends share:

```{hmp-params}
simulation.process.solvers
solver.backend
flow.first_period_steady
simulation.time.substeps_per_period
flow.active_sinks_sources
flow.sinks_sources.recharge.negative_to_evt
flow.sinks_sources.etp.surface_offset
flow.sinks_sources.etp.extinction_depth
```

MODFLOW-NWT:

```{hmp-params}
modflownwt.runtime.nwt.headtol
modflownwt.runtime.nwt.fluxtol
modflownwt.runtime.nwt.maxiterout
modflownwt.runtime.nwt.thickfact
modflownwt.runtime.nwt.linmeth
modflownwt.runtime.nwt.options
modflownwt.runtime.nwt.backflag
modflownwt.runtime.nwt.stoptol
modflownwt.runtime.upw.iphdry
modflownwt.runtime.upw.hdry
modflownwt.runtime.upw.layvka
modflownwt.process_specific.vka
```

MODFLOW 6:

```{hmp-params}
modflow6.runtime.mf6_newton
modflow6.runtime.mf6_newton_under_relaxation
modflow6.runtime.mf6_enable_rewet
modflow6.runtime.mf6_enable_xt3d
modflow6.runtime.mf6_ims_complexity
modflow6.runtime.mf6_outer_dvclose
modflow6.runtime.mf6_inner_dvclose
modflow6.runtime.mf6_inner_rclose
modflow6.runtime.mf6_outer_maximum
modflow6.runtime.mf6_inner_maximum
modflow6.runtime.mf6_linear_acceleration
modflow6.runtime.mf6_under_relaxation
modflow6.runtime.mf6_ats
modflow6.process_specific.vka
modflow6.process_specific.evt_extinction_depth
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.solver.modflow6
hydromodpy.solver.modflow_nwt
hydromodpy.solver.modflow_common
hydromodpy.solver.modflow_grid
```

## In the code

| What | Where |
|---|---|
| Backend registry and capabilities | `hydromodpy/solver/base/registry.py` |
| Refusals made when a file is read | `hydromodpy/config/hydromodpy_config.py`, `hydromodpy/physics/flow/boundary_condition_registry.py` |
| NWT grid, `DIS` and structured check | `hydromodpy/solver/modflow_nwt/nwt/nwt_solver.py` (`_build_spatial_discretization`, `_build_dis_package`) |
| NWT Newton package and closure | the same file, `_initialize_solver_packages` |
| NWT `UPW`, `RCH`, `EVT`, `DRN`, `WEL` | `hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py` (`assemble_flopy_packages`) |
| NWT `EVT` payload | `hydromodpy/solver/modflow_nwt/nwt/payloads/recharge_etp.py` (`build_etp_payload`) |
| MF6 simulation, `DISV`, `NPF`, `STO`, `IMS` | `hydromodpy/solver/modflow6/build.py` (`run_pre_processing`) |
| MF6 Newton options and guards | the same file, `newton_options`, `guard_newton_rewet`, `guard_newton_linear_acceleration` |
| MF6 XT3D decision and `IMS` preset | `hydromodpy/solver/modflow6/builders/solver_options.py` |
| MF6 `RCHA` and `EVTA` | `hydromodpy/solver/modflow6/builders/recharge.py` |
| Steady and transient periods in `STO` | `hydromodpy/solver/modflow6/builders/period_forcing.py` (`sto_period_settings`) |
| Time grid shared by both | `hydromodpy/solver/modflow_grid/discretization_temporal.py` |
| Negative recharge to `EVT` | `hydromodpy/solver/modflow_common/recharge_evt_routing.py` |

## See also

- {doc}`../guides/choose-a-solver`: which backend fits a model.
- {doc}`../guides/non-convergence`: what to read when a run does not converge.
- {doc}`bibliography`: the full list of references.
- {doc}`index`: the other theory pages.
