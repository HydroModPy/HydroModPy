# What the model computes

HydroModPy solves the flow of water in the saturated part of the ground of a catchment.
For each cell of the map and each timestep, it computes the height of the water table (the
*hydraulic head*), given how much water arrives from the soil, how fast the ground carries and
stores it, and where it can leave. Everything else (water table depth, seepage, flow, stream
network) is derived from this.

## In one diagram

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} What it is given
The relief (digital elevation model), the properties of the ground, the recharge, the
thickness of the aquifer.
:::

:::{grid-item-card} What it solves
The hydraulic head of the water table in every cell, month after month, with drains at the
ground surface through which water leaves the aquifer.
:::

:::{grid-item-card} What it produces
The water table depth, the seepage cells, the baseflow, the streams that flow or dry up, the
water budget.
:::

::::

In example 04, the stream network is not an input. The model produces springs, and the network
is derived from these springs. The mapped streams and the flow measured at the outlet are used
to compare and to calibrate (see {ref}`two-stage-calibration`).

## What it computes

| Result | What it means in the model | Where to read it |
|---|---|---|
| The water table | The hydraulic head of each cell, hence the elevation of the water table and its depth below the ground (never negative). | {ref}`reading-depth` |
| Seepage | The cells where the water table reaches the ground surface. Water leaves the aquifer there through a drain placed at the surface. | {ref}`reading-seepage` |
| Baseflow | The water that leaves the aquifer through the drains, summed over the whole catchment: the groundwater part of the flow at the outlet. | {ref}`reading-discharge`, {ref}`reading-budget` |
| Intermittence | For each month, the cells that flow. Over a year: always (perennial), sometimes (intermittent), never (dry). | {ref}`reading-persistence` |
| The budget | What enters the aquifer (the recharge), what leaves it (the drainage) and the change in the stock of water. | {ref}`reading-budget` |

A note on the "simulated network". A cell where the aquifer gives water back to the surface is
a point where a stream appears, not a stretch of river. The model extends these cells
downstream, following the slope of the ground, down to the outlet. This extension is the
simulated network, the one that is compared with the map of streams. There is no hydraulic
computation of the river in this path.

## What it is computed from

| Data | Role | In example 04 |
|---|---|---|
| Relief | It gives the ground surface, hence the elevation at which water leaves. It delimits the catchment from the outlet and tells where the water flows downstream. | A digital elevation model, 75 m cells ({toml}`data.dem`); 64.6 km² catchment traced from the outlet ({toml}`geographic.catchment.snap_dist`). |
| Geology | It sets how easily water moves (the hydraulic conductivity K) and the volume of water released when the water table drops (the specific yield Sy). One value for the whole aquifer, or one per zone of a geological map ({doc}`guide <../guides/k-per-zone>`). | A single value of K and a single value of Sy for the whole catchment: the geological map is not used. {toml}`flow.param.K.field.value`, {toml}`flow.param.Sy.field.value`. |
| Recharge | The water that reaches the water table. It is provided (a series from a file, or SIM2 data from Météo-France), or computed by a soil reservoir from rainfall and potential evapotranspiration ({doc}`guide <../guides/recharge>`). | A single monthly series for the whole catchment ({toml}`data.recharge`), and a runoff series ({toml}`data.runoff`). |
| Thickness | The depth of the aquifer below the ground surface. It is an assumption, not a measurement. | 30 m everywhere ({toml}`domain.depth_model.thickness`). |
| Observations | The mapped network and the flow measured at the outlet are not part of the physical computation. They are used to compare the results and to calibrate K and Sy. | The permanent stretches of the BD TOPO ({toml}`data.hydrography`) and the NANCON station ({toml}`data.hydrometry`). |

The solver is MODFLOW 6, the reference code of the United States Geological Survey (USGS).
HydroModPy prepares the data, runs MODFLOW 6 and reads its results back.

## The assumptions to keep in mind

Each row says what the model assumes and what that changes when reading the maps.
The rows marked "example 04" describe that configuration file, not the software:
another model can lift them.

| Assumption | Consequence for reading |
|---|---|
| Unconfined aquifer, a single layer of constant thickness below the ground (example 04: 30 m). | No deep aquifer and no layers of different kinds. The depth of the water table cannot exceed the thickness of the model. |
| Uniform K and Sy (example 04). | The pattern of the water table mostly follows the relief. Geological contrasts are not represented. |
| Water leaves through drains placed at the ground surface, in one direction only. | Water that leaves does not return to the aquifer. A river does not feed the aquifer in this setup. |
| The efficiency of a drain depends on K ({toml}`solver.drain_bed_thickness_m`). | The larger K is, the more the aquifer is drained. This is why the seepage network carries information on K. |
| Identical recharge over the whole catchment, monthly average (example 04). | No variation of rainfall from one hillside to another, or from one day to another within the month. |
| One timestep per month, and the first month in steady state ({toml}`flow.first_period_steady`). | The first month sets the starting state. The documentation of the parameter {toml}`simulation.time.substeps_per_period` states that a single step per month changes the monthly flow by 4 to 28 % compared with a refined computation, depending on the case. |
| No hydraulic model of the rivers. | No water level, flood or propagation. A stream that "flows" means: the aquifer feeds it. |
| The simulated network follows the slope of the ground downstream of the seepage cells. | Its shape depends on the digital elevation model and on the cell size. |
| If the recharge comes from the soil reservoir ({toml}`flow.sinks_sources.recharge.soil`): the soil ignores the height of the water table, and snow counts as rain. | A high water table does not reduce the soil reserve. The documentation of the soil reservoir judges it unsuitable for a snow-covered catchment. Available with MODFLOW 6 only. |

The intended range of validity of the project, according to its scientific documentation:
shallow aquifers at catchment scale, unconfined or weakly confined, where the relief, the
stream network and the geology organise the flow. Large deep sedimentary basins and coupled
surface and atmosphere models fall outside this range.

(two-stage-calibration)=
## Calibration in two stages

K cannot be measured at catchment scale. The model of example 04 infers it in two stages,
with the method published by Abhervé et al. (2023, *Hydrology and Earth System Sciences*, 27,
3221-3239). The example file also cites their 2025 article for the second stage:

1. K is adjusted, in steady state, until the simulated seepage network matches the mapped
   network.
2. Sy is adjusted, in monthly transient state, against the flow measured at the outlet, with
   the first year used as a spin-up.

Direct consequence: in a calibrated run, the map of the network and the flow curve show what
was adjusted. Their agreement is expected. It does not prove on its own that the model is
right. The page {doc}`reading-results` comes back to this point map by map. The parameters
of this method: {toml}`calibration.protocol.name`.

## What it does not compute

- **River hydraulics**: water level, floods, propagation, storage in the riverbed.
- **Surface runoff**, unless it is provided as data (example 04) or, with the soil
  reservoir, for the sealed part of the surface. The groundwater model does not produce
  floods.
- **The unsaturated zone in detail.** The soil reservoir is a simple budget (usable reserve,
  evapotranspiration, delay before reaching the water table), not an infiltration model.
- **Abstractions**, unless they are declared as wells in the configuration.
- **Water quality.** Solute transport and particle tracking exist separately and are not
  covered here.
- **The future by default.** The model replays the forcings it is given. For a climate
  projection, projection data must be provided. Comparison with measurements then no longer
  makes sense.

## The limits of this example

- A single catchment and three years: the result says nothing about the variability from one
  year to the next.
- No comparison with piezometer levels or with field flow observations: example 04 does not
  use them.
- A 75 m cell: a map is read at the scale of the hillside, not of the field.

Next: {doc}`reading-results`.
