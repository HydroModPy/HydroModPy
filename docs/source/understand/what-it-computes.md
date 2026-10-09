# What the model computes

HydroModPy solves the flow of water in the saturated part of the ground of a catchment, the
part that lies below the {term}`water table`. For each {term}`cell` of the map and each time
step, it computes the height of the water table (the {term}`hydraulic head`), given how much
water arrives from the soil, how fast the ground carries and stores it, and where it can leave.
Everything else (water table depth, seepage, flow, stream network) is derived from this.

Terms that link to the {doc}`glossary` are defined there.

## In one diagram

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} What it is given
The relief (a {term}`digital elevation model`), the properties of the ground, the
{term}`recharge`, the thickness of the {term}`aquifer`.
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
{term}`simulated network`, the one that is compared with the map of streams. In this setup,
which is the default, there is no hydraulic computation of the river. The
{doc}`stream-network` page shows the options that route the water along declared reaches.

## What it is computed from

| Data | Role | In example 04 |
|---|---|---|
| Relief | It gives the ground surface, hence the elevation at which water leaves. It delimits the {term}`catchment` from the {term}`outlet` and tells where the water flows downstream. | A digital elevation model, 75 m cells; 64.6 km² catchment traced from the outlet. |
| Geology | It sets how easily water moves (the {term}`hydraulic conductivity` K) and the volume of water released when the water table drops (the {term}`specific yield` Sy). One value for the whole aquifer, or one per zone of a geological map ({doc}`[flow.param] <../reference/parameters/flow/param>`). | A single value of K and a single value of Sy for the whole catchment: the geological map is not used. Both are calibrated ({ref}`two-stage-calibration`). |
| Recharge | The water that reaches the water table. It is provided (a series from a file, or {term}`SIM2` data from Météo-France), or computed by a {term}`soil reservoir` from rainfall and {term}`potential evapotranspiration` ({doc}`theory <../theory/soil-reservoir>`). | A single monthly recharge series for the whole catchment, and a runoff series ({doc}`data sources <../reference/data-sources>`). |
| Thickness | The depth of the aquifer below the ground surface. It is an assumption, not a measurement. | 30 m everywhere. |
| Observations | The {term}`mapped network` and the flow measured at the outlet are not part of the physical computation. They are used to compare the results and to calibrate K and Sy. | The permanent stretches of the {term}`BD TOPO` and the {term}`NANCON station`. |

Where each dataset comes from is on {doc}`where-the-data-come-from`.

In the drain setup of example 04, the solver is {term}`MODFLOW 6`, the reference code of the
United States Geological Survey (USGS). HydroModPy prepares the data, runs MODFLOW 6 and reads
its results back. Other solvers exist, see {ref}`other-solvers` below.

## The assumptions to keep in mind

Each row says what the model assumes and what that changes when reading the maps.
The rows marked "example 04" describe that configuration file, not the software:
another model can lift them. The rows marked "drain setup" hold for the drain condition used
in example 04 and not for the other conditions of {doc}`stream-network`.

| Assumption | Consequence for reading |
|---|---|
| Unconfined aquifer, a single layer of constant thickness below the ground (example 04: 30 m). | No deep aquifer and no layers of different kinds. The depth of the water table cannot exceed the thickness of the model. |
| Uniform K and Sy (example 04). | The pattern of the water table mostly follows the relief. Geological contrasts are not represented. |
| Water leaves through {term}`drains <drain>` placed at the ground surface, in one direction only (drain setup). | Water that leaves does not return to the aquifer. A river does not feed the aquifer in this setup. |
| The efficiency of a drain depends on K and on the thickness of the clogging layer of the drain bed ({doc}`stream-network`). | The larger K is, the more the aquifer is drained. This is why the seepage network carries information on K. |
| Identical recharge over the whole catchment, monthly average (example 04). | No variation of rainfall from one hillside to another, or from one day to another within the month. |
| One {term}`stress period` per month, and the first month in {term}`steady state`. | The first month sets the starting state. The documentation of the setting that cuts a month into several steps, {toml}`simulation.time.substeps_per_period`, states that a single step per month changes the monthly flow by 4 to 28 % compared with a refined computation, depending on the case. |
| No hydraulic model of the rivers (drain setup). | No water level, flood or propagation. A stream that "flows" means: the aquifer feeds it. |
| The simulated network follows the slope of the ground downstream of the seepage cells. | Its shape depends on the digital elevation model and on the cell size. |
| If the recharge comes from the {term}`soil reservoir` ({doc}`theory <../theory/soil-reservoir>`): the soil ignores the height of the water table, and snow counts as rain. | A high water table does not reduce the soil reserve. The documentation of the soil reservoir judges it unsuitable for a snow-covered catchment. Available with MODFLOW 6 only. |

The intended range of validity of the project, as the scientific documentation states it:
shallow aquifers at catchment scale, unconfined or weakly confined, where the relief, the
stream network and the geology organise the flow. Large deep sedimentary basins and coupled
surface and atmosphere models fall outside this range. The limits are listed in
[the theory of the flow problem](../theory/groundwater-flow.md#limits), and the page
{doc}`what-validated-means` says how far the model has been tested.

(other-solvers)=
## Other solvers

Example 04 uses {term}`MODFLOW 6`. HydroModPy runs two other flow solvers behind the same
configuration file: MODFLOW-NWT, an older code of the same family, and a Boussinesq solver
that is part of HydroModPy. They do not support the same boundaries or the same meshes. Lakes,
reservoirs and routed streams, for example, need MODFLOW 6. A lumped rainfall-runoff model,
{term}`GR4J`, can be calibrated in place of the distributed model. The
{doc}`list of solvers <../reference/solvers>` says what each one supports. Every statement
about the solver on this page is about example 04.

(two-stage-calibration)=
## Calibration in two stages

K cannot be measured at catchment scale. The model of example 04 infers it, a step called
{term}`calibration`, in two stages,
with the method published by Abhervé et al. (2023, *Hydrology and Earth System Sciences*, 27,
3221-3239). The example file also cites their 2025 article for the second stage:

1. K is adjusted, in steady state, until the simulated seepage network matches the mapped
   network.
2. Sy is adjusted, in monthly {term}`transient` state, against the flow measured at the
   outlet, with the first year used as {term}`spin-up`.

Direct consequence: in a calibrated run, the map of the network and the flow curve show what
was adjusted. Their agreement is expected. It does not prove on its own that the model is
right. The page {doc}`reading-results` comes back to this point map by map. The settings
of this method are those of
{doc}`[calibration.protocol] <../reference/parameters/calibration/protocol>`.

## What it does not compute

- **River hydraulics** in the drain setup: water level, floods, propagation, storage in the
  riverbed. The routed stream option of MODFLOW 6 adds a routing of the water along declared
  reaches ({doc}`stream-network`).
- **Surface runoff**, unless it is provided as data (example 04) or, with the soil
  reservoir, for the sealed part of the surface. The groundwater model does not produce
  floods.
- **The unsaturated zone in detail.** The soil reservoir is a simple budget (usable reserve,
  evapotranspiration, delay before reaching the water table), not an infiltration model.
- **Abstractions**, unless they are declared as wells in the configuration.
- **Water quality.** Solute transport and particle tracking exist separately and are not
  covered here. Neither are lakes and reservoirs, which exist as an option of MODFLOW 6.
- **The future by default.** The model replays the forcings it is given. For a climate
  projection, projection data must be provided. Comparison with measurements then no longer
  makes sense.

## The limits of this example

- A single catchment and three years: the result says nothing about the variability from one
  year to the next.
- The figures and the numbers of {doc}`reading-results` come from one calibrated run, described
  at the end of that page. A new run gives different values.
- No comparison with piezometer levels or with field flow observations: example 04 does not
  use them.
- A 75 m cell: a map is read at the scale of the hillside, not of the field.

Next: {doc}`reading-results`. To know when not to use the model, see the end of the
{doc}`door index <index>`.
