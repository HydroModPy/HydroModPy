# Changelog

All notable changes to this project will be documented in this file.

The format follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention
and this project adheres to [Semantic Versioning](https://semver.org/).

---

## About this file

This changelog lists every significant modification of the HydroModPy project,
from new features to fixes and internal updates.

Each release section includes the following standard categories:

- **Added** - for new features
- **Changed** - for updates in existing functionality
- **Deprecated** - for soon-to-be removed features
- **Removed** - for removed features or files
- **Fixed** - for any bug fixes
- **Security** - for security improvements

### How to update it

1. During development, document all notable changes under the **[Unreleased]** section.
2. When creating a new release (e.g., `v1.1.0`, `v2.0.0a1`, `v2.0.0b1`,
   or `v2.0.0rc1`), move that content into a new section named
   `## [vX.Y.Z] - YYYY-MM-DD` or the matching pre-release tag.
3. Keep the `[Unreleased]` section empty to start recording changes for the next release.

---

## [Unreleased]

### Fixed

- `hmp doctor --fix-config` now moves a `maxfev`-style option of a calibration phase into `max_trials` when the phase takes its method from `[calibration]`, and keeps the section's budget as a bound.
- A sealed run config with `roptim_max` other than 2 now reads and replays. The key is dropped. A live file with such a value is still refused.
- `Project.calibrate()` refuses `method`, `max_trials`, `save_runs`, `seed`, `outputs`, `objective_blocks` and `phases` when the calibration comes from a file or the project config, and unknown options on the config route, instead of ignoring them.
- `Project.calibrate(resume=True)` now resumes on the programmatic routes.
- `Project.calibrate` without phases now honours `uncertainty.method = "linearized"`. The width was computed for
  `hmp calibrate` and for staged calibrations, but a Python call without phases skipped it and returned no
  `parameter_uncertainty`. An evaluator that runs no HydroModPy model now gets the same refusal on this route as on the
  command line.
- `Project.calibrate(phases=...)` with `resume=True` reopens the session of an earlier call. The document it writes is now
  named after the case (`sessions/<case>.toml`) instead of a timestamp, so the staged run names the same case each time.
- A calibration run from Python names its case by one rule, the same as the command line: `[simulation] name`, else
  the stem of the project file.
- `hmp doctor --fix-config` now reads the files a file inherits for the timestep, `start_datetime` and `[site] gauge`. It no longer leaves `warmup_periods` with a false reason, and no longer writes a second gauge over the parent's.
- The doctor always writes a date without a time when it rewrites `warmup_periods`, and its change line says the date counts from `start_datetime`. The old count ran from the first aligned sample, so the two agree only when the record starts at `start_datetime`.
- `hmp config check` now takes off `validation_window` when it decides whether a protocol `window` equals the recipe's default.
- `hmp doctor --fix-config` keeps the share of each map when a child file adds an extent or weights under a parent it already rewrote. It used to drop the weights and score the permanent map alone.
- `hmp doctor --fix-config` says what to do when a file gives `map.calibrate_on` and old `extent.weights` that differ, and no longer drops the weights.
- `hmp doctor --fix-config` refuses a network output written with dotted keys under a parent table, with a line that asks for a `[calibration.outputs.<name>]` table. It used to stop on a raw error, or to write the new tables outside `[calibration]`.
- The warning for two roots more than half a decade apart now fires when the maximal root lies below the minimal one, as on the Nancon.
- A minimiser on one parameter and two bounds is refused only when a metric is a signed residual, so scoring `distance_mean` is no longer sent to a root search that cannot run it.
- The warning about `distance_gap` beside another parameter no longer points to `balanced_evaluation`.
- A run resumed at its derive step says in a warning that no station series is written.
- One failing observing output no longer drops the series of the others.
- Two parameters on one path, `path` with `target`, and `mode = "scale"` on a zero or unset value are refused at load instead of silently doing nothing.
- The registry label of `vka` said Kv/Kh, and the key is Kh/Kv.
- A calibration that scores different blocks in different phases is no longer refused as a sum of costs of different units.
- A phased calibration run from a project held in memory no longer fails with a frozen-configuration error when a phase overrides the regime.
- A worker that dies marks its trial `crashed`, and the search goes on with a new worker. A stuck `mf6` is killed with its worker.
- A stop (Ctrl-C, SIGTERM) of a search at `parallel` above 1 now ends the solves in flight at once. Without it, the workers of the previous change, which have their own session, made the stop wait for the longest trial.
- The runs of a linearized width no longer enter the retention of the solves a promotion may keep. They were ranked with the trials at cost 0.0, so one could push the Nth best trial out of a `save_runs = "best_n"` search.

### Changed

- `hydromodpy.calibration.evaluation.registry` and `forward_registry` now share one engine. Their functions keep their names, and their first parameter is now called `name`. A plugin that passed it by keyword (`get(evaluator_id=...)`) passes it by position.
- The calibration TOML written by a Python call with phases is `sessions/<case>.toml`, overwritten by the next call of
  the case. It no longer piles up as `python-<date>-<id>.toml`.
- Example 04 `run_calibration_api_daily.toml` calibrates on 2016-2018 and validates on 2019-2020.
- Changing the validation window starts a new cache scope and a new session, as a changed scoring window does. A document
  without the key keeps its cache keys.
- A file that writes an old key of `[calibration]` is now refused with the new name, and `hmp doctor --fix-config` rewrites it. This covers `scoring_window`, `optimizer_kwargs`, `steady_engine_options`, `transient_engine_options`, `max_iter`, `tolerance` and their stage forms, `transform` and `prior`, the two extent step counts, `tolerance` and `mode` of `[calibration.uncertainty]`, the evaluation counts in method options and `roptim_max`. These keys used to load with a warning. The section is experimental, so it takes no delay. A sealed `config.toml` is still read. Other sections keep their delay.
- `Project.calibrate` on a project read from a file now names its case as `hmp calibrate` does, so the two share one session and `resume` finds it. The case no longer comes from a name the file inherits.
- The seepage threshold is described as a fraction of the mean basin recharge over the cell's own area, in the field, the protocol deviation and the docs. No value changes.
- The example calibration files of 04, 10, 12 and 21 use the new `map`, `model` and `verdict` tables.
Numbers: none.
- The preflight refuses a minimiser on one parameter scored on two network bounds of positive weights, because the value returned would depend on the method. Search it with `bisection` on `distance_gap`, or weigh one bound zero.
- The preflight warns when `distance_gap` enters a cost beside another parameter or another metric, because that cost can fall by trading excess for missing stream.
- A root search warns when its two roots lie more than half a decade apart, because the value returned between them satisfies neither map.
- A root search (bisection) now refuses a set of objective blocks unless every block publishes a signed residual. Before, one residual block was enough.
- The composite example of example 04 scores its network block on `distance_mean` instead of `distance_gap`.
- The `balanced_evaluation` description says that its report keeps no roots record and no Delta.
- A run stores the series it simulates at each observed station under the id of the station, all in one write. A gauge the mesh cannot place is no longer stored under its own name with the outlet series: it is listed as unscored and a warning names it.
- A promoted run reads the stations with the outputs of the phase it comes from.
- `hmp.read(run, "head")` or a lake stage with several stations needs `station=`.
- `hmp run` ends a calibration with the same lines as `hmp calibrate`. `hmp calibrate` prints the unit after each value.
- `Project.calibrate()` refuses an unknown argument by its name, and no longer merges extra keywords into the configuration.
- `sampling = "normal"` is refused by the Optuna engine instead of being drawn as uniform.
- A raw residual cost in a unit (such as an RMSE in m3/s) beside pure-number costs is refused unless `normalize_cost = true`.
- The `path` description says it inherits the field's space and draw when the catalogue carries the path.
- Comments and docstrings cite `hmp config check` instead of `hmp calibrate --check`.
- The rate of a well now has a physical range, from -1 to 1 m3/s in the unit of the well, whatever its sign. Calibration bounds outside it are refused.
- A steady search scored on the network alone that moves K and the recharge factor is now refused, because that state reads K/R and nothing else. The same search with other parameters still warns.
- `factor` is refused beside `[flow.sinks_sources.recharge.soil]`, written in the file or calibrated, because the soil reservoir computes that recharge.
- `hmp.calibrate("file.toml", ...)` goes through `Project.calibrate(config_path=...)`, so `dry_run`, `case`, `protocol` and `resume` are accepted and an unknown option is a `TypeError` that names it.
- `hmp campaign promote` lists the five best trials of each phase, because the costs of two phases cannot be compared.
- Two parameters may write one path when no phase moves both.
- The `kge` score says why it is NaN when the simulation is constant.
- With `parallel` above 1, the trials of a search that runs the HydroModPy pipeline now run in worker processes that last, instead of threads. The parent keeps the engine, the journal, the cache and the catalog. Costs do not change.
- A Python script that calibrates with `parallel` above 1 needs the `if __name__ == "__main__":` guard, because each worker imports the script again.
- A `metric_fn` for a search with `parallel` above 1 must be defined at the top level of a module. A lambda or a closure is refused before the first solve, and the message says so.
- `[modflow6.runtime] mf6_api_timeout_s` now limits one whole trial of a parallel search, whichever runner solves it. The default stays 2400 s, so a trial longer than that, which used to finish under the `subprocess` runner, now ends `crashed`. The message says how to raise it. A serial search has no limit, as before.
- `hmp calibrate --dry-run` shows the widest `parallel` of the phases under `solves in parallel`, not the one of `[calibration]` alone.
- With `parallel` above 1, a grid, a Latin hypercube and a random search feed one queue of `parallel` workers. A free worker takes the next point at once, and no batch waits for its slowest trial. The points and the costs are the same as before.
- With `parallel` above 1, the progress bar moves as each trial ends, not when its whole batch has.
- With `parallel` above 1, the restarts of `uncertainty.method = "multistart"` run side by side on one shared set of workers, so together they run `parallel` trials at once and no more. They no longer run one after the other. A restart no longer finds the trials the restarts before it solved in the cache.
- With `parallel` above 1, the derivatives of `uncertainty.method = "linearized"` (one run per parameter, plus the reference) run side by side in workers that last for these runs only.
- `scipy_de` now accepts `parallel` above 1 and `hmp calibrate --dry-run` no longer says it proposes one trial at a time. From a width of 2 it scores a whole generation from the one before it (`updating = "deferred"`). Its path differs from the one it follows at `parallel = 1`, which is unchanged. For the same number of evaluations it reaches a higher cost (see Numbers), and it runs the trials of a generation side by side.
- With `parallel` above 1, Optuna's `tpe` sampler counts the trials in flight as the worst cost so far (`constant_liar`), so the points of one batch do not land on each other.

### Numbers

- A Python calibration without phases that asks for a `linearized` width now carries `parameter_uncertainty` and pays for
  the model runs of that width, one per calibrated parameter plus one at the optimum. Search results, costs and every
  other route are unchanged.
- The cost of a document without `validation_window` does not move, bit for bit, and its cache key does not move. A test holds this.
- `run_calibration_api_daily.toml` ranks its five K on 2016-2018 instead of 2016-2020. This was not run, so the size of the
  change in its costs is not measured.
- None moves. The option is off by default, and the new messages change no result.
- The composite example changes its network cost; no stored result or golden depends on it.
- None.
None. No metric value changes.
- No number moves at factor 1. No run was replayed for this change.
- No number moves. One real solve of each trial of the cut example 04 (30 x 30, monthly, one year, K on two values): costs at `parallel = 2` equal to those at `parallel = 1` to the last digit, 0.5363546813031831 and 0.5756840896779987.
- At `parallel = 1` nothing moves, to the last digit: the candidates and costs of `scipy_de` and the Jacobian are equal to those of the previous build (checked on a toy cost).
- `scipy_de` at a width of 4 against a width of 1, 30 seeds, population 10 times the number of parameters, median of the best cost at the same number of evaluations. 4 parameters on a narrow ridge: 0.0057 against 0.0041 at 400 evaluations, 5.5e-5 against 1.2e-5 at 1200. Rosenbrock on 3 parameters: 0.38 against 0.43 at 400, 4.7e-4 against 7.9e-5 at 1200. So the side by side path costs up to 1.5 to 5 times more evaluations to reach the same late precision, and wins when the solves dominate and `parallel` is 2 or more.
- Optuna `tpe` with `constant_liar`, 40 seeds, 64 evaluations, batches of the width, median of the best cost. 4 parameters on a ridge: 0.052 against 0.040 at width 2 (22 wins of 40 for the lie), 0.081 against 0.060 at width 4 (23 of 40), 0.095 against 0.051 at width 8 (26 of 40). Rosenbrock on 3 parameters: 3.7 against 3.8 at width 2 (23 of 40), 4.8 against 3.0 at width 4 (27 of 40), 5.7 against 3.6 at width 8 (29 of 40). Neutral at a width of 2, better from 4.

### Removed

- The B0 network and transient discharge case left the `hydromodpy` package for `validation_cases/calibration/network_transient_b0/`. The wheel no longer ships its page. `hydromodpy.calibration.reporting`, `hydromodpy.calibration.observations.natural_observations`, `network_cost`, `network_transient_truth` and `hydromodpy.calibration.optim.objective_mapping` are gone, and `step_render_network_transient_calibration_html` is no longer in `hydromodpy.workflow.steps.calibration`.
- A network output can no longer score against `geographic.river_network`. The DEM-derived network is no observation. `hmp doctor --fix-config` says to write `map.complete = "data.hydrography"` or a vector file, and a sealed run simply drops the key. The `observed_network_is_dem_derived` trial diagnostic is gone with it.
- The unused `area_m2` argument of `_add_runoff_to_discharge_series`.

### Added

- `[calibration] validation_window = {start, end}` keeps dates apart from a search. Every trial is scored on them beside its
  cost, from the series it has already simulated, under the component `validation.cost`. The promoted run stores the period
  in `checks.calibrated_by.windows` (role `validation`) and the score of its trial in `checks.calibrated_by.validation_cost`.
- `[metrics] window` minus the validation window is the default calibration window, on the section, on a phase and on the
  transient stage of the network protocol. A phase that writes only a start is closed by it too.
- A validation window that overlaps a calibration window, covers all of `[metrics] window`, falls outside it, leaves a bound
  open or has no dated record to score is refused by name. So is one beside a metric function or another evaluator.
- A phase can set `balanced_evaluation = true`: every point of its search closes the root of J on K with its own root search, and is scored there. It is meant for comparing structures such as a thickness or a K(z) profile. `max_trials` counts the points, and each point costs about fifteen solves. Off by default, and not yet measured on the synthetic twin.
- A balanced phase whose outer method cannot count its points and runs with `max_trials = "auto"` is refused, naming the points times the solves of each.
- `Project.calibrate()` takes `protocol`, `case`, `resume`, `dry_run`, `workspace`, `project`, `project_label`, `metric_fn` and `objective` by name, on every route. `dry_run=True` returns the plan.
- `hmp campaign promote CASE` without `--trial` lists the five best completed trials.
- `hmp config targets` shows the search space, the draw and the default bounds of each target. Names with a dot are written between quotes, as TOML needs.
- The session README gives the best values with their unit and interval, what the cost means and the pairs it was scored on.
- A parameter on a path the catalogue does not carry now warns that its unit is unknown and the sample is written as drawn.
- `kge` and `nse_seasonal` say why they return NaN (too few pairs, constant observations, observations summing to zero, fewer than two cycles).
- `flow.sinks_sources.recharge.factor` multiplies the recharge in force, from `values` or from `[data.recharge]`, gridded or by station. Its default of 1 changes no number. A calibration reaches it as `recharge.factor`, searched in log space between 0.5 and 2 unless the file says otherwise. The run keeps the multiplied recharge in `forcing/` and seals the factor in its config.
- `vka` can be calibrated under MODFLOW 6 as `[calibration.parameters.vka]`, in log space, with bounds the file states. It is not offered when the project declares `Kv`.
- `Project.calibrate(protocol=...)` now builds on the parameters and outputs of the project's own `[calibration]` section, and writes the phases on top of them.
- `hmp config check` refuses the `normal` sampling on the `lhs` and `optuna` methods before anything is prepared.
- `hmp config check` refuses a calibrated recharge factor when the run carries no recharge rate to multiply, and when `recharge.values` is calibrated beside it.

## [v2.0.0rc1] - 2026-11-03

This is the first release candidate of 2.0.0. The notes below are for a reader who comes from
version 1 or from an alpha. The long development notes of the alphas are kept in
[Changes during the alphas](https://github.com/HydroModPy/HydroModPy/blob/main/docs/source/about/changes-during-the-alphas.md).

### What to do when you update

- Runs and sessions stored by an alpha are refused. Run them again with this version.
- A TOML file written for an alpha or for version 1 may use old keys. Run
  `hmp doctor --fix-config` on it. It rewrites the renamed keys and says what it changed.
- If you come from version 1, read `docs/source/get-started/from-v1.md`.
- The keys and commands that moved between versions are listed in the reference page
  `docs/source/reference/changes.md`, "What changed in the TOML". It is built from the models, so
  this file does not repeat the table.
- A file that does not say which calibration protocol it wants follows protocol 1.3.

### Added

- A page for users of version 1, with the table of old keys and commands.
- A `NOTICE` file with the licences of PyHELP and of the data, and `version` in `CITATION.cff`.
- JSON Schemas for `manifest.json`, `provenance.json` and the output of `hmp calibrate`.
- A sha256 for each file of a run. `hmp doctor` reports a sealed file that is missing or changed.
- `--format table|json|csv` on the commands that print a result, and a `HMPY.Exxx` code at the
  start of each error line.
- A transient Boussinesq run writes a `storage` budget term, so its domain budget closes.
- `hydromodpy_version_min` in `workspace.toml` is enforced.
- Checks of the MODFLOW binaries and of the HELP3O extension against a pinned sha256.
- `docs/source/about/versions.md` states what a version number may change.

### Changed

- The defaults of the soil reservoir change. `alpha` goes from 0.6 to 0.45, which means p = 0.55,
  the value of FAO-56 table 22 for cereals and maize. `flow.sinks_sources.etp.extinction_depth`
  goes from 1 m to 2 m, also for MODFLOW-NWT with a loaded ETP. A negative recharge routed to EVT
  keeps its 1 m, and a file that writes these keys reads as before.
- The soil reservoir gives each SAFRAN cell its share of the catchment in the basin mean it
  prints, and in the mean of the capacity classes. A run without a catchment polygon, or on a
  grid that misses it, still gives the cells the same weight. The grids handed to MODFLOW 6 do
  not change.
- Each stored format declares the oldest version that reads it. Every later 2.x reads every 2.0.0 run.
- A name can be renamed in a minor version. The old name keeps working for two minor versions.
- A calibration with no pin on the protocol follows 1.3: the map is cut to the catchment and
  the network is rasterized from the heads of the observed streams.
- A tie on the cost in the last phase of a search promotes the trial that the search answered.
- A date written on a stamp belongs to the period `(s, e]` that the stamp closes.
- A chain of TOML files that sets one key under an old and a new name keeps the value of the last file.
- `hmp.run` returns a `Run`, and a calibration goes through `hmp.calibrate`. Overrides go through
  `set=`. `Project.run` is now `Project.launch`. `hmp.__all__` holds the verbs, the main objects
  and the main exceptions. A name that left is refused with its new path.
- A boundary condition is active when its table is declared, and `enabled = false` turns it off.
  `active_bc` and `active_sinks_sources` are no longer written. Boussinesq and PETSc settings move
  to `[flow.runtime]`, and the discriminator is `kind` everywhere.
- On the command line, `-w` works on every verb, also before it. `hmp replay` is removed,
  `hmp test` is now `hmp dev test`, and `hmp campaign` holds the verbs of a plan of cases.
- A budget flux is negative when water leaves the aquifer, for every solver.
- A time series has a `source` column, `simulated` or `observed`, and the catchment row is named
  `catchment`. NetCDF and VTU write one variable with a layer dimension, so opening a NetCDF in
  QGIS needs `layer=` on the export.

### Removed

- The commands and flags that left before 2.0.0 have no alias. They are refused with a message.
- `catchment_mismatch` as it was. The old number is now called `basin_mismatch`.

### Fixed

- A project whose DEM comes from a `[data.dem]` source alone, with no `dem_init_path`, opens again.
  Assigning the geographic section refused it before any step ran.
- The citations of the soil reservoir are checked against the sources. The AMC I and III
  formulas now cite NEH-630, whose table they fit, the limits of `curve_number` point to the same
  handbook, and the default of `alpha` says it is a choice made here.
- The description of `curve_number` no longer says that the smoothing of SAFRAN explains a
  calibrated number above the table, which no source supports.
- The theory page of the soil reservoir now says that the retention of the curve number is not a
  store, where each piece comes from, how much the capacity moves the recharge, and what the
  bypass, the transit, the overflow and the extinction depth do to the low flows. It also says that
  its default recharge stands for the drainage plus the runoff of SIM2.
- A soil run on a steady first period now names `[flow.ic] kind`, and step 6 of example 04 uses
  the `kind` key and the `[flow.sinks_sources.etp]` table.
- The MODFLOW 6 `discharge` of a run with a lake and no SFR, the Boussinesq `discharge`, and the
  Boussinesq budget terms. The sizes are in Numbers.
- A network output whose `time` falls on a stamp, and a window that ends on a stamp.
- A calibration trial on a mesh wider than its catchment.

### Numbers

Every change below can move a stored number. Sizes come from example 04 unless another case is
named. Runs of older versions are not comparable on these quantities.

- Recharge the soil alone prints on example 04, 2015 to 2020, for a capacity of 50, 100, 150, 200
  and 250 mm. It was 443, 392, 356, 325 and 295 mm/year and is now 443, 389, 350, 315 and 280
  mm/year. Giving the cell that holds 83 % of the catchment its 83 % adds 7 to 9 mm/year, and the
  lower `alpha` takes back 7 to 24 mm/year.
- Discharge of step 6 of example 04 with K = 3.16e-5 m/s and Sy = 0.04, monthly, 2016 to 2020.
  NSE log goes from 0.903 to 0.932, KGE from 0.911 to 0.947, NSE from 0.904 to 0.929, the July to
  September bias from +0.022 to 0.000 m3/s, and the lowest monthly flow of 2019 from 0.183 to 0.151
  m3/s, for 0.153 gauged.
- MODFLOW 6 with a lake and no SFR, `discharge` over a three-month valley with a buffer. It was
  3.855e-05, 3.856e-05, 3.855e-05 m3/s and is now 0.100996, 0.143696, 0.087693 m3/s, about 2 600
  to 3 700 times more. The old number was the lake outlet alone. SFR and SFR with a lake do not
  move. MODFLOW-NWT cannot hold a lake.
- Boussinesq `discharge`, island of the test suite, three months. It was 4.2e-9, 9.6e-10 and
  4.2e-11 m3/s and is now 0.012709, 0.025505 and 0.010800 m3/s. MODFLOW 6 on the same mesh reads
  0.011417, 0.023888 and 0.009734 m3/s. Any score of a Boussinesq discharge changes with it.
- Boussinesq calibration trial on a mesh wider than its catchment. The old series was the domain
  sum, 2.0 times the published one on an island cut in half. It now equals the published one. With
  no buffer nothing moves.
- Boussinesq `budget/drain` and `budget/surface_excess` change sign, the size stays. The signed
  fields now close against the change of storage, to 3.7e-7 of the recharge on the steady period.
  They were off by 1.48 times the recharge.
- Boussinesq `residual` of `compare` on the island: -1.47e-05 m3/s before and -1.40e-09 after.
  Steady runs and the MODFLOW solvers do not move.
- A network output whose `time` falls on a stamp reads one period earlier. With
  `time = "2002-10-01"`, `distance_gap` goes from 86.32 to 79.08 m (-8.4 %), `D_optim` from 142.4
  to 139.2 m (-2.2 %) and the simulated network from 473 to 481 cells. A date inside a period does
  not move, so the date of the example, `2002-10-15`, gives the same numbers. On a daily run a
  date reads the day before.
- A window that ends on a stamp keeps one period fewer. `2001-01-01` to `2002-01-01` on a monthly
  run is 12 periods, it was 13. February 2000 reads 1 simulated value and 29 measurements, where
  it read 2 and 30.
- A tie on the cost in a last phase. On the shipped mesh, trials 13 and 14 tie at J = 0.8106 m
  and the promoted K goes from 8.058e-5 to 7.962e-5 m/s (-1.2 %). On 30 x 30 it goes from
  1.4678e-4 to 1.5034e-4 m/s (+2.4 %). A phase before the last does not move, so the K frozen by
  stage one does not move. A two-root bisection in a last phase now promotes the combined value
  that the report prints.
- The cut to the catchment under `heads`. On the shipped mesh and on 60 x 60 every K and cost is
  the same, and the heads examined fall from 154 to 29. On 30 x 30, J at the best trial goes from
  11.0 to 50.3 m. Under `crossing`, 3 mapped cells of 499 leave and J goes from 1.965 to 1.985 m.
- `catchment_mismatch` changes meaning on every run and enters no cost. On the shipped mesh of
  21 406 cells 0 becomes 0.37 %, and on 30 x 30 it becomes 11.0 %.
- The veto at 5 % now stops a run with no pin on a coarse mesh. It refuses Nancon on a grid of
  45 cells a side or fewer, on a Voronoi mesh of 400 m and on a grid of 120 a side.
- A file pinned on protocol 1.2 gives the same K, Sy, costs and arrays as the same file at the
  base with `observed_rasterization = "crossing"`, and 23 trials on 30 x 30. With `heads` written
  it takes 19.
- Protocol 1.3 options, for the record. `crossing` against the default `heads`: K +1.8 %, Sy -2.0 %,
  D_optim 114.0 against 104.1 m. `diagonal_neighbors = false` against D8: K -12.9 %, D_optim
  100.8 against 104.1 m, 662 mapped cells against 473. No default moves.
- Every cache key of a calibration changes once, so the trials of an earlier session are solved again.
- No number moves for MODFLOW 6 on example 04: the 55 arrays, 14640 rows of `timeseries`, 288 rows
  of `budgets` and the 11 scores (NSE 0.9345) are bit for bit the same. The comparator reads 213
  targets and no drift.
- No number moves for a run with no override, for a value override in the unit the file declares,
  or for the pinned MODFLOW release 23.0.

## [Earlier versions]

Every alpha and 0.x release is in
[Changes during the alphas](https://github.com/HydroModPy/HydroModPy/blob/main/docs/source/about/changes-during-the-alphas.md).
