# Calibrate

You end with values for the parameters you chose to move, a cost for each trial the search tried, and the best trial replayed as a full run with its figures. Everything sits in one project file with `[workflow].mode = "calibration"`. The session is written to disk as the search goes, so an interrupted search keeps what it evaluated.

This page follows one file from the first parameter to the report. Read the steps in order once. Later, each step stands alone.

```{note}
Rule of the project: an observed network, BD Topage or any mapped one, is a calibration target and a diagnostic. It is never an input of the model. The model builds its own network from the elevation model, and the criterion compares the two. Nothing in a calibration writes the mapped network into the mesh, the drains or the conductivity.
```

## What you need first

- A project file that already runs with `hmp run`. A calibration changes values in that model. It does not build one.
- The parameters you want to move exist in that model. A calibration cannot move a property the model does not have.
- Something to compare with: a gauged record loaded under `[data.hydrometry]`, a piezometer record, or a vector file of a mapped network.
- The file `project.toml` of example 04 (`examples/projects/04_streamflow_intermittence_in_transient`). Its calibration files are `run_calibration.toml` and its siblings. They are the worked case of this page.

To see what the model offers a calibration, run:

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

The first column is the name you write under `[calibration.parameters]`. The last column is the configuration path the sampled value replaces.

## 1. Switch to calibration mode and choose the parameters

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

Each table name under {toml}`calibration.parameters` is a name from the first column above. The bounds are in the unit of the parameter. Example 04 gives K this range:

```{hmp-resolved} calibration.parameters.K.bounds
:config: run_calibration.toml
```

Take the structure, not the numbers. A range belongs to the site. A range much wider than the evidence makes the search spend trials in a region you already exclude.

```{hmp-params}
calibration.parameters.<name>.bounds
calibration.parameters.<name>.transform
calibration.parameters.<name>.prior
```

The transform decides the space the search walks in. Unset, it follows the parameter: a hydraulic conductivity declares a log transform where it is defined, so you write the key only to depart from it.

### Reach a value that has no name

When a name resolves to nothing, or two targets answer to the same name, write the path yourself. A path you write wins without a lookup.

To multiply the value of the model instead of replacing it, set `mode = "scale"`. The sampled number is then a factor.

```toml
base_config = "project.toml"

[calibration.parameters.K_factor]
path = "flow.param.K.field.value"
mode = "scale"
bounds = [0.1, 10]
```

```{hmp-params}
calibration.parameters.<name>.path
calibration.parameters.<name>.mode
```

## 2. Say what the model is compared with

An output is a simulated quantity paired with its observation. You name each one.

A discharge at a gauge:

```toml
base_config = "project.toml"

[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
observes = "NANCON"
```

{toml}`observes|calibration.outputs.<name>.observes` names a station whose record the project loaded. The record is aligned on the simulated dates. No number is typed in the file.

```{hmp-params}
calibration.outputs.<name>.support
calibration.outputs.<name>.variable
calibration.outputs.<name>.observes
```

A mapped stream network, to be compared with the simulated seepage network:

```toml
base_config = "project.toml"

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["seepage_network"]
```

A network output has to be read by a block with `distance_gap` or `distance_mean`. A series metric cannot score it. A relative path is looked for beside the calibration file, then in the two folders above it, and in a `data/hydrography` folder under each. The network output has many more keys: how the map is rasterised, the validity length, the two bounds of the yearly extent. They are on their own cards, and {doc}`calibrate-on-the-stream-network` goes through them. The distance behind the criterion is explained in {doc}`../theory/downslope-distance`.

```{hmp-params}
calibration.outputs.<name>.stream_geometry_path
calibration.outputs.<name>.observed_network
```

Give exactly one of the two. With `stream_geometry_path`, the file is read from that path and from nowhere else. With `observed_network`, the criterion reads the network the data step loaded and clipped to the catchment, or the one the elevation model derived. Example 04 does the first in `run_calibration.toml` and the second in `run_calibration_bdtopage.toml`.

## 3. Say how the comparison is scored

An objective block scores one or several outputs with one metric. The metrics split in three families.

- Efficiency scores: `nse`, `kge`, `nse_log`, `nse_delta`, `nse_seasonal`, `reservoir`. HydroModPy minimises a cost, so the cost of these is one minus the score.
- Errors: `rmse` and `mae`, in the unit of the observation.
- Network distances: `distance_gap` and `distance_mean`, in metres.

```{hmp-params}
calibration.objective_blocks.metric
calibration.objective_blocks.uses_outputs
```

`nse_log` is the NSE of the log of the series. It gives the recessions as much weight as the peaks, which is where storage shows. It is not the logarithm of a cost: that is {toml}`transform|calibration.objective_blocks.transform`.

```toml
base_config = "project.toml"

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["hydrograph"]

[calibration.scoring_window]
start = "2001-01-01"
```

The first year of a run is still forgetting its initial state. {toml}`calibration.scoring_window` names the dates that count, so the same line means the same span at any time step. Example 04 leaves its first year out of the discharge stage, and `run_calibration_by_hand.toml` shows where the date is written.

```{hmp-params}
calibration.scoring_window.start
calibration.scoring_window.end
```

### Several targets in one cost

Declare one block per target and give each a weight. The weights are relative.

```toml
base_config = "project.toml"

[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
observes = "NANCON"

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["hydrograph"]
weight = 0.7

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["seepage_network"]
weight = 0.3
normalize_cost = true
```

Without `normalize_cost`, a cost in metres and a cost without unit add up, and the unit sets the weighting instead of the weight.

```{hmp-params}
calibration.objective_blocks.weight
calibration.objective_blocks.normalize_cost
```

A file with no block at all scores one series with {toml}`calibration.objective` and {toml}`calibration.variable`. Use it for a quick test. For anything you will report, write the outputs and blocks, so that the file says what is compared with what. {doc}`calibration-recipes` has complete files.

(calibrate-method)=
## 4. Choose the method

The method is the engine that proposes the next values. You do not have to write one.

```{hmp-params}
calibration.method
```

Left unset, HydroModPy picks. It takes `bisection` when the search moves one parameter in log space and every block is signed, which means a network distance `distance_gap`. The answer is then a zero to find. Otherwise it takes `scipy_nelder_mead`, a cost to minimise. `hmp calibrate --list-phases` prints the method of each search and the reason.

The method names are fixed. A name that is not in the table is refused:

```text
ERROR   [calibration]: method 'simplex' is not registered. Available: bisection, cma_es, da_mh_gp, gp_mapping, grid, lhs, optuna, random_search, scipy_de, scipy_nelder_mead.
```

| Method | What it does | Options it takes | Pick it when |
|---|---|---|---|
| `bisection` | Finds the zero of a signed criterion on one parameter. A coarse sweep in log space, then the bracket is halved. | `rel_tol`, `signed_component`, `sweep_points`, `bracket_expand` | One parameter, in log space, scored on `distance_gap`. It is the stream-network stage. |
| `scipy_nelder_mead` | A local simplex. It starts from the middle of the box and takes a start point from an earlier phase. | `maxiter`, `maxfev`, `xatol`, `fatol` | The range is already narrow, or you refine the result of a coarse search. |
| `optuna` | An Optuna study driven trial by trial. The default sampler is TPE. | `sampler`, `direction` | A first adaptive search on a few parameters. |
| `cma_es` | Covariance matrix adaptation. | `sigma0`, `popsize`, `max_evaluations`, `normalize`, `restarts` | Several parameters, a cost with plateaus, a box still broad. |
| `scipy_de` | Differential evolution. It runs one trial at a time. | `maxiter`, `popsize`, `tol` | A robust global search where parallel runs are not an option. |
| `grid` | Every point of a regular grid. The axes are even in the space the parameter is sampled in, so a log parameter gets a log axis. | `points_per_dim` | One or two parameters, a map of the cost, a deterministic reference. |
| `lhs` | One Latin hypercube design, evaluated whole. Each stratum of each parameter is hit once. | `n_samples` (required), `optimization` | An even scan with a fixed budget, more parameters than a grid affords. |
| `random_search` | Independent draws from the priors. It never decides it has converged, so it runs to its budget. | none | A cheap baseline to judge another method against. |
| `gp_mapping` | A Gaussian-process surrogate of the cost, refined where the expected improvement is highest. Every candidate it returns was run through the real model. | `max_iter`, `n_init`, `ei_tol`, `ei_patience`, and more | Each run is expensive and the parameters are few. |
| `da_mh_gp` | A delayed-acceptance Metropolis-Hastings chain with a surrogate and an exact second stage. It reads its cost as an RMSE. The best candidate is the posterior mode. | `max_iter`, `burn_in`, `proposal_sigma`, `sigma_noise`, and more | You want a sample of plausible values, not one optimum. Score it on `rmse`. |

Write the options under {toml}`calibration.method_options`, with `method` beside them. Each method refuses the keys of another:

```text
  /path/to/file.toml: calibration: Value error, [calibration] method_options: 'grid' does not take sampler; the options it takes are: points_per_dim. (input={...})
```

```{hmp-params}
calibration.method_options
calibration.max_iter
calibration.tolerance
calibration.seed
```

`cma_es` and the `cmaes` sampler of `optuna` need the packages of the `calibration` extra. `optuna`, `gp_mapping` and `da_mh_gp` need nothing more than the base install.

(calibrate-stopping)=
### How a search stops

An engine stops on its own rule, on its budget, or both.

- `bisection` and `scipy_nelder_mead` stop on a precision of the parameter. That is {toml}`calibration.tolerance`. The other engines stop on their budget and refuse a tolerance:

  ```text
  ERROR   [calibration]: tolerance asks 'optuna' to stop at a precision on the parameter, and that engine stops on its evaluation budget instead. Set max_iter, or run this search on an engine that converges on the parameter.
  ```

- `max_iter = "auto"` lets an engine that can count its evaluations size its own budget. `bisection` and `lhs` count them: `lhs` budgets its whole design. Every other engine gets a default budget from `"auto"`, and no extension.
- A search that spends its budget before its rule is met is reported as not converged. A re-run with a larger `max_iter` replays the trials already solved from the cache.

### How to choose

1. One parameter in log space and a network distance: `bisection`. Do not look further.
2. A narrow range, or a result to refine: `scipy_nelder_mead`.
3. A first look at a new catchment: `grid` on one or two parameters, or `lhs` on more. They map the cost before you search it.
4. A search on several parameters with a broad box: `optuna` or `cma_es`. Set {toml}`calibration.seed` so a re-run gives the same trials.
5. Expensive runs and few parameters: `gp_mapping`.
6. A sample of plausible values: `da_mh_gp`. An interval around a calibrated value does not need a sampler: see {doc}`calibration-uncertainty`.

Chain them when one method is not enough. That is the next step.

## 5. Chain searches as phases

A phase is one search with its own parameters, criteria and method. The values a phase finds are frozen for the next ones. Declaring {toml}`calibration.phases` is what switches the run to staged mode.

```toml
base_config = "project.toml"

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.hydrograph]
support = "point"
variable = "discharge"
observes = "NANCON"

[[calibration.objective_blocks]]
name = "hydrograph"
metric = "nse_log"
uses_outputs = ["hydrograph"]

[[calibration.phases]]
name = "scan"
description = "K alone on a log grid."
parameters = ["K"]
objective_blocks = ["hydrograph"]
method = "grid"
method_options = { points_per_dim = 7 }

[[calibration.phases]]
name = "refine"
description = "K and Sy together, from the best value of the scan."
parameters = ["K", "Sy"]
objective_blocks = ["hydrograph"]
method = "scipy_nelder_mead"
depends_on = "scan"
```

```{hmp-params}
calibration.phases.parameters
calibration.phases.depends_on
calibration.phases.freeze_on_success
calibration.phases.regime
calibration.phases.objective_blocks
```

A phase that lists a parameter an earlier phase passed on moves it again. It starts from the passed value when its method accepts a start point. `scipy_nelder_mead` and `cma_es` do. Each phase names the blocks it evaluates. A phase that names neither `objective_blocks` nor its own `variable` and `objective` is refused when the file loads, because it would be scored on blocks that other phases were built for.

A phase that does not converge freezes nothing. If a later phase depends on it, the chain stops instead of calibrating against values you did not intend:

```text
phase 'steady_conductivity' freezes what ['transient_storage'] calibrate on top of, but its session ... spent ... trial(s) ...
```

`--phase` runs one phase of a staged file, and only that phase. A phase that declares `depends_on` is refused, because the phase it depends on does not run in that call: `phase 'refine' depends on 'scan', which did not run in this invocation, so the values 'scan' freezes are missing.` Run the whole file instead.

### Name a published method

A protocol is a published recipe that expands into phases and blocks. You write its name, and the parameters and the outputs it needs.

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
```

```{hmp-params}
calibration.protocol.name
calibration.protocol.version
```

It runs two stages: the conductivity from the mapped network in steady state, then the specific yield from the gauge in transient state. The gauge needs no output: the protocol reads it from `[data.hydrometry]`. Each stage has its own keys under `[calibration.protocol]`, such as the budget of stage two. Example 04 shortens it:

```{hmp-resolved} calibration.protocol.transient_max_iter
:config: run_calibration.toml
```

`hmp calibrate run_calibration.toml --expand` prints the `[calibration]` section the protocol writes, as TOML. Paste it in place of the protocol to change a stage. Example 04 does exactly that in `run_calibration_by_hand.toml`. The full walk-through of this method is {doc}`calibrate-on-the-stream-network`.

## 6. Check before you solve

A calibration is hours of solver time. `hmp calibrate` has three modes that solve nothing and cost a second:

```bash
hmp calibrate my_calibration.toml --check
hmp calibrate my_calibration.toml --list-phases
hmp calibrate my_calibration.toml --expand
```

`--check` reports every problem at once, not the first one. It faces the names against each other, the bounds against the physics, each method against the traits it declares, the budgets, and the files an output needs. A clean file ends with:

```text
my_calibration.toml: ready to run.
```

Before that line, `--check` prints what each search compares with what:

```text
compares ([calibration]):
  hydrograph    nse_log    share 100%    discharge, station NANCON (whole-catchment series)    vs station NANCON ([data.hydrometry])
```

Read this line before every long run. It is the file as the code understood it.

`hmp config check my_calibration.toml` validates only the shape of the tables. It does not look at the search.

`--list-phases` prints one line per phase: its method, why that method was chosen, and the width of the interval the phase reads. `--expand` cannot be combined with `--check`, `--list-phases` or `--phase`.

## 7. Run it

```bash
hmp calibrate my_calibration.toml
```

`hmp run my_calibration.toml` does the same, because the file says `mode = "calibration"`. In Python, call `hmp.calibrate("my_calibration.toml")`, see {doc}`drive-from-python`.

Four keys decide the cost of the run.

```{hmp-params}
calibration.parallel
calibration.save_runs
calibration.save_best_n
calibration.rerun_best_with_outputs
```

- Each trial runs the model with the new values. The setup that the parameters do not touch, the data, the elevation model and the mesh, is prepared once. A trial of `K` or `Sy` replays only the solver preparation, the solve and the extraction. A trial of a parameter read earlier, such as `domain.depth_model.thickness`, replays from the process setup. A parameter of `geographic` replays from the geographic build.
- Derived fields, figures and exports run only for the trials that are promoted to full runs.
- With the defaults of {toml}`calibration.save_runs` and {toml}`calibration.rerun_best_with_outputs`, nothing is promoted: only the session is written. Example 04 sets `rerun_best_with_outputs` to replay the best trial of each stage with its figures.
- {toml}`calibration.parallel` solves trials side by side, each in its own folder and each with its own model in memory. `scipy_de` returns one point at a time, so `--check` warns that `parallel` buys nothing there.

A trial can fail. A failed trial is scored as a failure and logged, and the search goes on. When several trials fail in a row for the same reason, the search is stopped instead of running its budget on a file that cannot be scored.

To reject a trial whose water balance does not close, set {toml}`calibration.reject_water_budget_above`. It has no default, because the right limit depends on the model.

## 8. Read what it stored

`hmp calibrate` ends with the best value of each parameter, with its interval when the run produced one, and the cost it was reached at. A staged file prints one block per phase:

```text
Calibration finished: run_calibration.toml
phase steady_conductivity:
  K = ...  [..., ...]
  cost: ...
  search: converged on its rule (...), ... evaluation(s) of ... declared
phase transient_storage:
  Sy = ...  [..., ...]
  cost: ...
```

`hmp run` prints a shorter recap instead: one line per phase with the method, the number of runs, each best value with its unit and interval, and the cost, then the folders of the best runs and of the sessions.

Three kinds of lines need your attention.

- `-- reached the search bound` after a value: the optimum sits on a bound of `bounds`. Widen the range, or accept that the data cannot place it.
- `caution: K and Sy trade off (r = ...), not identified separately.` or `caution: K and Sy moved together (r = ...), not identified separately.` The data do not tell the two parameters apart. The first form comes from the `linearized` interval, the second from the trials of the search.
- `search: did NOT converge on its rule (...)`: the budget ended before the stopping rule was met. The value is where the budget ended.

### Files

Each session owns a folder at the project root. The files are the truth. The index is built from them.

| Path | Content |
|---|---|
| `sessions/<session>/session.json` | Identity, search space, objective, dates, best trial. For a root search, the final bracket or the two roots. Written before the first trial and rewritten at the end. |
| `sessions/<session>/trials.jsonl` | One JSON object per trial, appended as it completes: the trial number, status, cost, parameters, metrics, duration, and the hash that identifies the trial in the cache. |
| `sessions/<session>/trial_series/` | The simulated and observed series of each trial, one Parquet file per trial. Only with {toml}`calibration.persist_trial_series`. |
| `sessions/<session>/methods.md` | A methods paragraph with the citations. Only when the file declares a protocol. |
| `runs/<run>/` | One full run per promoted trial, with its figures. |
| `share/reports/<session>/report.html` | The HTML report of `hmp report render`. |

A staged calibration writes one session per phase. `session.json` carries the phase name and its place in the chain, so a rebuilt index gives the chain back.

### Look at the trials

The DuckDB index is derived. List the best trials of the last sessions with SQL:

```bash
hmp catalog query "SELECT iteration, objective_value, parameters FROM calibration_iterations ORDER BY objective_value LIMIT 5"
```

If the index is stale, `hmp catalog reindex` rebuilds it from `runs/` and `sessions/`.

Render the report of the last session, or of a given one:

```bash
hmp report render --open
```

The figures that read a calibration are in the figure reference: {doc}`../reference/figures`. List the ones you want under `[display].figures`. They apply to the promoted runs. Among them are `calibration_progress` for the convergence of any method, `parameter_cost_profile` for the cost against one parameter, `bisection_bracket_trace` and `downslope_distance_crossing` for a root search.

For an interval around each value, and for how well the data identify them, go to {doc}`calibration-uncertainty`.

## What can go wrong

Run `--check` first. These are its findings, with the real text.

| Message | Cause | Fix |
|---|---|---|
| `bounds are 0.001 .. 1e-07; the lower one has to be the smaller one.` | The two numbers are in the wrong order. | Write `[low, high]`. |
| `names nothing this project carries. It holds 'thickness', 'drainage', 'K', 'Ss', 'Sy'. ...` | The table name is not in `hmp config targets`. | Use a name from the list, or write `path`. |
| `lower bound 0.0 is outside what 'K' can physically be: hydraulic conductivity (id='k') value 0.0 outside [1e-14, 100.0] m/s` | A bound lies outside what the parameter can be. This one is refused when the file loads. | Move the bound inside the range. |
| `objective_block 'net' uses_outputs=['ghost'] but those names are not declared in [calibration.outputs]. Declared outputs: ['seepage_network'].` | A block names an output that does not exist. | Fix the name, or declare the output. |
| `stream_geometry_path 'nope.gpkg' is not there, and none of the places the run looks holds it. ...` | The mapped network file is not found. | Fix the path. It is looked for beside the calibration file and in the folders above it. |
| `'bisection' moves 1 parameter(s) at a time and this search declares 2: K, Sy.` | A root search on two parameters. | Move one parameter per phase, or choose another method. |
| `'bisection' closes a bracket on a signed residual ... Score it on distance_gap, or search it with a minimiser.` | A root search on a metric that has no sign. | Score the phase on `distance_gap`, or pick a minimiser. |
| `'grid' does not take sampler; the options it takes are: points_per_dim.` | `method_options` belongs to another method. | Write the options of the method you chose. |
| `phase 'refine' depends on 'scan', which is not declared before it.` | `depends_on` names a phase that comes later or does not exist. | Declare the phases in order. |

At run time:

| Message | Cause | Fix |
|---|---|---|
| `Calibration failed: ...` | The search could not be run as declared. The exit code is the calibration one, see {doc}`../reference/cli/exit-codes`. | Read the text after the colon. |
| `... calibration trials in a row failed, the last one with: ...` | Every trial fails the same way. | Run one simulation with the base file and read its error. {doc}`non-convergence` covers a solver that stops. |
| `search: did NOT converge on its rule (...)` | The budget ended first. | Raise `max_iter` or loosen `tolerance`. A re-run replays the solved trials from the cache. |
| A value with `-- reached the search bound` | The optimum is on a bound. | Widen `bounds`, or read the interval. |

## Next

- Complete files to copy: {doc}`calibration-recipes`.
- Calibrate on a mapped stream network: {doc}`calibrate-on-the-stream-network`, with the criterion in {doc}`../theory/downslope-distance`.
- An interval for each value: {doc}`calibration-uncertainty`.
- A method tried on many catchments: {doc}`test-a-method`.
- Every key of the section: {doc}`../reference/parameters/calibration/index`. The command: {doc}`../reference/cli/calibrate`. The Python verb: {doc}`../reference/python/hmp-calibrate`.
