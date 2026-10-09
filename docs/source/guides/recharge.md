# Choose how recharge enters the model

```{hmp-task}
Task
: Give the model its recharge: a rate you state, a series you load, or a soil reservoir fed by rain and ETP.

Time
: Five minutes to choose. The soil reservoir of step 6 of example 04 runs in about twenty minutes on one core.

Needs
: A model that runs, and the data of the route you take.

Gives
: A model with one recharge, never two.
```

Recharge is the water that reaches the water table. A model takes it from exactly one of
three places. Pick the one that matches the data you have.

````{grid} 1 1 3 3
:gutter: 3

```{grid-item-card} 1. State the rate
:link: route-values
:link-type: ref

You write a number, or a list with one number per time step.

+++
Take it when you know the rate, or want the simplest model.
```

```{grid-item-card} 2. Load a recharge series
:link: route-data
:link-type: ref

A recharge series or grid is read from files, from SIM2, or generated.

+++
Take it when you have a recharge record for your site.
```

```{grid-item-card} 3. Compute it from rain and ETP
:link: route-soil
:link-type: ref

A soil reservoir turns daily precipitation and ETP into recharge.

+++
Take it when you have rain and ETP, not a recharge.
```
````

Whatever the route, {toml}`flow.active_sinks_sources` must list `"recharge"`. An empty list
means the solver builds no sink or source package.

The blocks below are merged onto a file of example 04 and validated: step 1 for routes 1
and 2, step 4 for route 3.

(route-values)=
## 1. State the rate

Write the rate under {toml}`flow.sinks_sources.recharge`. Step 1 does it with one number:

```{hmp-toml}
:file: step1_minimal.toml
:tables: flow.sinks_sources.recharge
```

One number applies to every time step. A list gives one rate per stress period, which is
one time step of the model. The list needs as many values as the run has periods, and a
list of the wrong length stops the run. Three monthly periods take three values:

```{hmp-toml}
[flow]
flow_regime = "transient"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-03-31"
step_value = "1 month"

[flow.sinks_sources.recharge]
values = [2.1, 1.4, 0.6]
```

The three rates are only there to make the block complete. They are not typical values.

Two behaviours to know:

- In a transient run whose first period is steady, that period takes the mean of the list.
  This is the default of {toml}`first_clim|flow.sinks_sources.recharge.first_clim`.
- A negative rate goes to the evapotranspiration package, not to recharge. This is the
  default of {toml}`negative_to_evt|flow.sinks_sources.recharge.negative_to_evt`.

```{hmp-params}
flow.sinks_sources.recharge.values
flow.sinks_sources.recharge.units
flow.sinks_sources.recharge.first_clim
flow.sinks_sources.recharge.negative_to_evt
```

The rate is read in {toml}`units|flow.sinks_sources.recharge.units`, `"mm/day"` by
default. Step 1 writes `0.78`, which is 0.78 mm/day.

```{hmp-resolved} flow.sinks_sources.recharge.values
:config: step1_minimal.toml
```

`units` accepts a length per time, such as `m/s`, `m/day`, `mm/day` or `mm/h`. It is
converted to `m/s` when the run builds the flow. A unit that is not a length per time
passes `hmp config check` and is refused later, at that point.

(route-data)=
## 2. Load a recharge series

Add `"recharge"` to {toml}`data.types` and say where the series comes from. Step 4 does
it with a folder of local files:

```{hmp-toml}
:file: step4_transient.toml
:tables: data, data.recharge.sources
```

The same block, validated on step 1:

```{hmp-toml}
[data]
types = ["recharge"]

[[data.recharge.sources]]
source = "custom"
path = "recharge"
station_ids = ["NANCON"]
```

{toml}`source|data.recharge.sources.source` takes three values:

- `"custom"`: your files. `path` is a folder with a location file and one CSV per
  station, or a single NetCDF or GeoTIFF file.
- `"sim2"`: the Meteo-France SIM2 reanalysis. For recharge, the code reads its drainage
  product `DRAINC_Q`, in mm/day.
- `"synthetic"`: a series you generate, from `values` in mm/day.

A station series gives one series for the whole model. A gridded file gives one value per
cell. A record that ends before the window, or starts after it, stops the run by default;
a gap inside the record takes the last sample before it.
{toml}`coverage_policy|simulation.time.coverage_policy` set to `"warn"` or `"ignore"`
fills the uncovered periods with the nearest sample instead.

The data layer hands recharge to the flow in mm/day. So {toml}`units|flow.sinks_sources.recharge.units`
plays no part for a loaded series.

If the file also has a `values`, the loaded series replaces it when the data is bound to
the flow. Step 4 inherits `values = 0.78` from step 1 and never uses it. Delete it, so
the file says one thing:

```{hmp-toml}
[flow.sinks_sources.recharge]
values__delete = true
```

(route-soil)=
## 3. Compute it from rain and ETP

A daily soil reservoir turns precipitation and ETP into recharge. You declare it under
{toml}`flow.sinks_sources.recharge.soil`. Its one required field is `ru`, the water the
roots can draw, in mm.

```{hmp-toml}
:file: step6_soil_reservoir.toml
:tables: flow.sinks_sources.recharge.soil
```

The soil reads {toml}`data.precipitation` and {toml}`data.etp`. It takes the place of
{toml}`data.recharge`, and step 6 drops {toml}`data.runoff` too. This is the step 4 file
switched to the soil, validated:

```{hmp-toml}
[flow]
first_period_steady = false

[flow.ic]
type = "steady_state"

[flow.sinks_sources.recharge]
values__delete = true

[flow.sinks_sources.recharge.soil]
ru = "150 mm"

[data]
types = ["hydrography", "hydrometry", "precipitation", "etp"]
recharge__delete = true
runoff__delete = true

[[data.precipitation.sources]]
source = "sim2"
extent = "watershed"

[[data.etp.sources]]
source = "sim2"
extent = "watershed"
```

The value `150 mm` is the one of step 6, tied to the Nancon catchment. `ru` belongs to
the site and is required.

```{hmp-params}
flow.sinks_sources.recharge.soil.ru
```

Check the soil alone before a full run. The comment of step 6 says that this command
loads the rain and the ETP, prints the soil budget in mm/year, and writes no run:

```text
hmp run step6_soil_reservoir.toml --until load_data
```

After the full run, `flux_timeseries` shows what the soil hands to the aquifer: recharge
in bursts during the wet months and none in summer, against the steady outflow of the
drains.

```{image} /_static/figures/staircase/step6/flux_timeseries.webp
:class: only-light
:alt: Daily recharge computed by the soil reservoir of step 6, in bursts from autumn to spring, with the drain outflow of the aquifer.
```

```{image} /_static/figures/staircase/step6/flux_timeseries-dark.webp
:class: only-dark
:alt: Daily recharge computed by the soil reservoir of step 6, in bursts from autumn to spring, with the drain outflow of the aquifer.
```

The soil is wired to MODFLOW 6 only. Its other settings, and the equations, have their own
pages: {toml}`flow.sinks_sources.recharge.soil` and {doc}`../theory/soil-reservoir`.

## When to take which

- A steady model, or a test case: route 1. One number, no data.
- A transient model with a recharge record you trust: route 2.
- Rain and ETP are what you have, or the recharge product keeps a slow summer drainage
  that the aquifer model would then count twice: route 3. This is the reason step 6 gives
  for its switch. Its comment puts that drainage at about 0.3 mm/day all summer in the SIM2
  product from 2016 on.

## What can go wrong

Two routes at once would give the model two recharges, or the same water twice, and the
code refuses them. `hmp config check` shows the first five rows below. The calibration
case is refused when the calibration starts, the last two during the run.

| Symptom | Cause | Fix |
|---|---|---|
| `flow.sinks_sources.recharge.values = 0.78 is ignored when [flow.sinks_sources.recharge.soil] computes the recharge` | `values` and the soil. | Remove `values`. Write `values__delete = true` if a base file sets it. |
| `[flow.sinks_sources.recharge.soil] computes the recharge from the precipitation and the ETP, and data.types also loads one from [data.recharge]: the model would receive one and ignore the other.` | `"recharge"` in {toml}`data.types` and the soil. | Remove `"recharge"` from {toml}`data.types`, and write `recharge__delete = true` under `[data]` if a base file declares it. |
| `[data.runoff] loads a surface runoff that already takes its share of the rain the soil reservoir receives (SIM2 RUNC, for instance): the streams, the lakes and the gauged discharge would count that water twice.` | `"runoff"` in {toml}`data.types` and the soil. | Remove `"runoff"`. In soil mode, the water that seeps out of saturated ground reaches the streams through the drains. |
| `[flow.sinks_sources.recharge.soil] is wired to MODFLOW 6 only` | The soil with another solver. | Write `solvers = ["modflow6"]` in the flow process. |
| `[flow.sinks_sources.recharge.soil] computes a recharge that flow.active_sinks_sources does not list, so MODFLOW would receive none` | `"recharge"` missing from {toml}`flow.active_sinks_sources`. | Add it. |
| `[calibration.parameters.<name>] moves flow.sinks_sources.recharge.values, which the soil reservoir replaces: the search would change nothing.` | A calibration of `values` with the soil. | Calibrate `ru`, with `[calibration.parameters.ru]` and its bounds in mm. |
| `<record> does not cover stress period(s) <i> [<start>, <end>): no sample of the record is in force there.` | A loaded record that ends before the window or starts after it. | Extend the record, shorten [simulation.time], or set {toml}`simulation.time.coverage_policy`. |
| `model.recharge sequence length must be 1, nper (<n>), or ncpl (<m>); got <k>.` (MODFLOW 6) | The list of `values` does not have one rate per stress period. | Give one rate per period, or one number. |

A `values` beside a loaded series is not an error: the series replaces it. Delete `values`
so the file says one thing.

Soil mode adds conditions of its own, each checked when the file is read: the flow solver
is MODFLOW 6; `[data.precipitation]` and `[data.etp]` exist, and the precipitation takes
`components = ["total"]`; a transient run sets `flow.first_period_steady = false` and
`[flow.ic] type = "steady_state"`; a lake or a reservoir in `flow.active_bc` comes with
`"sfr"`, because in soil mode the water reaches a lake only through the streams.

With MODFLOW 6, where a lake is declared, aquifer recharge is set to zero on the lake
cells. The lake receives its own rain through the lake package, and recharge on the same
cells would count it twice.

## Next

- Every field of the soil: {toml}`flow.sinks_sources.recharge.soil`.
- What the soil computes: {doc}`../theory/soil-reservoir`.
- How `base_config` and `__delete` merge files: {doc}`inheritance`.
