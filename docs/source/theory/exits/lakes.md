# Lakes and reservoirs

A lake is a boundary package laid on the aquifer grid. Its cells are made
inactive in their top layers, and the LAK package of MODFLOW 6 holds the storage
and the exchange through connections it builds itself. The stage is a result.
To set up a lake, see {doc}`../../guides/lakes-and-reservoirs`.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(lakes-balance)=
## The balance

The volume of a lake changes with the water it gains and loses:

$$
\frac{dV_L}{dt} = A_L\,(P_L - E_L) + Q^{\mathrm{ro}} + Q^{\mathrm{in}} - Q^{\mathrm{wd}}
- Q^{\mathrm{out}} + \sum_{c} C^\mathrm{lak}_c\,(h_c - s_L),
\qquad V_L = V_L(s_L),\quad A_L = A_L(s_L).
$$ (eq-lake-balance)

The stage $s_L$ is the unknown. The volume and the surface area come from the
stage-volume-area table of the lake, which MODFLOW 6 reads as a lookup. $P_L$
and $E_L$ are the rain and the evaporation per unit of lake surface. The runoff
$Q^{\mathrm{ro}}$, the managed inflow $Q^{\mathrm{in}}$ and the withdrawal
$Q^{\mathrm{wd}}$ are volumes per time. The sum runs over the connections $c$ of
the lake with the aquifer, $h_c$ being the head of the connected cell, and a
positive term is water the lake gains. $Q^{\mathrm{out}}$ is the discharge of the
outlets, to the outside, to another lake or to the mover
({doc}`streams-and-mover`). The exact form of the outlets is that of MODFLOW 6
{cite:p}`langevin2017`.

The table is checked before MODFLOW 6 sees it. The stage increases strictly, the
volume increases strictly with it, the surface area does not decrease, and no
volume or area is negative.

In the code: `build_lake_table`.

(lakes-connections)=
## The connections

Each connection carries a conductance, the resistances of the bed and of the
aquifer in series:

$$
C^\mathrm{lak}_c = \left(\frac{1}{\lambda_b\,A_c} + \frac{1}{C^{\mathrm{aq}}_c}\right)^{-1}.
$$ (eq-lake-connection)

$A_c$ is the contact area and $C^{\mathrm{aq}}_c$ the conductance of the aquifer
cell towards the lake face. A leakance of zero seals the bed and gives a
conductance of zero. HydroModPy builds two kinds of connection for each lake
column:

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
there would send the leakage of the lake straight back to the streams, through
the aquifer, the drain and the mover, and the exchange would recirculate.

(lakes-forcing)=
## What falls on the lake

The rain and the evaporation of a lake are the watershed means of the loaded
precipitation and ETP, unless the lake declares its own. The runoff is the
catchment runoff rate times the catchment area $A$. It reaches the lake directly
only when no stream network routes the runoff; otherwise it arrives through the
reaches and the mover ({doc}`../forcing`). A declared forcing wins over these
defaults.

The managed inflow and the withdrawal are set to zero in the steady periods. A
steady period has no storage term, and a managed flux that does not balance the
natural budget has no equilibrium stage: the solve would diverge.

The package takes one smoothing depth for the wet and dry transition of the lake
edge, {toml}`surfdep|flow.sinks_sources.lakes.<name>.surfdep`: the largest
declared among the lakes.

(lakes-mask)=
## The mask on the other packages

The lake cells carry no recharge and no aquifer evapotranspiration: the lake
takes its own rain and evaporates through LAK. Without the recharge mask,
MODFLOW 6 would hand the recharge of an inactive lake cell to the first active
cell below it, and the rain would be counted twice ({doc}`drains-and-et`).

## Assumptions

- A lake has one stage. The volume and the surface area follow the table.
- A lake exchanges with the cells under and beside its footprint, and with no
  other.

## Limits

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
