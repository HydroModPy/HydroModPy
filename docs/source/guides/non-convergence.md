# A run does not converge

The solver stops, and `hmp run` reports an error. Or the run ends and the water budget
does not close. This guide says where the evidence is, what HydroModPy does with it, and
which settings exist for MODFLOW 6 and MODFLOW-NWT.

It gives no recommended value. Neither the code nor the current documentation gives one,
and a value copied from another catchment is a guess. The defaults shown below are the
defaults of the code.

## 1. What you see

A flow run that does not converge ends with this message. The text is built in
`run_flow_model`; the folder differs by solver.

```text
step 'run_solver' failed: SolverDivergedError: [HMPY.E401] Flow solver 'modflow6'
failed for run 'flow_main'. Final water-budget PERCENT DISCREPANCY = <x>.
See <solver folder>/mfsim.lst for diagnostics.
```

- `run 'flow_main'` is the `id` of the process in `[[simulation.process]]`.
- The `PERCENT DISCREPANCY` sentence exists for MODFLOW 6 only, and only when a model
  listing prints one.
- For MODFLOW-NWT the last sentence names the solver folder, not a file.
- In Python the exception is `SolverDivergedError`, a `SolverError`, code `HMPY.E401`.

HydroModPy decides that a solve failed from the solver's own termination message. It does
not read the iteration counts itself.

- **Default runner** (`subprocess`). FloPy runs the executable and looks for the words
  `normal termination` in its console output.
- **`api` runner** ({toml}`modflow6.runtime.mf6_runner`). The return value of libmf6 is
  `None` whether the solve converged or not, so HydroModPy reads the listing instead. The
  run is a success only if `mfsim.lst` holds `Normal termination of simulation`.

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
- the figure `mass_balance_error` draws it. A `hmp viz show @last mass_balance_error`
  renders it, and `mass_balance_error` is a valid name for {toml}`display.figures`. The
  band it shades is its `tolerance` option, 1 by default. That is a drawing option, not a
  rule;
- on MODFLOW 6, the run metrics `water_budget_percent_discrepancy` (the last block) and
  `water_budget_worst_percent_discrepancy` (the largest in magnitude) are recorded with
  the run. The code scans `*.lst` files, so a NWT run, whose listing ends in `.list`,
  does not get them.

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

## 4. Settings of MODFLOW 6

All of them sit in `[modflow6.runtime]`. They are `expert` settings. The reference
page is {doc}`../reference/parameters/modflow6`.

### Iterations and closure

```{hmp-params}
:flat:
modflow6.runtime.mf6_outer_maximum
modflow6.runtime.mf6_inner_maximum
modflow6.runtime.mf6_outer_dvclose
modflow6.runtime.mf6_inner_dvclose
modflow6.runtime.mf6_inner_rclose
```

Raising a maximum gives the solver more iterations. Loosening a closure criterion makes a
run pass by accepting a less exact solution, so check the budget afterwards. The
steady-state initial condition already does this on its own. Its auxiliary solve never uses
a head closure tighter than `1e-3` or a maximum below 1000 iterations, whatever you wrote,
and it forces Newton, no rewetting and `BICGSTAB`. If that solve fails but its final
`PERCENT DISCREPANCY` is within 0.1 in magnitude, the run goes on with a warning. Otherwise
it stops with `MODFLOW 6 steady-state initial-condition solve failed.`

### Solver recipe

```{hmp-params}
:flat:
modflow6.runtime.mf6_ims_complexity
modflow6.runtime.mf6_linear_acceleration
modflow6.runtime.mf6_under_relaxation
```

- A key left unset keeps the preset of the complexity you chose.
- `SIMPLE` is not always what is written. HydroModPy promotes it to `MODERATE` when Newton
  is on, which is the default, and to `COMPLEX` when XT3D is on.

### Newton and dry cells

```{hmp-params}
:flat:
modflow6.runtime.mf6_newton
modflow6.runtime.mf6_newton_under_relaxation
modflow6.runtime.mf6_enable_rewet
modflow6.runtime.mf6_rewet_wetfct
modflow6.runtime.mf6_rewet_iwetit
modflow6.runtime.mf6_rewet_ihdwet
modflow6.runtime.mf6_rewet_wetdry
```

Two combinations pass the schema and are refused when the model is built:

- `mf6_newton = true` with `mf6_enable_rewet = true` (error `HMPY.E405`). MODFLOW 6 does
  not allow rewetting under Newton.
- `mf6_newton = true` with `mf6_linear_acceleration = "CG"` (error `HMPY.E406`). The Newton
  matrix is not symmetric, and CG needs a symmetric one. Use `BICGSTAB`, or leave the key
  unset.

Dry cells: with Newton, rewetting is off. A cell that is dry in the results holds `-1e30`,
and HydroModPy reads that value as dry. The water table helpers turn it into no data.

## 5. Settings of MODFLOW-NWT

Choose the solver in the process, then write the solver settings under
`[modflownwt.runtime.nwt]`. The reference page is {doc}`../reference/parameters/modflownwt`.

```{hmp-toml}
[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]

[modflownwt.runtime.nwt]
iprnwt = 1
```

```{hmp-params}
:flat:
modflownwt.runtime.nwt.options
modflownwt.runtime.nwt.headtol
modflownwt.runtime.nwt.fluxtol
modflownwt.runtime.nwt.maxiterout
modflownwt.runtime.nwt.linmeth
modflownwt.runtime.nwt.thickfact
modflownwt.runtime.nwt.ibotav
modflownwt.runtime.nwt.iprnwt
modflownwt.runtime.nwt.continue_run
modflownwt.runtime.nwt.backflag
modflownwt.runtime.nwt.stoptol
```

Three things to know before you change them:

- **`options`** is the NWT preset. FloPy's documentation of the package says that
  `MODERATE` is for when `SIMPLE` does not converge, and `COMPLEX` for when `MODERATE`
  does not. HydroModPy starts at `COMPLEX`.
- **`backflag` and `stoptol` do nothing under a preset.** FloPy writes them only when
  `options` is `"SPECIFIED"`, and `SPECIFIED` also puts FloPy's own defaults on the NWT
  values that HydroModPy does not expose. Switching it on replaces the preset.

  ```{hmp-toml}
  [modflownwt.runtime.nwt]
  options = "SPECIFIED"
  backflag = 1
  ```

- **`continue_run`** adds the `CONTINUE` option: after a time step that does not converge,
  NWT goes on to the next one. HydroModPy takes the verdict from the termination message.
  This guide did not check what NWT prints at the end of a run that skipped a step. Open the
  listing and the `mass_balance` table before you trust such a run.

Dry cells in NWT:

```{hmp-params}
:flat:
modflownwt.runtime.upw.hdry
modflownwt.runtime.upw.iphdry
```

`hdry` is the head written for a cell that became dry. FloPy documents it as an indicator
that plays no role in the calculation. Read `-100` as dry, not as a head of -100 m.

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
3. Ask whether the step is too long for that period: `substeps_per_period`, or `mf6_ats`.
4. Check the solver recipe: Newton, the complexity, under-relaxation.
5. Raise an iteration maximum, or loosen a closure criterion, last. Each one changes what
   the word "converged" means, so write it down with the results.
6. Keep the drain and recharge keys out of this loop. They change the model.
