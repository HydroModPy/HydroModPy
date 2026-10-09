# A run does not converge

```{hmp-task}
Task
: Find out why a MODFLOW 6 or MODFLOW-NWT run stops, or ends with a budget that does not close, and decide what to change.

Time
: Minutes to read the listing. A rerun costs one run.

Needs
: The message of the failed run, which names the listing, and access to the project folder. A failed run keeps its solver folder.

Gives
: The listing to open, the lines to read in it, a table of patterns that were measured on named cases, and what to attach to a bug report.
```

The solver stops, and `hmp run` reports an error. Or the run ends and the water budget
does not close. This guide says where the evidence is, what HydroModPy does with it, which
patterns are known, and where the settings of MODFLOW 6 and MODFLOW-NWT are.

It gives no value to copy: a value taken from another catchment is a guess. It gives a
method, and a table of patterns that were found by replaying real cases.

## 1. What you see

A flow run that does not converge ends with this message, and exit code 15. The text is
built in `run_flow_model`; the folder differs by solver.

```text
step 'run_solver' failed: SolverDivergedError: [HMPY.E401] Flow solver 'modflow6'
failed for run 'flow_main'. Final water-budget PERCENT DISCREPANCY = <x>.
See <solver folder>/mfsim.lst for diagnostics.
```

- `run 'flow_main'` is the `id` of the process in `[[simulation.process]]`.
- The `PERCENT DISCREPANCY` sentence exists for MODFLOW 6 only, and only when a model
  listing prints one.
- For MODFLOW-NWT the last sentence names the solver folder, not a file.
- In Python the exception is `SolverDivergedError`, a `SolverError`, code
  <a href="../reference/python/exceptions.html#HMPY.E401"><code>HMPY.E401</code></a>.

HydroModPy decides that a solve failed from the solver's own termination message. It does
not read the iteration counts itself.

- **Default runner** (`subprocess`). FloPy runs the executable and looks for the words
  `normal termination` in its console output.
- **`api` runner** ({toml}`modflow6.runtime.mf6_runner`). The return value of libmf6 is
  `None` whether the solve converged or not, so HydroModPy reads the listing instead. The
  run is a success only if `mfsim.lst` holds `Normal termination of simulation`. That
  verdict is the weakest link of the chain: see pattern 4 below.

HydroModPy does not retry, loosen a criterion or change the step after a failure. What you
write in the file is what the solver gets.

## 2. Find the listing

The listing is a solver file, so it lives in the solver working folder, not in `runs/`. A
run folder holds results, never diagnostics.

```text
<project>/.hmp/scratch/<run label>.p<process id>/<model name>/
```

`.hmp/` is hidden: use `ls -a`. The run label comes from the run name, and the process id
is the one of the `hmp` process. The error message prints the exact path.

| Solver | Files to open | What is in them |
|---|---|---|
| MODFLOW 6 | `mfsim.lst` | The simulation listing: the IMS solver and the termination message. |
| MODFLOW 6 | `<model name>.lst` | The model listing: one water budget block per step, with its `PERCENT DISCREPANCY`. |
| MODFLOW-NWT | `<model name>.list` | The only listing. NWT writes `.list`, not `.lst`. |

The model name is the run name with spaces turned into underscores. For MODFLOW 6, a name
longer than 16 characters is cut and a short hash is added, so copy the name from the error
message rather than guessing it.

Two more places hold solver text:

- `<project>/.hmp/logs/hydromodpy_debug.log` receives the console lines of the solver at
  DEBUG level, whatever the console verbosity is.
- A transient run that starts from {toml}`flow.ic.h.type` `"steady_state"` solves an
  auxiliary steady model first, in `_ssic/ssic/` under the model folder. Its listing is
  `ssic.lst`.

### How long the listing lives

- A **failed run** keeps its solver folder: the cleanup runs in the export step, which a
  failed solve never reaches.
- A **successful run** removes it once the results are stored, unless
  {toml}`simulation.results.keep_solver_files` is `true`.
- In both cases, the **next run of the same project** removes the scratch folders of
  processes that no longer run. Copy the listing before you start again.

```{hmp-toml}
[simulation.results]
keep_solver_files = true
```

## 3. Read the evidence

### Two questions, not one

Convergence says that the solver reached its closure criteria. The water budget says that
what came in equals what went out. A run can pass the first and fail the second. HydroModPy
keeps the second for every step of every run:

- the `mass_balance` table has a `percent_error` column, for both solvers;
- the figure `mass_balance_error` draws it. `hmp viz show @last mass_balance_error`
  renders it, and `mass_balance_error` is a valid name for {toml}`display.figures`. The
  band it shades is its `tolerance` option, 1 by default. That is a drawing option, not a
  rule;
- on MODFLOW 6, the run metrics `water_budget_percent_discrepancy` (the last block) and
  `water_budget_worst_percent_discrepancy` (the largest in magnitude) are recorded with
  the run. The code scans `*.lst` files, so a NWT run, whose listing ends in `.list`,
  does not get them.

```{figure} /_static/figures/guides/mass_balance_error.webp
:alt: Mass-balance closure error in percent per timestep, flat at zero inside the plus or minus 1 percent band.
:width: 90%

`mass_balance_error` of the calibrated run of example 04. A run that closes stays inside
the band at every step. A step outside it is where to start reading the listing.
```

The code comments warn that a percent discrepancy divides by the mean of inflow and
outflow. When a transient model routes almost no water, the quotient is large while the
imbalance is negligible. Look at the absolute terms in the listing before you conclude.

In a calibration, {toml}`calibration.reject_water_budget_above` rejects a trial whose
discrepancy is larger than the limit you write, instead of scoring it. It is unset by
default.

### In the MODFLOW 6 listing

By default the IMS prints nothing per step. Ask for it:

```{hmp-toml}
[modflow6.runtime]
ims_print_option = "SUMMARY"
```

`SUMMARY` adds one line per time step with the outer and inner iteration counts. It is the
only way to tell an expensive iteration from too many of them. Do not use
{toml}`modflow6.runtime.mf_verbose` for this: it also prints every boundary flux at every
step, and a run with one drain per cell has a lot of them.

```{hmp-params}
:flat:
modflow6.runtime.ims_print_option
modflow6.runtime.print_head
modflow6.runtime.mf_verbose
```

### In the MODFLOW-NWT listing

HydroModPy sets {toml}`modflownwt.runtime.nwt.iprnwt` to 1 by default, so the `.list`
already carries the solver diagnostics. You only need to open it.

## 4. Known patterns

These patterns were found by replaying real runs against the MODFLOW 6 binary, in the audits
of the lake and stream stack of 2026-09-14 and 2026-09-26. The case is named, so you can
tell whether yours looks like it. A pattern is not a diagnosis of your run: read your own
listing first, then compare.

| Pattern | What you see | Case | What to try, and what to attach |
|---|---|---|---|
| 1. Backtracking of the IMS `COMPLEX` preset under Newton | The run fails at one stress period, with the outer iteration count at its maximum. The head creeps by about 1.8 cm per iteration. `COMPLEX` and `mf6_newton = true` are the defaults, so most MODFLOW 6 files inherit them. | The two-dam Chèze reservoir (lake and Voronoi mesh), failed at stress period 51 on every Voronoi variant. A structured 75 m grid passed only by chance, at 481 of 500 iterations. With `BACKTRACKING_NUMBER 0` the period solved in 33 iterations and the solve fell from 207 s to 18 s. The solution agreed to 1.9 cm at that period. | No key sets the backtracking number at this version, so this cannot be switched off from the file. Turn on `ims_print_option = "SUMMARY"` and attach the lines of the failed period. Try {toml}`modflow6.runtime.mf6_ims_complexity` as a test, and say so: that choice was not measured. Do not compare runs of that case before the listing shows convergence at every period. |
| 2. Lake banks placed under the carved bed | The run converges, and the lake stage is too low. A stage of the right shape sits 0.5 to 1 m under the observed one, and the lake loses water through columns that are dry. | The same reservoir, `dynamic_area` (marnage) with bank connections: the HORIZONTAL connections were written under the carved bed. About 1.3 million m³ per year lost, and a stage 0.58 m too low on average (1.18 m at most) in the audit. | Not a solver failure, so the listing does not help. Switch {toml}`bank_seepage\|flow.sinks_sources.lakes.<name>.bed_reconstruction.bank_seepage` off and compare the stage, and attach both runs. Calibrations of `bedleak`, K or Sy made in marnage with banks are suspect until this is settled. The audit found it open on 2026-09-26: check the changelog of your version. |
| 3. Picard sweeps lost on a mover | An SFR network fed by a mover creeps instead of converging. In the listing, the mover inflow `qfrommvr` of a reach falls by about 1 % per outer iteration and is still above its criterion at iteration 500, while the head has settled. The run can fail at stress period 3 even with 1500 iterations. | The Nançon catchment at 25 m, steady and daily transient, with the hillslope drainage routed to the reaches (`route_drainage`). Fixed for that case: the sweeps are kept when `route_drainage` is on. | The guard tests `route_drainage` only (`builders/sfr.py`). A network that feeds a lake through `outflow_to_lake` without `route_drainage` was found with the same creep in the audit of 2026-09-14. If you meet it, attach the listing and the `[flow.sinks_sources.sfr.<name>]` table. |
| 4. A run reported as completed after a step that did not converge | `hmp run` exits 0 and the run is `completed`, with a head field that looks plausible. | The Chèze reservoir on the `api` runner (`exposed_band_runoff = true`): the Python bridge went on after the step that failed, and `mfsim.lst` still ended with `Normal termination of simulation`. | Read the model listing, `<model name>.lst`, for the convergence flags and `PERCENT DISCREPANCY` of every period, not `mfsim.lst`. Draw `mass_balance_error`. A subprocess run does not hide it: set {toml}`modflow6.runtime.mf6_runner` to `"subprocess"` when you do not need the API. |
| 5. A solve that stalls at the steady initial condition | `MODFLOW 6 steady-state initial-condition solve failed.` before the first transient period. | Any file with `flow.ic.type = "steady_state"`. The auxiliary solve forces Newton, no rewetting and `BICGSTAB`, and never uses a head closure tighter than `1e-3` or a maximum below 1000 iterations. | Open `ssic.lst` under the model folder. A solve that fails with a final `PERCENT DISCREPANCY` within 0.1 in magnitude continues with a warning. Otherwise change the initial condition ({doc}`time-and-initial-state`). |

### What to attach to a bug report

A report that can be replayed is a report that is read. Attach:

- the whole message of the failed step, with its code;
- the listing, `<model name>.lst` for MODFLOW 6 or `<model name>.list` for MODFLOW-NWT, and
  `mfsim.lst`. Copy them before the next run removes the scratch folder;
- the configuration of the run: `runs/<name>/config.toml` for a run that registered, or the
  output of `hmp config resolve <file>` for a file;
- `hmp --version` and `hmp doctor`;
- the stress period where it fails and, with `ims_print_option = "SUMMARY"`, the iteration
  lines around it;
- the runner, `subprocess` or `api`, and whether the run exited 0.

## 5. The settings

The settings that matter sit in `[modflow6.runtime]` and `[modflownwt.runtime.nwt]`. All of
them are `expert` keys, and each card in the reference says what it does and its default:
{doc}`../reference/parameters/modflow6` and {doc}`../reference/parameters/modflownwt`. What
is not on the cards:

- **Iterations and closure.** {toml}`modflow6.runtime.mf6_outer_maximum`,
  {toml}`modflow6.runtime.mf6_inner_maximum`, {toml}`modflow6.runtime.mf6_outer_dvclose`,
  {toml}`modflow6.runtime.mf6_inner_dvclose` and {toml}`modflow6.runtime.mf6_inner_rclose`.
  Raising a maximum gives the solver more iterations. Loosening a closure criterion makes a
  run pass by accepting a less exact solution, so check the budget afterwards.
- **Solver recipe.** {toml}`modflow6.runtime.mf6_ims_complexity`,
  {toml}`modflow6.runtime.mf6_linear_acceleration` and
  {toml}`modflow6.runtime.mf6_under_relaxation`. A key left unset keeps the preset of the
  complexity you chose. `SIMPLE` is not always what is written: HydroModPy promotes it to
  `MODERATE` when Newton is on, which is the default, and to `COMPLEX` when XT3D is on.
- **Newton and dry cells.** {toml}`modflow6.runtime.mf6_newton` and the rewetting keys.
  Two combinations pass the schema and are refused when the model is built: Newton with
  rewetting (<a href="../reference/python/exceptions.html#HMPY.E405"><code>HMPY.E405</code></a>), and Newton with
  `mf6_linear_acceleration = "CG"` (<a href="../reference/python/exceptions.html#HMPY.E406"><code>HMPY.E406</code></a>),
  because the Newton matrix is not symmetric. With Newton, rewetting is off. A cell that is
  dry in the results holds `-1e30`, and HydroModPy reads that value as dry.
- **MODFLOW-NWT.** Choose the solver in the process, then write the solver settings under
  `[modflownwt.runtime.nwt]`. {toml}`modflownwt.runtime.nwt.options` is the preset: FloPy
  documents `MODERATE` for when `SIMPLE` does not converge, and `COMPLEX` for when `MODERATE`
  does not. HydroModPy starts at `COMPLEX`. `backflag` and `stoptol` do nothing under a
  preset: FloPy writes them only when `options = "SPECIFIED"`, which also puts FloPy's own
  defaults on the NWT values that HydroModPy does not expose.
  {toml}`modflownwt.runtime.nwt.continue_run` adds the `CONTINUE` option: after a time step
  that does not converge, NWT goes on to the next one. Open the listing and the
  `mass_balance` table before you trust such a run.
- **Dry cells in NWT.** {toml}`modflownwt.runtime.upw.hdry` is the head written for a cell
  that became dry. FloPy documents it as an indicator that plays no role in the
  calculation. Read `-100` as dry, not as a head of -100 m.

```{hmp-toml}
[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]

[modflownwt.runtime.nwt]
iprnwt = 1
```

## 6. The time step

Each period of `[simulation.time]` is one stress period. By default it is solved in one
backward-Euler step. The number of steps inside a period is a setting of the time section,
and it applies to both solvers.

```{hmp-params}
:flat:
simulation.time.step_value
simulation.time.substeps_per_period
```

The cost is linear in the count. For monthly periods, the reference says that 30 gives
daily steps.

MODFLOW 6 has one more tool. With adaptive time stepping, each period starts at the step
you asked for, and MODFLOW 6 cuts it only where the solver cannot converge. It never makes
a step longer, so turning it on cannot coarsen a run. NWT has no such key. Merged onto
`step4_transient.toml`, which already sets the window:

```{hmp-toml}
[simulation.time]
substeps_per_period = 30

[modflow6.runtime]
mf6_ats = true
```

```{hmp-params}
:flat:
modflow6.runtime.mf6_ats
modflow6.runtime.mf6_ats_dtmin_s
```

## 7. Drains at the ground surface

In example 04, {toml}`flow.active_bc` is `["drainage"]`: every cell has a drain at its top,
and it is the only boundary. This is the model, not the solver, so these keys change the
answer and not only the way it is reached. The code and the documentation do not tie them
to convergence. Use them for a physical reason, and keep the solver keys for numerics.

```{hmp-params}
:flat:
solver.drain_bed_thickness_m
solver.drain_band_depth_m
solver.sink_fill
solver.drain_conductance_floor_m2_s
```

- With no conductance declared, each drain gets `C = K * cell_area / drain_bed_thickness_m`.
  The drain follows K, so a change of K is also a change of the drain.
- `drain_band_depth_m` and `sink_fill` answer the same question, a land surface that is not
  flat inside a cell. The reference says they are mutually exclusive.
- `drain_conductance_floor_m2_s` is there for degenerate cells: zero thickness, zero
  conductivity. Its description says that raising it makes a degenerate mesh audible.

## 8. A way to proceed

1. Open the listing, and read the budget before the closure. Draw `mass_balance_error`.
2. Turn on `ims_print_option = "SUMMARY"` (MODFLOW 6) and rerun. Find the period where the
   iteration counts grow.
3. Compare with the patterns of step 4. If one fits, follow its row and attach what it asks.
4. Ask whether the step is too long for that period: `substeps_per_period`, or `mf6_ats`.
5. Check the solver recipe: Newton, the complexity, under-relaxation.
6. Raise an iteration maximum, or loosen a closure criterion, last. Each one changes what
   the word "converged" means, so write it down with the results.
7. Keep the drain and recharge keys out of this loop. They change the model.

## How to check it worked

- The run ends with `Run completed:` and exit code 0, and the model listing ends with
  `Normal termination of simulation` for every period.
- `mass_balance_error` stays inside its band at every step.
- `hmp catalog show <run>` prints `water_budget_worst_percent_discrepancy` close to zero
  (MODFLOW 6).
- A solution that depends on the setting you changed is not a converged one. Run again with
  the previous value and compare the heads.

## What can go wrong

| What you see | Cause | Fix |
|---|---|---|
| `step 'run_solver' failed: SolverDivergedError: [HMPY.E401] Flow solver ... failed for run '<id>'. ... See <folder>/mfsim.lst for diagnostics.` (exit 15) | The solver did not converge. | Sections 2 and 3, then the patterns of section 4. |
| The path in the message does not exist | The next run of the project removed the scratch folder, or you look in `runs/`. | The listing is in `.hmp/scratch/`, and only a failed run keeps it. Run again and copy the listing. |
| `[HMPY.E405] mf6_newton and mf6_enable_rewet are mutually exclusive in MODFLOW 6 ...` | Newton forbids rewetting. | Disable one of the two. |
| `[HMPY.E406] mf6_linear_acceleration='CG' is invalid with mf6_newton=True ...` | The Newton matrix is not symmetric. | Use `BICGSTAB`, or leave the key unset. |
| `MODFLOW 6 steady-state initial-condition solve failed.` | The auxiliary steady solve failed and its budget does not close. | Open `ssic.lst`, and change the initial condition ({doc}`time-and-initial-state`). |
| `MF6 API subprocess for <folder> timed out after <n>s.` | The `api` runner has a time budget per solve. | Raise {toml}`modflow6.runtime.mf6_api_timeout_s`, or use the `subprocess` runner. |
| The run is `completed` and the heads look wrong | An `api` run can pass after a step that did not converge (pattern 4). | Read `<model name>.lst`, not `mfsim.lst`. |
| `PERCENT DISCREPANCY` is large and the flows are tiny | The quotient divides by the mean of inflow and outflow. | Read the absolute terms in the listing before you conclude. |
| No `water_budget_percent_discrepancy` metric on a NWT run | The code scans `*.lst`, and NWT writes `.list`. | Read the `mass_balance` table and the `.list` file. |

## Where to go next

- {doc}`troubleshooting` for the other messages, by stage.
- {doc}`choose-a-solver` for what each solver supports.
- {doc}`compare-runs` to compare two solver settings on one case.
- {doc}`../theory/solvers` for what the solvers solve.
