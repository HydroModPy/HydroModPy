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

## Data

| File | Family | Role |
|---|---|---|
| `dem/DEM_armorican_massif.tif` | dem | regional 75 m DEM (covers the Nancon) |
| `recharge/recharge_custom_NANCON_*.csv` | recharge | observed monthly recharge (mm/d) |
| `runoff/runoff_custom_NANCON_*.csv` | runoff | monthly runoff, added to baseflow |

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

The tightest of the three is why `mf6_ats = true` is in the config. At
Sy = 0.001 the water table moves tens of metres inside a monthly stress
period and Newton cannot close it in one step; adaptive time stepping splits
only the months that fail, and leaves the other two specific yields untouched.

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
