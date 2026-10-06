# Route streams with SFR

You want the water that the aquifer gives back to travel down a river, not to leave the
model at the cell where it surfaces. This guide turns the river network that HydroModPy
draws on the DEM into a MODFLOW 6 SFR (streamflow routing) network. Each reach exchanges
water with the aquifer through its streambed, passes its flow to the reach below, and the
network ends at the model outlet or in a lake.

You get a simulated discharge for every reach, and a catchment discharge that is the water
that reached the network and left it.

## What you need first

- **MODFLOW 6.** SFR exists for this solver only, and MODFLOW-NWT builds no SFR package.
  Example 04 sets `solvers = ["modflow6"]` in its `[[simulation.process]]`. A file that
  lists `"sfr"` in {toml}`flow.active_bc` and picks another solver with
  {toml}`solver.backend.backend` is refused when it is read, with a message that contains
  `does not support the 'sfr' boundary`. A process that names `"modflow_nwt"` in
  `solvers` passes the check, so name MODFLOW 6 there.
- **A river network from the DEM.** The reaches are the stream links of the network that
  HydroModPy extracts from the DEM, cut by the model mesh. An observed network never
  becomes a reach.
- **Drains at the ground surface.** Example 04 has `"drainage"` in
  {toml}`flow.active_bc`. Section 4 keeps it, because the drains are what the
  network collects.
- **One network.** The model takes one SFR network. A second one stops the build with
  `one SFR network per model is supported`.

The blocks below are merged onto `step4_transient.toml` of example 04: monthly, three
years, with a runoff series loaded. Example 04 does not use SFR today, so each block adds
it. That file takes {toml}`flow.active_bc` from `step1_minimal.toml`:

```{hmp-resolved} flow.active_bc
:config: step4_transient.toml
```

## 1. Switch the river network on

SFR traces its reaches on the generated river network, and the threshold of that network
is the only threshold. The SFR block has none of its own. A small threshold gives many
short reaches and a large one gives a few long ones.

```toml
base_config = "step4_transient.toml"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.1
```

The value `0.1` only completes the block. It belongs to your catchment and your mesh.

```{hmp-params}
geographic.river_network.enabled
geographic.river_network.threshold_mode
geographic.river_network.threshold_area_km2
geographic.river_network.threshold_cells
geographic.river_network.compute_stream_links
geographic.river_network.compute_strahler_order
geographic.river_network.prune_short_streams
geographic.river_network.min_stream_length_m
```

Leave {toml}`compute_stream_links|geographic.river_network.compute_stream_links` on: the
reaches are the links. {toml}`compute_strahler_order|geographic.river_network.compute_strahler_order`
matters when the width depends on the stream order (section 3). Without the order raster,
every reach reads as order 1.

## 2. Declare the network and switch SFR on

Name the network under {toml}`flow.sinks_sources.sfr` and add `"sfr"` to
{toml}`flow.active_bc`. A list replaces the one of the parent file, so write `"drainage"`
again.

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "sfr"]

[flow.sinks_sources.sfr.main]
```

The name, `main` here, is yours. It appears in the series the run stores,
`sfr:main:<reach>`.

The two keys must agree. A network declared without `"sfr"` in
{toml}`flow.active_bc` is refused when the file is read: `declares stream networks but
flow.active_bc does not list 'sfr'`. The reverse, `"sfr"` listed with no network, passes
the check and builds no SFR package.

## 3. Set the streambed

Every reach shares these values. The unit of the conductivity is its own key.

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "sfr"]

[flow.sinks_sources.sfr.main]
streambed_k = 1e-5
streambed_k_unit = "m/s"
streambed_thickness = "1 m"
manning = 0.035

[flow.sinks_sources.sfr.main.width]
kind = "constant"
value = "2 m"
```

The numbers are placeholders to make the block complete. The streambed conductivity is the
unknown that matters most here. A value of 0 turns the exchange off and keeps pure routing.

```{hmp-params}
flow.sinks_sources.sfr.<name>.streambed_k
flow.sinks_sources.sfr.<name>.streambed_k_unit
flow.sinks_sources.sfr.<name>.streambed_thickness
flow.sinks_sources.sfr.<name>.manning
flow.sinks_sources.sfr.<name>.min_slope
flow.sinks_sources.sfr.<name>.connected_to_aquifer
flow.sinks_sources.sfr.<name>.min_reach_length
```

The width is one of three laws, chosen by {toml}`kind|flow.sinks_sources.sfr.<name>.width.kind`.

```{hmp-params}
flow.sinks_sources.sfr.<name>.width.kind
flow.sinks_sources.sfr.<name>.width.value
flow.sinks_sources.sfr.<name>.width.widths
flow.sinks_sources.sfr.<name>.width.coef
flow.sinks_sources.sfr.<name>.width.exp
```

A width per Strahler order, written as a table:

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "sfr"]

[flow.sinks_sources.sfr.main.width]
kind = "by_order"
widths = { 1 = "1 m", 2 = "3 m", 3 = "6 m" }
```

An order you did not declare takes the width of the nearest lower order you declared. An order below all of them takes the narrowest width.

### Where the bed sits

The streambed top is read on the model top, one value per reach cell. Then each reach is
solved inside its own cell: no bed sits above the ground of its cell, and none sits too
close to the cell bottom. The beds step down along the flow where the cells allow it. When
the DEM climbs along a reach, the code relaxes the downhill order and warns.

{toml}`bed_incision|flow.sinks_sources.sfr.<name>.bed_incision` sets the bed a fixed depth
below the cell top. The card says how to pick it. MODFLOW 6 treats a reach as connected
or disconnected at the bed top minus the bed thickness, so a bed near the seasonal water
table can toggle at every outer iteration.

```{hmp-params}
flow.sinks_sources.sfr.<name>.bed_incision
flow.sinks_sources.sfr.<name>.max_bed_sag
```

## 4. Choose how water enters the network

Four sources feed the reaches, besides the exchange through the streambed.

**The drains of the hillslope.** Without {toml}`route_drainage|flow.sinks_sources.sfr.<name>.route_drainage`,
only the cells that hold a reach exchange with the aquifer. The drains elsewhere send their
water out of the model, and the catchment discharge does not count it (see
{ref}`What the run reports <sfr-reports>`). With it, every drain cell of the
catchment hands its discharge to the first reach or lake cell that it meets going downhill.

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "sfr"]

[flow.sinks_sources.sfr.main]
route_drainage = true
```

Four rules apply.

- The path downhill follows the descent D, a filled copy of the model top. D never
  changes the model top. Each run builds it and stores it. Where the river network
  crosses a cell, D follows the network.
- A drain cell whose path leaves the model first keeps a plain drain, and so does a
  drain cell outside the drainage basin of D (the buffer around the catchment).
- The drain cells that hold a reach are removed, so the baseflow goes into the stream.
- It needs `"drainage"` in {toml}`flow.active_bc`. Without drains there is nothing to
  route, and neither the check nor the build says so.

It also needs a single drain stress period. A drain whose conductance changes from one
period to the next stops the build with `route_drainage requires a static DRN`.

**The runoff.** A runoff series loaded as data, {toml}`data.types` with `"runoff"`, is taken
by the network automatically. The watershed mean rate times the catchment area becomes the
`runoff` of the network, shared over the reaches by length. `step4_transient.toml` loads
one, so this block needs no change. With an active SFR network, a lake no longer receives
the runoff directly: it gets it through the reaches, so the same water is not counted
twice. A {toml}`runoff|flow.sinks_sources.sfr.<name>.runoff`
written in the network block wins over the data.

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "sfr"]

[flow.sinks_sources.sfr.main.runoff]
kind = "constant"
value = 0.002
units = "m3/s"
```

In soil mode, the runoff the soil reservoir computes is the one the network takes. See
{doc}`recharge`.

**An inflow at the head.** {toml}`headwater_inflow|flow.sinks_sources.sfr.<name>.headwater_inflow`
is a volume per time that enters the headwater reaches, shared by drainage area. It is for
water that comes from outside the model, such as a spring or a transfer.

**Rain and evaporation on the channel.** {toml}`rainfall|flow.sinks_sources.sfr.<name>.rainfall`
and {toml}`evaporation|flow.sinks_sources.sfr.<name>.evaporation` are rates applied to
every reach.

```{hmp-params}
flow.sinks_sources.sfr.<name>.route_drainage
flow.sinks_sources.sfr.<name>.runoff
flow.sinks_sources.sfr.<name>.headwater_inflow
flow.sinks_sources.sfr.<name>.rainfall
flow.sinks_sources.sfr.<name>.evaporation
flow.sinks_sources.sfr.<name>.storage
```

A volume per time is read in `m3/s` unless the forcing says otherwise, and a rate in `m/s`.
The `units` key of a forcing converts them. A forcing that varies in time is written inline
or as a MODFLOW 6 time series, with the same choice as the lake package.

## 5. End the network in a lake

A reach that enters the footprint of a declared lake is cut at the shoreline and its
flow passes to the lake through a water mover (MVR). This is how a reservoir receives
the streamflow of its catchment. The lake itself, its geometry and its outlets are in
{doc}`lakes-and-reservoirs`.

The lake is declared under {toml}`flow.sinks_sources.lakes`, and `"lake"` joins
{toml}`flow.active_bc`. Then {toml}`outflow_to_lake|flow.sinks_sources.sfr.<name>.outflow_to_lake`
gives the number of the receiving lake, counted from 1 in the order the lakes are declared.
It is the receiver of a reach that the DEM did not tag with a lake, and of the single
outlet of a network that never reaches a shoreline.

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "sfr"]

[flow.sinks_sources.sfr.main]
outflow_to_lake = 1
```

The block shows the key only. Without a lake declared and `"lake"` in
{toml}`flow.active_bc`, the build stops with `declares outflow_to_lake but no lake is
active`.

```{hmp-params}
flow.sinks_sources.sfr.<name>.outflow_to_lake
flow.sinks_sources.sfr.<name>.outflow_mvrtype
flow.sinks_sources.sfr.<name>.outflow_value
flow.sinks_sources.sfr.<name>.lake_feeder_snap
flow.sinks_sources.sfr.<name>.outlet_keepout
```

A network with no lake needs none of these. Its last reach leaves the model, and the run
reports that flow as `ext_outflow`.

## 6. Keep the channel one cell wide (optional)

The reaches follow a raster network, and on a coarse mesh they can cross several cells
side by side. {toml}`rectify_on_mesh|flow.sinks_sources.sfr.<name>.rectify_on_mesh`
traces the channel again on the mesh, along D, from every cell the delineation found. It
gives a channel with one downstream cell per cell, that reaches a lake or the outlet. The
streambed top is still read on the model top.

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "sfr"]

[flow.sinks_sources.sfr.main]
rectify_on_mesh = true
```

Two more keys tune it. A short stub that runs beside a stronger reach goes back to hillslope
drainage, and so does a component smaller than a set number of cells. Their water still
reaches the network, through the drains, when
{toml}`route_drainage|flow.sinks_sources.sfr.<name>.route_drainage` is on.

```{hmp-params}
flow.sinks_sources.sfr.<name>.rectify_on_mesh
flow.sinks_sources.sfr.<name>.rectify_stub_max_upstream
flow.sinks_sources.sfr.<name>.rectify_min_component_cells
```

## 7. Give the reaches yourself (optional)

{toml}`reaches|flow.sinks_sources.sfr.<name>.reaches` replaces the delineation. Each row is
one reach, with its cell, length, width, slope and bed top. The connections are the
1-based numbers of the reaches above and below. The two lists must agree: a reach that
feeds another must be listed in the upstream list of that one. The first reach cannot
be the downstream of another, so number the most upstream reach first. A network with
this table needs no river network. {toml}`diversions|flow.sinks_sources.sfr.<name>.diversions`
split a flow between two reaches, and work on an explicit table only.

```{hmp-params}
flow.sinks_sources.sfr.<name>.reaches
flow.sinks_sources.sfr.<name>.reaches.cell
flow.sinks_sources.sfr.<name>.reaches.length
flow.sinks_sources.sfr.<name>.reaches.width
flow.sinks_sources.sfr.<name>.reaches.slope
flow.sinks_sources.sfr.<name>.reaches.top
flow.sinks_sources.sfr.<name>.reaches.upstream
flow.sinks_sources.sfr.<name>.reaches.downstream
flow.sinks_sources.sfr.<name>.reaches.ustrf
flow.sinks_sources.sfr.<name>.diversions
```

## 8. Ask for the figures and the series

Three figures read the reach series from the run. List them with
{toml}`display.figures`. `step4_transient.toml` already sets {toml}`display.time`, which the longitudinal
profile uses. `[[export__append]]` adds a CSV of the series to the exports of that file.

```toml
base_config = "step4_transient.toml"

[display]
figures__append = ["sfr_reach_network", "sfr_reach_timeseries", "sfr_longitudinal_profile"]

[display.overrides.sfr_reach_timeseries]
variable = "gw_exchange"
reach = 3

[[export__append]]
variables = ["downstream_flow", "gw_exchange"]
```

- `sfr_reach_network`: the delineated network, coloured by Strahler order when the layer
  has it, with the reach count and the last discharge of the outlet reach.
- `sfr_reach_timeseries`: one quantity on one reach. By default the most downstream reach
  and `downstream_flow`. The options are `variable`, `reach` and `log_y`. Reach 3 above is
  an example: pick a reach of your network.
- `sfr_longitudinal_profile`: one quantity along the reach numbers, at one date. The
  options are `variable` and `time`.

## Put it together

This file adds the whole chain to `step4_transient.toml`: the network, the streambed, the drains routed
to the reaches, the figures.

```toml
base_config = "step4_transient.toml"

[simulation]
name = "nancon_step4_sfr"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.1

[flow]
active_bc = ["drainage", "sfr"]

[flow.sinks_sources.sfr.main]
streambed_k = 1e-5
streambed_k_unit = "m/s"
streambed_thickness = "1 m"
manning = 0.035
route_drainage = true

[flow.sinks_sources.sfr.main.width]
kind = "constant"
value = "2 m"

[display]
figures__append = ["sfr_reach_network", "sfr_reach_timeseries", "sfr_longitudinal_profile"]

[[export__append]]
variables = ["downstream_flow", "gw_exchange"]
```

## Check that it worked

1. `hmp config check` loads the file and refuses the combinations the schema knows, such
   as `"sfr"` missing from {toml}`flow.active_bc`. It does not look at the DEM: a
   network declared with the river network off passes.
2. `hmp run <file> --until load_data` runs the geographic step and the data step. The
   reaches are delineated and bound at the end of the data step, so a missing river
   network stops here, before the mesh.
3. `hmp run <file> -v` runs everything and prints the INFO lines. The line that starts with
   `Drainage routing on the descent:` gives, for the drain cells of the basin, how many
   were routed, how many to a reach, how many to a lake, how many kept a plain drain, and
   how many reaches received no drainage. If almost no cell is routed, look at the mesh
   and at the river network before you look at the solver.
4. Open `sfr_reach_network`, then `sfr_longitudinal_profile` of `downstream_flow`. The flow
   should grow from head to outlet. `hmp viz list` names every figure and
   `hmp viz show @last sfr_reach_network` draws one for the last run.

(sfr-reports)=
## What the run reports

Each reach stores its series under the station `sfr:<network>:<reach>`. The reach number
is the one of the build, counted from 0, and it grows downstream: a reach always has a
smaller number than the reach it feeds. This is the number that the `reach` option of the
figures takes. The connection lists of an explicit table (section 7) count from 1.

| Series | Unit | Meaning |
|---|---|---|
| `stage`, `depth` | m | Water level and depth in the reach. |
| `downstream_flow` | m3/s | The flow leaving the reach downstream. Stored positive. |
| `ext_inflow` | m3/s | Flow from outside the model, the `headwater_inflow`. |
| `ext_outflow` | m3/s | Flow that leaves the model at the reach. Stored positive. |
| `runoff` | m3/s | The overland inflow added to the reach. |
| `gw_exchange` | m3/s | Exchange with the aquifer. Positive when the reach gains water from the aquifer. |
| `to_mvr`, `from_mvr` | m3/s | Flow handed to and received from a water mover. Present when the network is coupled to a lake or receives routed drainage. |

`gw_exchange` exists only for the reaches connected to a cell. The geometry of every
reach as built (cell, layer, length, width, slope, bed top, bed thickness, conductivity,
roughness, order) is kept in the table `sfr_reaches` of the run, in `tables.parquet/`.
The MODFLOW 6 files are scratch, so this table is the only record of which cell holds
which reach.

When the run has an SFR network, the catchment `discharge` series changes meaning. It is
the sum of `ext_outflow` over the reaches and the lake outlets. The water that left
through a plain drain is not in it. This is why {toml}`route_drainage|flow.sinks_sources.sfr.<name>.route_drainage`
matters if you compare `discharge` with a gauge. The export above writes the
series as a CSV with the columns `datetime`, `station_id`, `variable`, `value` and `unit`.

## What can go wrong

| What you see | Cause | What to do |
|---|---|---|
| `flow.sinks_sources.sfr needs the river-network products; set [geographic.river_network] enabled = true.` | The network is declared, the river network is off. | Section 1. |
| `flow.sinks_sources.sfr needs the stream-link raster; set [geographic.river_network] compute_stream_links = true.` | The link raster is switched off. | Remove the key, or set it to `true`. |
| `No stream cells (link_id > 0); cannot delineate an SFR network.` | No stream link falls inside the catchment. Most often the threshold is larger than the contributing areas. | Lower {toml}`threshold_area_km2\|geographic.river_network.threshold_area_km2`. |
| `one SFR network per model is supported` | Two networks under {toml}`flow.sinks_sources.sfr`. | Keep one. |
| `declares outflow_to_lake but no lake is active` | The coupling is set and no lake is built. | Declare the lake, or drop the key. See {doc}`lakes-and-reservoirs`. |
| `route_drainage requires a static DRN` | The drain conductance changes between periods. | Use a constant drain conductance, or turn the routing off. |
| `cannot hold a streambed` | The cell of a reach is too thin for `bed_incision` plus the bed thickness. | Lower `bed_incision`, thin {toml}`streambed_thickness\|flow.sinks_sources.sfr.<name>.streambed_thickness`, or deepen the model. |
| A warning `dead-end reach(es) stop short of every shoreline and stay unrouted` | Some reaches stop before the lake and their flow leaves the model. | Raise {toml}`lake_feeder_snap\|flow.sinks_sources.sfr.<name>.lake_feeder_snap`, as the message says. |
| A warning `crosses inactive cell` | A reach crosses a cell outside the aquifer. | None needed. That reach routes water and exchanges nothing there. |
| The solver does not converge | Routed drainage adds a coupling that the solver must converge. | {doc}`non-convergence`. |

With {toml}`route_drainage|flow.sinks_sources.sfr.<name>.route_drainage` on, the code does not
cap the SFR Picard iterations at one, as it does without it. A run that stops at a stress
period is therefore a solver question first, and the solver guide is the place to start.

## Next

- Every key of the network: {toml}`flow.sinks_sources.sfr`.
- The lake that the network can feed: {doc}`lakes-and-reservoirs`.
- How the model makes streams, in plain words: {doc}`../understand/stream-network`.
- Compare the simulated network with an observed one: {doc}`calibrate-on-the-stream-network`.
- When the solver stops: {doc}`non-convergence`.
