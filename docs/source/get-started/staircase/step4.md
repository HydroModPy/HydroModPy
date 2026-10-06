# Step 4: the transient run

Step 4 turns step 2 into a monthly transient run over 2000-2002. The recharge and the
runoff are no longer one mean: 36 monthly values replace the steady rate. The first period
is solved steady and gives the initial heads. K, Sy and Ss are assumed here, not
calibrated. The question changes from where the water table reaches the surface to which
cells flow, and for how long.

## The file

```{hmp-step} step4_transient.toml
```

## Run it

```bash
hmp run step4_transient.toml
```

Two points of the file are worth a second look. {toml}`flow.flow_regime` is written again,
because an inherited `"steady"` is not undone by the default. {toml}`data.types` is written
in full, because a list replaces the parent's.

## What you get

Five figures. The instant of the one-instant figures comes from {toml}`display.time`, here
15 October 2002, the driest month according to the file.

| Figure | What it shows |
|---|---|
| `flux_timeseries` | The components of the water balance through time, inflows positive and outflows negative |
| `hydrograph_sim_obs` | The simulated discharge against the gauged one |
| `seepage_map` | The seepage cells of October 2002 |
| `flow_persistence_map` | The share of the three years each cell flows: dark where the channel ran all year, pale where it ran only at the wettest steps |
| `flow_intermittence_map` | One calendar year, 2002 (`cycle = "2002"`): each cell is perennial, intermittent or dry |

Six exports in `share/nancon_step4_transient/`: the four inherited ones, now of a transient
run (the GeoTIFFs hold December 2002, the last month), and two more.

| Block | File |
|---|---|
| `["head", "watertable_depth"]` | the water table over the 36 months, one NetCDF file |
| `["discharge", "discharge_obs"]` | simulated and gauged discharge, a CSV: the model monthly, the gauge daily |

## Key fields

```{hmp-params}
simulation.time.start_datetime
simulation.time.end_datetime
flow.param.Ss.field.value
display.time
```

The time step is not written: {toml}`simulation.time.step_value` defaults to one month.

Next: {doc}`step5`, which writes the results in every format.
