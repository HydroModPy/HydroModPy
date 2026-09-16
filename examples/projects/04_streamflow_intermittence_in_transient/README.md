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

`run_manual.py` counts seepage cells for each month. Over this period, the
wet network goes from ~450 cells (dry month) to ~1670 (wet month): about
**1200 cells switch on and off** over time. These are the intermittent
reaches; the core that stays active throughout is the perennial network.
The script renders `seepage_map` for the wettest and the driest month (same
figure, two `timestep` values).

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
`[flow.bc.drainage] value = 0.0` keeps the drain conductance proportional to
`K`, which is what makes the ratio `K/R` the calibrated quantity; and
`[simulation.results.derived] release_flux = true` is the per-cell seepage the
criterion reads. See
`docs/source/user_guide/workflows/stream-network-calibration.rst` for the
diagnostics each trial publishes, and publish the ratio `K/R` rather than the
conductivity, dividing by the `R_mean_m_s` every trial reports.

## Figures

| Figure | What it shows |
|---|---|
| `watershed_id_card` | catchment identity card |
| `mesh_map` | solver grid |
| `piezometric_map` | watertable elevation (last timestep) |
| `watertable_depth_map` | watertable depth + seepage |
| `seepage_map` | seepage zones (time-varying) |
| `flow_persistence_map` | share of the run each cell carried flow |
| `flow_intermittence_map` | perennial, intermittent and dry cells over one year |
| `simulated_active_network` | active draining network |
| `simulated_active_network_reference_overlay` | the same, over the mapped network |
| `hydrographic_network_reference` | the mapped stream network |
| `hydrograph` | simulated discharge over time |
| `hydrograph_sim_obs` | simulated against the gauged discharge |
| `scatter_one_to_one` | simulated against observed, one point per timestep |
| `residuals` | simulated minus observed over time |
| `duration_curve` | flow duration, simulated and observed |
| `seasonal_boxplot` | discharge spread month by month |
| `flux_timeseries` | water budget per timestep |
| `cross_section` | topography / watertable cross section |
| `water_budget` | cumulative budget per component |
| `mass_balance_error` | percent closure error per timestep |

## How intermittence is read

Three ways, from the coarsest to the finest. `flow_persistence_map` collapses
the whole record onto one share per cell. `flow_intermittence_map` classifies
each cell inside one calendar year, which separates a reach that stops every
summer from one that only stopped in the dry year. `run_manual.py` drives the
specific-yield sweep and plots the seeping share month by month, which is the
same phenomenon read as a time series rather than as a map.

The legacy `persistency_index` and `intermittency_monthly` rasters are the
first two. Both read `accumulation_flux`, not a field of their own.


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
discharge at the Nancon station, which `hydrograph_sim_obs`, `scatter_one_to_one`
and `residuals` compare the simulated baseflow to, and which the run scores with
eleven fit metrics of its own.

The ONDE observers who record whether a site still flows are not declared here:
their record on this catchment starts in 2012, ten years after the window this
example simulates.

Two library fixes came with this: `scatter_one_to_one` and `residuals` looked
for observations at the *simulated* station, the `_catchment` pseudo-station,
where a gauge never writes. They now find the observing station, or say which
ones to choose between.
