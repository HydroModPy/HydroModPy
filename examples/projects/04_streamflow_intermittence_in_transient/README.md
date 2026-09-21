# 04 - Streamflow intermittence in transient

Nancon catchment (Brittany, EPSG:2154), extracted from the regional 75 m
DEM by outlet snapping. **Monthly transient** groundwater flow over three
years (2000-2002), solved with **MODFLOW 6**, forced by observed monthly
recharge and runoff.

The theme is intermittence: as recharge oscillates between wet winters and
dry summers, the watertable rises and falls, so the seepage cells and the
simulated active network expand and contract over the year.

## Run

```bash
hmp run examples/projects/04_streamflow_intermittence_in_transient/project.toml

# seasonal intermittence: seepage at the extreme months, via the Python API
python examples/projects/04_streamflow_intermittence_in_transient/run_manual.py

hmp viz gallery examples/projects/04_streamflow_intermittence_in_transient/project.toml

# the same model, with K and Sy read off the data instead of assumed
hmp calibrate examples/projects/04_streamflow_intermittence_in_transient/project.toml
```

Runtime: about 40 s for the run itself (36 timesteps, COMPLEX solver), on top
of the geographic step, which the burn makes the longer half of a first run
and which is then reused.

## Console output

A run prints one spinner line per pipeline step, turned into a checkmark and
a duration once the step is done, plus the warnings and the two or three lines
saying what was written. That is the `normal` level, and `[workflow] verbosity`
sets it per file: `quiet` keeps only warnings and errors, `verbose` adds every
INFO line the run emits, `debug` adds the DEBUG ones with their module and line
number. `hmp run -q | -v | --debug` overrides the file for one run, and
`HMP_VERBOSITY` overrides both for a whole shell. `step1_minimal.toml` carries
the same table as a comment, and nothing is lost by running quiet: the complete
DEBUG trace always goes to `.hmp/logs/hydromodpy_debug.log`.

## Variants

Three files here build directly on `project.toml` through `base_config`, each
changing one thing and inheriting the rest. None of them repeats the
catchment, the burn, the layer, the boundary conditions or the parameters, so
a correction to `project.toml` reaches all three. Tables merge key by key,
lists replace unless the key carries `__append`, and `<key>__delete = true`
drops an inherited key.

| File | What it changes | Run it with |
|---|---|---|
| `run_daily.toml` | daily step instead of monthly, and the daily forcing that makes the step mean something | `hmp run .../run_daily.toml` |
| `run_calibration.toml` | the workflow `hmp run` dispatches: calibration instead of simulation | `hmp run .../run_calibration.toml` |
| `run_calibration_by_hand.toml` | the same two stages, declared rather than named, and stage two scored on the network as well as the gauge | `hmp calibrate .../run_calibration_by_hand.toml` |

```bash
hmp run examples/projects/04_streamflow_intermittence_in_transient/run_daily.toml
hmp run examples/projects/04_streamflow_intermittence_in_transient/run_calibration.toml
hmp run examples/projects/04_streamflow_intermittence_in_transient/run_calibration_by_hand.toml
```

`run_daily.toml` is four changes, and three of them follow from the first.
`step_value = "1 day"` gives 1096 stress periods instead of 36. The monthly
recharge and runoff are replaced by the daily areal means of the same
catchment, declared as the station `NANCON_REA`: a daily step reading a
monthly mean sees no storm, only a staircase. `duration_curve` and `recession`
are appended to the eight figures, because the 36 monthly points that made
both unreadable are now 1096. And the two `timestep` overrides move from 33 to
1018, since a step index names a different instant once the step changes:
15 October 2002 is step 1019 of 1096 here and was step 34 of 36 there.

`run_calibration.toml` is two declarations, `[workflow] mode = "calibration"`
and a name of its own. The method itself is not there: it is the `[calibration]`
block of `project.toml`, which `hmp calibrate project.toml` already runs. What
the variant adds is that a plain `hmp run` dispatches it, and that the
calibrated result and the assumed-values result sit side by side in the
catalog instead of one replacing the other.

`run_calibration_by_hand.toml` runs the same two stages with the protocol name
deleted and the stages written out, which is the subject of its own section
below.

## Staircase

`run_daily.toml` and `run_calibration.toml` each swap one axis of the model
above. The five `step*.toml` files are a different shape: a reading order,
not five alternatives, each one adding exactly what the file before it
lacked, from the shortest config that runs to the full declarative pipeline.

| File | Run | `base_config` | What it changes |
|---|---|---|---|
| `step1_minimal.toml` | `nancon_step1_minimal` | none | the shortest file that runs to completion: steady state, local DEM, homogeneous K, drainage boundary |
| `step2_local_data.toml` | `nancon_step2_local` | `step1_minimal.toml` | the mapped stream network and the burn, from local files |
| `step3_api_data.toml` | `nancon_step3_api` | `step1_minimal.toml` | the same model as step2, with hydrography from the BD TOPAGE API and hydrometry from Hub'Eau instead of local files |
| `step4_transient.toml` | `nancon_step4_transient` | `step2_local_data.toml` | monthly transient 2000-2002 with storage and the observed recharge and runoff forcing, still with no calibration |
| `step5_export.toml` | `nancon_step5_export` | `step4_transient.toml` | a declarative `[export]` writing four GeoTIFF rasters, a time-series CSV and a NetCDF, plus a `[display]` figure list |

```bash
hmp run examples/projects/04_streamflow_intermittence_in_transient/step1_minimal.toml
hmp run examples/projects/04_streamflow_intermittence_in_transient/step2_local_data.toml
hmp run examples/projects/04_streamflow_intermittence_in_transient/step3_api_data.toml
hmp run examples/projects/04_streamflow_intermittence_in_transient/step4_transient.toml
hmp run examples/projects/04_streamflow_intermittence_in_transient/step5_export.toml
```

step3 is not a child of step2: both declare `base_config = "step1_minimal.toml"`,
so both build the same model from the same root. What differs between them is
where the hydrography and hydrometry come from, the BD TOPAGE API and Hub'Eau
instead of a local file, which is a provenance question and not a modeling
one. Read step2 and step3 side by side, not one after the other.

step5 is the fourth file in the chain that starts at step1: step1, step2,
step4, step5, each holding only what changes from the one before it. Four
levels is the point, not an accident of where the export happened to land:
a correction to `step1_minimal.toml` reaches every step below it, the same
guarantee `project.toml` gives `run_daily.toml` and `run_calibration.toml`
above, and `[export]` gets to be one more level instead of one more file to
repeat the other four in.

## Data

| File | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | regional 75 m DEM (covers the Nancon) |
| `recharge/recharge_custom_NANCON_*.csv` | recharge | observed monthly recharge (mm/d) |
| `runoff/runoff_custom_NANCON_*.csv` | runoff | monthly runoff, added to baseflow |
| `recharge/recharge_custom_NANCON_REA_*.csv` | recharge | daily areal mean, 1990-2020, read by `run_daily.toml` |
| `runoff/runoff_custom_NANCON_REA_*.csv` | runoff | the same, daily |

## Intermittence

At the values in the config, the seeping network goes from 364 cells in
October 2002, the driest month of the record, to 1 399 in January 2001, the
wettest: about **1 000 cells switch on and off**. Those are the intermittent
reaches, and the core that never stops is the perennial network. Counted on
the drained network rather than on the seepage cells, 1 567 cells carried
flow at some point over the three years and only 381 carried it at every
timestep of 2002.

`run_manual.py` counts them month by month and renders `seepage_map` for the
wettest and the driest month (same figure, two `timestep` values).

## Calibrating it

Which reaches dry up in August is a statement about `K` and `Sy`, so the maps
above mean what they say only once the two have been fitted. The same file
carries the calibration, as the named protocol
`matching_hydrographic_network` (Abherve et al., 2023,
doi:10.5194/hess-27-3221-2023), in two stages:

| stage | regime | moves | against |
|---|---|---|---|
| `steady_conductivity` | steady, mean recharge over the record | `K` | the extent of the mapped network, by bisection on the signed gap |
| `transient_storage` | monthly transient, `K` frozen | `Sy` | the gauged hydrograph, on `nse_log` |

The order is the method, not a convenience: a steady solve carries no storage,
so the first stage is blind to it, which is what makes the conductivity
identifiable there without any discharge record at all.

The budget is 18 single-period steady solves at most for the first stage, a
seven-point logarithmic sweep across the four decades of the search followed by
the bisection on the one crossing it finds, and up to 30 of the 36-month
transient run for the second. Count it in solves rather than in minutes: it is
the run above, repeated.

```bash
hmp calibrate .../project.toml --check         # every problem at once, no solve
hmp calibrate .../project.toml --list-phases   # the assembly the protocol wrote
hmp calibrate .../project.toml                 # both stages, in order
```

### Named, or written out

The protocol name is a shorthand for an ordinary two-stage calibration, and
`--list-phases` prints what it expands to. Nothing in the engine knows the
name afterwards: the stages, the criteria and the freezing are the same
`[[calibration.phases]]` any file may declare, and the four calibration
figures read the phase records rather than the protocol.

`run_calibration_by_hand.toml` is that expansion typed out. Same order, same
criteria, same budgets, with `protocol__delete = true` to drop the inherited
name, which a file may not carry beside stages of its own:

| | `project.toml` | `run_calibration_by_hand.toml` |
|---|---|---|
| stage one | `steady_conductivity`, bisection on K | the same, written out |
| stage two | `transient_storage`, `nse_log` on the gauge | the same, plus the network extent |
| what carries K over | `depends_on` + `freeze_on_success`, written for you | the same pair, written out |
| what the run records | the method, its version, its deviations from the paper | what the file declares, and no citation |

Read the long form when the method has to deviate, which is the one thing the
name cannot do. Here stage two is scored on the hydrograph **and** on the
agreement with the mapped network, as two weighted objective blocks. The
published method scores it on the hydrograph alone, so the protocol will not
write that, and three things had to be said explicitly to get it:

- **the gauge becomes an output.** The single-metric route, `variable` plus
  `objective`, declares none and cannot be combined with a block. The gauge is
  then `support = "point"` with `observes = "NANCON"`, which reads what the
  single-metric route reads, the station's cell where the loader placed one
  and the whole-catchment series where it did not, and adds the runoff to the
  simulated baseflow either way. The same target as `support = "boundary"` on
  the drain would score the drain budget, which is baseflow without runoff.
- **the spin-up year is dropped in samples, not in dates.** A `scoring_window`
  cuts a record on its dates and the network block of the same stage is scored
  on two distances that carry none, so declaring one there is refused.
  `warmup = 12` on the hydrograph block is the same twelve months.
- **a network output in a transient run is read at the last stress period**,
  whatever its `time` says. The second block therefore compares the December
  2002 network to the mapped one, which is sensitive to `Sy` and is not an
  average over the record. Scoring the seasonal extension itself is Abherve et
  al. (2024), doi:10.1002/hyp.15167, and needs an intermittence record this
  window predates.

The two costs are in different units, metres against an efficiency, and
nothing normalises them: `weight` is the exchange rate and the file states the
arithmetic it chose. Both terms are reported per trial, so what the weight
bought is readable rather than assumed.

What it produced here, in 15 steady solves and 16 monthly runs: `K` =
9.763e-05 m/s at a signed gap of 2.7 m, then `Sy` = 0.083 at a December gap of
15.2 m and an NSElog of 0.810. Over those sixteen trials the network term
weighed 0.15 to 0.24 and the hydrograph term 0.19 to 0.27, so neither rode
along: they moved the search together. The gap itself took four distinct
values, a network retracting by whole cells, which is what sets the region and
leaves the hydrograph the fine work inside it.

Three premises are written into the config rather than assumed, and each one
silently returns a number when it is wrong: `[geographic.enforce_streams]`
burns the mapped network into the routing surface, so the criterion measures
hydrogeology and not a disagreement between two datasets;
`[flow.bc.drainage]` writes no conductance, so it is derived from `K`, which keeps it proportional to
`K`, which is what makes the ratio `K/R` the calibrated quantity; and
`[simulation.results.derived] release_flux = true` is the per-cell seepage the
criterion reads. See
`docs/source/user_guide/workflows/stream-network-calibration.rst` for the
diagnostics each trial publishes, and publish the ratio `K/R` rather than the
conductivity, dividing by the `R_mean_m_s` every trial reports.

## Figures

Eight, and each answers a question the others do not. A run that draws
twenty is not more informative than one that draws eight: it just leaves the
reader to find out which two of five hydrograph panels carry the argument.
What was dropped is listed below with the reason, and any of them still
renders on demand:

```bash
hmp viz show @last duration_curve --workspace examples/projects/04_streamflow_intermittence_in_transient
```

| Figure | What it shows |
|---|---|
| `watershed_id_card` | the catchment, its topography and the run's identity |
| `flux_timeseries` | recharge in and drainage out, month by month |
| `hydrograph_log_nse` | simulated against the NANCON gauge, on the log axis the recessions are read on |
| `cross_section` | the water table under the interfluves, south to north |
| `seepage_map` | the seeping cells in October 2002, the driest month |
| `flow_persistence_map` | the share of the three years each cell carried flow |
| `flow_intermittence_map` | perennial, intermittent and dry cells over 2002 |
| `seepage_network_confusion_map` | simulated against mapped: valid, excess, missing |

Four more are declared and apply only to a run the calibration promoted:
`downslope_distance_crossing`, `bisection_bracket_trace`,
`parameter_cost_profile` and `matching_hydrographic_network_card`. On a plain
`hmp run` they skip themselves and say why.

Every figure that draws one instant draws the same instant, step 34 of 36,
which is October 2002. The default, the last timestep, is a December with a
nearly full network, and a map of intermittence taken at the wettest moment
of the year shows none.

| Dropped | Why |
|---|---|
| `hydrograph` | the same simulated series, without the gauge |
| `hydrograph_sim_obs` | the same two series on a linear axis, where an etiage is a flat line |
| `scatter_one_to_one`, `residuals` | the same 36 residuals as the hydrograph, folded two more ways |
| `duration_curve` | 36 monthly points, and the simulated series alone |
| `seasonal_boxplot` | a box per month over three values |
| `water_budget` | a sum of timestep rates, which is not a volume |
| `mass_balance_error` | flat at 0 % here: a sentence, not a figure |
| `mesh_map` | the same topography as the id card, under a grid |
| `piezometric_map` | the elevation `cross_section` shows in section |
| `watertable_depth_map` | `seepage_map` is this map at the threshold that matters |
| `simulated_active_network` | the perennial class of `flow_intermittence_map` |
| `simulated_active_network_reference_overlay` | `seepage_network_confusion_map` names the three cases instead of overlaying two layers |
| `hydrographic_network_reference` | the mapped network, already under the confusion map |
| `downslope_distance_map` | the calibration criterion, and `03` is where it is explained |

## How intermittence is read

Three ways, from the coarsest to the finest. `flow_persistence_map` collapses
the whole record onto one share per cell. `flow_intermittence_map` classifies
each cell inside one calendar year, which separates a reach that stops every
summer from one that only stopped in the dry year. `run_manual.py` drives the
specific-yield sweep and plots the seeping share month by month, which is the
same phenomenon read as a time series rather than as a map.

The legacy `persistency_index` and `intermittency_monthly` rasters are the
first two. Both read `accumulation_flux`, not a field of their own.

**The two maps do not cover the same window, and their titles say so.**
Persistence answers over 2000-01 to 2002-12, intermittence classifies inside
2002-01 to 2002-12. 787 cells carried flow during the wet years and none at
all in 2002: they are pale blue on one map and grey on the other, which is a
dry year and not a disagreement. To read the two side by side over the same
window, pass the same cycle to both:

```python
hmp.figure(run, "flow_persistence_map")                # the whole record
hmp.figure(run, "flow_persistence_map", cycle="2002")  # the year classified
```


## What the legacy example did that this one now does again

The legacy script was a sweep, not a single run: three specific yields, two
decades apart, because Sy is what decides whether a catchment remembers its
winter. `run_manual.py` drives that sweep and draws the two figures only a
script can give, the seepage share month by month and the three hydrographs
against the gauge.

```bash
python examples/projects/04_streamflow_intermittence_in_transient/run_manual.py
```

| Sy | what it stands for |
|---|---|
| 0.001 | a fissured bedrock that empties before summer |
| 0.05 | a normal weathered mantle |
| 0.3 | a store so loose it barely drains |

The tightest of the three converges without `mf6_ats`: the key defaults to
`false` and nothing in this example turns it on. At Sy = 0.001 the water
table still moves tens of metres inside a monthly stress period, and what
closes it is the default MODFLOW 6 Newton-Raphson formulation with
under-relaxation (`mf6_newton` and `mf6_newton_under_relaxation`, both on by
default), not adaptive time stepping.

The gauge itself is now declared too: `[data.hydrometry]` loads the daily
discharge at the Nancon station, which `hydrograph_log_nse` compares the
simulated baseflow to, and which the run scores with eleven fit metrics of its
own. The other four comparison figures read those same 36 pairs, so the gallery
keeps one and leaves the rest to `hmp viz show`.

The ONDE observers who record whether a site still flows are not declared here:
their record on this catchment starts in 2012, ten years after the window this
example simulates.

Two library fixes came with this: `scatter_one_to_one` and `residuals` looked
for observations at the *simulated* station, the `_catchment` pseudo-station,
where a gauge never writes. They now find the observing station, or say which
ones to choose between. Both render on demand, out of the gallery.
