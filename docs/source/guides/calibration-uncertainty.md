# Read the uncertainty of a calibration

A calibration returns one number per parameter. Beside it, HydroModPy reports how wide that
number is: the range of values the search tried that scored almost as well as the best one.
This guide shows where the range is printed, how to choose between the three methods that
produce it, how to change its width, and what it does not tell you.

The calibrated value never moves. The uncertainty is read after the search, and it only
decides what is printed beside the value.

```{hmp-task}
Task
: Read, choose and widen the interval printed beside each calibrated value.

Time
: Nothing for the default; one model run per parameter for `linearized`; the whole search again per restart for `multistart`.

Needs
: A calibration file that runs.

Gives
: An interval or a width per parameter, and the pairs of parameters the data did not tell apart.
```

You need a calibration file that already runs. The worked case is example 04,
`examples/projects/04_streamflow_intermittence_in_transient`, file
`run_calibration_composite.toml`. It searches K and Sy together on two criteria, the
seepage network and the gauged discharge. The blocks below are merged onto that file with
`base_config`.

## What the interval is, and what it is not

The interval is read off the trials the search already ran. It says one thing: inside this
range, other values scored almost as well as the best one.

- It is not a posterior distribution. A posterior needs a likelihood, and a likelihood needs
  residuals with an error model on each observation. NSE, KGE and `nse_log` are aggregates
  without units. A posterior computed from one would show a precision that nothing in the
  calculation established. `method = "posterior"` is refused, with that reason.
- A narrow interval has two possible causes. The parameter is well constrained, or the
  search never tried far from the best value. The interval alone does not tell which. The
  section "How to read it" gives the checks that do.

## 1. See which width a phase reads

Without any `[calibration.uncertainty]` table, every phase reads its interval from its own
trace, with a width that follows what the phase scores. List the phases to see it:

```text
hmp calibrate run_calibration_composite.toml --list-phases
```

Each phase line ends with the width in use and where it was written. For the composite file
it reads `width 5 % of the best cost (default)`.

The rule has one exception, because the two families of criteria do not share a zero.

- A phase scored only by network distances (every one of its blocks uses `distance_gap` or
  `distance_mean`) reads an absolute width of one mesh cell, in metres. A stream cannot move
  by less than a cell, so two gaps closer than that are not two different answers. The cell
  is the median distance between neighbouring cell centres, measured by the network
  criterion on the mesh it scores.
- Every other phase reads a width relative to the best cost.

A network gap is solved at zero. A fraction of zero is zero, so a relative width on it would
report no interval at all.

```{hmp-params}
calibration.uncertainty.method
calibration.uncertainty.tolerance
calibration.uncertainty.mode
```

## 2. Choose a method

The method is {toml}`calibration.uncertainty.method`. Three exist.

| method | extra model runs | what it can see | what it needs |
|---|---|---|---|
| `cost_profile` | none | one basin, read off the trace already run | nothing |
| `multistart` | the whole search again, once per restart | a second basin, if a restart lands in it | {toml}`restarts\|calibration.uncertainty.restarts` |
| `linearized` | one model run per parameter | which parameters trade off against which | {toml}`perturbation\|calibration.uncertainty.perturbation` |

::::{tab-set}

:::{tab-item} cost_profile
It keeps every sampled value whose cost stayed within the width of the best cost. It is the
default, costs nothing and rests on no error model. It cannot see a second, separate
optimum: if the search explored one basin, the interval describes that basin. You write
nothing to get it.
:::

:::{tab-item} multistart
It runs the whole search again from other starting points and reports the spread of the
optima reached. It is the only method that can see a second basin. The first restart is the
search you would have run without it, the others start from draws of the priors, and the
calibrated value is the best of them. Each restart is a full search.

```toml
base_config = "run_calibration_composite.toml"

[calibration.uncertainty]
method = "multistart"
restarts = 3
```

It is refused on an engine that returns the same answer every time, `bisection` and `grid`,
so the network stage of the published method cannot take restarts.
:::

:::{tab-item} linearised
It takes derivatives of the simulated values around the answer, one model run per
parameter, and reports for each parameter a first-order width, `sigma`, and the parameter it
trades off against. It needs an output that names a station to take residuals from.

```toml
base_config = "run_calibration_composite.toml"

[calibration.uncertainty]
method = "linearized"
perturbation = 0.01
```

The step is a fraction of each calibrated value: 0.01 moves it by one per cent. Too small and
the difference is solver noise; too large and it is no longer a derivative. Run it twice with
two steps: if the width moves with the step, do not trust it. It refuses a cost that drops
leading samples with `warmup_periods`: cut the record with
{toml}`calibration.scoring_window` instead.
:::

::::

```{hmp-params}
calibration.uncertainty.restarts
calibration.uncertainty.perturbation
```

## 3. Change the width

Write {toml}`calibration.uncertainty.tolerance` and {toml}`calibration.uncertainty.mode`
only when the default reads wrong for the criterion. Two cases justify it.

- The default reads too wide or too narrow. An efficiency near 1 leaves little room below
  it, so a fraction of a small cost can already reach the search bounds.
- You want a coarser or finer agreement than one mesh cell, on purpose.

A section-level value applies to every phase that does not say otherwise.

```toml
base_config = "run_calibration_composite.toml"

[calibration.uncertainty]
mode = "relative"
tolerance = 0.10
```

With `mode = "relative"` the tolerance is a fraction of the best cost. With
`mode = "absolute"` it is a number in the unit of the cost, which is metres for a network
distance read on its own.

A section-level tolerance reaches every phase, and the mode of each phase still follows what
it scores. On a two-stage file, a tolerance written in metres for the network phase would be
read as a fraction by the discharge phase. Write it in the phase instead. A phase carries
its own `uncertainty` table, and a key written there wins for that phase, then the section's
key, then the default.

```toml
base_config = "run_calibration_composite.toml"

[[calibration.phases]]
name = "conductivity_and_storage"
parameters = ["K", "Sy"]
regime = "transient"
objective_blocks = { hydrograph = 0.7, network = 0.3 }
method = "optuna"
max_iter = 60
uncertainty = { tolerance = 0.02 }

[calibration.phases.scoring_window]
start = "2001-01-01"
```

A phase that names another `method` than the section does not inherit the section's
`restarts` or `perturbation`. Those numbers were sized for the section's method.

```{hmp-params}
calibration.phases.uncertainty
calibration.phases.uncertainty.method
calibration.phases.uncertainty.restarts
calibration.phases.uncertainty.perturbation
calibration.phases.uncertainty.tolerance
calibration.phases.uncertainty.mode
```

## Check before you run

`hmp calibrate FILE --check` reads everything the search needs and exits without solving.
It reports every problem at once, and it ends with `FILE: ready to run.` when there is none.
Run `--list-phases` too: the width of each phase is printed on its line, with where it was
written (`written in the phase`, `written in [calibration.uncertainty]` or `default`).

`--check` refuses the mistakes of this guide before any model runs. Its messages are listed
in the last section.

## Read the result

### The recap and the console

`hmp run FILE` ends with one line per phase. Each line carries the method, the number of
runs, then each best value with its interval, then the cost. The part for one parameter
reads as below. The placeholders in angle brackets stand for your numbers.

```text
K = <value> <unit> in [<lower>, <upper>]
K = <value> <unit> (no other trial within the tolerance)
```

`hmp calibrate FILE` prints one line per parameter under the name of the phase.

```text
phase conductivity_and_storage:
  K = <value>  [<lower>, <upper>]
  Sy = <value>  [<lower>, <upper>]  -- reached the search bound
  cost: <value>
```

With `linearized`, `(sigma <value>)` replaces the interval in the `hmp calibrate` output.
The `hmp run` recap still prints the interval read off the trace.

The log lines that say more are INFO lines. Ask for them with `--verbose`, or read
`.hmp/logs/hydromodpy_debug.log`. A search with `multistart` logs one line per parameter,
for example `K: best <value>, restarts spanned <low> to <high> over 3 searches`. For a
staged file, `hmp run --verbose` also prints the spreads as `restart_spreads`.

### The figure

The figure `parameter_cost_profile` draws the cost against one parameter, one point per
trial, marks the trial the calibration returned and shades the interval. Its note gives the
two half-widths, and says which side is wider. On a log axis the half-widths are factors.
The composite file lists the figure in {toml}`display.figures` and selects the parameter in
its own table:

```toml
base_config = "run_calibration_composite.toml"

[display.overrides.parameter_cost_profile]
parameter = "Sy"
```

```{figure} ../_static/figures/guides/parameter_cost_profile.webp
:alt: The cost 1 - NSElog against Sy for the 8 trials of stage two in example 04, with a minimum at Sy = 0.045 and a shaded band from 0.0418 to 0.0517.
:width: 80%

`parameter_cost_profile` of stage two in example 04: 6 of 8 trials scored within 5 % of the
best, so $S_y$ lies in $[0.0418, 0.0517]$. The half-widths are $-0.0032$ and $+0.0067$: the
interval is 2.1 times wider above the value than below it.
```

The best run of the calibration holds the figure in its `figures` folder: the `hmp run`
recap prints that folder on its `Best runs:` line. Draw it again for that run with:

```text
hmp viz show <run> parameter_cost_profile
```

`<run>` is the id or the name of the best run.

### In Python

{doc}`hmp.calibrate() <../reference/python/hmp-calibrate>` returns the report. A staged
calibration returns one report per phase, in `phases`. Each report keeps its intervals under
`extra["parameter_intervals"]`, the width it read under `extra["interval_width"]`, and a
`linearized` width in `parameter_uncertainty`. The trials themselves are in the session
folder of the project, `sessions/<date>-<method>-<id8>`.

## How to read it

Read in this order. Each point can cancel the next.

1. **Search bounds.** A value that reaches a search bound is the best point of a search
   that was forbidden to look further. It was not found by the trials. The console says so
   with `-- reached the search bound`, and a WARNING line names the bound and the cost.
   Widen {toml}`calibration.parameters.<name>.bounds` and run again before you read
   anything else.
2. **An interval of one trial.** `no other trial within the tolerance` means the best trial
   is alone inside the width. That is not a value known exactly. It means the width is
   narrower than the spacing of the trials.
3. **Open ends.** In the figure, an end that no rise in cost produced is not a bound of the
   parameter, it is a bound of the sampling. The note says `is open: the sweep stops before
   the cost rises`. If both ends are open, it says `no trial rose above the tolerance: the
   sweep identifies nothing`.
4. **Trade-offs.** Two parameters that moved together over the trace were not told apart by
   the data. The console prints `caution: K and Sy moved together (r = <value>), not
   identified separately.` With `linearized`, the caution reads `trade off` and comes from
   the covariance of the derivatives, which quantifies the trade-off instead of only flagging
   it. Two parameters at a high correlation are one number and a ratio, not two numbers.
5. **Method.** State beside every interval which method produced it. A `cost_profile`
   interval is what one search saw. A `multistart` spread is the distance between the optima
   of several searches. A `linearized` `sigma` is a first-order width.

When you publish a conductivity, say which method and which width the interval rests on.

## Limits

- The `cost_profile` interval depends on where the sampler went. An engine that converges
  fast puts most of its trials near the best value, and the interval then measures how far
  it wandered, not how well the data constrain the parameter. It does not see a second
  basin.
- The interval of one parameter is read over trials where the other parameters also moved.
  It is not a slice with the others held fixed.
- With `multistart`, the interval printed beside the value is the one of the best restart's
  own trace. The spread between restarts is the extra information. A parameter whose optima
  land more than a factor ten apart was not identified, whatever the profile of any one
  restart looks like. The log says so: `more than a factor ten, so this calibration did not
  identify it`.
- `linearized` is exact where the cost is linear around the optimum and approximate in
  proportion to how curved it is. `sigma` is in the unit of the parameter and symmetric: if
  `sigma` is larger than half the value, the band reaches zero and the linear reading has
  stopped meaning anything. It needs more observations than parameters.
- A search that closes one root per bound, such as a two-root `bisection`, gets no interval
  of trials. Its width is the spread between its roots, reported with them.
- In a staged calibration, a phase calibrates only its own parameters. The width of a phase
  is conditional on the values frozen by an earlier phase, and it does not carry their
  uncertainty. With `linearized`, the phase records the note `conditional on <names>, frozen
  by an earlier phase rather than recalibrated here`. When the file names a protocol, the
  methods paragraph written to `methods.md` repeats it.

## What can go wrong

These come from the file load and from `hmp calibrate FILE --check`, before any solve.

| Symptom | Cause | Fix |
|---|---|---|
| `method='posterior' is not offered` | No posterior exists here, for the reason given at the top. | Use `linearized` or `multistart`. |
| `method='multistart' needs 'restarts'` | Restarts without their number. | Write {toml}`restarts\|calibration.uncertainty.restarts`, at least 2. |
| `method='linearized' needs 'perturbation'` | A derivative without its step. | Write {toml}`perturbation\|calibration.uncertainty.perturbation`. |
| `restarts=3 is only read by method='multistart'` | An option of another method. | Remove it, or set the method. The same holds for `perturbation`. |
| `phase 'conductivity_and_storage' writes an uncertainty that does not hold once read over [calibration.uncertainty]` | The phase table, merged over the section, is invalid. | Read the reason at the end of the message. |
| `'bisection' returns the same answer every time` | `multistart` on an engine that never moves. | Use `cost_profile`, or another engine for that phase. |
| `no calibration output names a station to be compared against` | `linearized` needs residuals. | Declare {toml}`observes\|calibration.outputs.<name>.observes`, or use `cost_profile`. |
| `Score the burn-in out with scoring_window` | `linearized` on a cost that drops leading samples. | Use {toml}`calibration.scoring_window`. |

Three warnings appear at run time instead, and the calibration still ends with its value.

| Symptom | Cause | Fix |
|---|---|---|
| `No interval was reported around the calibrated values: the width is one mesh cell, and no trial measured the mesh.` | No network criterion measured the mesh. | Write {toml}`tolerance\|calibration.uncertainty.tolerance` in metres. |
| `No interval was reported around the calibrated values: mode = 'relative' reads the width as a fraction of the best cost` | A relative width on a phase scored on network distances only. | Write `mode = "absolute"` with a tolerance in metres, or neither key. |
| `No width is reported: the normal matrix J'J is singular` | Two parameters move the simulated values in the same way. | Report the value, not a width. |

## Next

- Run the calibration itself: {doc}`calibrate`.
- A calibration on the stream network, and the measure it uses: {doc}`calibrate-on-the-stream-network`.
- The search methods and their options: {doc}`../reference/calibration-methods`.
- Complete calibration files to download: {doc}`calibration-recipes`.
- The equations of each width: {doc}`../theory/calibration/inverse-problem-formulation`.
- Every key of the section: {doc}`../reference/parameters/calibration/uncertainty`.
- The command and its options: {doc}`../reference/cli/calibrate`.
