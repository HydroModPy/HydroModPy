# Lakes and reservoirs

A lake is a boundary package laid on the aquifer grid. Its cells are made
inactive in their top layers, and the LAK package of MODFLOW 6 holds the storage
and the exchange through connections it builds itself. The stage is a result.
The keys of a lake are in {doc}`../../reference/parameters/flow/sinks_sources/lakes`.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(lakes-balance)=
## The balance

The LAK package of MODFLOW 6 solves a water balance of the lake: the stage
$s_L$ is the unknown, and the volume $V_L$ and the surface area $A_L$ are looked
up in the stage-volume-area table of the lake. The lake gains rain, runoff and
managed inflow, loses evaporation, withdrawal and outlet discharge, and exchanges
with the aquifer through its connections
([input guide](https://modflow6.readthedocs.io/en/latest/_mf6io/gwf-lak.html),
{cite:p}`langevin2017`, chapter 7). The outlets go to the outside, to another
lake or to the mover ({doc}`streams-and-mover`).

HydroModPy checks the table before MODFLOW 6 sees it. The table has at least two
rows. The stage increases strictly, the volume increases strictly with it, the
surface area does not decrease, and no volume or area is negative.

In the code: `build_lake_table`.

(lakes-connections)=
## The connections

MODFLOW 6 gives each connection the conductance of the bed and the aquifer in
series, $C^\mathrm{lak}_c$, from the leakance $\lambda_b$ and the contact area. A
leakance of zero seals the bed. HydroModPy builds two kinds of connection for
each lake column:

- one vertical connection to the first active cell under the occupied layers:
  the leakage towards the aquifer, through the vertical conductivity;
- one horizontal connection per occupied layer across every edge shared with an
  active neighbour that is not a lake cell: the bank seepage, through the
  horizontal conductivity. Its width is the length of the shared edge, its length
  the distance from the neighbour centre to the edge, and its elevations those of
  the neighbour layer clipped to the vertical extent of the lake.

A cutoff wall seals the horizontal connections to the cells behind it.

In the code: `build_lake_connectiondata`.

(lakes-footprint)=
## Two ways to hold the footprint

In the fixed-area mode, the footprint cells are inactive and the table alone
gives the storage. In the active-shore mode,
{toml}`dynamic_area|flow.sinks_sources.lakes.<name>.bed_reconstruction.dynamic_area`,
the bed cells stay active with the carved bathymetry as their top. A cell
exchanges with the lake while it is under water, and recharges as land when the
shore falls below its bed. The drain rows of those cells are removed: a drain
there would send the leakage of the lake straight back to the streams, through the
aquifer, the drain and the mover, and the exchange would recirculate.

(lakes-forcing)=
## What falls on the lake

The rain and the evaporation of a lake are the catchment means of the loaded
precipitation and ETP, unless the lake declares its own. The runoff is the
catchment runoff rate times the catchment area $A$. It reaches the lake directly
only when no stream network routes the runoff; otherwise it arrives through the
reaches and the mover ({doc}`../forcing`). A declared forcing wins over these
defaults.

The managed inflow and the withdrawal are set to zero in the steady periods. A
steady period has no storage term, and a managed flux that does not balance the
natural budget has no equilibrium stage: the solve would diverge.

By default the stage is free from the first period. With
{toml}`steady_stage_hold|flow.sinks_sources.lakes.<name>.steady_stage_hold`, and a
run that starts with a steady period, the build holds it at the starting stage
(LAK status constant) through the steady warm-up, and frees it on the first
transient period. A managed reservoir whose
observed level is far from the natural equilibrium then keeps that level, and the
aquifer settles around it.

The package takes one smoothing depth for the wet and dry transition of the lake
edge, {toml}`surfdep|flow.sinks_sources.lakes.<name>.surfdep`: the largest
declared among the lakes.

(lakes-mask)=
## The mask on the other packages

The lake cells carry no recharge and no aquifer evapotranspiration: the lake
takes its own rain and evaporates through LAK. Without the mask, MODFLOW 6 would
hand the recharge of an inactive lake cell to the first active cell below it, and
the rain would be counted twice ({doc}`drains-and-et`).

## Limits

- **A lake has one stage.** The volume and the surface area follow the table, and
  the lake exchanges with the cells under and beside its footprint, and with no
  other.
- **A lake needs MODFLOW 6.** The check stops a file that declares one with
  another solver.
- **A lake in soil mode needs a stream network.** The check refuses a lake
  without `"sfr"` when the soil reservoir is declared, because the water that
  seeps out of the ground reaches the lake only through the streams.
- **The active-shore mode is harder for the solver.** Many cells change between
  wet and dry at once. A larger
  {toml}`surfdep|flow.sinks_sources.lakes.<name>.surfdep` helps, and blurs the
  shoreline.

## Parameters of this page

```{hmp-params}
flow.sinks_sources.lakes.<name>.bedleak
flow.sinks_sources.lakes.<name>.surfdep
flow.sinks_sources.lakes.<name>.steady_stage_hold
flow.sinks_sources.lakes.<name>.bed_reconstruction.dynamic_area
flow.sinks_sources.lakes.<name>.outlets.mover.mvrtype
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.solver.modflow6.builders.lake
```

## In the code

| What | Where |
|---|---|
| Table, connections, period data | `hydromodpy/solver/modflow6/builders/lake.py` |
| Outlets | `hydromodpy/solver/modflow6/builders/_lake_outlets.py` |
