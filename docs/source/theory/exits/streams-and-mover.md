# Streams and the water mover

A stream network (SFR) routes the water it receives from reach to reach and
exchanges water with the aquifer through its bed. The water mover (MVR) hands
the outflow of one package to another: a drain to a reach, a reach to a lake, a
lake to a reach. Both need MODFLOW 6. The keys of a network are in
{doc}`../../reference/parameters/flow/sinks_sources/sfr`.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(streams-reach)=
## What a reach is

An SFR network is a set of reaches. Each reach $j$ has a length $L_j$, a width
$w_j$, a gradient $S_j$, a bed top $z^{\mathrm{rtp}}_j$, a bed thickness $b_s$, a
bed conductivity $K_b$ and a Manning roughness $n_M$. It exchanges water with
the aquifer cell under it, and passes its flow to the reach below.

The reaches are the cells that the generated stream network crosses, cut by the
mesh, or the rows of an explicit table of reaches. An observed network never
becomes a reach. With
{toml}`rectify_on_mesh|flow.sinks_sources.sfr.<name>.rectify_on_mesh`, the cells
of the generated network are the seeds of a single-flow-direction channel
re-derived on the descent $D$ ({doc}`routing-on-the-mesh`): from every seed, the
receivers of $D$ are followed one cell at a time until the trace reaches a lake,
a fixed-head cell or a channel cell already traced. The result is one cell wide,
continuous on $D$, follows the thalweg of $D$, and ends at a real sink. Short
parallel stubs beside a longer channel are demoted to hillslope drainage. Each
cell keeps the width, the stream order and the bed properties of the seed whose
trace reached it. The gradient is $S_j = \max(S_j^{\mathrm{delineated}}, S_\mathrm{min})$.

In the code: `rectify_reach_graph`.

(streams-bed)=
## The bed

The beds of a network are placed by one solve, in two passes. The cell is the hard
constraint and the downhill order the soft one. Each reach has a box from its own
cell:

$$
z^{\mathrm{bot}}_j + b_s + 0.1\ \mathrm{m} \;\leq\; z^{\mathrm{rtp}}_j \;\leq\; z^{\mathrm{top}}_j - \beta_\mathrm{inc},
$$ (eq-reach-box)

where $z^{\mathrm{top}}_j$ and $z^{\mathrm{bot}}_j$ are the top and the bottom of
the reach cell, and $\beta_\mathrm{inc}$ is zero when the incision is not set. A
bed never sits above the ground of its own cell. When the incision is set, the
bed may also not sink more than
{toml}`max_bed_sag|flow.sinks_sources.sfr.<name>.max_bed_sag` below the upper
bound. An empty box stops the build and names the reach. Inside the boxes the bed
descends downstream by at least $S_\mathrm{min}$ times the mean length of two
neighbouring reaches. Where a traced channel climbs and the box and the order
cannot both hold, the box wins and the build logs the worst step, so a defect of
the trace cannot drag a bed far below the ground of its cell.

In the code: `solve_reach_bed_profile`.

(streams-flow)=
## Flow and exchange

The flow out of reach $j$ is what comes in plus what the reach gains:

$$
Q_j = \sum_{k \in \mathrm{up}(j)} f_{kj}\,Q_k + Q^{\mathrm{ext}}_j + Q^{\mathrm{ro}}_j
+ w_j L_j\,(P - E) + Q^{\mathrm{gw}}_j + Q^{\mathrm{mvr}}_j.
$$ (eq-reach-flow)

$f_{kj}$ is the share of reach $k$ that goes to $j$: 1, unless $k$ is a
bifurcation, whose shares sum to 1. $Q^{\mathrm{ext}}$ is the inflow of the
headwater reaches, split by drainage area. $Q^{\mathrm{ro}}_j$ is the share of
reach $j$ in the catchment runoff of the period ({doc}`../forcing`), distributed
over the reaches by length. $P$ and $E$ are the rain and the evaporation on the
open channel. $Q^{\mathrm{mvr}}$ is what the mover hands to the reach.

The exchange with the aquifer goes through the streambed. MODFLOW 6 takes the
head of the aquifer, or the bottom of the bed when the head is lower
{cite:p}`langevin2017`:

$$
Q^{\mathrm{gw}}_j = C^{\mathrm{sb}}_j\,\Bigl(\max\bigl(h_j,\ z^{\mathrm{rtp}}_j - b_s\bigr) - s_j\Bigr),
\qquad C^{\mathrm{sb}}_j = \frac{K_b\,A^{\mathrm{sb}}_j}{b_s}.
$$ (eq-reach-exchange)

$h_j$ is the head of the cell under the reach, $s_j$ the stage of the reach, and
$A^{\mathrm{sb}}_j$ the wetted area of the bed, which MODFLOW 6 computes from the
width, the length and the stage. A positive $Q^{\mathrm{gw}}$ is water the aquifer
gives to the stream. The reach switches between connected and disconnected at
$z^{\mathrm{rtp}}_j - b_s$. The stage comes from Manning's equation for the
rectangular section MODFLOW 6 assumes, with $A^\mathrm{x}_j$ the flow area and
$R_{h,j}$ the hydraulic radius:

$$
Q_j = \frac{1}{n_M}\,A^\mathrm{x}_j\,R_{h,j}^{2/3}\,S_j^{1/2}.
$$ (eq-manning)

With {toml}`connected_to_aquifer|flow.sinks_sources.sfr.<name>.connected_to_aquifer`
off, the network is pure routing and has no exchange with the aquifer.

A cell that hosts a connected reach loses its drain row: its baseflow goes into
the stream through the bed, not out of the model through a drain. The drain rows
of the cells around stay, and `route_drainage` sends their outflow to the stream
(below).

(streams-numerics)=
## The numerical choice

MODFLOW 6 can skip the extra Picard iterations of SFR when the reaches are
numbered from upstream to downstream. HydroModPy numbers them that way and sets
the maximum to 1, except when `route_drainage` is on. The mover then feeds the
reaches, and that exchange belongs to the nonlinear coupling, not to the routing
order: one pass per outer iteration would let the inflow creep while the head has
settled.

In the code: `build_sfr_package_args`.

(streams-mover)=
## The water mover

The MVR package takes water from a provider, a feature of one package, and gives
it to a receiver, a feature of another, by a rule. The rule acts on the flow
$Q_{\mathrm{avail}}$ the provider has available, with the value $v$ of the record:

$$
Q^{\mathrm{FACTOR}} = v\,Q_{\mathrm{avail}}, \qquad
Q^{\mathrm{UPTO}} = \min(v,\ Q_{\mathrm{avail}}), \qquad
Q^{\mathrm{EXCESS}} = \max(Q_{\mathrm{avail}} - v,\ 0).
$$ (eq-mover)

The fourth rule, THRESHOLD, is all or nothing above the value. HydroModPy writes
records for three connections, and writes MVR last, after every package it names.

| Provider | Receiver | Rule | Set by |
|---|---|---|---|
| a drain cell of the basin | the first reach or lake met on $D$ | FACTOR, value 1 | {toml}`route_drainage\|flow.sinks_sources.sfr.<name>.route_drainage` |
| a terminal reach | a lake | the rule of the network | {toml}`outflow_to_lake\|flow.sinks_sources.sfr.<name>.outflow_to_lake` |
| a lake outlet | another lake, a reach, or the reach at the foot of the dam | the rule of the outlet | {toml}`flow.sinks_sources.lakes.<name>.outlets.mover.mvrtype` |

```{eval-rst}
.. plot:: theory/figures/exits_mover.py
   :alt: A graph of boxes. A drain cell of the basin sends its water by FACTOR 1 to the first reach or lake met on D; the network routes it to a terminal reach, which sends it to a lake; a lake outlet sends water to a dam-foot reach or another lake.

   The three connections of the mover. The orange arrows are MVR records, with
   their rule and the key that sets them. The dashed arrow is the routing of SFR
   itself.
```

(streams-route-drainage)=
## Routing the hillslope drainage

With `route_drainage`, every drain cell in the basin of $D$ hands its whole
outflow to the water body it would physically reach. The walk starts at the
drain cell and follows the receivers of $D$, the version that stops on a
fixed-head cell. It ends at the first connected reach cell or lake cell. A cell
whose chain leaves the model first keeps a plain drain, and so does a cell outside
the basin.

The basin is the set of cells whose chain passes through the catchment outlet.
The outlet follows the rule of the stream criterion: the most drained cell near
the outlet the catchment was closed on, else inside the catchment polygon, else
the largest basin of the domain.

On a quad mesh $D$ steps along diagonals, and a chain can cross a reach between
two cells that only touch at a corner. When both cells beside a diagonal step are
reach cells, the walk ends on the lower of the two.

The provider of a record is the position of the drain in the list of its period.
The drain must therefore be static, with a single period of data: a series of
conductances would renumber the providers and send the water to the wrong place,
and the build refuses it. The budget stores the part the mover took as its own
record, `drain_to_mover`.

```toml
base_config = "step4_transient.toml"

[geographic.river_network]
enabled = true
threshold_mode = "area_km2"
threshold_area_km2 = 0.1

[flow]
active_bc = ["drainage", "sfr"]

[flow.sinks_sources.sfr.main]
route_drainage = true
```

In the code: `build_drainage_mover_records`.

## Assumptions

- A reach is one cell wide, has one downstream reach (or the declared
  bifurcation), and has a rectangular section.
- The bed of a reach and its cell are one: the reach exchanges with the cell
  under it.
- Water routed by the mover reaches its receiver in the same period.

## Limits

- **SFR and MVR need MODFLOW 6.** The check stops a file that lists `"sfr"` and
  names another solver.
- **One SFR network per model.** A second one stops the build.
- **A bed near the water table toggles.** MODFLOW 6 switches a reach between
  connected and disconnected at $z^{\mathrm{rtp}}_j - b_s$. A bed placed near the
  depth the water table reaches in a season can change state at every outer
  iteration and stall the solve. The box of {eq}`eq-reach-box` keeps every bed
  inside its cell for this reason.
- **No overland flow beyond SFR and the mover.** The runoff reaches the streams
  as a forcing, not through the ground.

## Parameters of this page

```{hmp-params}
geographic.river_network.enabled
flow.sinks_sources.sfr.<name>.streambed_k
flow.sinks_sources.sfr.<name>.streambed_thickness
flow.sinks_sources.sfr.<name>.manning
flow.sinks_sources.sfr.<name>.min_slope
flow.sinks_sources.sfr.<name>.bed_incision
flow.sinks_sources.sfr.<name>.max_bed_sag
flow.sinks_sources.sfr.<name>.connected_to_aquifer
flow.sinks_sources.sfr.<name>.rectify_on_mesh
flow.sinks_sources.sfr.<name>.route_drainage
flow.sinks_sources.sfr.<name>.outflow_to_lake
flow.sinks_sources.lakes.<name>.outlets.mover.mvrtype
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.solver.modflow6.builders.sfr
hydromodpy.solver.modflow6.builders.mvr
```

## In the code

| What | Where |
|---|---|
| The network, the package, the mover records of a network | `hydromodpy/solver/modflow6/builders/sfr.py` |
| The bed | `hydromodpy/solver/modflow6/builders/_sfr_bed.py` |
| The channel on $D$ | `hydromodpy/solver/modflow6/builders/sfr_rectify.py` |
| Hillslope drainage to the streams | `hydromodpy/solver/modflow6/builders/_sfr_drainage.py` |
| The mover records | `hydromodpy/solver/modflow6/builders/mvr.py` |
