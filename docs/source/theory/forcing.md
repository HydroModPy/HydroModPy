# Rain and evaporation: the forcing

Rain falls and the air asks for water every day. The aquifer model does not see
days: it sees stress periods, and one rate per cell for each period. This page
gives the rules that turn daily series and daily grids into those rates, and the
terms the solver builds from them. How the outputs are put back on the same
periods is on {doc}`time-alignment`. To set up a run, see
{doc}`../guides/recharge` and {doc}`../guides/time-and-initial-state`.

:::{note}
**Scope.** Every rule below is the same under the three flow solvers, MODFLOW 6,
MODFLOW-NWT and Boussinesq, and for one value per period, a mapping or one grid
per period. The daily soil reservoir that turns rain and ETP into recharge has
its own page, {doc}`soil-reservoir`; here it is one more source of daily grids.
:::

::::{dropdown} Notation of this page
$k$ is a stress period, $n_\mathrm{per}$ the number of periods. $j$ is one sample
of a record, stamped $t_j$. Rates are volumes per area and per time, so lengths
per time. A positive recharge adds water to the aquifer; a positive ETP removes
it. Every symbol of the site is on {doc}`notation`.

```{hmp-notation}
```
::::

(forcing-window)=
## 1. The window is cut into periods

The edges start at $b_0 = t_0$ and advance by one step $\Delta t$ until the first
edge that reaches the end of the last day:

$$
b_{k+1} = b_k + \Delta t,
\qquad
b_{n_\mathrm{per}} = t_\mathrm{end} + 1\ \text{day}\quad(+ 1\ \text{hour for an hourly step}).
$$ (eq-period-edges)

Period $k$ is the half-open interval $[b_k, b_{k+1})$. The end date is part of the
run, so the last edge is the day after it. A step that does not land on that edge
is refused: the window is not aligned with the step.

In the code: `build_simulation_time_boundaries`.

(forcing-series)=
## 2. One series per variable

The data layer hands a variable over as station records or as grids. Two rules
reduce them to the shape the flow needs.

**Stations.** Several stations are averaged at each stamp, with equal weights. A
single station is used as it is.

**Spatial mode.** {toml}`spatial_mode|flow.sinks_sources.recharge.spatial_mode`
decides what stays a series and what stays a grid:

| Mode | Stations | Grids |
|---|---|---|
| `auto` | one series | kept as a grid |
| `homogeneous` | one series | reduced to one spatial mean per stamp |
| `heterogeneous` | placed on the cells if they have coordinates, else one series | kept as a grid |

Under `auto`, station records with coordinates become a grid only when no series
can be built from them. A grid is not resampled when it is loaded: it is placed
on the cells of the solver mesh once the mesh exists, by the method of
{toml}`interpolation_method|flow.sinks_sources.recharge.interpolation_method`
(`nearest`, `linear` or `idw`). The ETP has the same two keys.

In the code: `resolve_forcing`.

(forcing-units)=
## 3. Units

Every data manager hands rain, ETP, recharge and runoff over in mm/day. The
binders convert them with the fixed factor $1/(1000 \times 86400)$ m/s per mm/day,
whatever {toml}`units|flow.sinks_sources.recharge.units` says. That key is read
for a rate written in the file:
{toml}`values|flow.sinks_sources.recharge.values` and a numeric
{toml}`first_clim|flow.sinks_sources.recharge.first_clim` are converted from it
to m/s when the flow is built.

A sample is a rate. The code averages samples and never sums them: a monthly
total in mm must be turned into mm/day before it is given to the model.

(forcing-coverage)=
## 4. A record gets one value per period

One rule holds for every forcing record: a series, a station, or a grid with a
time axis, which is averaged cell by cell of its own grid before it is placed on
the mesh.

**Samples inside the period.** Period $k$ takes the equal-weight mean of the
$n_k$ samples stamped inside it:

$$
\bar x_k = \frac{1}{n_k} \sum_{t_j \in [b_k,\, b_{k+1})} x_j \qquad \text{if } n_k > 0 .
$$ (eq-period-value)

The mean has equal weights, so it is the time mean only for a record with one
sample per equal step. Several gridded records that cover one period are averaged
the same way, with equal weights.

**No sample inside.** A sample is the rate of the interval from its stamp to the
next stamp. The last sample stands for one step $\Delta t_r$ of the record, the
median spacing of its stamps, and a record of one sample stands for all later
time. A period with no sample inside is covered when the interval of the latest
earlier sample reaches into it, and takes that sample. So daily data on hourly
periods, and a gap inside a record, are covered.

**Not covered.** A period that no interval reaches, before the first stamp or
after the end of the last step, is not covered.
{toml}`coverage_policy|simulation.time.coverage_policy` decides: `"error"`, the
default, stops the run and names the periods; `"warn"` warns once per record;
`"ignore"` says nothing. Under the last two, the period takes the nearest sample
in time: the last one after the record, the first one before it.

```{eval-rst}
.. plot:: theory/figures/forcing_period.py
   :alt: Six monthly periods and a weekly record with a gap over March that ends in late April. January, February and April take the mean of their samples; March and May take the sample in force; June is not covered.

   A weekly record on six monthly periods, matched by ``samples_by_period``.
   Each sample stands for the interval up to the next one, and the last for one
   step. March holds no sample and takes the one in force; May is still inside
   the last step; June is past it and stops the run by default.
```

Four records on monthly periods from 1 January 2000, from calls of
`align_forcing_series_to_simulation_window`:

| The record | Window | Under `"error"` | The periods take |
|---|---|---|---|
| daily, 1 mm/day in January, 3 in February, 5 in March | January to March | runs | 1, 3, 5 |
| 2 on 1 January and 6 on 1 March | January to March | runs | 2, 2 (in force), 6 |
| one sample, 4 on 1 February | January to March | stops: January is before the first stamp | 4, 4, 4 under `"warn"` |
| 60 daily samples from 1 January, valued 0 to 59 | January to June | stops: March to June are after the last step | 15, 45, then 59 four times under `"warn"` |

**The `last` rule.** A forcing declared by a CSV file under a well, a lake, a
stream network or a boundary has an `aggregate` key, for example
{toml}`flow.sinks_sources.lakes.<name>.rainfall.aggregate`. `"mean"` is the rule
above. `"last"` reads the record as a state that holds until it changes: period
$k$ takes the latest sample at or before $b_k$, and no coverage check applies.
The rain, ETP, recharge and runoff of the data layer have no such key.

In the code: `samples_by_period`, `enforce_coverage`.

(forcing-steady)=
## 5. Steady periods and `first_clim`

A steady period stands for the long-term state a run starts from. It does not
take the rate of its own dates.
{toml}`first_clim|flow.sinks_sources.recharge.first_clim` sets the rate $\hat N$
of every steady stress period, and of no other period:

$$
\hat N =
\begin{cases}
\dfrac{1}{n_\mathrm{per}} \displaystyle\sum_{k=0}^{n_\mathrm{per}-1} N_k & \texttt{"mean"},\\[1.5ex]
N_0 & \texttt{"first"},\\[0.5ex]
F & \text{a number } F,\ \text{in the units of the values.}
\end{cases}
$$ (eq-steady-rate)

The mean has one weight per period, whatever the length of the period. The
steady periods are every period of a steady run, and period 0 of a transient run
when {toml}`flow.first_period_steady` is true. A transient period keeps its own
rate, whatever its index. The Boussinesq solver integrates every period of a
transient run in time, so a transient Boussinesq run has no steady period and
`first_clim` does not act on it. Under MODFLOW-NWT the ETP follows the same rule
with {toml}`first_clim|flow.sinks_sources.etp.first_clim`.

Four periods with rates 2, 4, 9 and 1, from calls of `apply_first_clim`:

| Period 0 | `"mean"` | `"first"` | the number 7 |
|---|---|---|---|
| first period steady | 4 | 2 | 7 |
| first period transient | 2 | 2 | 2 |

Periods 1 to 3 keep 4, 9 and 1 in both rows.

A run that starts from a steady state of its own ({toml}`flow.ic`, type
`steady_state`) builds an auxiliary steady model for that state, with
`first_clim` set to `"mean"`, or to the prescribed rate. The guide
{doc}`../guides/time-and-initial-state` describes the starting states.

```toml
base_config = "step4_transient.toml"

[flow.sinks_sources.recharge]
first_clim = "first"
```

In the code: `apply_first_clim`.

(forcing-negative)=
## 6. Negative recharge goes to the ETP package

A net recharge can be negative: a series of rain minus ETP, for example. With
{toml}`negative_to_evt|flow.sinks_sources.recharge.negative_to_evt`, it is split
into a recharge part and a deficit part:

$$
N^+_k = \max(N_k,\, 0), \qquad N^-_k = \max(-N_k,\, 0).
$$ (eq-recharge-split)

The recharge package receives $N^+_k$ and the evapotranspiration package
$N^-_k$. A transient period keeps its own split. A steady period takes
`first_clim` on each part: `"mean"` gives the mean of $N^+_k$ and the mean of
$N^-_k$, `"first"` gives $N^+_0$ and $N^-_0$, and a number $F$ gives $\max(F, 0)$
and $\max(-F, 0)$. So the net rate of a steady period, $\hat N^+ - \hat N^-$, is
always the one `first_clim` states: the mean of the net rates, $N_0$, or $F$.

A negative number for `first_clim` needs `negative_to_evt`, or the file is
refused. With `negative_to_evt` off, a negative rate in the file is refused when
it is read. The deficit is drawn from the water table near the top of each cell,
down to the extinction depth $d_\mathrm{ext}$, and not under the sea, a river
head or a lake ({doc}`exits/drains-and-et`).

In the code: `split_net_recharge`.

(forcing-solver)=
## 7. What the solver does with N and E

Both rates are fluxes per unit of area. The recharge package multiplies $N_k$ by
the area of the cell and adds that volume per time to the cell (the RCH package
of MODFLOW, {cite:p}`harbaugh2005`; RCHA of MODFLOW 6, {cite:p}`langevin2017`).
The rates are constant during a stress period.

The ETP package removes at most the rate $E_k$, in full when the head is at or
above its surface and linearly less down to the extinction depth. Which rate
reaches it depends on the solver:

- **MODFLOW-NWT.** The loaded ETP drives the package, with the deficit of
  {ref}`forcing-negative`.
- **MODFLOW 6 without a soil reservoir.** The loaded ETP is ignored, with a
  warning if `"etp"` is in {toml}`flow.active_sinks_sources`. Only the deficit
  reaches the package.
- **MODFLOW 6 with a soil reservoir.** The ETP the soil could not meet reaches the
  package.
- **Boussinesq.** `"etp"` in {toml}`flow.active_sinks_sources` is refused.

The law, the surface and the depth of each case are on
{doc}`exits/drains-and-et`. Under MODFLOW 6 the recharge is set to zero on lake
cells: the lake gets its own rain through the lake package.

(forcing-runoff)=
## 8. Runoff is not recharge

The runoff of the data layer, {toml}`data.runoff`, never enters the aquifer as a
diffuse term. It enters the model, when it enters at all, as a volume per time:

$$
Q^\mathrm{ro}_k = \bar q^\mathrm{ro}_k\,A ,
$$ (eq-runoff)

where $\bar q^\mathrm{ro}_k$ is the watershed mean of the runoff, in m/s, put on
the periods by the rule of {ref}`forcing-coverage`, and $A$ the catchment area.

- With an active stream network, $Q^\mathrm{ro}_k$ is shared among the reaches by
  their length and routed downstream. A forcing written in the file wins over the
  loaded series, and a lake then gets no direct share, so the same water is not
  counted twice ({doc}`exits/streams-and-mover`).
- Without a network, a declared lake receives $Q^\mathrm{ro}_k$ directly
  ({doc}`exits/lakes`).
- Without either, the runoff stays outside the flow.

A lake also gets the watershed mean of the loaded rain and ETP as open-water
rates, unless it declares its own.

When a calibration compares a simulated drain budget with a gauge, the runoff is
added to the simulated discharge, averaged on each period and multiplied by the
catchment area, or by the area the gauge drains ({doc}`time-alignment`). If a
stream network already carries the runoff, nothing is added.

(forcing-soil)=
## 9. The soil reservoir as a source of grids

With a soil reservoir ({toml}`flow.sinks_sources.recharge.soil`), the data layer
loads rain and ETP, and the reservoir computes three daily grids in mm/day:
recharge, the ETP it could not meet, and runoff. The binders take them where they
would take a loaded recharge, ETP and runoff, so they go through the rules of
{ref}`forcing-coverage` and {ref}`forcing-runoff`. A daily step gives one slice per period; a monthly step
gives the mean of the daily slices of the month.

A soil run refuses a steady first period, since that period would hold the
recharge of one day only. A soil run therefore has no steady period, and
`first_clim` acts on none of its periods. The daily rules are on
{doc}`soil-reservoir`.

## Assumptions

- A sample is a rate over the interval from its stamp to the next stamp; the last
  one stands for one step of its record.
- A period with samples takes their equal-weight mean: samples are assumed
  regular.
- Rain and ETP are one value per period and per cell, constant within the period.
- Recharge is a flux set from outside. It does not read the water table.
- A negative net recharge is a deficit that the ETP package draws from the water
  table near the cell top.
- Runoff reaches the aquifer only through a stream network or a lake, never as a
  diffuse term.

## Limits

- **`"mean"` weights each period equally.** On periods of unequal length, the
  steady rate is not the time mean of the record.
- **The ETP is not read under MODFLOW 6 outside soil mode.** A loaded ETP is
  ignored, with a warning.
- **Aggregation by `last` exists for declared forcings only.** The data layer
  always takes the mean.
- **No energy balance.** Rain, ETP and the negative-recharge rule are inputs. The
  model does not compute evapotranspiration from temperature, wind or radiation.

## Parameters of this page

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

The step of example 04, then the first period of its soil run:

```{hmp-resolved} simulation.time.step_value
:config: project.toml
```

```{hmp-resolved} flow.first_period_steady
:config: step6_soil_reservoir.toml
```

A daily run with every period transient, rain minus ETP routed to the ETP
package:

```toml
base_config = "step6_soil_reservoir.toml"

[flow.sinks_sources.recharge]
negative_to_evt = true
spatial_mode = "auto"
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.physics.forcing
hydromodpy.physics.forcing.steady_periods
hydromodpy.physics.flow.time_forcing
hydromodpy.physics.flow.structure_binders
hydromodpy.core.time
hydromodpy.core.time.coverage
hydromodpy.solver.modflow_common.recharge_evt_routing
hydromodpy.solver.modflow6.builders.recharge
```

## In the code

| What | Where |
|---|---|
| Window and edges | `hydromodpy/core/time/window.py` |
| Station mean, spatial mode | `hydromodpy/physics/forcing/forcing_bridge.py` |
| The coverage rule, for every record | `hydromodpy/core/time/coverage.py` |
| Series to periods | `hydromodpy/physics/forcing/time_alignment.py`, `hydromodpy/physics/flow/time_forcing.py` |
| Grids to periods | `hydromodpy/spatial/mesh/cartesian_grid/_sgrid_field_xarray.py`, `sgrid_field_discretization.py` |
| Units, the binders, runoff and lake forcing | `hydromodpy/physics/flow/structure_binders.py`, `hydromodpy/workflow/steps/data.py` |
| Steady periods and the split of a negative recharge | `hydromodpy/physics/forcing/steady_periods.py` |
| The recharge and ETP packages | `hydromodpy/solver/modflow6/builders/recharge.py`, `hydromodpy/solver/modflow_nwt/nwt/payloads/recharge_etp.py`, `hydromodpy/solver/boussinesq/forcing/` |

## See also

- {doc}`time-alignment`: how outputs and observations are put on the periods.
- {doc}`soil-reservoir`: the daily balance that turns rain and ETP into recharge.
- {doc}`exits`: how water leaves the aquifer.
- {doc}`../guides/recharge`: choose where the recharge comes from.
- {doc}`../guides/time-and-initial-state`: the window, the first period and the
  starting state.
