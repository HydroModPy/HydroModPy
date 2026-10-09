# MODFLOW 6 and MODFLOW-NWT

The same project file can run on MODFLOW 6 or on MODFLOW-NWT. Both write the balance
{eq}`eq-cell-balance` and solve it with Newton steps ({ref}`solvers-newton`). This page
says where the two differ: the smoothing of a drying cell, the tests that stop the
iteration, the output, and what each one refuses. It ranks neither. What each one
supports is listed in {doc}`../reference/solvers`.

The solver that runs is the first name in {toml}`simulation.process.solvers` of the `flow`
process; {toml}`solver.backend` is the fallback when no process names one, and the key the
compatibility checks of a file are run against. Write the same name in both. The
settings live in `[modflownwt]` and `[modflow6]`.

## What changes, in one table

| Topic | MODFLOW-NWT | MODFLOW 6 |
|---|---|---|
| Grid | `DIS`, structured only | `DISV` for every grid, structured or not |
| Flow package | `UPW`, upstream weighting | `NPF`, upstream weighting under Newton |
| Newton | always | on by default, can be switched off |
| Smoothing of a drying cell | over {toml}`thickfact\|modflownwt.runtime.nwt.thickfact` of the thickness | over $10^{-6}$ of the thickness under Newton, none without |
| Dry cells | no rewetting (`laywet = 0`) | rewetting off, refused with Newton |
| Non-orthogonal flux | not available | `XT3D`, automatic on irregular meshes |
| Stopping tests | head change and a norm of the residual, on the nonlinear loop | head change on the outer loop, head change and largest residual on the inner loop |
| Time | `DIS`, equal steps in a period | `TDIS`, equal steps, optional adaptive stepping |
| Output | head and budget at every step | head and budget at the last step of each period |
| Loaded ETP | drives `EVT` | ignored outside soil mode |
| Streams, lakes, barriers | refused | `SFR`, `LAK`, `HFB` |
| Restart, cyclic spin-up | refused | supported |
| Transport | MT3DMS, MODPATH | GWT, PRT |

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(mf6-nwt-smoothing)=
## A drying cell

Both solvers keep a cell in the equations when its head falls to its bottom, and weight
the conductance by the upstream cell, the one with the higher head. Neither switches a
cell off: they replace the saturated fraction $\sigma_n = B_n / H_n$ by a smooth function
$\tilde\sigma(\sigma_n)$ that enters the conductance and the storage. The two codes use
the same piecewise quadratic, with $a = 1 / (1 - \varepsilon_s)$:

$$
\tilde\sigma(\sigma) =
\begin{cases}
\dfrac{a\,\sigma^2}{2\,\varepsilon_s} & 0 \le \sigma < \varepsilon_s,\\[1.5ex]
a\,\sigma + \dfrac{1 - a}{2} & \varepsilon_s \le \sigma < 1 - \varepsilon_s,\\[1.5ex]
1 - \dfrac{a\,(1 - \sigma)^2}{2\,\varepsilon_s} & 1 - \varepsilon_s \le \sigma < 1,\\[1.5ex]
1 & \sigma \ge 1 .
\end{cases}
$$ (eq-smoothed-saturation)

The function and its slope are continuous, so the Jacobian of {eq}`eq-newton` stays
defined when a water table crosses the bottom or the top of a cell. $\varepsilon_s$ is a
fraction of the cell thickness, not a length:

- **MODFLOW-NWT** reads it from {toml}`modflownwt.runtime.nwt.thickfact`, $10^{-5}$ by
  default, in its function `SAT_THICK` {cite:p}`niswonger2011`. It also floors $\sigma$
  at $10^{-9}$, so a cell below its bottom keeps a tiny positive fraction. A dry cell is
  written with {toml}`hdry|modflownwt.runtime.upw.hdry` when
  {toml}`iphdry|modflownwt.runtime.upw.iphdry` is on, and the reader of the results turns
  that value into a missing value.
- **MODFLOW 6** sets $\varepsilon_s = 10^{-6}$ under Newton, in the `NPF` package, and
  HydroModPy has no key for it. Without Newton, $\varepsilon_s = 0$ and
  $\tilde\sigma = \min(\max(\sigma, 0), 1)$ {cite:p}`langevin2017`.

$\tilde\sigma$ differs from the plain clip by at most about $\varepsilon_s / 2$. The
smoothing is there to keep the Newton step defined, not to move the water table. The Boussinesq solver clips without smoothing,
{eq}`eq-saturated-thickness`. In the code: `_initialize_solver_packages` passes
`thickfact` to MODFLOW-NWT.

```{eval-rst}
.. plot:: theory/figures/mf6nwt_smoothing.py
   :alt: The smoothed saturated fraction against the saturated fraction for the three solvers, on the whole range and near zero.
   :caption: :eq:`eq-smoothed-saturation` for the three solvers. Left: over the whole
      range the three curves are one line. Right: the first :math:`3 \times 10^{-5}` of
      the thickness. Look at the MODFLOW-NWT curve: it starts flat at zero and joins a
      line shifted by :math:`\varepsilon_s / 2`; MODFLOW 6 does the same over a tenth of
      the width, and the clip has a kink at zero.
```

The vertical conductivity is a ratio in both, $K_z = K / \beta$: the key is
{toml}`modflownwt.process_specific.vka` for MODFLOW-NWT, with `layvka` set so that `vka`
is read as a ratio, and {toml}`modflow6.process_specific.vka` for MODFLOW 6.

## When the iteration stops

The tests are written in {eq}`eq-closure`. The keys that set them:

| | MODFLOW-NWT | MODFLOW 6 |
|---|---|---|
| Head change | {toml}`modflownwt.runtime.nwt.headtol` | {toml}`modflow6.runtime.mf6_outer_dvclose`, {toml}`modflow6.runtime.mf6_inner_dvclose` |
| Residual | {toml}`modflownwt.runtime.nwt.fluxtol`, Euclidean norm over the cells | {toml}`modflow6.runtime.mf6_inner_rclose`, largest cell |
| Iteration cap | {toml}`modflownwt.runtime.nwt.maxiterout` | {toml}`modflow6.runtime.mf6_outer_maximum`, {toml}`modflow6.runtime.mf6_inner_maximum` |
| Update factor $\omega$ | backtracking, {toml}`modflownwt.runtime.nwt.backflag` | {toml}`modflow6.runtime.mf6_under_relaxation` |
| Linear solver | {toml}`modflownwt.runtime.nwt.linmeth` | {toml}`modflow6.runtime.mf6_linear_acceleration` |
| Preset | {toml}`modflownwt.runtime.nwt.options` | {toml}`modflow6.runtime.mf6_ims_complexity` |

To compare the two solvers, set the head test to the same value on both sides; the
residual tests do not measure the same thing:

```toml
base_config = "step4_transient.toml"

[modflownwt.runtime.nwt]
headtol = 1e-5

[modflow6.runtime]
mf6_outer_dvclose = 1e-5
mf6_inner_dvclose = 1e-5
```

## Sources and sinks

Recharge, wells, drains and constant heads are the same quantities in both, written as
`RCH` and `EVT` in MODFLOW-NWT, `RCHA` and `EVTA` in MODFLOW 6. Two points differ.

- **The loaded ETP** is a sink in MODFLOW-NWT, with its surface at the top minus
  {toml}`flow.sinks_sources.etp.surface_offset` and the extinction depth
  {toml}`flow.sinks_sources.etp.extinction_depth`. MODFLOW 6 draws none outside soil
  mode, and says so; in soil mode it writes the ETP the soil left unmet
  ({doc}`soil-reservoir`).
- **A negative recharge** sent to `EVT` by {toml}`flow.sinks_sources.recharge.negative_to_evt`
  follows the same rule in both ({doc}`forcing`), with a different geometry: the model top
  and {toml}`modflow6.process_specific.evt_extinction_depth` in MODFLOW 6, the two `etp`
  keys above or fixed constants in MODFLOW-NWT.

## What the validation shows

The table lists the validation cases that run both solvers, generated from the tests.
Each case scores every solver against the same closed-form solution. A solver reads the
shared `tolerances.toml` of the case folder, or its own threshold file when the cell
says so.

```{hmp-solver-matrix}
:require: modflow_nwt, modflow6
```

A threshold is a bound a test accepts, not an error that was measured, so the table says
how the checks are set and nothing about which solver is more accurate. Two own
thresholds of MODFLOW-NWT are relaxations:

- `brutsaert_recession_linearized_deep_1d` accepts a relative RMSE of the discharge of 1.0
  for MODFLOW-NWT, against 0.03 in the shared file. The file says "Temporary relaxation
  for the known MODFLOW-NWT regression on this case": the variant is a smoke test until
  that regression is fixed.
- `brutsaert_recession_boussinesq_thin_1d` accepts 0.23 for MODFLOW-NWT and for MODFLOW 6,
  and 0.24 for Boussinesq, against 0.04 in the shared file.

The repository has no run that compares the two solvers on a real basin.

## Limits

When {toml}`solver.backend` names `modflow_nwt`, the file is refused when it is read if
it asks for {toml}`flow.active_bc` with `sfr`, `lake`, `reservoir` or `stream`, flow
barriers or a dam cutoff wall, {toml}`flow.restart_from`, or a head initial condition of
type `spinup_cyclic`. A soil reservoir is refused as soon as either key names
`modflow_nwt`. An unstructured mesh stops the build with
`MODFLOW NWT requires a structured grid`. MODFLOW 6 refuses Newton with rewetting
(`HMPY.E405`) and Newton with the `CG` linear solver (`HMPY.E406`).

```toml
# not checked: asks for a stream network, which MODFLOW-NWT does not build, so the file is refused
base_config = "step4_transient.toml"

[solver.backend]
backend = "modflow_nwt"

[flow]
active_bc = ["drainage", "sfr"]
```

## Parameters of this page

```{hmp-params}
simulation.process.solvers
solver.backend
modflownwt.runtime.nwt.thickfact
modflownwt.runtime.nwt.headtol
modflownwt.runtime.nwt.fluxtol
modflownwt.runtime.nwt.maxiterout
modflownwt.runtime.nwt.backflag
modflownwt.runtime.upw.iphdry
modflownwt.runtime.upw.hdry
modflownwt.process_specific.vka
modflow6.runtime.mf6_newton
modflow6.runtime.mf6_enable_rewet
modflow6.runtime.mf6_outer_dvclose
modflow6.runtime.mf6_inner_dvclose
modflow6.runtime.mf6_inner_rclose
modflow6.process_specific.vka
```

## Checked by

```{hmp-tested-by}
hydromodpy.solver.modflow6
hydromodpy.solver.modflow_nwt
hydromodpy.solver.modflow_common
```

## In the code

| What | Where |
|---|---|
| Solver registry and capabilities | `hydromodpy/solver/base/registry.py` |
| Refusals made when a file is read | `hydromodpy/config/hydromodpy_config.py`, `hydromodpy/physics/flow/boundary_condition_registry.py` |
| NWT grid, Newton package and closure | `hydromodpy/solver/modflow_nwt/nwt/nwt_solver.py` (`_build_dis_package`, `_initialize_solver_packages`) |
| NWT `UPW`, `RCH`, `EVT`, `DRN`, `WEL` | `hydromodpy/solver/modflow_nwt/nwt/_pre_processing.py` (`assemble_flopy_packages`) |
| MF6 `DISV`, `NPF`, `STO`, `IMS`, Newton | `hydromodpy/solver/modflow6/build.py` (`run_pre_processing`, `newton_options`, `optional_ims_kwargs`) |
| Negative recharge to `EVT` | `hydromodpy/solver/modflow_common/recharge_evt_routing.py` |
| The validation table | `docs/source/_ext/hmp_notation.py` (`solver_matrix_rows`) |

## See also

- {doc}`solvers`: the packages each solver writes and the nonlinear solve.
- {doc}`validation`: every check, with its thresholds.
