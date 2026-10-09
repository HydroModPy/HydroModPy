# Set the time window and the starting state

```{hmp-task}
Task
: Set the window and the step of a transient run, choose how the first period is solved and what the aquifer holds before it, spin the model up, and keep the start out of the score.

Time
: Minutes to write. A spin-up costs one extra solve per cycle, for every run.

Needs
: A transient flow model on MODFLOW 6. The blocks below are merged onto `step4_transient.toml` of example 04 (monthly, 2000 to 2002) and validated. A forcing that covers the window ({doc}`recharge`). For the last step, a calibration file: example 04 has `run_calibration.toml`.

Gives
: A time grid you can count, a starting state you can name, and a first stamp you can read.
```

A transient run needs three answers. Which dates does it cover, and how long is one
period? What did the aquifer hold before the first period? And what does a time stamp in
the output mean? This guide sets all three, and shows how to spin the model up so that the
start does not leak into the numbers you report.

## 1. Write the window and the step

The window is two dates and a step. {toml}`simulation.time.start_datetime` is the first day.
{toml}`simulation.time.end_datetime` is the last day, and it is included. The step is one
stress period: the stretch of time that gets one forcing value.

```{hmp-params}
simulation.time.start_datetime
simulation.time.end_datetime
simulation.time.step_value
simulation.time.step_unit
```

Example 04 writes the window and the step like this:

```{hmp-resolved} simulation.time.start_datetime
:config: step4_transient.toml
```

```{hmp-resolved} simulation.time.step_value
:config: project.toml
```

The window is cut into whole periods. From 2000-01-01 to 2002-12-31 at one month, you get
36 periods, and the last edge is 2003-01-01, the day after the end date. The end date must
fall on a step boundary. A step of one year over that window gives 3 periods. A window that
ends mid-month at a monthly step cannot be cut (see the end of this guide).

```toml
base_config = "step4_transient.toml"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = "1 day"
```

A daily step gives 1096 periods here. The forcing must be daily too: `run_daily.toml` of
example 04 swaps in a daily recharge series.

The solver can also split each period into several steps. That is a separate key and it
changes the accuracy, not the output grid:

```{hmp-params}
simulation.time.substeps_per_period
```

## 2. Decide how the first period is solved

{toml}`flow.first_period_steady` makes period 0 a steady state. Storage plays no part in a
steady period: the heads settle where the forcing of that period puts them. Period 1 then
starts from them.

```{hmp-params}
flow.first_period_steady
```

```{hmp-resolved} flow.first_period_steady
:config: step6_soil_reservoir.toml
```

Three consequences follow.

- **The first period is not a month of the calendar.** With a steady first period, the
  first stamp of a monthly run holds an equilibrium, not the state at the end of January.
- **The forcing of that period may be the mean of the record.** For a recharge with one
  value per period, {toml}`first_clim|flow.sinks_sources.recharge.first_clim` says which rate
  a steady period takes: `"mean"` of the per-period rates, `"first"` for the rate of period 0,
  or a number. It sets the rate of every steady stress period and of no other. A transient
  period keeps its own rate, whatever its index. The rule is the same under every solver, and
  for one value per period and one grid per period alike.
- **The starting heads of {toml}`flow.ic.h.type` are only a guess.** A steady period does
  not depend on where the solver starts. The initial condition changes convergence, not the
  state reached. To make the run start from a state you choose, write
  `first_period_steady = false`. Period 0 is then a transient period like the others.

A soil reservoir needs the second form. Its recharge is zero after a dry day, so a
one-period steady state would open on a drained aquifer. The code refuses the file when the
first period is steady, and tells you what to write instead (see {doc}`recharge`).

## 3. Choose the starting state

With `first_period_steady = false`, {toml}`flow.ic.h.type` decides what the aquifer holds
before period 0. Write it as a flat table: `[flow.ic]`.

| You want | Write | Note |
|---|---|---|
| A full aquifer | `type = "top"` | The water table at the surface. The first months drain it. |
| An empty aquifer | `type = "bottom"` | The streams appear late. |
| A water table a stated depth down | `type = "top_offset"` and `value` | A guess, not a state the model produced. |
| One elevation everywhere | `type = "custom"` and `value` | Same remark. |
| The equilibrium of the forcing | `type = "steady_state"` | One extra steady solve, on the mean recharge of the run. |
| The equilibrium of a rate you state | `type = "steady_state"`, `source = "prescribed"` and `rate` | The start does not depend on the window. |
| A state that follows the sequence of the forcing | `type = "spinup_cyclic"` | Step 4. |
| The final state of an earlier run | {toml}`flow.restart_from` | Step 4. |

```{hmp-params}
flow.ic.h.type
flow.ic.h.value
```

A guess is crude: a run that starts from one spends its first months forgetting it. Use it
when a burn-in follows (step 5), or as the first guess of a solver.

### The equilibrium of the record

`steady_state` solves an auxiliary steady model first, with the recharge held at the mean of
the whole run, and starts the transient from its heads. The solve belongs to the run, so in
a calibration every trial starts from the equilibrium of its own parameters.

```toml
base_config = "step4_transient.toml"

[flow]
first_period_steady = false

[flow.ic]
type = "steady_state"
```

It says: before the record, the catchment sat at the equilibrium its mean forcing implies.
That fits a headwater under a stationary climate. It does not fit a record that starts in a
drought, because the mean of your window then stands for decades it did not see.

```{hmp-params}
flow.ic.h.source
flow.ic.h.recharge_statistic
flow.ic.h.boundary_condition_policy
```

`steady_state` needs transient flow. A file with a steady regime is refused.

### The equilibrium of a rate you state

Hold the same solve at one rate, whatever the record says. Use it for a pre-development
baseline, a rate a regulation names, a long-term normal drawn from a longer series, or to
make two runs with different windows start from the same state.

```toml
base_config = "step4_transient.toml"

[flow]
first_period_steady = false

[flow.ic]
type = "steady_state"
source = "prescribed"
rate = "500 mm/yr"
```

```{hmp-params}
flow.ic.h.rate
```

`source = "prescribed"` and `rate` go together. Either one alone is refused.

### A level you write

```toml
base_config = "step4_transient.toml"

[flow]
first_period_steady = false

[flow.ic]
type = "top_offset"
value = "2 m"
```

## 4. Spin the model up

A steady solve carries the mean of the forcing and nothing of its history. A deep aquifer,
or a lake whose storage spans several seasons, ends in a state that depends on the
sequence. Spin-up repeats a stretch of forcing until the state stops moving. Both ways below
need `first_period_steady = false`: a steady first period would solve the same equilibrium
at the head of every cycle, whatever the cycle starts from.

### Inside the run

`spinup_cyclic` repeats the simulated period. Each cycle starts from the heads the
previous one ended on. The loop stops when the largest head change anywhere falls below
the tolerance.

```toml
base_config = "step4_transient.toml"

[flow]
first_period_steady = false

[flow.ic]
type = "spinup_cyclic"
max_cycles = 6
tol_head = "2 cm"
first_cycle_from = "steady_state"
```

```{hmp-params}
flow.ic.h.max_cycles
flow.ic.h.tol_head
flow.ic.h.first_cycle_from
```

The cycles are auxiliary solves inside the run, like the steady one. A calibration trial
can use them, and they never touch the run store. They cost one solve per cycle, for every
trial.

The measure is the largest change, not the mean: a basin that is settled on average while
one corner still drifts has not settled. A loop that runs out of cycles hands back its last
state and warns. Pass `-v` to see the line that reports a loop that settled.

MODFLOW 6 is the only backend that does this. A file whose flow process selects
MODFLOW-NWT is refused by `hmp config check`: {toml}`solver.backend` follows the solver of
the process, and the message names it (see the end of this guide).

### Outside the run

`hmp spinup` repeats a window, but each cycle is a full run of the catalog, and the state
passes from one to the next through its stored fields. The converged state is a file you
can reuse in many runs.

```toml
base_config = "step4_transient.toml"

[flow]
first_period_steady = false

[spinup]
window_start = "2000-01-01"
window_end = "2000-12-31"
max_cycles = 6
tol_head = 0.02
tol_stage = 0.02
```

```{hmp-params}
spinup.window_start
spinup.window_end
spinup.max_cycles
spinup.tol_head
spinup.tol_stage
```

Without a window, each cycle repeats {toml}`simulation.time`. Cycle 0 starts from
{toml}`flow.ic.h.type`. Each later cycle starts from the stored heads of the one before.
The loop converges when the largest head change and the largest lake-stage change both fall
below their tolerance. A model without a lake counts a stage change of zero.

```text
hmp spinup step_spinup.toml
```

The command prints one line per cycle, then the path of the state:

```text
Spin-up converged in 3 cycle(s).
  cycle 0: initial state
  cycle 1: d_head=<x> m, d_stage=<y> m
  cycle 2: d_head=<x> m, d_stage=<y> m
Converged state: <path>/fields.zarr
```

The placeholders stand for the changes the run measured. When the loop does not converge, the
first line reads `Spin-up did NOT converge in <n> cycle(s).`, the path line says `Last
state reached`, and a `Warning:` line says that the state is the last one reached and not a
settled one. Only a converged loop tags its last run `spinup-converged`. The other cycles
are tagged `spinup-intermediate`.

Point the production run at the path:

```toml
base_config = "step4_transient.toml"

[flow]
first_period_steady = false
restart_from = "path/printed/by/hmp/spinup/fields.zarr"
```

```{hmp-params}
flow.restart_from
```

`hmp spinup step_spinup.toml --then-run` does the same in one go: it runs the production
chronicle from the converged state, with the original file.

Three rules for a restart.

- The two runs share the mesh, cell for cell. A gmsh mesh is not reproducible from run to
  run, so enable {toml}`mesh_catchment.cache`. A cell count that differs is refused.
- The lake stage comes along with the heads. A lake absent from the earlier run keeps its
  own starting stage ({doc}`lakes-and-reservoirs`).
- Leave `steady_state` and `spinup_cyclic` out of the production file. The code reads the
  restart first and then runs those solves, and their heads replace it.

Only MODFLOW 6 reads {toml}`flow.restart_from`. Another backend refuses the key rather
than start from {toml}`flow.ic.h.type` in silence.

## 5. Keep the start out of the score

A calibration that scores the first months scores the relaxation of the initial guess, and
the storage parameters absorb it. {toml}`calibration.scoring_window` names the first date
that counts. Every series keeps its stamps from that date on.

```toml
base_config = "run_calibration.toml"

[calibration.scoring_window]
start = "2001-01-01"
```

```{hmp-params}
calibration.scoring_window.start
calibration.scoring_window.end
```

The date names the same span at any step. Place it by insensitivity: move it later until
the objective stops changing. Past that date, the metric no longer depends on how the run
started. A phase can write its own {toml}`calibration.phases.scoring_window`, which replaces
this one. The calibration guides give the rest: {doc}`calibrate` and
{doc}`calibrate-on-the-stream-network`.

## Reading the time stamps

A run stores one record per stress period and stamps it with the **end** of the period.
A flux is the mean over the period, and a state is the value at the stamp. In a monthly run
starting on 2000-01-01, period 0 is stamped 2000-02-01: the discharge stamped there is the
mean of January, and the head stamped there is the water table on the day January ends. The
convention, with the stamps of a steady run, of the budget tables and of the observations, is
written once in {doc}`/theory/time-alignment`.

Two consequences belong to this guide.

- **A date picks the period that holds it.** {toml}`display.time` and {toml}`export.time`
  take a date, `"first"` or `"last"`. `"2002-10-15"` selects the period from 2002-10-01 to
  2002-11-01.
- **The first stamp may not be a month.** With a steady first period, the first record is
  the equilibrium, not January (step 2).

```{hmp-params}
display.time
export.time
```

Calibration scores from runs made before this convention compare a stamp with the middle of
its period. They are not comparable with scores made now.

## Check that it worked

1. **Check the file.** `hmp config check step.toml` prints `OK:` and the path. It also
   refuses a date in {toml}`display.time` or {toml}`export.time` that falls outside the
   record. It does not catch a window that the step cannot cut: count the periods yourself.
2. **Look at the first stamps.** Step 4 of example 04 already exports the discharge: run it
   and open the CSV. For a monthly run from 2000-01-01, the first `datetime` is 2000-02-01.
   In a file of your own, add an `[[export]]` block with `variables = ["discharge"]`
   ({doc}`export-results`). The figure `hydrograph_sim_obs` shows the same series against the
   gauge. A hydrograph that starts high and recedes for months says the aquifer started too
   full.

   ```{figure} /_static/figures/guides/hydrograph_sim_obs.webp
   :alt: Simulated and observed monthly discharge of the Nançon catchment, 2000 to 2002.
   :width: 100%

   `hydrograph_sim_obs` of the calibrated run of example 04. The first simulated point is
   stamped 2000-02-01, the end of the first period.
   ```
3. **Read the spin-up.** `hmp spinup` prints each cycle. For `spinup_cyclic`, run with `-v`
   and look for the line `Cyclic spin-up settled after <n> cycle(s).` Without it, look for
   the warning.
4. **Change the start and run again.** Swap `steady_state` for `top_offset`, or move the
   scoring date. If what you report moves, the initial condition is part of your result.
   Say so next to the parameters. {doc}`compare-runs` shows how to put two runs side by side.

## What can go wrong

The messages below are the ones the code prints. `hmp config check` starts a refusal with
`Config invalid:` or `Config check failed:`, then the file, then the key. The messages name
the initial condition as `flow.ic.type`, which is the flat form `[flow.ic] type = ...` that
this guide writes. The reference card is {toml}`flow.ic.h.type`.

| You see | Cause | What to do |
|---|---|---|
| `simulation.time.step_value has no unit. Write an inline unit (for example '1 month' or '30 day') or set simulation.time.step_unit.` | `step_value = 1` | Write `"1 month"`. |
| `simulation.time.end_datetime must be greater than or equal to start_datetime.` | The dates are swapped. | Swap them back. |
| `simulation.time window is not aligned with step_value/step_unit under inclusive end semantics. Ensure end_datetime falls exactly on a time-step boundary.` | The end date cuts a period. Raised when the run builds its time grid. | Move the end date to the last day of a period. |
| `display.time: 1999-06-01 is outside the record: the record runs from 2000-01-01 to 2003-01-01.` | A date outside the run. | Use a date inside the record. |
| `flow.ic.rate is required when flow.ic.source='prescribed'` | `prescribed` without `rate`. | Write `rate = "500 mm/yr"`. |
| `flow.ic.rate is only read when flow.ic.source='prescribed'` | A `rate` with another source. | Add `source = "prescribed"`, or delete `rate`. |
| `flow.ic.value is required when type='top_offset'` | No `value`. | Write `value = "2 m"`. |
| `flow.ic.type must be one of: 'bottom', 'custom', 'spinup_cyclic', 'steady_state', 'top', 'top_offset'` | A misspelled type. | Use one of them. |
| `flow.ic.type='steady_state' is only supported when flow.flow_regime='transient'` | A steady run. | Write `flow_regime = "transient"`, or another type. |
| `solver.backend='modflow_nwt' does not read flow.restart_from; it would be silently ignored and the run would start from flow.ic instead.` | A restart with the flow process on MODFLOW-NWT. `solver.backend` follows the solver of the process. | Use MODFLOW 6, or drop the key. |
| `flow.ic.type='spinup_cyclic' repeats the simulated period until the state settles, and solver.backend='modflow_nwt' cannot` | A cyclic spin-up with the flow process on MODFLOW-NWT. | Use MODFLOW 6, or run `hmp spinup` and set `flow.restart_from`. |
| `restart_from: prior head shape (...) does not match this run (...). Enable [mesh_catchment] cache = true so the mesh, and the cell count, is identical between the two runs.` | The two meshes differ. | Enable {toml}`mesh_catchment.cache` and redo both runs. |
| `MODFLOW 6 steady-state initial-condition solve failed.` | The auxiliary solve did not converge and its budget does not close. | See {doc}`non-convergence`. A solve that fails with a budget error within 0.1 in magnitude continues with a warning. |
| `[flow.sinks_sources.recharge.soil] sends each day's recharge to MODFLOW, and flow.first_period_steady = true solves the first stress period ...` | A soil reservoir with a steady first period. | Write `first_period_steady = false` and `type = "steady_state"` under `[flow.ic]`. |
| `<forcing> does not cover stress period(s) 0 [2000-01-01, 2000-02-01): no sample of the record is in force there. Extend the record, shorten [simulation.time], or set simulation.time.coverage_policy to 'warn' or 'ignore' to fill these periods with the nearest sample.` | A forcing record ends before the window, or starts after it. A gap inside the record is covered by the last sample before it. | Extend the record, or shorten the window. `'warn'` fills the period with the nearest sample and says so. |
| `flow.sinks_sources.recharge.first_clim = <x> is a negative rate, and negative_to_evt is false: a steady period cannot take it.` | A negative number for `first_clim`. | Set `negative_to_evt = true` to route it to EVT, or give a rate of zero or more. |
| `the cyclic spin-up ran its <n> allowed cycle(s) without the head field settling, and the run starts from the last one anyway.` | The loop ran out of cycles. | Raise {toml}`flow.ic.h.max_cycles`, or loosen {toml}`flow.ic.h.tol_head`, and say in the write-up that the start did not settle. |

## Next

- Where the recharge of period 0 comes from: {doc}`recharge`, and
  {doc}`/theory/forcing`. What a time stamp means: {doc}`/theory/time-alignment`.
- The soil reservoir has a starting state of its own, {toml}`flow.sinks_sources.recharge.soil.spinup`:
  {doc}`../theory/soil-reservoir`.
- A run that does not converge: {doc}`non-convergence`.
- Every key of this guide: {doc}`../reference/parameters/simulation`,
  {doc}`../reference/parameters/flow/ic` and {doc}`../reference/parameters/spinup`.
- The command: {doc}`../reference/cli/spinup`.
