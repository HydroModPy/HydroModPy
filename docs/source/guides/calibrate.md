# Calibrate

A calibration moves the parameters you choose until the model matches what was observed. It
writes every trial to disk as it goes, replays the best one as a full run with its figures,
and prints each value with an interval. Everything sits in one file with
`[workflow].mode = "calibration"`, written on top of a project that already runs.

```{hmp-task}
Task
: Fit one or more parameters of a model to a gauge, a piezometer or a mapped stream network.

Time
: A second to check the file, then one run of the model per trial. On example 04, the two stages took 15 steady runs in 2.5 minutes and 8 monthly runs in 6.6 minutes.

Needs
: A project file that runs with `hmp run`, and an observed record or map.

Gives
: The best value of each parameter with its interval, one session folder per phase, and the best trial replayed as a run.
```

```{note}
An observed network or record is a calibration target and a diagnostic. It is never an input
of the model: nothing in a calibration writes the mapped network into the mesh, the drains
or the conductivity.
```

The worked case is example 04, `examples/projects/04_streamflow_intermittence_in_transient`.
Its file `run_calibration.toml` is the one this page runs. To see what a project offers a
calibration, list its targets:

```bash
hmp config targets project.toml
```

```text
name            current       unit  physical range            path
thickness            30          m  0 .. 10000                domain.depth_model.thickness
drainage              0       m2/s  -                         flow.bc.drainage.value
K                 5e-05        m/s  1e-14 .. 100              flow.param.K.field.value
Ss                1e-05        m-1  1e-12 .. 0.001            flow.param.Ss.field.value
Sy                 0.05          -  0.0001 .. 0.5             flow.param.Sy.field.value
```

The first column is the name you write under `[calibration.parameters]`. The last column is
the configuration path the sampled value replaces.

## 1. Choose the parameters

Start a new file next to `project.toml`. It inherits the model and adds the search.

```toml
base_config = "project.toml"

[workflow]
mode = "calibration"

[simulation]
name = "nancon_calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]
```

The bounds are in the unit the parameter is written in: a recharge value, for instance, in the
unit of {toml}`flow.sinks_sources.recharge.units`. They belong to the site: a range much wider
than the evidence makes the search spend trials where you already know the answer is not.
Every key a calibration can move, with its range, is listed in
{doc}`../reference/parameters/calibrable`.

```{hmp-params}
calibration.parameters.<name>.bounds
calibration.parameters.<name>.transform
calibration.parameters.<name>.prior
```

The transform decides the space the search walks in. Unset, it follows the parameter: a
conductivity is searched in log space, so you write the key only to depart from it.

### Reach a value that has no name

A path you write wins without a lookup. With `mode = "scale"`, the sampled number multiplies
the value of the model instead of replacing it.

```toml
base_config = "project.toml"

[calibration.parameters.K_factor]
path = "flow.param.K.field.value"
mode = "scale"
bounds = [0.1, 10]
```

### Calibrate the aquifer thickness

The thickness is a target on the two scalar depth models. `hmp config targets` lists the one
your {toml}`domain.depth_model.kind` exposes, under its short name:

| Depth model | Name | Searched in |
|---|---|---|
| `constant_thickness` | {toml}`thickness\|domain.depth_model.thickness` | log space |
| `flat_substratum` | {toml}`substratum_elevation\|domain.depth_model.substratum_elevation` | linear space, an elevation can be negative |

`bounds` is required for both. A raster depth model lists nothing: a map is not a scalar, so
compare one run per raster instead. A trial of the thickness replays the model from the
process setup, not from the mesh. On the stream-network criterion, the thickness and $K$ act
only through their product $T = K d$: search one of the two, or add a second target, such as
the hydrograph, that tells them apart. `hmp calibrate --check` warns when a network-only
search moves both.

## 2. Say what the model is compared with

An output pairs a simulated quantity with its observation. A gauged discharge:

```toml
base_config = "project.toml"

[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
observes = "NANCON"
```

{toml}`observes|calibration.outputs.<name>.observes` names a station the project loaded. Its
record is aligned on the simulated dates, and no number is typed in the file. A mapped stream
network is an output with `support = "network"`: {doc}`calibrate-on-the-stream-network` goes
through its keys.

```{hmp-params}
calibration.outputs.<name>.support
calibration.outputs.<name>.variable
calibration.outputs.<name>.observes
```

## 3. Say how it is scored

An objective block scores one or more outputs with one metric. The search always minimises a
cost: one minus an efficiency score, an error or a distance as it is. Every metric, with its
formula, unit and direction, is in {ref}`the reference <calibration-metrics>`.

```toml
base_config = "project.toml"

[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
observes = "NANCON"

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["hydrograph"]

[calibration.scoring_window]
start = "2001-01-01"
```

`nse_log` is the NSE of the log of the series: the recessions, where storage shows, weigh as
much as the peaks. The first year of a run is still forgetting its initial state, so
{toml}`calibration.scoring_window` names the dates that count. A date means the same span at
any time step.

```{hmp-params}
calibration.objective_blocks.metric
calibration.scoring_window.start
calibration.scoring_window.end
```

A file that inherits blocks from its `base_config` and writes `[[calibration.objective_blocks]]`
replaces them all; `[[calibration.objective_blocks__append]]` adds to them instead (see
{doc}`../reference/parameters/grammar`).

Several targets are several blocks, each with a {toml}`weight|calibration.objective_blocks.weight`.
The weights are shares: they are divided by their sum. A cost in metres and a cost without
unit do not add up as shares until
{toml}`normalize_cost|calibration.objective_blocks.normalize_cost` divides the first by a
scale of its own. {download}`recipes/calibration_multi_objective.toml` is a complete file.

## 4. Choose the method

The method is the engine that proposes the next values. Left unset, HydroModPy picks
`bisection` when the search moves one parameter in log space on signed criteria only, and
`scipy_nelder_mead` otherwise. Every method, with its options, defaults and stopping rule, is
in {doc}`../reference/calibration-methods`.

```{hmp-params}
calibration.method
calibration.method_options
calibration.max_iter
calibration.tolerance
calibration.seed
```

1. One parameter in log space against a mapped network: `bisection`.
2. A narrow range, or a value to refine: `scipy_nelder_mead`.
3. A first look at a new site: `grid` on one or two parameters, `lhs` on more. They map the
   cost before you search it.
4. Several parameters and a broad box: `optuna` or `cma_es`, with a `seed`.
5. Expensive runs and few parameters: `gp_mapping`.
6. A sample of plausible values: `da_mh_gp`, scored on `rmse`. An interval around one value
   does not need a sampler: see {doc}`calibration-uncertainty`.

{toml}`calibration.tolerance` is a precision on the parameter. Only the engines that stop on
one take it; the others stop on {toml}`calibration.max_iter` and refuse it. A search that
spends its budget first is reported as not converged, and a re-run with a larger `max_iter`
replays the solved trials from the cache.

(calibrate-phases)=
## 5. Chain phases, or name a protocol

A phase is one search with its own parameters, blocks and method. The values a phase finds
are frozen for the next ones. This is the K stage of example 04 written by hand, followed by
a transient stage on the gauge:

```toml
base_config = "project.toml"

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"

[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
observes = "NANCON"

[[calibration.objective_blocks]]
name = "network_extension"
metric = "distance_gap"
uses_outputs = ["seepage_network"]

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["hydrograph"]

[[calibration.phases]]
name = "steady_conductivity"
parameters = ["K"]
regime = "steady"
objective_blocks = ["network_extension"]
method = "bisection"

[[calibration.phases]]
name = "transient_storage"
parameters = ["Sy"]
regime = "transient"
objective_blocks = ["hydrograph"]
depends_on = "steady_conductivity"
max_iter = 30
tolerance = 0.05

[calibration.phases.scoring_window]
start = "2001-01-01"
```

```{hmp-params}
calibration.phases.parameters
calibration.phases.regime
calibration.phases.objective_blocks
calibration.phases.depends_on
calibration.phases.freeze_on_success
```

A phase that does not converge freezes nothing, and a phase that depends on it does not
start. `--phase NAME` runs one phase only, and only one that depends on no other.

A protocol is a published method that writes the phases for you. You name it in a table, and
keep the parameters and the outputs it needs:

```toml
base_config = "project.toml"

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"

[calibration.protocol]
name = "matching_hydrographic_network"
transient_max_iter = 30
```

`hmp calibrate FILE --expand` prints the `[calibration]` section the protocol writes, as TOML.
Paste it in place of the protocol to change a stage. A file that inherits a protocol from its
`base_config` and writes its own phases drops it with `protocol__delete = true` under
`[calibration]`. A file cannot name a protocol and declare phases or blocks that differ from
the ones it writes.

## 6. Check, then run

Three modes of `hmp calibrate` solve nothing and take a second. `--check` reports every
problem at once, `--list-phases` prints each phase with its method and the reason for it,
`--expand` prints what a protocol writes. `--expand` takes no other mode.

::::{tab-set}

:::{tab-item} Command line
```bash
hmp calibrate run_calibration.toml --check
hmp calibrate run_calibration.toml --list-phases
hmp calibrate run_calibration.toml
```
:::

:::{tab-item} Python
```python
import hydromodpy as hmp

phases = hmp.calibrate("run_calibration.toml", list_phases=True)
report = hmp.calibrate("run_calibration.toml")
```
:::

::::

Before its verdict, `--check` prints what each phase compares with what. Read it before every
long run: it is the file as the code understood it.

```text
compares (steady_conductivity):
  network_extension  distance_gap  share 100%  release_flux (network)  vs .../nancon_stream_network.gpkg
compares (transient_storage):
  hydrograph  nse_log  share 100%  discharge, station NANCON (whole-catchment series)  vs station NANCON ([data.hydrometry])
run_calibration.toml: ready to run.
```

`hmp run run_calibration.toml` runs it too, since the file says `mode = "calibration"`. Four
keys set what a run costs:

```{hmp-params}
calibration.parallel
calibration.save_runs
calibration.rerun_best_with_outputs
calibration.reject_water_budget_above
```

The data, the elevation model and the mesh are prepared once. A trial of `K` or `Sy` replays
only the solver. Figures and exports are drawn for the promoted runs only: with the defaults,
nothing is promoted, and `rerun_best_with_outputs = true` replays the best trial of each
phase. A failed trial is scored as a failure and the search goes on; several failures in a
row for the same reason stop it.

## 7. Read the result

`hmp calibrate` ends with the value of each parameter, its interval and its cost, phase by
phase. On example 04:

```text
Calibration finished: run_calibration.toml
phase steady_conductivity:
  K = 7.96236e-05  [7.49894e-05, 8.25404e-05]
  cost: 0.810634
  k_over_r = 8774 against R_mean_m_s = 9.075e-09 m/s on output 'seepage_network', ...
  roptim (seepage_network) = 1.39, Doptim = 104.1 m <= 150 m (auto), Eq. 4 holds
  bracket on K: [7.91476e-05, 7.96236e-05], width 0.60% (closed)
  search: converged on its rule (rel_tol), 15 evaluation(s) of 23 declared
phase transient_storage:
  Sy = 0.045002  [0.041833, 0.0517337]
  cost: 0.0838082
  search: converged on its rule (xatol), 8 evaluation(s) of 30 declared
  hydrograph: 25 pair(s) from 2001-01-01 to 2003-01-01 (first trial)
```

The cost of stage two, 0.0838, is an NSE on log discharge of 0.916 over the 25 scored months.
The lines of stage one are read in {doc}`calibrate-on-the-stream-network`.

```{figure} ../_static/figures/guides/calibration_progress.webp
:alt: Three panels for the transient stage of example 04. The value of Sy tried at each of 8 runs converges on 0.045; the cost of each run falls to 0.0838; the NSE on log discharge reaches 0.916.
:width: 100%

`calibration_progress` of stage two in example 04: the value tried at each run, its cost,
and the fit to the gauge.
```

Three kinds of lines ask for your attention:

- `-- reached the search bound` after a value: the optimum sits on a bound. Widen the range,
  or accept that the data cannot place it.
- `caution: K and Sy moved together (r = ...), not identified separately.`: the data do not
  tell the two apart.
- `search: did NOT converge on its rule (...)`: the budget ended before the stopping rule was
  met. The value is where the budget ended.

The interval, and how far to trust it, is the subject of {doc}`calibration-uncertainty`.

### Files

Each session owns a folder at the project root. The files are the truth; the index is built
from them, and `hmp catalog reindex` rebuilds it.

| Path | Content |
|---|---|
| `sessions/<session>/session.json` | Identity, search space, objective, dates, best trial, and the final bracket of a root search. |
| `sessions/<session>/trials.jsonl` | One line per trial, appended as it completes: parameters, cost, metrics, duration, cache hash. |
| `sessions/<session>/trial_series/` | The simulated and observed series of each trial, with {toml}`calibration.persist_trial_series`. |
| `sessions/<session>/methods.md` | A methods paragraph with its citations, when the file names a protocol. |
| `runs/<run>/` | One full run per promoted trial, with its figures. |

A staged calibration writes one session per phase.

(calibration-trial-series)=
### The series of every trial

With {toml}`calibration.persist_trial_series` set to `true`, each completed trial writes
`sessions/<session>/trial_series/trial-NNNNNN.parquet`: one row per scored date of each
series output, with the columns `trial`, `output`, `station`, `time`, `simulated` and
`observed`. A network output writes nothing there: its cost is already in `trials.jsonl`.
Read them back in one table:

```python
from hydromodpy.results.session_journal import read_trial_series

series = read_trial_series("sessions/20261008-232132-scipy_nelder_mead-347e7a76")
```

`hmp report render --open` renders the HTML report of the last session. The figures that read
a calibration, such as `calibration_progress`, `parameter_cost_profile` and
`bisection_bracket_trace`, are in {doc}`../reference/figures`.

(calibrate-use-the-value)=
## Use the calibrated value

The best run of the last phase already holds every calibrated value. `hmp catalog show` prints
them under `Parameters`:

```bash
hmp catalog show nancon_intermittence_mf6_calibrated_transient_storage
```

```text
Parameters:
                value unit parameterization
param_name
K            0.000080  m/s      homogeneous
Ss           0.000010  m-1      homogeneous
Sy           0.045002    -      homogeneous
```

The full values are in `runs/<run>/config.toml`. To run the model with them, over another
window or with other outputs, write them in a file on top of the project:

```toml
base_config = "project.toml"

[simulation]
name = "nancon_calibrated"

[flow.param.K.field]
value = 7.962e-5

[flow.param.Sy.field]
value = 0.045
```

In Python, a staged calibration returns every value it froze, with the path it was written
to:

```python
import hydromodpy as hmp

report = hmp.calibrate("run_calibration.toml")
for parameter in report.frozen:
    print(parameter.name, parameter.path, parameter.value)
```

The metrics `hmp catalog show` prints for a run cover the whole run, spin-up included: they
are not the cost of the search, which reads the scoring window only. To pick among the runs of
a project, `@best:<metric>` follows the direction of the metric: `hmp catalog show
@best:log_nse` shows the completed run with the highest NSE on log discharge, calibrated or
not, and `@best:rmse` the one with the lowest error. The catalog names that metric `log_nse`
where a calibration file writes `nse_log`.

## What can go wrong

`hmp calibrate FILE --check` finds these before any solve, and exits with code 14 (see
{doc}`../reference/cli/exit-codes`).

| Symptom | Cause | Fix |
|---|---|---|
| `bounds are 0.001 .. 1e-07; the lower one has to be the smaller one.` | The two bounds are in the wrong order. | Write `[low, high]`. |
| `names nothing this project carries. It holds 'thickness', 'drainage', 'K', 'Ss', 'Sy'.` | The table name is not a target of the project. | Use a name `hmp config targets` lists, or write `path`. |
| `lower bound 0.0 is outside what 'K' can physically be` | A bound lies outside the physical range. | Move the bound inside the range `hmp config targets` prints. |
| `objective_block 'net' uses_outputs=['ghost'] but those names are not declared in [calibration.outputs].` | A block names an output that does not exist. | Fix the name, or declare the output. |
| `stream_geometry_path 'nope.gpkg' is not there, and none of the places the run looks holds it.` | The map file is not found. | Fix the path. It is looked for beside the file and in the two folders above it. |
| `method 'simplex' is not registered. Available: bisection, cma_es, ...` | The method name does not exist. | Use a name of {doc}`../reference/calibration-methods`. |
| `'grid' does not take sampler; the options it takes are: points_per_dim.` | `method_options` belongs to another method. | Write the options of the method you chose. |
| `tolerance asks 'optuna' to stop at a precision on the parameter, and that engine stops on its evaluation budget instead.` | A precision on an engine that stops on its budget. | Set `max_iter`, or choose `bisection` or `scipy_nelder_mead`. |
| `'bisection' moves 1 parameter(s) at a time and this search declares 2: K, Sy.` | A root search on two parameters. | Move one parameter per phase. |
| `'bisection' closes a bracket on a signed residual ... Score it on distance_gap, or search it with a minimiser.` | A root search on an unsigned metric. | Score it on `distance_gap`, or leave `method` unset. |
| `phase 'late' depends on 'nowhere', which is not declared before it.` | `depends_on` names a later or missing phase. | Declare the phases in order. |

At run time, `Calibration failed: ...` exits with code 21:

| Symptom | Cause | Fix |
|---|---|---|
| `phase 'transient_storage' depends on 'steady_conductivity', which did not run in this invocation` | `--phase` on a phase that depends on another. | Run the whole file. |
| `... calibration trials in a row failed, the last one with: ...` | Every trial fails the same way. | Run the base project once with `hmp run` and read its error; {doc}`non-convergence` covers a solver that stops. |
| `search: did NOT converge on its rule (...)` | The budget ended first. | Raise `max_iter`. The trials already solved come back from the cache. |
| A value with `-- reached the search bound` | The optimum is on a bound. | Widen `bounds`, or report the bound. |

## Next

- Complete files to download: {doc}`calibration-recipes`.
- Calibrate on a mapped stream network: {doc}`calibrate-on-the-stream-network`, and on two
  maps: {doc}`score-two-maps`.
- An interval for each value: {doc}`calibration-uncertainty`.
- Every method and metric: {doc}`../reference/calibration-methods`. Every key:
  {doc}`../reference/parameters/calibration/index`. The command:
  {doc}`../reference/cli/calibrate`.
- What is minimised, in equations: {doc}`../theory/calibration/inverse-problem-formulation`.
