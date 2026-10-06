# Rain and evaporation: the forcing

Rain falls and the air asks for water every day. The aquifer model does not see days: it
sees stress periods, and for each period one rate per cell. This page gives the rules that
turn daily series and daily grids into those rates, the terms the solver builds from them,
and the matching rule that puts the outputs back on the same periods. It does not say how
to set up a run: for that, see {doc}`../guides/recharge` and
{doc}`../guides/time-and-initial-state`.

:::{note}
**Scope.** The alignment rules (sections 1 to 5) are common to the three flow solvers.
The period 0 rule of section 6 differs between MODFLOW 6 on one side and MODFLOW-NWT and
Boussinesq on the other. The daily soil reservoir that turns rain and ETP into recharge has
its own page: {doc}`soil-reservoir`. Here it only appears as one more source of daily
grids (section 10).
:::

## The path, in the order of the code

| Step | What happens | Function |
|---|---|---|
| 1 | The window is cut into stress periods | `build_simulation_time_boundaries` |
| 2 | Stations or grids give one series per variable | `extract_homogeneous_series`, `resolve_forcing` |
| 3 | mm/day becomes m/s | `factor_to_m_per_s` |
| 4 | A series gets one value per period | `align_forcing_series_to_simulation_window` |
| 5 | A grid gets one array per period | `discretize_from_xarray` |
| 6 | Period 0 may take a representative value | `series_payload_value`, `recharge_to_spd` |
| 7 | Negative recharge is split into recharge and ETP | `route_negative_recharge_to_evt` |
| 8 | The solver packages receive the rates | RCH, EVT (the MODFLOW 6 builders) |
| 9 | Runoff and the soil outputs go where they belong | `apply_runoff_to_sfr_networks` and the other binders |
| 10 | Outputs are read back on the periods | `period_mean_on_index`, `period_point_on_index` |

The binders of steps 2 to 9 run once per run, in this order:
`apply_recharge_load_result_to_flow`, `apply_etp_load_result_to_flow`, the lake flux
binders, `apply_runoff_to_sfr_networks`, `apply_lake_meteo_forcings_to_flow`
(`hydromodpy/workflow/steps/data.py`, function `apply_structural_updates_from_data`).

## Notation

$i$ is a stress period, $N$ the number of periods. $j$ is one sample of a series, taken at
time $t_j$. Rates are volumes per area and per time, so they are lengths per time.

| Symbol | Meaning | Unit | Read from |
|---|---|---|---|
| $s$, $e$ | first and last day of the run, the last day included | date | {toml}`start_datetime\|simulation.time.start_datetime`, {toml}`end_datetime\|simulation.time.end_datetime` |
| $\Delta$ | length of one stress period | month, day, hour | {toml}`step_value\|simulation.time.step_value`, {toml}`step_unit\|simulation.time.step_unit` |
| $b_i$ | edge $i$ of the periods, $i = 0 \dots N$ | date | state, not a field |
| $x_j$ | one sample of a daily series | mm/day | {toml}`data.precipitation`, {toml}`data.etp`, {toml}`data.recharge`, {toml}`data.runoff` |
| $\bar x_i$ | the value period $i$ gets | mm/day, then m/s | state, not a field |
| $c$ | factor from mm/day to m/s | m/s per mm/day | not a field: $1/(1000 \cdot 86400)$ |
| $R_i$, $E_i$ | recharge and ETP rate of period $i$ | m/s | {toml}`values\|flow.sinks_sources.recharge.values`, {toml}`values\|flow.sinks_sources.etp.values` |
| $F$ | value that period 0 takes | m/s | {toml}`first_clim\|flow.sinks_sources.recharge.first_clim` |
| $D_i$ | climatic deficit routed to EVT | m/s | {toml}`negative_to_evt\|flow.sinks_sources.recharge.negative_to_evt` |
| $d_\mathrm{ext}$ | extinction depth of the routed deficit | m | {toml}`evt_extinction_depth\|modflow6.process_specific.evt_extinction_depth` |
| $A_c$ | area of the catchment | m² | the delineated catchment, not a field |

The sign convention is the one of the packages. A positive recharge adds water to the
aquifer. A positive ETP removes it.

## 1. Cut the window into periods

The edges start at $b_0 = s$ and advance by one step $\Delta$ until the first edge that
reaches the end of the last day:

$$
b_{k+1} = b_k + \Delta,
\qquad
b_N = e + 1\ \text{day}\quad(e + 1\ \text{hour for an hourly step}).
$$

Period $i$ is the half-open interval $[b_i, b_{i+1})$. The end date is part of the run, so
the last edge is the day after it. A step that does not land on that edge is refused: the
error says that the window "is not aligned with step_value/step_unit". The code is
`_build_time_boundaries` in `hydromodpy/core/time/window.py`.

## 2. One series per variable

The data layer hands a variable over as station records or as grids. Two rules reduce them
to the shape the flow needs. They live in `hydromodpy/physics/forcing/forcing_bridge.py`.

**Stations.** Several stations are averaged at each time stamp, with equal weights
(`extract_homogeneous_series`). A single station is used as it is.

**Spatial mode.** {toml}`spatial_mode|flow.sinks_sources.recharge.spatial_mode` decides
what stays a series and what stays a grid (`resolve_forcing`):

| Mode | Stations | Grids |
|---|---|---|
| `auto` | one series | kept as a grid |
| `homogeneous` | one series | reduced to one spatial mean per time stamp |
| `heterogeneous` | placed on the cells if they have coordinates, else one series | kept as a grid |

Under `auto`, station records that have coordinates become a grid only when no series can
be built from them. A grid is not resampled when it is loaded: it is placed on the cells of
the solver mesh later, once the mesh exists, by the method of
{toml}`interpolation_method|flow.sinks_sources.recharge.interpolation_method`
(`nearest`, `linear` or `idw`).

The ETP has the same two keys, {toml}`spatial_mode|flow.sinks_sources.etp.spatial_mode` and
{toml}`interpolation_method|flow.sinks_sources.etp.interpolation_method`.

## 3. Units

Every data manager hands rain, ETP, recharge and runoff over in mm/day. The binders convert
with the fixed factor $c$, whatever {toml}`units|flow.sinks_sources.recharge.units` says:

$$
c = \frac{1}{1000 \times 86400} = 1.157 \times 10^{-8}\ \mathrm{m/s}
\ \text{per mm/day}.
$$

`units` is read for a rate written in the file: {toml}`values|flow.sinks_sources.recharge.values`
and a numeric {toml}`first_clim|flow.sinks_sources.recharge.first_clim` are converted from
`units` to m/s when the flow is built (`Flow._normalize_recharge_config` and
`_flux_payload_update` in `hydromodpy/physics/flow/flow.py`). A loaded series is not
affected (`apply_recharge_load_result_to_flow`, in
`hydromodpy/physics/flow/structure_binders.py`).

A sample is a rate. The code averages samples and never sums them. A monthly total in mm
has to be turned into mm/day before it is given to the model.

## 4. A series gets one value per period

`align_forcing_series_to_simulation_window` (`hydromodpy/physics/forcing/time_alignment.py`)
gives period $i$ the mean of the samples stamped inside it. A sample belongs to the period
that contains its time stamp. If the period holds no sample, it takes the last sample
before its end:

$$
\bar x_i =
\begin{cases}
\dfrac{1}{n_i} \displaystyle\sum_{t_j \in [b_i,\, b_{i+1})} x_j & \text{if } n_i > 0,\\[2ex]
x_{j^*},\ \ j^* = \max\{\, j : t_j < b_{i+1} \,\} & \text{if } n_i = 0.
\end{cases}
$$

Here $n_i$ is the number of samples in period $i$. The mean has equal weights, so it is
the time mean only for a series with one sample per equal step. If no sample exists before
the end of the period, the run stops with "has no value available before simulation period
ending at".

Two cases, on a window from 2000-01-01 to 2000-03-31 with a monthly step. The values come
from calls of `aggregate_forcing_series`. A series whose only sample is on 1 February
stops the run, because January has no sample before its end.

| The series | January | February | March |
|---|---|---|---|
| Daily, 1 mm/day in January, 3 in February, 5 in March | 1 | 3 | 5 |
| Two samples: 2 on 1 January, 6 on 1 March | 2 | 2 (carried) | 6 |

The carry is silent. A record that ends before the window does is extended with its last
value, and the coverage check of {toml}`coverage_policy|simulation.time.coverage_policy`
does not see it, because it runs on the series after the alignment (see the limits).

### The `last` rule

A forcing declared by a CSV file under a well, a lake, a stream network or a boundary
condition has an `aggregate` key, for example
{toml}`flow.sinks_sources.lakes.<name>.rainfall.aggregate`. Its value `"mean"` is the rule
above. Its value `"last"` holds the series like a state. Period $i$ takes the latest
sample at or before its start:

$$
\bar x_i = x_{j}, \qquad j = \max\{\, j : t_j \le b_i \,\}.
$$

This is `aggregate_forcing_series` in `hydromodpy/physics/flow/time_forcing.py`. The
rain, ETP, recharge and runoff of the data layer have no such key: they always take the mean.

## 5. A grid gets one array per period

A gridded forcing with a time axis is averaged in time first, cell of the source grid by
cell, over the slices stamped in $[b_i, b_{i+1})$. The mean array is then placed on the
cells of the solver mesh by the interpolation method of section 2, and multiplied by $c$
(`discretize_from_xarray`, in
`hydromodpy/spatial/mesh/cartesian_grid/_sgrid_field_xarray.py`). A grid without a time axis
gives the same array to every period.

A period with no slice is not carried forward here. The rule follows
{toml}`coverage_policy|simulation.time.coverage_policy`:

| Policy | A period with no slice |
|---|---|
| `error` | the run stops |
| `warn` | a warning, and the slice nearest to the start of the period is used |
| `ignore` | the slice nearest to the start of the period is used, with no message |

## 6. Period 0 and `first_clim`

{toml}`first_clim|flow.sinks_sources.recharge.first_clim` replaces the value of one period
with a representative value. It takes one of three forms:

| Value | $F$ |
|---|---|
| `"mean"` | $\dfrac{1}{N}\displaystyle\sum_{i=0}^{N-1} R_i$ |
| `"first"` | $R_0$ |
| a number | that number, in `units` |

The mean has equal weights, one per period, whatever the length of the period. The ETP has
its own key, {toml}`first_clim|flow.sinks_sources.etp.first_clim`, with the same three
forms.

The periods that $F$ replaces depend on the solver:

| Solver | Replaced period | Code |
|---|---|---|
| MODFLOW 6, one value per period | every steady period, which is period 0 when {toml}`first_period_steady\|flow.first_period_steady` is true | `recharge_to_spd` |
| MODFLOW 6, a grid per period | none: `first_clim` is not read, and a steady period keeps its own grid. When the grids hold a negative value and it is routed to EVT, a steady period takes the mean of all periods instead (section 7) | `resolve_deferred_heterogeneous_recharge` |
| MODFLOW-NWT and Boussinesq | period 0, steady or not, when the run is transient and has more than one period | `assemble_rch_data`, `apply_first_clim_2d`, `recharge_period_series` |

For a grid per period, MODFLOW-NWT and Boussinesq take the mean of all the periods when the
regime is steady or the run has one period. A transient MODFLOW 6 run whose first period is
transient ignores a numeric `first_clim`.

Four periods with rates 2, 4, 9 and 1 (the numbers are arbitrary), from calls of
`recharge_to_spd`:

| MODFLOW 6 | `"mean"` | `"first"` | a number, 7 |
|---|---|---|---|
| First period steady: period 0 | 4 | 2 | 7 |
| First period transient: period 0 | 2 | 2 | 2 |

Periods 1 to 3 keep 4, 9 and 1 in both rows.

A run that starts from a steady state of its own ({toml}`flow.ic`, type `steady_state`)
does not use this key for that solve. The auxiliary steady model is built with `first_clim`
set to `"mean"`, or with the prescribed rate in its place
(`apply_steady_state_initial_condition_strategy` in
`hydromodpy/solver/steady_initial_conditions.py`). The guide
{doc}`../guides/time-and-initial-state` describes the starting states.

```toml
base_config = "step4_transient.toml"

[flow.sinks_sources.recharge]
first_clim = "first"
```

## 7. Negative recharge goes to the ETP package

A net recharge can be negative: a series of rain minus ETP, for example. With
{toml}`negative_to_evt|flow.sinks_sources.recharge.negative_to_evt` true, the
two parts are separated:

$$
R^{+}_i = \max(R_i,\, 0), \qquad D_i = \max(-R_i,\, 0).
$$

The recharge package receives $R^{+}_i$. The EVT package receives $D_i$. On a steady
period, with `first_clim` at `"mean"`, both are the means over all the periods, not the
parts of the mean:

$$
R^{+}_\mathrm{steady} = \frac{1}{N}\sum_i R^{+}_i,
\qquad
D_\mathrm{steady} = \frac{1}{N}\sum_i D_i,
$$

so the net rate of that period, $R^{+}_\mathrm{steady} - D_\mathrm{steady}$, is the mean of
the net rates. A transient period keeps its own parts. The code is
`route_negative_recharge_to_evt` (`hydromodpy/solver/modflow_common/recharge_evt_routing.py`),
shared by MODFLOW 6 and MODFLOW-NWT for grids; the MODFLOW 6 series path splits the
series itself in `extract_evt_payload`, by the same rule.

The order matters. For a series, the clipping happens first, and the `first_clim` of
section 6 then acts on $R^{+}$ (`extract_evt_payload`, then `recharge_to_spd`, in
`hydromodpy/solver/modflow6/builders/recharge.py`). So `"mean"` gives the mean of the
clipped series, which is the $R^{+}_\mathrm{steady}$ above.

Under MODFLOW 6 the routed deficit is an EVT rate from the top of each cell. It falls
linearly to zero at the depth $d_\mathrm{ext}$ below it, and it is not drawn in the cells
of the ocean boundary, of the `stream` imposed-head boundary or under a lake
(`_evt_keep_mask_and_top_layer`, called by `build_evt_array_stress_period_data`). With {toml}`negative_to_evt|flow.sinks_sources.recharge.negative_to_evt`
set to false, a negative rate in the file is refused when it is read.

## 8. What the solver does with $R$ and $E$

Both rates are fluxes per unit of area. The recharge package multiplies $R_i$ by the area
of the cell and adds that volume per time to the cell (the RCH package of MODFLOW,
{cite}`harbaugh2005`; the RCHA package of MODFLOW 6, {cite}`langevin2017`). The flow
rates are constant during a stress period.

The ETP package removes at most the rate $E$, in full when the head is at or above an EVT
surface and linearly less down to the extinction depth below it (the EVT package,
{cite}`harbaugh2005`). Which rate reaches it depends on the solver:

- **MODFLOW-NWT.** The loaded ETP drives the EVT package, with the deficit of section 7.
- **MODFLOW 6 without a soil reservoir.** The loaded ETP is ignored. The run logs a
  warning if `"etp"` is in {toml}`flow.active_sinks_sources`. Only the deficit of section 7
  reaches an EVT package.
- **MODFLOW 6 with a soil reservoir.** The ETP the soil could not meet reaches the EVT
  package.
- **Boussinesq.** `"etp"` in {toml}`flow.active_sinks_sources` is rejected.

The law, the surface and the extinction depth of each case are on {doc}`exits`.

Under MODFLOW 6, the recharge is set to zero on lake cells (`mask_recharge_on_lake_cells`).
The lake gets its own rain through the lake package, and MODFLOW 6 would otherwise move the
recharge of an inactive cell to the active cell below it.

## 9. Runoff is not recharge

The runoff of the data layer, {toml}`data.runoff`, never enters the aquifer as a diffuse
term. It enters the model, when it enters at all, as a volume per time:

$$
Q^\mathrm{ro}_i = c\,\bar q_i\,A_c ,
$$

where $\bar q_i$ is the watershed mean of the runoff in mm/day, aligned by the rule of
section 4, and $A_c$ the catchment area. `_watershed_mean_rates` takes that mean with the
`homogeneous` mode of section 2.

- With an active stream network, $Q^\mathrm{ro}_i$ is shared among the reaches by their
  length and routed downstream (`apply_runoff_to_sfr_networks`). A forcing already written
  in the file wins over the loaded series. The lake binder then skips its direct feed, so
  the same water is not counted twice (`sfr_routes_catchment_runoff`).
- Without a network, a declared lake receives $Q^\mathrm{ro}_i$ directly
  (`apply_lake_meteo_forcings_to_flow`).
- Without either, the runoff stays outside the flow. It remains a loaded series.

A lake also gets the watershed mean of the loaded rain and ETP as open-water rates, with
or without a stream network. A rain or evaporation series that the file declares for the
lake wins over the loaded one.

At scoring time, a calibration compares the simulated discharge with the gauge. If the
simulated discharge is a drain budget, the runoff is added to it, averaged on each period
by the rule of section 11 and multiplied by $A_c$, or by the area a gauge drains
(`add_runoff_to_discharge`, in `hydromodpy/calibration/metrics/series.py`). If a stream
network already carries the runoff, nothing is added.

## 10. The soil reservoir as a source of grids

With a soil reservoir ({toml}`flow.sinks_sources.recharge.soil`), the data layer loads rain
and ETP, and the reservoir computes three daily grids in mm/day: recharge, the ETP it could
not meet, and runoff (`compute_soil_forcings`). The binders then take these grids where
they would take a loaded recharge, ETP and runoff. The grids go through section 5, and the
runoff through section 9. A daily step gives one slice per period. A monthly step gives the
mean of the daily slices, so the mean recharge of the month is the sum of the daily
recharge divided by the number of days.

The daily rules are on {doc}`soil-reservoir`. Two consequences for this page: a soil run
must not start with a steady period, because that period would hold the recharge of one day,
and the first_clim of section 6 does not act on these grids under MODFLOW 6.

## 11. Outputs are read back on the periods

The solvers stamp a stress period at its end. The time axis of a run is the start of the
run plus the elapsed solver time. January 2000 of a monthly run is stamped 2000-02-01. A
steady run over 2000 to 2002 has one period, stamped 2003-01-01. Period $i$ is therefore
$[b_i, b_{i+1})$, and its stamp is $b_{i+1}$.

What a stamp stands for depends on the quantity. The rule is the one of the CF
`cell_methods` of the field, or, for a calibration variable the registry does not hold, the
table `OBSERVABLE_TIME_METHODS`. A name that nothing declares is a mean
(`hydromodpy/core/time/time_method.py`).

| Method | Quantity | The value at stamp $b_{i+1}$ stands for |
|---|---|---|
| `mean` | recharge, drain and seepage fluxes, discharge, runoff, lake inflow and outflow | the mean of the flux over $[b_i, b_{i+1})$ |
| `point` | head, water table elevation and depth, seepage mask, lake level, volume | the state at the instant $b_{i+1}$ |

A flux read on a period is a mean: the flux that fills the period, in the units of a rate.
A state is the value at the end of the period. For a steady first period, the head is the
equilibrium under the forcing of that period, stamped at the end of it.

An observation is put on the periods by the same rule, so a simulated and an observed value
mean the same thing. The code is `observed_on_periods`
(`hydromodpy/core/time/period_aggregation.py`).

**A mean quantity.** Observations are stamped at the start of what they average: a daily
mean at its day, a monthly mean at its month start. The period takes the mean of the
observations stamped in $[b_i, b_{i+1})$ (`period_value_on_index`). A period with no
observation takes the last observation at or before $b_i$ when the interval that
observation stands for covers the whole period, $b_{i+1} \le t_h + r$, where $r$ is the step
of the chronicle. This is a monthly mean on a daily run. Otherwise the period has no value.

**A forcing is not an observation.** `period_mean_on_index` has the same mean and no hold.
A period with no sample is a gap, `NaN`, never the previous value. The derived catchment
discharge and the runoff added to a drain budget use it. The forcing of section 4 is the one
that carries a value forward. On the daily series of section 4 with the days of February
removed, the three periods read 1, `NaN` and 5.

**A state.** A chronicle finer than the run is averaged on a window centred on the stamp,
which reaches halfway to the neighbouring stamps. A chronicle as coarse as the run, or
coarser, gives the sample nearest to the stamp, within a tolerance
(`period_point_on_index`). Averaging a state over $[b_i, b_{i+1})$ would compare it with a
value half a period earlier.

**A steady period.** One stamp does not say where the period starts. The scorer takes the
start of the first period from the time grid of the run, so a steady discharge is compared
with the mean of the gauge over the window of the run and not with the last day of it. A
steady head is still read at its stamp.

## Assumptions

- A forcing sample is a rate over the interval it stands for, stamped at the start of that
  interval.
- A period with samples takes their equal-weight mean. Samples are assumed to be regular.
- A period with no sample of a series takes the last earlier sample.
- Rain and ETP are one value per period and per cell, constant within the period.
- Recharge is a flux set from outside. It does not read the water table.
- A negative net recharge is a deficit that the ETP package draws from the water table
  near the cell top.
- Runoff does not touch the aquifer except through a stream network or a lake.
- A stamp closes its period: a flux is a period mean, a state is a value at the stamp.

## Limits

- **A record that ends early is extended.** The coverage check of
  {toml}`coverage_policy|simulation.time.coverage_policy` runs on the series after the
  alignment, which has already carried the last value forward. Checked at HEAD with a
  60-day series on a six-month window: no error, and the four periods after the record all
  take its last sample. A grid is checked, with the policy of section 5.
- **Several grid records are not averaged with equal weights.** When more than one
  gridded record covers a period, they are merged pairwise with weights 1/2 and 1/2
  (`discretize_fields_on_sgrid`), which is the mean for two records only.
- **`first_clim` is the same word for three behaviours.** See section 6. A numeric value
  is ignored on a transient first period under MODFLOW 6.
- **The routed deficit mixes two rules.** Under MODFLOW 6 with a steady first period, a
  `first_clim` other than `"mean"` changes the recharge of that period, and the routed
  deficit stays the mean deficit (`extract_evt_payload` and `recharge_to_spd`). The net
  rate of that period is then not the one `first_clim` states.
- **The ETP is not read under MODFLOW 6 outside soil mode.** A loaded ETP is ignored, with a
  warning.
- **Aggregation by `last` exists for declared forcings only.** The data layer always takes
  the mean.
- **No energy balance.** Rain, ETP and the negative-recharge rule are inputs. The model does
  not compute evapotranspiration from temperature, wind or radiation.
- **PyHELP.** The repository holds a PyHELP package. No key of a project file reaches it, so
  this page does not describe it.

## Parameters of this page

The fields below appear in the equations. Open a row for its card.

```{hmp-params}
simulation.time.start_datetime
simulation.time.end_datetime
simulation.time.step_value
simulation.time.step_unit
simulation.time.coverage_policy
flow.first_period_steady
flow.sinks_sources.recharge.units
flow.sinks_sources.recharge.first_clim
flow.sinks_sources.recharge.negative_to_evt
flow.sinks_sources.recharge.spatial_mode
flow.sinks_sources.recharge.interpolation_method
flow.sinks_sources.etp.first_clim
modflow6.process_specific.evt_extinction_depth
```

The window and the step of example 04, then its first period:

```{hmp-resolved} simulation.time.step_value
:config: project.toml
```

```{hmp-resolved} flow.first_period_steady
:config: step6_soil_reservoir.toml
```

A file that keeps every period transient, aligns the rain and ETP of a daily run and
leaves `first_clim` at its default:

```toml
base_config = "step6_soil_reservoir.toml"

[flow.sinks_sources.recharge]
negative_to_evt = true
spatial_mode = "auto"
```

## Checked by

The tests that import the code of this page. The box is generated: a new test appears here
on the next build.

```{hmp-tested-by}
hydromodpy.physics.forcing
hydromodpy.physics.flow.time_forcing
hydromodpy.physics.flow.structure_binders
hydromodpy.core.time
hydromodpy.solver.modflow_common.recharge_evt_routing
hydromodpy.solver.modflow6.builders.recharge
hydromodpy.results.derive.time_alignment
```

## In the code

| What | Where |
|---|---|
| Window, edges, the end date | `hydromodpy/core/time/window.py` (`build_simulation_time_boundaries`, `validate_recharge_coverage`) |
| Station mean, spatial mode, series builder | `hydromodpy/physics/forcing/forcing_bridge.py` (`resolve_forcing`, `build_forcing_series`) |
| Series to periods | `hydromodpy/physics/forcing/time_alignment.py`, `hydromodpy/physics/flow/time_forcing.py` (`aggregate_forcing_series`) |
| Grid to periods | `hydromodpy/spatial/mesh/cartesian_grid/_sgrid_field_xarray.py` (`discretize_from_xarray`) |
| Units, the binders, runoff and lake forcing | `hydromodpy/physics/flow/structure_binders.py`, `hydromodpy/workflow/steps/data.py` |
| `first_clim` in MODFLOW 6 | `hydromodpy/solver/modflow6/builders/recharge.py` (`series_payload_value`, `recharge_to_spd`) |
| `first_clim` in MODFLOW-NWT, Boussinesq | `hydromodpy/solver/modflow_nwt/nwt/payloads/recharge_etp.py`, `hydromodpy/solver/boussinesq/forcing/` |
| Negative recharge to EVT | `hydromodpy/solver/modflow_common/recharge_evt_routing.py` |
| Stamp, mean and point rules | `hydromodpy/core/time/period_aggregation.py`, `hydromodpy/core/time/time_method.py`, `hydromodpy/results/derive/time_alignment.py` |
| Runoff added to a drain budget | `hydromodpy/calibration/metrics/series.py` (`add_runoff_to_discharge`) |

## See also

- {doc}`../guides/recharge`: choose where the recharge comes from.
- {doc}`../guides/time-and-initial-state`: the window, the first period and the starting state.
- {doc}`soil-reservoir`: the daily balance that turns rain and ETP into recharge.
- {doc}`exits`: how water leaves the aquifer.
- {doc}`index`: the other theory pages.
