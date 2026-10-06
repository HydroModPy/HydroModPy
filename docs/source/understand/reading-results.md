# Reading the results

This page is a reading guide to the main outputs of example 04 (the Nançon catchment, see
{doc}`index`). For each map or curve: what it shows, how to read it, the pitfalls, and what makes
it reliable or only indicative.

## Three rules before reading

1. **One map, one month.** Snapshot maps show a single month. In example 04, it is October 2002,
   the driest month of the series according to the comments in the configuration file: so the map
   shows the case where the network is at its smallest. A map of a wet month would show much more.
2. **A cell is 75 m wide.** A stream fills one cell in width, and we count cells, not meters of
   stream. The maps are read at the hillslope scale.
3. **Calibrating is not validating.** In a calibrated run, the simulated network and the discharge
   are what the calibration tried to reproduce ({ref}`two-stage-calibration`). Their agreement is
   expected. A validation compares with measurements that the calibration has not seen.

## In one table

Three reliability labels are used:

- **Numerical check**: an internal check of the computation, independent of the calibration.
- **Calibrated**: the agreement was sought by the calibration, so it is not independent evidence.
- **Indicative**: no field measurement was compared with this result in the example.

| Figure | Question | Label |
|---|---|---|
| {ref}`reading-depth` | How deep is the water table? | Indicative |
| {ref}`reading-seepage` | Where does water come out of the ground? | Indicative |
| {ref}`reading-network` | Does the model find the mapped streams? | Calibrated |
| {ref}`reading-persistence` | Which reaches dry up, and when? | Indicative |
| {ref}`reading-discharge` | Are the volume and the season of the discharge right? | Calibrated |
| {ref}`reading-budget` | How much water comes in and goes out? | Numerical check for the closure, indicative for the values |

(reading-depth)=
## Water table depth

```{figure} img/ex04_watertable_depth_map.png
:alt: Map of the depth of the water table below the ground surface, Nançon catchment, October 2002. Dark colors are water tables close to the ground, pale yellow ones are deep water tables.
:width: 75%

`watertable_depth_map`, October 2002. Legend in English: "Depth of the water table below land surface (m)".
```

**What the map shows.** The distance between the ground and the top of the water table, in meters,
for each cell. It is derived from the hydraulic head: ground elevation minus water table
elevation, set to zero when the water table reaches the ground.

**How to read it.** Dark blue: the water table is close to the ground, which is where water can
come out. Pale yellow: the water table is deep. The water table is close to the ground in the
valley bottoms and deep under the interfluves, which the map shows clearly.

**Pitfalls.**

- *The scale stops at the model thickness.* The modeled aquifer is 30 m thick
  ({toml}`domain.depth_model.thickness`). A pale yellow color means "at the bottom of the model",
  not "at exactly 30 m". On the run of this page, about 6.5% of the cells have, in October 2002,
  the water table within 0.5 m of the bottom (computed from the stored data of the run).
- *The pattern follows the relief by construction.* K is uniform and the drains are at the
  surface: a water table close to the ground in the valleys is the expected result of the setup,
  not a discovery.
- *This is a monthly mean state,* not the level of a given day.

**Reliability.** Indicative. Example 04 does not compare this map with piezometer levels.
The overall shape is consistent with the physics of the setup; the absolute depths are not
validated.

(reading-seepage)=
## Seepage cells

```{figure} img/ex04_seepage_map.png
:alt: Map of the seepage cells of the Nançon catchment, October 2002. The blue cells, isolated or in short lines, are those where the water table reaches the surface.
:width: 75%

`seepage_map`, October 2002. Legend in English: "seepage (110 cells)", "no seepage (11,378 cells)".
```

**What the map shows.** The cells where the water table reaches or exceeds the ground surface,
one by one, with no extension downstream. This is the raw state of the model: in October 2002,
110 cells of the catchment out of 11,488.

**How to read it.** Each blue cell is a point where water appears, a spring. These are not
streams: isolated cells or short lines of cells are normal. The pale cells outside the catchment
outline are in the model margin and are not counted.

**Pitfalls.**

- *This is not the network.* The simulated network extends the seepage cells downstream
  ({ref}`reading-network`). The two maps do not use the same definition of a cell that
  "seeps", so their cell counts cannot be compared.
- *The extent depends on K.* Example 04 observes this: when K varies, the simulated discharge does
  not tell the values apart, but the seepage area does. This is why the calibration of K relies on
  the network.
- *A cell is a yes or no state.* It says nothing about the flow that comes out.

**Reliability.** Indicative. The map is consistent with the computation, but no observation of a
spring or a seep is compared with it in the example.

(reading-network)=
## Comparison with the mapped network

```{figure} img/ex04_seepage_network_confusion_map.png
:alt: Map comparing the simulated network and the mapped network, Nançon catchment, October 2002. Dark blue: simulated and mapped; yellow: simulated only; red: mapped only.
:width: 75%

`seepage_network_confusion_map`, October 2002. Dark blue "valid" (228 cells), yellow "excess" (131), red "missing" (268).
```

**What the map shows.** Each cell belongs to a single class:

- *valid* (dark blue): the simulated network and the mapped network both pass through this cell;
- *excess* (yellow): only the model puts a stream there;
- *missing* (red): only the map puts a stream there;
- gray: no stream.

The mapped network is made of the permanent reaches of the BD TOPO, placed on the model grid. The
simulated network is the downstream extension of the seepage cells, following the slope of the
terrain ({doc}`what-it-computes`).

**How to read it.** A perfect agreement would be all dark blue: we look for little yellow and
little red at the same time. Here, the model misses a good share of the upstream reaches of the
map (red, at the edge of the network), and adds short segments (yellow) along the main axis. A
plain count of cells does not say whether a small gap comes from a good fit or from two errors
that cancel each other: the map shows it.

```{figure} img/ex04_downslope_distance_map.png
:alt: Map of the downslope distances between each cell of the simulated network and the mapped network, in four classes from 0 to more than 1000 m.
:width: 75%

`downslope_distance_map`, October 2002. Distance traveled downslope by each simulated cell before it reaches the mapped network: 0 to 75 m (229 cells), 75 to 500 m (119), 500 to 1000 m (15), more than 1000 m (0).
```

The second map no longer counts the cells that coincide: it measures how far each one is off. A
simulated cell that coincides with the mapped network is at 0 m. The four classes are those of the
reference paper (Abhervé et al., 2023). Its counts cannot be compared one to one with those of the
previous map: the two maps do not count exactly the same cells.

**Pitfalls.**

- *The mapped network holds only the permanent reaches.* An "excess" can be a real temporary
  stream that the map ignores, or an error of the model: the map does not settle it.
- *One month only,* October 2002.
- *The threshold matters.* A cell is counted as seepage if it returns more than 0.01% of its own
  recharge ({toml}`calibration.outputs.<name>.tau_specific_ratio`). Another threshold moves the
  three classes.
- *The mapped network is placed on the 75 m grid* with a transfer rule
  ({toml}`calibration.outputs.<name>.observed_rasterization`): a one-cell gap can come from the
  transfer and not from the model.

**Reliability.** Calibrated. K was adjusted so that this network looks like the map: a good
agreement is the goal reached, not an independent validation. The method itself is published and
peer reviewed (Abhervé et al., 2023).

(reading-persistence)=
## Flow persistence

```{figure} img/ex04_flow_persistence_map.png
:alt: Flow persistence map of the Nançon catchment over three years. Dark blue cells flow almost all the time, light blue ones part of the time.
:width: 75%

`flow_persistence_map`, January 2000 to December 2002. Color bar: "Timesteps flowing (%)". Title: 768 cells flow at least one month out of the 36.
```

**What the map shows.** For each cell, the share of the 36 months during which it flows. Dark
blue: almost always. Light blue: only in the wettest months. Gray: never.

```{figure} img/ex04_flow_intermittence_map.png
:alt: Map of perennial streams in blue, intermittent ones in orange and dry ones in gray, Nançon catchment, year 2002.
:width: 75%

`flow_intermittence_map`, year 2002. Blue "perennial" (336 cells), orange "intermittent" (126), gray "dry" (11,026).
```

The second map classes each cell over a single calendar year (2002): *perennial* if it flows all
12 months, *intermittent* if it flows some months, *dry* if it never flows. The stream heads are
orange: they dry up first.

**How to read it.** A cell "flows" if it is downstream of a seepage cell and carries at least
1 L/s of water coming from the aquifer ({toml}`calibration.outputs.<name>.extent.visible_flow`).
This is not the same meaning as on the seepage map, which counts only the exit points.

**Pitfalls.**

- *The timestep is monthly.* A reach that dries up for two weeks does not appear. "Intermittent"
  means: dry at least one month in the year.
- *The 1 L/s threshold is a convention.* The parameter documentation notes that no value is
  agreed on: thresholds from 1 to 3 L/s are used in the field, and Zanetti et al. (2024) use
  10 L/s for a simulated discharge. Another threshold changes the layout.
- *The three years include the first year,* 2000, which serves as the spin-up of the model. And
  three years say nothing about the year-to-year variability.
- *The year 2002 is the driest year of the series* according to the comment in the example. So the
  orange reaches are orange for a dry year.
- *The two maps do not cover the same duration* (36 months against 12): a cell can be dark on one
  and orange or gray on the other without any contradiction.

**Reliability.** Indicative. The only network compared with a map is the permanent network of
October. The example uses no field observation of dry reaches: the distinction between perennial
and intermittent is a model output, not verified.

(reading-discharge)=
## Simulated against observed discharge

```{figure} img/ex04_hydrograph_log_nse.png
:alt: Simulated and observed discharge at the Nançon outlet from 2000 to 2002, on a logarithmic axis. The scored period, 2001 and 2002, is shaded gray.
:width: 90%

`hydrograph_log_nse`. Blue line: total simulated discharge. Black dashes: discharge observed at the NANCON station. Gray area: scoring window, 24 of the 36 months. Logarithmic vertical axis, in m³/s.
```

**What the curve shows.** The monthly discharge at the outlet, simulated and measured at the
NANCON station (the daily measurement is averaged over each month). The simulated discharge is the
total: what leaves the aquifer through the drains, plus the runoff given as input data, since this
model has no river network. The figure itself states: "total discharge only: this run stores no
groundwater / surface split".

**How to read it.** The axis is logarithmic: low flows weigh as much as floods, and a gap of 0.1
to 0.2 m³/s is as visible as a gap of 1 to 2. This is intended: the calibration of Sy uses a
Nash-Sutcliffe efficiency computed on the logarithms
({toml}`calibration.protocol.transient_metric`), which gives weight to the recessions. The gray
area is the scoring window (2001 and 2002); 2000, the spin-up year, is not scored
({toml}`calibration.protocol.scoring_window`).

**The scores of this run.** The run metrics table covers the 36 months, spin-up included:
Nash-Sutcliffe efficiency (NSE) 0.68, volume bias (PBIAS) +20.5%, meaning a simulated discharge
lower than the measured one. Recomputed on the 2001 and 2002 window only, from the stored series,
the same measures give an NSE of about 0.94 and a bias of about +8%. The first year therefore
weighs a lot: the model clearly underestimates the discharge of 2000.

To put these numbers in context, Moriasi et al. (2007) propose, for catchment models at the
monthly timestep, to judge an agreement "satisfactory" from an NSE of 0.50 and a volume bias of
±25%, and "good" from 0.65 and ±15%. This scale comes from other catchment models: it gives a
reference, not a threshold specific to HydroModPy.

**Pitfalls.**

- *Runoff is an input.* It is given to the model ({toml}`data.runoff`): only the groundwater part
  is computed. A good agreement of the total does not prove that the groundwater part is right.
- *Sy was calibrated on this window.* A high NSE on 2001 and 2002 shows that the calibration
  worked, not that the model would predict another period.
- *A good discharge agreement does not tell K values apart.* Several K values give a similar
  discharge (see {ref}`reading-seepage`).
- *The monthly timestep* smooths the flood peaks and says nothing about the discharge of a given
  day.

**Reliability.** Calibrated. The season and the volume are well reproduced over the calibrated
period. The test that would count, a period or a catchment not used for calibration, is not in
the example.

(reading-budget)=
## The water budget

```{figure} img/ex04_flux_timeseries.png
:alt: Step curves of recharge, positive in blue, and drainage, negative in red, in m³/s, from 2000 to 2002, over the Nançon catchment.
:width: 90%

`flux_timeseries`. Blue: recharge, which enters the aquifer. Red: drainage, which leaves it. In m³/s, over the delineated catchment. Legend in English: "positive = into the aquifer".
```

**What the curve shows.** The two fluxes that cross the aquifer, month by month: recharge
(positive, it enters) and drainage through the drains (negative, it leaves). The change in storage
is not plotted: it is the difference between the two curves.

**How to read it.**

- *In winter, the aquifer fills up.* In January 2001, recharge reaches 3.1 m³/s for a drainage of
  1.7 m³/s: the difference goes into storage.
- *In summer, it slowly empties and feeds the streams.* From July to September 2002, recharge is
  almost zero (0.01 to 0.02 m³/s) and drainage continues at 0.25 to 0.29 m³/s. This is the
  *baseflow*: the water stored in winter that sustains the streams in dry periods.
- *The first month is in steady state,* so recharge and drainage are roughly equal there.

**Pitfalls.**

- *m³/s, not mm.* The figure can also be plotted as a water depth (option
  `units = "mm/period"` of {toml}`display.overrides`), which is easier to compare with rainfall.
- *The catchment and not the domain.* The model extends beyond the catchment
  ({toml}`geographic.catchment.buff_area`, 10% more area); the figure says "frame: the delineated
  catchment".
- *The `water_budget` bar chart has another use:* it adds up the flows stored at each timestep:
  it is a sum of flows, not a volume.

**Reliability.** Two things to tell apart. The *closure* of the budget is a numerical check: the
run reports a budget error of 0.00%, meaning that the solver conserves water. It does not say
that the model is right. The *values* are what was put in as input (the recharge) and what K and
Sy allow to store and release: they stay indicative as long as the recharge has not been compared
with another estimate.

## Where these figures come from

The eight figures are real outputs of the run
`nancon_intermittence_mf6_calibrated_transient_storage`, produced on 2026-09-29 by
`hmp run run_calibration.toml` with HydroModPy 2.0.0a4 (a run promoted from trial 8 of the
calibration). The files are copies from `runs/<run>/figures/` in the example 04 project. Two
remarks:

- they were drawn before the changes of 2026-10-05 on the relief and the network: in the current
  version, the mapped network is placed on the grid by the default `heads` rule, whereas this run
  used `crossing`. A new run can therefore give slightly different maps;
- the titles and the legends are in English.

To redraw a figure of an existing run at another date, from the project folder:

```bash
hmp viz show nancon_intermittence_mf6_calibrated_transient_storage seepage_map --time 2002-01-15
```

## Going further

- {doc}`what-it-computes`: what the model assumes and does not do.
- {doc}`glossary`: the terms used on this page.
- {doc}`../get-started/staircase/index`: rebuild this model step by step, in six files.
