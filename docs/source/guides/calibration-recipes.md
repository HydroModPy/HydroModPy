# Calibration recipes

Four complete calibration files to download. Each one sits beside `project.toml` of example 04
and runs there as it is; for another site, point its `base_config` at your own project file
and change the station, the map and the dates. A unit test loads all four on example 04 at
every change of the code, which keeps them true after a key is renamed.

```{hmp-task}
Task
: Start a calibration from a file that already works.

Time
: A second to check; from 7 runs (recipe 1) to about 45 runs (recipe 4) of the monthly model of example 04, one minute each or less.

Needs
: Example 04 in a workspace (`hmp example add`), or your own project file.

Gives
: A calibration file to run, then to adapt.
```

| Recipe | Use it when | What it decides |
|---|---|---|
| [One gauge, a first scan](#recipe-single-gauge) | One discharge record and one property to identify. | The range, the metric, the spin-up. |
| [Two targets, weighted](#recipe-multi-objective) | A gauge and a mapped network constrain the same model. | The share of the cost each target carries. |
| [A published method, named](#recipe-protocol) | The catchment is mapped, and the method of the paper fits. | Almost nothing: the method is named. |
| [The same method, written out](#recipe-staged-by-hand) | A stage needs to say more than the protocol. | Every stage, block and window. |

Save a file in `examples/projects/04_streamflow_intermittence_in_transient/`, then check it
and run it:

```bash
hmp calibrate calibration_single_gauge.toml --check
hmp calibrate calibration_single_gauge.toml
```

The steps behind each key are in {doc}`calibrate`.

(recipe-single-gauge)=
## One gauge, a first scan

{download}`recipes/calibration_single_gauge.toml`

K on a grid of seven values, scored on the gauged discharge with `nse_log`, from 2001 on. A
grid does not search: it maps the cost, so you see its shape before you spend a search on it.
On example 04 it ends with:

```text
Calibration finished: calibration_single_gauge.toml
  K = 1e-05  [1e-05, 3.16228e-05]
  cost: 0.0816791
  search: converged on its rule (budget), 7 evaluation(s) of 100 declared
  hydrograph: 25 pair(s) from 2001-01-01 to 2003-01-01 (first trial)
```

The grid ends after its seven points, well under the default budget. Read the shape of the
cost with the figure `parameter_cost_profile`, then narrow the bounds and switch to
`scipy_nelder_mead` if the minimum is clear.

```{literalinclude} recipes/calibration_single_gauge.toml
:language: toml
:start-at: base_config
```

(recipe-multi-objective)=
## Two targets, weighted

{download}`recipes/calibration_multi_objective.toml`

K and Sy together, scored at once on the gauge (70 %) and on the mapped network of October
2002 (30 %), by `optuna` with a fixed seed and 40 runs. The network gap is in metres:
`normalize_cost` divides it by the validity length of the output, so the two costs add up as
shares. Read `hydrograph.normalized_cost` and `network.normalized_cost` in `trials.jsonl` to
see what each share bought.

```{literalinclude} recipes/calibration_multi_objective.toml
:language: toml
:start-at: base_config
```

(recipe-protocol)=
## A published method, named

{download}`recipes/calibration_matching_hydrographic_network.toml`

K from the extent of the mapped network in steady state, then Sy from the gauge in transient
{cite:p}`abherve2023`. The protocol writes both stages; the file keeps the two ranges, the map
and the budget of stage two. `--expand` prints the stages it stands for, and `--check` lists
each departure from the paper. The guide of this method is
{doc}`calibrate-on-the-stream-network`.

```{literalinclude} recipes/calibration_matching_hydrographic_network.toml
:language: toml
:start-at: base_config
```

(recipe-staged-by-hand)=
## The same method, written out

{download}`recipes/calibration_staged_by_hand.toml`

The two stages of recipe 3 as phases, with one change the protocol cannot express: stage two
scores the gauge for 80 % and keeps the network gap, normalised, for 20 %. Start from this
file when a stage needs its own blocks, window or method.

```{literalinclude} recipes/calibration_staged_by_hand.toml
:language: toml
:start-at: base_config
```

## What can go wrong

`hmp calibrate FILE --check` finds each of these before any solve, and exits with code 14.

| Symptom | Cause | Fix |
|---|---|---|
| `the file does not load: [Errno 2] No such file or directory: '.../project.toml'` | The recipe is not beside the project it inherits. | Save it in the folder of `project.toml`, or point `base_config` at your project file. |
| `observes station 'NANCON', which no source of [data.hydrometry] lists in station_ids.` | Your project loads another station. | Write a station your `[data.hydrometry]` lists in `observes`. |
| `stream_geometry_path 'nancon_stream_network.gpkg' is not there, and none of the places the run looks holds it.` | Your site has another map. | Point `stream_geometry_path` at your map. |
| `scoring_window 2001-01-01 to open holds no date of the run, which runs from ...` | Your run does not cover the window of the recipe. | Move the window inside your run. |

Every other message is in the table of {doc}`calibrate`.
