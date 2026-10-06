# How water leaves the aquifer

Water enters the saturated zone as recharge and leaves it through a few exits. Each exit is
a MODFLOW 6 boundary package with its own law: a drain that discharges where the water
table reaches the ground, a fixed head at the sea, a stream that routes what it receives,
a lake that stores it. This page gives the law of each exit, the way HydroModPy builds it,
the descent D that decides where drained water goes next, and how the cells where the water
table reaches the surface become a simulated active network. It does not say how to set up
a run: for that, see {doc}`../guides/route-streams-with-sfr` and
{doc}`../guides/lakes-and-reservoirs`.

:::{note}
**Scope.** Every exit below is built by MODFLOW 6. MODFLOW-NWT builds the drains, the sea,
the side heads and the evapotranspiration package, and no stream, lake or water mover. A file
that lists `"sfr"`, `"lake"` or `"reservoir"` in {toml}`flow.active_bc` and names another
solver in {toml}`solver.backend` is refused when it is read. The Boussinesq solver has its own surface exchange, in
{doc}`boussinesq`. The descent D is built by both MODFLOW solvers.
:::

## The exits in one table

| Exit | Law | MODFLOW 6 | MODFLOW-NWT | Switched on by |
|---|---|---|---|---|
| Drain at the ground surface | one-sided, head dependent | DRN | DRN | `"drainage"` in {toml}`flow.active_bc` |
| Sea | fixed head | CHD | BAS and CHD | `"ocean"` in {toml}`flow.active_bc` |
| River head, lateral heads | fixed head | CHD | lateral heads only | `"stream"`, `"west_side"` and the other sides |
| Stream network | routed flow, head dependent streambed | SFR | none | `"sfr"` |
| Lake or reservoir | storage, head dependent bed and banks | LAK | none | `"lake"` or `"reservoir"` |
| Water transfer between exits | rule on a provider flow | MVR | none | a mover key of an exit |
| Evapotranspiration from the water table | linear in depth | EVTA | EVT | `"etp"` in {toml}`flow.active_sinks_sources`, or a negative recharge |

Wells are a prescribed flux and are not covered here. Recharge is not an exit, but its
package and the evapotranspiration it leaves behind are built next to the exits and are
written in section 3.

## What the build does, in order

The MODFLOW 6 build (`hydromodpy/solver/modflow6/build.py`, `run_pre_processing`) puts the
exits together in this order. The sections below follow it.

1. The lake cells are made inactive, so that the other exits see the aquifer without them.
2. The constant-head supports are built: sea, river, sides (section 1).
3. The descent D is built from the model top, the constant-head cells and the lakes
   (section 2).
4. The SFR reaches are resolved on the mesh. The package itself waits.
5. The recharge package RCHA and the evapotranspiration package EVTA are written
   (section 3).
6. The drains are written, minus the cells that host a reach or a lake bed, and the
   hillslope drainage is routed on D when asked (sections 4 and 7).
7. The constant-head rows are merged into one CHD package.
8. The lake package LAK is written (section 5).
9. The stream package SFR is written (section 6).
10. The water mover MVR is written last, because it names the packages above (section 7).

After the run, the derived fields that build the simulated active network read the budget and
the stored D (section 8).

## Notation

Heads and elevations are in metres above the datum. Fluxes through a cell are in m³/s.
Fluxes per unit of area are in m/s. The index $i$ is a cell of the mesh, $\ell$ a layer and
$t$ a stress period.

| Symbol | Meaning | Unit | Read from |
|---|---|---|---|
| $h_{\ell,i}$ | head of the aquifer | m | state, not a field |
| $z_{T,i}$ | top of the model in cell $i$, as the solver sees it | m | state, not a field |
| $\tilde z_i$ | the filled copy of the top that D descends | m | state, not a field |
| $A_i$ | area of cell $i$ | m² | state, not a field |
| $K_i$ | hydraulic conductivity of the top layer in cell $i$ | m/s | {toml}`flow.param.K.field.value` |
| $C_i$ | drain conductance | m²/s | {toml}`flow.bc.<name>.value`, or derived from $K_i$ |
| $b$ | thickness of the drain bed | m | {toml}`solver.drain_bed_thickness_m` |
| $C_{\min}$ | floor of every drain conductance | m²/s | {toml}`solver.drain_conductance_floor_m2_s` |
| $\delta$ | depth of the discharge band of a drain (called D on its field card) | m | {toml}`solver.drain_band_depth_m` |
| $h_\mathrm{sea}(t)$ | sea level of period $t$ | m | {toml}`flow.bc.<name>.value` of `ocean` |
| $R_i$ | recharge flux into cell $i$ | m/s | {toml}`flow.sinks_sources.recharge`, or the soil reservoir |
| $e_i$ | evapotranspiration the aquifer may still be asked for | m/s | {toml}`flow.sinks_sources.etp`, or the soil reservoir |
| $d$ | extinction depth of the evapotranspiration | m | {toml}`flow.sinks_sources.etp.extinction_depth`, {toml}`modflow6.process_specific.evt_extinction_depth` |
| $o$ | distance of the evapotranspiration surface below its reference | m | {toml}`flow.sinks_sources.etp.surface_offset` |
| $K_b$ | hydraulic conductivity of a streambed | m/s | {toml}`streambed_k\|flow.sinks_sources.sfr.<name>.streambed_k` |
| $b_s$ | thickness of a streambed | m | {toml}`streambed_thickness\|flow.sinks_sources.sfr.<name>.streambed_thickness` |
| $n$ | Manning roughness of a reach | s/m^(1/3) | {toml}`manning\|flow.sinks_sources.sfr.<name>.manning` |
| $S_{\min}$ | floor of the gradient of a reach | - | {toml}`min_slope\|flow.sinks_sources.sfr.<name>.min_slope` |
| $\lambda$ | leakance of a lake bed | 1/s | {toml}`bedleak\|flow.sinks_sources.lakes.<name>.bedleak` |
| $V(s)$, $A_s(s)$ | volume and surface area of a lake at stage $s$ | m³, m² | the stage-volume-area table of the lake, {doc}`../guides/lakes-and-reservoirs` |
| $\epsilon$ | step of the flood that builds D | m | constant of the code, not a field |
| $\eta$ | tolerance of the flood, twice the drop under which the receiver graph sees no descent | m | constant of the code, not a field |
| $\tau$ | share of its own recharge a cell must release to seep | - | {toml}`tau_specific_ratio\|calibration.outputs.<name>.tau_specific_ratio` |
| $\Phi_\mathrm{vis}$ | routed discharge a cell must carry to flow | m³/s | {toml}`visible_flow\|calibration.outputs.<name>.extent.visible_flow` |
| $\rho_i$, $q_i$, $F_i$ | release flux, drain outflow, accumulated flux of cell $i$ | m³/s | state, not a field |

## 1. Fixed heads: the sea, the rivers and the sides

A fixed head takes the head out of the solution. In every layer of a constant-head cell,

$$
h_{\ell,i}(t) = h^{\mathrm{bc}}(t),
$$

and the flux across the cell is a result. It is stored in the budget as `constant_head`.
The head of a period is the value that the boundary, or its forcing, gives for that period.

The sea cells are the cells of the model domain whose DEM is not above the highest sea level
of the run:

$$
\mathcal{O} = \{\, i \in \text{domain} : \mathrm{dem}_i \leq \max_t h_\mathrm{sea}(t) \,\}.
$$

A cell below the sea level on land, far from the coast, is in the set. The code does not test
the connection to the sea. A sea level of 0 m is declared as follows, and the drains stay.

```toml
base_config = "step4_transient.toml"

[flow]
active_bc = ["drainage", "ocean"]

[flow.bc.ocean]
value = 0.0
```

The river cells are the river cells of the mesh support, or the cells with the
{toml}`support_label|flow.bc.<name>.support_label` given to the boundary. A side boundary is
the cells along one side of the model. A cell that falls in two sets keeps the last head
written, in the order sea, river, side. Because one CHD package carries the three, the build
writes which cells are sea and which are river in a file beside the solver files
(`<model>.chd_roles.json`). The extraction reads it to tell a river head from a sea head.

The fixed head is a Dirichlet condition. It is not a conductance-limited exchange of the GHB
or RIV kind, and HydroModPy builds neither of those packages. A river that must exchange
through a streambed is an SFR network (section 6).

Where it is in the code: `build_ocean_boundary_chd_spd`, `build_stream_boundary_chd_spd`,
`build_side_boundary_chd_spd` and `assemble_constant_head_stress_period_data`, in
`hydromodpy/solver/modflow6/builders/boundary_conditions.py`.

## 2. The descent D

A mesh top has pits that a DEM routed on its own grid never had, and a pit holds the water
it receives. Routing needs a surface on which every cell has a way down. The model top is
not that surface, and raising it would change the ground the solver sees. D solves this on a
copy. The copy is filled, the receivers of every cell are read on it, and it never goes back
to the solver. The drain elevations, the streambeds and the reach tops keep reading
$z_T$.

### The flood

D is the result of a priority flood. Its seeds are the cells of the rim of the routable
domain and the constant-head cells of section 1. The flood visits the cells in order of
their filled level, from the lowest seed up. A cell $j$ reached from a cell $i$ of filled level
$\tilde z_i$ takes

$$
\tilde z_j =
\begin{cases}
\tilde z_i + \epsilon_j & \text{if } z_{T,j} \leq \tilde z_i + \eta,\\
z_{T,j} & \text{otherwise.}
\end{cases}
$$

The tolerance $\eta$ is twice the drop under which the receiver graph sees no descent, about $10^{-9}$ of the range of the top. A cell
within it of the flood level is raised too, so that no receiver link ever drops by less
than the tolerance of the receiver graph. The step $\epsilon_j$ is 1 mm. When the run has a
channel network A (below), the step is 1 mm on the channel cells and 2 mm elsewhere, so that
a filled flat climbs faster away from the channel than along it and its steepest descent
heads into the channel.

A lake is crossed, never used as a seed. Its cells keep their value of $z_T$ and are
flooded to their spill level like any depression. The lake drains through its outlet, and the
cells below a dam keep draining downstream. The role of a sink belongs to the walks that
read D: they stop at the first lake cell.

### The receivers

On the filled copy, the receiver $r(i)$ of a cell is its steepest descent per metre among
the neighbours that are lower than it by more than the tolerance:

$$
r(i) = \underset{j \in N(i),\ \tilde z_i - \tilde z_j > \eta}{\arg\max}\
\frac{\tilde z_i - \tilde z_j}{\lVert x_i - x_j \rVert},
\qquad r(i) = -1 \text{ if there is none.}
$$

The distance is between cell centres. The neighbours $N(i)$ are the cells that share a node
with $i$ on a quad mesh (the D8 descent, diagonals included), and the cells that share a face
on any other mesh. A seed keeps its steepest descent too, so that an accumulation passes
through a constant-head cell. The walks that must end where water leaves the model read
the receiver with $-1$ on the constant-head cells.

By construction every link of D descends, so the receiver chains never cycle and every
routable cell reaches a seed. The build refuses a D where a cell has no way down.

### The channel tree

When the run has the generated river network A (see
{doc}`../guides/route-streams-with-sfr`), D follows it. A was traced on the D8 pointer of the
DEM routing. On the mesh, a cell that holds a pixel of A is a channel cell, and it is pinned to
the next channel cell along A. A pinned cell drains to its pin, adjacent or not, even where
$z_T$ climbs along A. Without this, D would descend its own flats by flood order and run
beside A, and the hillslope would join the river lower down. A cell outside A keeps its
steepest descent. A run without A, because {toml}`geographic.river_network.enabled` is
off, has no pinned cell.

### What D is used for

- The SFR reaches are re-derived as a single-flow-direction channel on its receivers
  (section 6).
- With `route_drainage`, each drain cell hands its outflow to the first reach or lake its
  chain meets (section 7).
- The per-cell discharge accumulates on it (section 8).
- The flow direction figure reads its receivers, and the heads rule of the stream criterion
  reads the dam feet stored with it, the cell below the dam of each lake whose spillway is
  declared.

Every MODFLOW 6 and MODFLOW-NWT build computes it, writes it beside the model as
`<model>.descent.npz`, and the extraction stores it with the run, in the `mesh` group of the
field store, with the mesh. A run stored without it gets one rebuilt on read from the stored
top, without channel pins, constant-head seeds or lakes, and the log says so. An auxiliary
model, a steady initialization or a spin-up cycle, is never extracted, and builds D only
when one of its SFR networks walks it. MODFLOW-NWT seeds D on the cells it writes as
constant head (`ibound` of -1, or a CHD row). It builds no stream head and no lake.

### A pit, by hand

A 3 by 3 grid of squares of 10 m, with a pit in the middle and a lower cell on the south side.
The tops in metres, from the north row to the south row:

| | west | middle | east |
|---|---|---|---|
| north | 5 | 5 | 5 |
| centre | 5 | 3 | 5 |
| south | 5 | 4 | 5 |

The seeds are the eight rim cells, and a seed keeps its top. The flood starts at the lowest,
the south cell at 4 m, and reaches the centre. The centre is below the flood level, so it takes
$4 + 0.001$ m.

| Cell | Receiver on D | Why |
|---|---|---|
| north, west, east, north-west, north-east | centre | the centre, at 4.001 m, is the lowest neighbour |
| south-west, south-east | south | the south cell drops 1 m over 10 m, the centre 0.999 m over 14.1 m |
| centre | south | the only lower neighbour |
| south | none | no neighbour is lower: water leaves the model here |

These numbers come from one call of `build_descent` on this grid. The pit is raised on D
only. Its top in the solver stays 3 m.

Where it is in the code: `build_descent` and `descent_graph` in `hydromodpy/core/descent.py`;
`build_solver_mesh_descent`, `project_channel_tree` and `write_descent_sidecar` in
`hydromodpy/solver/modflow_common/mesh_descent.py`; `write_descent_sidecar_to_store` in
`hydromodpy/solver/modflow_common/descent_store.py`.

## 3. Recharge in, residual evapotranspiration out

### The recharge package

MODFLOW 6 receives the recharge as one array per stress period (RCHA). The flux into a column
is $R_i A_i$. The package puts it on the top layer, and on the first active layer below
when the top cell is inactive. That reassignment is what the lake mask prevents: on a lake
cell, whose top layers are inactive, the recharge is set to zero, because the lake takes its
own rain through the package LAK. Without that mask the rain would be counted twice.

The recharge comes from a series or a grid that the run loads, or from the daily soil
reservoir of {doc}`soil-reservoir`. How a daily series becomes one value per stress period is
in {doc}`forcing`. A negative recharge is a climatic deficit $E^{\mathrm{def}}_i$. With
{toml}`flow.sinks_sources.recharge.negative_to_evt`, it is clipped out of the recharge and
sent to the evapotranspiration package; the split, and what a steady period receives, are
in section 7 of {doc}`forcing`.

### The evapotranspiration package

MODFLOW 6 and MODFLOW-NWT use the same law {cite}`harbaugh2005,langevin2017`. The package draws water from the cell where
the water table is near the surface $z_s$, at the full rate $e_i$ when the head is at or above
$z_s$, and at a rate that falls linearly to zero at the depth $d$ below it:

$$
Q^{\mathrm{ET}}_i = A_i\, e_i\, \kappa\!\left(\frac{h_i - (z_s - d)}{d}\right),
\qquad \kappa(x) = \min\bigl(1, \max(0, x)\bigr).
$$

Three sources feed it, with a different surface and a different depth.

| Source | Rate $e_i$ | Surface $z_s$ | Depth $d$ |
|---|---|---|---|
| MODFLOW 6, deficit of a negative recharge | $E^{\mathrm{def}}_i$ | $z_{T,i}$ | {toml}`evt_extinction_depth\|modflow6.process_specific.evt_extinction_depth` |
| MODFLOW 6, residual ETP of the soil reservoir | the ETP the soil could not meet | $z_{T,i} - \tfrac{\delta}{2} - o$ | {toml}`extinction_depth\|flow.sinks_sources.etp.extinction_depth` |
| MODFLOW-NWT, loaded ETP and deficit | the ETP as loaded, plus the deficit | $z_{T,i} - o$ | {toml}`extinction_depth\|flow.sinks_sources.etp.extinction_depth` |

In the second row, $\delta$ counts only when drains are active, and $o$ is
{toml}`surface_offset|flow.sinks_sources.etp.surface_offset`. The surface of the soil
residual sits at the drain elevation of the cell (the top, or the top lowered by half of the
band of section 4) because the soil has already taken the ETP it could. What is left may only
draw from the water that would otherwise reach the drain. The field card of the offset says
which value applies to which solver.

The sea cells, the river cells and the lake cells carry no aquifer evapotranspiration. The lake
evaporates through LAK. The deficit of a negative recharge is also kept off the cells that have
no active layer.

The word `"etp"` in {toml}`flow.active_sinks_sources` means three things. Under MODFLOW-NWT the
loaded ETP drives the package. Under MODFLOW 6 it acts only in soil mode, where it sends
the residual ETP of the reservoir to EVTA. The Boussinesq solver rejects it. Outside soil
mode MODFLOW 6 ignores it and logs a warning that starts with `flow.active_sinks_sources lists "etp", and MODFLOW 6 draws no ETP
from the water table outside soil mode`.

Where it is in the code: `mask_recharge_on_lake_cells`, `build_soil_evta_payload`,
`build_evt_array_stress_period_data` in
`hydromodpy/solver/modflow6/builders/recharge.py`; `route_negative_recharge_to_evt` in
`hydromodpy/solver/modflow_common/recharge_evt_routing.py`.

## 4. Drains at the top of the model

### The law

A drain removes water from a cell when the head is above the drain elevation $z^d_i$, in
proportion to the excess:

$$
Q^{\mathrm{drn}}_i = C_i \,\max\bigl(h_i - z^d_i,\ 0\bigr).
$$

This is the law of the DRN package of MODFLOW 6 and MODFLOW-NWT
{cite}`harbaugh2005,langevin2017`. It is one-sided: a drain never feeds the aquifer. In
HydroModPy the drain stands for seepage at the ground surface. There is one row per cell, in the
top layer, at the elevation of the top. The cells that carry no row are the cells outside the
model domain, the sea cells and the river cells of section 1. The rows are dropped later in
the cells that host a connected SFR reach (section 6) and in the cells of a lake bed that stays
active (section 5).

The drain does not read D. The elevation of a drain is $z_{T,i}$, never $\tilde z_i$.

### The conductance

When the file declares a conductance, every cell takes it as a conductance per cell, and the
floor applies:

$$
C_i = \max\bigl(C^{\mathrm{decl}},\ C_{\min}\bigr).
$$

When it declares none, which is the case of example 04, each drain derives its conductance
from the conductivity of its cell:

$$
C_i = \max\!\left(\frac{K_i\,A_i}{b},\ C_{\min}\right).
$$

The thickness $b$ is that of the clogging layer at the bottom of a watercourse. It is not the
thickness of the aquifer layer. The drain is proportional to $K_i$ by construction. A cell passes its own recharge $R_i$ when the head stands above the drain
elevation by

$$
h_i - z^d_i = \frac{R_i A_i}{C_i} = \frac{R_i\, b}{K_i}.
$$

The excess does not depend on the size of the cell. It depends on $K_i/R_i$, which is the
quantity a network calibration searches, and on $b$. The drain is meant to be a seepage face:
$K$ and the recharge decide where the water surfaces, and the drain must not limit it. The floor $C_{\min}$ exists only for
a degenerate cell, with a conductivity of zero for instance, whose formula would
give a conductance that MODFLOW reads as no drain at all.

```toml
base_config = "step4_transient.toml"

[solver]
drain_bed_thickness_m = 0.5
```

### The discharge band

A single drain elevation says that the land inside a cell is flat. The remedy that the USGS
documents is a sub-cell discharge band, not an edit of the elevation: the average undulation
depth of a cell in UZF1, and the depth of the drain band in the DRN package of MODFLOW 6
{cite}`langevin2017`. The depth can be taken from the standard deviation of the fine land
surface elevations inside a cell {cite}`feinstein2020drain`. With a band of depth $\delta$, the
drain sits lower and its conductance grows:

$$
z^d_i = z_{T,i} - \frac{\delta}{2},
\qquad
C^{\delta}_i = C_i\,\frac{b}{\delta}.
$$

The factor is the bed thickness $b$ and not the cell area. The conductance it scales is
already $K_i A_i / b$, so the product is $K_i A_i / \delta$, the conductance of a band of
depth $\delta$. With the derived conductance, $b$ drops out. The cell begins to discharge
before the head reaches its mean elevation, and discharges harder as the head climbs into the
band. No elevation is raised and no DEM is rewritten. Every other package sees the top it
would have seen. MODFLOW 6 solves its own band with a smooth curve. The rule here is the
piecewise equivalent of the same idea, applied alike by both MODFLOW solvers.

```toml
base_config = "step4_transient.toml"

[solver]
drain_band_depth_m = 0.5
```

One reader cannot ignore the band: the seepage criterion of section 8. A banded cell
discharges at $z_{T,i} - \delta/2$ and never climbs back to $z_{T,i}$, so the mask is tested
against that elevation, and the run keeps $\delta$ in its store for every figure drawn later.

### The other answer: remove the drain from the pits

{toml}`solver.sink_fill` sets the conductance to zero in every cell that sits in a closed
depression of the top. The depressions are found on the solver mesh, by a priority flood
seeded on every cell water can leave the domain through, and counted on the four shared
faces that MODFLOW connects, not on the eight neighbours of a raster fill. Both MODFLOW
backends read the same mask. No manual or USGS document removes a discharge boundary where a
pit is detected, and the card of the field says so. The two answers are opposite, and the file
is refused when it sets both.

```toml
# not checked: both keys together are refused when the file is read
base_config = "step4_transient.toml"

[solver]
sink_fill = true
drain_band_depth_m = 0.5
```

The message begins `solver.sink_fill and solver.drain_band_depth_m are two opposite answers
to the same question and cannot both be set`.

### One cell, by hand

A cell of 25 m by 25 m ($A = 625$ m²), $K = 10^{-7}$ m/s, and a recharge of 439 mm per year,
which is $1.39 \times 10^{-8}$ m/s. The conductance and the head the drain needs to pass the
recharge, from `hk_fallback_drain_conductance` and `drain_discharge_band`:

| Drain bed $b$ | Band $\delta$ | $C$ (m²/s) | Elevation | Head above the elevation |
|---|---|---|---|---|
| 30 m | none | $2.08 \times 10^{-6}$ | $z_T$ | 4.17 m |
| 1 m | none | $6.25 \times 10^{-5}$ | $z_T$ | 13.9 cm |
| 0.1 m | none | $6.25 \times 10^{-4}$ | $z_T$ | 1.4 cm |
| 1 m | 0.5 m | $1.25 \times 10^{-4}$ | $z_T - 0.25$ m | 7.0 cm |

The first row is the old choice, the layer thickness taken as the bed. At that thickness the
drain, not the aquifer, limits the discharge. In the last row the head stands 7.0 cm above
the drain at $z_T - 0.25$ m, which is 18 cm under the top of the cell. The cell passes its
recharge without the water table reaching the ground.

### Declared or derived

The declared conductance is {toml}`flow.bc.<name>.value` of the boundary `drainage`. A zero
or a negative number selects the derivation. It does not close the boundary. The conductance
is static unless the value is a series. A period is written only when the declared value
changes, and MODFLOW 6 reuses the last data for the periods that are left out.

Where it is in the code: `build_drain_stress_period_data` in
`hydromodpy/solver/modflow6/builders/boundary_conditions.py`;
`hk_fallback_drain_conductance` and `drain_discharge_band` in
`hydromodpy/solver/modflow_common/drain_conductance.py`; `build_drainage_spd` in
`hydromodpy/solver/modflow_nwt/nwt/payloads/well_drainage.py`.

## 5. Lakes

A lake is a boundary package laid on the aquifer grid. Its cells are made inactive in
the top layers, and the package LAK holds the storage and the exchange through connections it
builds itself. The stage is a result.

### The balance

The volume of a lake changes with the water it gains and loses:

$$
\frac{dV}{dt} = A_s\,(P - E) + Q^{\mathrm{ro}} + Q^{\mathrm{in}} - Q^{\mathrm{wd}}
- Q^{\mathrm{out}} + \sum_{c} C_c\,(h_c - s),
\qquad V = V(s),\quad A_s = A_s(s).
$$

The stage $s$ is the unknown. The volume and the surface area come from the stage-volume-area
table of the lake, which MODFLOW 6 reads as a lookup. $P$ and $E$ are rates per unit of lake
surface, $Q^{\mathrm{ro}}$, $Q^{\mathrm{in}}$ and $Q^{\mathrm{wd}}$ are volumes per time. The
sum runs over the connections of the lake with the aquifer. A positive term of the sum is
water the lake gains from the aquifer. $Q^{\mathrm{out}}$ is the discharge of the outlets,
to the outside, to another lake or to a mover (section 7). The exact form of the outlets is
that of MODFLOW 6 {cite}`langevin2017`.

The table is checked before MODFLOW 6 sees it. The stage increases strictly, the volume
increases strictly with it, the surface area does not decrease, and no volume or area is
negative.

### The connections

Each connection carries a conductance, the two resistances of the bed and of the aquifer in
series:

$$
C_c = \left(\frac{1}{\lambda\,A_c} + \frac{1}{C^{\mathrm{aq}}_c}\right)^{-1}.
$$

$A_c$ is the contact area and $C^{\mathrm{aq}}_c$ the conductance of the aquifer cell towards
the lake face. The leakance $\lambda$ is
{toml}`bedleak|flow.sinks_sources.lakes.<name>.bedleak`. A leakance of zero seals the bed
and gives a conductance of zero. HydroModPy builds two kinds of connection for each lake
column:

- one vertical connection to the first active cell under the occupied layers. It is the
  leakage towards the aquifer, and uses the vertical conductivity.
- one horizontal connection per occupied layer across every shared edge with an active
  neighbour that is not a lake cell. It is the bank seepage, and uses the horizontal
  conductivity. Its width is the length of the shared edge, its length the distance from the
  neighbour centre to the edge, and its elevations the neighbour layer clipped to the
  vertical extent of the lake.

A cutoff wall seals the horizontal connections to the cells behind the wall.

### Two ways to hold the footprint

In the fixed-area mode, the footprint cells are inactive and the table alone gives the
storage. In the active-shore mode,
{toml}`dynamic_area|flow.sinks_sources.lakes.<name>.bed_reconstruction.dynamic_area`, the
bed cells stay active with the carved bathymetry as their top. A cell exchanges with the lake
while it is under water, and recharges as land when the shore falls below its bed. The drain
rows of those cells are removed. A drain there would send the leakage of the lake itself straight back
to the streams, through the aquifer, the drain and the mover, and the exchange would
recirculate.

### What falls on the lake

The rainfall and the evaporation of a lake come from the watershed mean of the loaded
precipitation and ETP, unless the lake declares its own. The runoff is the catchment runoff
rate times the catchment area, and it reaches the lake directly only when no SFR network
routes the runoff: in that case the water arrives through the reaches and the mover.
A declared forcing wins over these defaults. The inflow and the withdrawal are managed
transfers. They are set to zero in the steady periods, because a steady period has no
storage term, and a managed flux that does not balance the natural budget has no equilibrium
stage. The solve would diverge.

The package takes a smoothing depth {toml}`surfdep|flow.sinks_sources.lakes.<name>.surfdep`
for the dry and wet transition of the lake edge. It is one value for the package, the
largest declared among the lakes.

### The mask on the other packages

The lake cells carry no recharge and no aquifer evapotranspiration: the lake takes its own
rain and evaporates through LAK. Without the recharge mask, MODFLOW 6 would hand the recharge
of an inactive lake cell to the first active cell below it, and the rain would be counted twice.

Where it is in the code: `build_lake_connectiondata`, `build_lake_table`,
`build_lak_package_args`, `build_lake_period_data` in
`hydromodpy/solver/modflow6/builders/lake.py`; the outlets in `_lake_outlets.py`.

## 6. Streams

### What a reach is

An SFR network is a set of reaches. Each reach has a length $L_j$, a width $w_j$, a gradient
$S_j$, a bed top $z^{\mathrm{rtp}}_j$, a bed thickness $b_s$, a bed conductivity $K_b$ and a
Manning roughness $n$. It exchanges water with the aquifer cell under it, and passes its
flow to the reach below.

The reaches are the cells that the generated river network A crosses, cut by the mesh, or the
rows of an explicit table of reaches that you write. An observed network never becomes a
reach. With
{toml}`rectify_on_mesh|flow.sinks_sources.sfr.<name>.rectify_on_mesh`, the cells of A are
the seeds of a single-flow-direction channel re-derived on D: from every seed, the receivers
of D are followed one cell at a time until the trace reaches a lake, a constant-head cell or a
channel cell already traced. The result is one cell wide, continuous on D, follows the
thalweg of D, and ends at a real sink. Short parallel stubs next to a longer channel are
demoted to hillslope drainage. Each cell keeps the width, the stream order and the bed
properties of the seed whose trace reached it. The gradient is
$S_j = \max(S_j^{\mathrm{delineated}}, S_{\min})$.

### The bed

A bed is placed by one solve for the network, in two passes. The cell is the hard constraint
and the downhill order is the soft one. Each reach has a box from its own cell,

$$
z^{\mathrm{bot}}_j + b_s + 0.1\ \mathrm{m} \;\leq\; z^{\mathrm{rtp}}_j \;\leq\; z^{\mathrm{top}}_j - \beta,
$$

where $z^{\mathrm{top}}_j$ and $z^{\mathrm{bot}}_j$ are the top and the bottom of the reach cell,
and $\beta$ is {toml}`bed_incision|flow.sinks_sources.sfr.<name>.bed_incision`, zero when it is
not set. A bed never sits above the ground of its own cell, whether the incision is set or
not. When it is set, the bed may also not sink more than
{toml}`max_bed_sag|flow.sinks_sources.sfr.<name>.max_bed_sag` below the upper bound. An empty
box stops the build and names the reach. Inside the boxes the bed descends downstream by at
least $S_{\min}$ times the mean length of two neighbouring reaches. When a traced channel
climbs and the box and the order cannot both hold, the box wins and the build logs the worst
step. A defect of the trace therefore cannot drag a bed far below the ground of its cell.

### Flow and exchange

The flow out of reach $j$ is the sum of what comes in and what the reach gains:

$$
Q_j = \sum_{k \in \mathrm{up}(j)} f_{kj}\,Q_k + Q^{\mathrm{ext}}_j + Q^{\mathrm{ro}}_j
+ w_j L_j\,(P - E) + Q^{\mathrm{gw}}_j + Q^{\mathrm{mvr}}_j.
$$

$f_{kj}$ is the share of reach $k$ that goes to $j$. It is 1 unless $k$ is a bifurcation, in
which case the shares of the reaches it feeds sum to 1. $Q^{\mathrm{ext}}$ is the inflow of
the headwater reaches, split by drainage area. $Q^{\mathrm{ro}}$ is the catchment runoff,
distributed over the reaches by length. $P$ and $E$ are the rainfall and the evaporation
on the open channel. $Q^{\mathrm{mvr}}$ is what the mover hands to the reach (section 7).

The exchange with the aquifer goes through the streambed. MODFLOW 6 takes the head of the
aquifer, or the bottom of the bed when the head is lower:

$$
Q^{\mathrm{gw}}_j = C^{\mathrm{sb}}_j\,\Bigl(\max\bigl(h_j,\ z^{\mathrm{rtp}}_j - b_s\bigr) - s_j\Bigr),
\qquad C^{\mathrm{sb}}_j = \frac{K_b\,A^{\mathrm{sb}}_j}{b_s}.
$$

Here $s_j$ is the stage of the reach and $A^{\mathrm{sb}}_j$ the wetted area of the streambed,
which MODFLOW 6 computes from the width, the length and the stage {cite}`langevin2017`. A
positive $Q^{\mathrm{gw}}$ is water the aquifer gives to the stream. The reach changes
between connected and disconnected at $z^{\mathrm{rtp}}_j - b_s$. The stage comes from
Manning's equation for the section MODFLOW 6 assumes:

$$
Q_j = \frac{1}{n}\,\Omega_j\,R_{h,j}^{2/3}\,S_j^{1/2}.
$$

With {toml}`connected_to_aquifer|flow.sinks_sources.sfr.<name>.connected_to_aquifer` off, the
network is pure routing and has no exchange with the aquifer.

### The drains and the reaches

A cell that hosts a connected reach loses its drain row. The baseflow of that cell goes into
the stream through the streambed, and not out of the model through a drain. The drain rows
of the cells around stay, and `route_drainage` sends their outflow to the stream (section 7).

### The numerical choices

MODFLOW 6 can skip the extra Picard iterations of SFR when the reaches are numbered from
upstream to downstream. HydroModPy numbers them that way, and sets the maximum to 1, except
when `route_drainage` is on. The mover then feeds the reaches, and that exchange belongs to
the nonlinear coupling and not to the routing order. One pass updates it once per outer
iteration, and the inflow creeps. A measured case on the Nancon at 25 m, steady, still read
$4.04 \times 10^{-4}$ at iteration 500 against a criterion of $10^{-4}$, while the head had
settled.

Where it is in the code: `resolve_sfr_networks`, `build_sfr_package_args`,
`build_sfr_mover_records` in `hydromodpy/solver/modflow6/builders/sfr.py`;
`solve_reach_bed_profile` in `_sfr_bed.py`; `rectify_reach_graph` in `sfr_rectify.py`.

## 7. The water mover

The MVR package takes water from a provider, a feature of one package, and gives it to a
receiver, a feature of another, by a rule. The rule acts on the flow $Q_{\mathrm{avail}}$ that
the provider has available, with the value $v$ of the record:

$$
Q^{\mathrm{FACTOR}} = v\,Q_{\mathrm{avail}}, \qquad
Q^{\mathrm{UPTO}} = \min(v,\ Q_{\mathrm{avail}}), \qquad
Q^{\mathrm{EXCESS}} = \max(Q_{\mathrm{avail}} - v,\ 0).
$$

The fourth rule, THRESHOLD, is all or nothing above the value. HydroModPy builds records for
three connections, and writes MVR last, after every package it names.

| Provider | Receiver | Rule | Set by |
|---|---|---|---|
| a drain cell of the basin | the first reach or lake met on D | FACTOR, value 1 | {toml}`route_drainage\|flow.sinks_sources.sfr.<name>.route_drainage` |
| a terminal reach | a lake | the rule of the network | {toml}`outflow_to_lake\|flow.sinks_sources.sfr.<name>.outflow_to_lake` |
| a lake outlet | another lake, a reach, or the reach at the foot of the dam | the rule of the outlet | {toml}`flow.sinks_sources.lakes.<name>.outlets.mover.mvrtype` |

### Routing the hillslope drainage

With `route_drainage`, every drain cell in the basin of D hands its whole outflow to the
water body it would physically reach. The walk starts at the drain cell and follows the
receivers of D, the version that stops on a constant-head cell. It ends at the first
connected reach cell or lake cell. A cell whose chain leaves the model first keeps a plain
drain, and so does a cell outside the basin.

The basin is the set of cells whose chain passes through the catchment outlet. The outlet
follows the rule of the stream criterion: the most drained cell near the outlet the catchment
was closed on, else inside the watershed polygon, else the largest basin of the domain.

On a quad mesh D steps along diagonals, and a chain can cross a reach between two cells that
only touch at a corner. When both cells beside a diagonal step are reach cells, the walk
ends on the lower of the two.

The provider of a record is the position of the drain in the list of its period. The drain
must therefore be static, with a single period of data: a series of conductances would
renumber the providers and send the water to the wrong place. The build says
`flow.sinks_sources.sfr route_drainage requires a static DRN`. The budget carries the part
that the mover took as a record of its own, `drain_to_mover`.

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

Where it is in the code: `build_drainage_mover_records` and `sfr_drain_cells_to_drop` in
`hydromodpy/solver/modflow6/builders/_sfr_drainage.py`; `MoverRecord` and
`build_mvr_period_records` in `hydromodpy/solver/modflow6/builders/mvr.py`; the basin in
`_drainage_basin` of `build.py`.

## 8. Where the water table reaches the surface

The model produces sources, not a stream network. A cell where the aquifer releases water to
the surface is a point of appearance, not a reach. The simulated active network is built from
those points. Four levels lead to it, and they should not be confused:

1. the cells where the water table reaches the drain (the seepage mask);
2. how much water the aquifer releases in each cell (the local release);
3. where that release goes on D (the accumulated flux and the active masks);
4. the cells that the stream criterion counts as flowing (the simulated active network).

### The seepage mask

The water table of a cell is the head of its uppermost layer with a finite head. A cell is
a seepage cell in period $t$ when the water table reaches the drain:

$$
m_i(t) = \begin{cases} 1 & h^{\mathrm{wt}}_i(t) \geq z_{T,i} - \delta/2,\\ 0 & \text{otherwise.}\end{cases}
$$

With no band, $\delta = 0$ and the test is against the top. A solver that reports a surface
release flux of its own (the Boussinesq solver) uses that flux instead: the cell seeps where
the flux is positive. The mask is the geometric answer. It says that the water table reached
the ground, not how much water left.

### The local release

The budget gives the flow through each exit, from the point of view of the aquifer, negative
when the aquifer loses water. `outflow_drain` is the positive part of the drain budget, with
the part handed to the mover, summed over layers:

$$
q_i(t) = \sum_{\ell} \max\!\Bigl(-\bigl(B^{\mathrm{drn}}_{\ell,i}(t) + B^{\mathrm{mvr}}_{\ell,i}(t)\bigr),\ 0\Bigr).
$$

A run that sends its streams through SFR sends most of its water through that package, so the
drain alone misses it. The release flux is the union of every path from the aquifer to the
surface:

$$
\rho_i(t) = q_i(t) + \max(-B^{\mathrm{sfr}}_i, 0) + \max(-B^{\mathrm{lak}}_i, 0)
+ \max(B^{\mathrm{exc}}_i, 0).
$$

The last term is the surface excess of the Boussinesq solver, already an outflow. A constant
head is not in the sum, because a stored constant-head term carries no role: an ocean or a
lateral boundary would count as groundwater released to the surface. The release flux is
rebuilt on read from the per-cell budget, which the run keeps only with
{toml}`simulation.results.budget.spatial_fields`.

### The accumulated flux, on D

The local release is routed downstream on the stored D. In descending order of $\tilde z$, the
accumulated flux of a cell is its own release plus that of every cell whose receiver it is:

$$
F_i = q_i + \sum_{j\,:\,r(j) = i} F_j .
$$

High values mark the confluences and the persistent branches. $F_i$ is a routed diagnostic.
The same water is counted again in every cell downstream, so the sum of $F$ over the cells is
not a water budget. Use the budget and $q_i$ for a mass balance. The same routing, applied to
$\rho_i$, gives the release accumulation. A run stored before D was kept rebuilds one on read,
and the log says so. The Boussinesq solver, whose store holds a top and no mesh connectivity,
routes on a Whitebox D8 raster instead.

A cell is active in period $t$ when a field, $F$ for instance, exceeds a threshold. A time
rule reduces the periods to one mask:

| Mode | Active when |
|---|---|
| `last` | the cell is active at the chosen period, the last by default |
| `any` | the cell is active at least once |
| `persistent` | the cell is active in at least a given share of the periods |
| `always_active` | the cell is active in every period (`perennial` is a synonym) |
| `persistence` | not a mask: the share of the periods where the cell is active |

The default depends on the regime. A steady run uses `last`, since it has one state. A
transient run uses `persistent`, with a share of one half unless another is given. An
always-active mask means active at every period of the window analysed. It is not a synonym of
a steady network.

The accumulated flux is a derived field that the run writes only when asked:

```toml
base_config = "step4_transient.toml"

[simulation.results.derived]
accumulation_flux = true
outflow_drain = true

[simulation.results.budget]
spatial_fields = true
```

### The simulated active network

The network that a calibration scores, and that the stream maps draw, is not a threshold of
$F$. It is built from the release flux $\rho$ on its own graph, in two steps.

A cell seeps in period $t$ when its release exceeds a threshold proportional to its own
recharge, strictly:

$$
\rho_i(t) > \tau\,\bar R\,A_i .
$$

Here $\bar R$ is the unweighted mean of the finite recharge rates over the periods and the
cells, and $\tau$ is
{toml}`tau_specific_ratio|calibration.outputs.<name>.tau_specific_ratio`. The threshold is a
flux per unit of area and not a discharge, so that the network follows the physics and not the
refinement of the mesh. A value of zero is the purely geometric criterion. The test is made on
the flux, which the mass balance anchors, and not on the head, which moves a lot when the drain
conductance moves.

A cell flows when it lies in the downstream closure of the seeping cells, on the receiver graph
of the criterion. When a visible flow $\Phi_\mathrm{vis}$ is set, it must also carry the routed discharge
$\Phi_i$, the release of the seeping cells accumulated down that graph:

$$
\Phi_i(t) = \sum_{j\,:\,j \rightsquigarrow i} \rho_j(t)\,\mathbb{1}[\,j \text{ seeps}\,] \;\geq\; \Phi_\mathrm{vis} .
$$

The sum runs over the seeping cells whose chain passes through $i$. The visible flow is a
discharge with its unit, or a share of the discharge at the outlet at the same period, and zero
is the geometric definition. The routed discharge never falls downstream, so the flowing cells
stay closed downstream whatever the threshold. It is a routed seepage discharge and not a river
discharge: no runoff and no loss in the bed enter it.

The graph of the criterion is the model top conditioned by a priority flood seeded on the
border of the active domain {cite}`barnes2014priority`. D is built the same way, with four
differences: its seeds include the constant-head cells, its lakes are traversed, its channel
cells follow A, and a cell a hair above the flood level is raised too. The two graphs are
therefore not the same, and $F$ and the simulated active network do not share their receivers.

The cells that flow are the field `simulated_active_network`, 1 where a stream flows and 0
elsewhere. It is rebuilt on read from the stored `release_flux` and from a stored network, the
mapped one or the generated one, on which the graph is rebuilt. It is never stored. The read
says why it cannot be served: for a run without the release field the message begins `run has
no per-cell release_flux: set [simulation.results.derived] release_flux = true`. Example 04
sets it.

Over a transient run, the criterion counts for each complete calendar year the periods each
cell flows, and builds a maximal and a minimal extent from those counts. How the result is
scored against a mapped network is in {doc}`downslope-distance`.

Where it is in the code: `seepage_mask`, `release_flux_stack`, `accumulate_on_downhill_graph`
in `hydromodpy/core/field_routing.py`; `compute_derived` in
`hydromodpy/simulation/extraction/derivation/derived.py`; `cell_field_active_mask` in
`hydromodpy/results/derive/views.py`; `build_simulated_network` and
`specific_seepage_threshold` in `hydromodpy/core/stream_network.py`; `flowing_cells` in
`hydromodpy/core/stream_extent.py`; `simulated_active_network_stack` in
`hydromodpy/results/derive/virtual_fields.py`.

## The budget closes

Every exit has a budget term, signed from the point of view of the aquifer. Per period, with
every term counted positive when water leaves the aquifer:

$$
\sum_i R_i A_i = \sum_i Q^{\mathrm{ET}}_i + \sum_i Q^{\mathrm{drn}}_i
+ \sum_i Q^{\mathrm{drn\to mvr}}_i + Q^{\mathrm{sfr}} + Q^{\mathrm{lak}}
+ Q^{\mathrm{chd}} + Q^{\mathrm{wel}} + \frac{\Delta S}{\Delta t}.
$$

The terms are stored as `recharge`, `evapotranspiration`, `drain`, `drain_to_mover`,
`stream`, `lake`, `constant_head`, `well` and `storage`. The part of the drain handed to the
mover leaves the aquifer through the drain record, and enters SFR or LAK as water from the
mover. The package budgets of SFR and LAK close the rest. The solver reports the percent
discrepancy of this sum, and the page {doc}`../guides/non-convergence` says what to read
when it is not small.

## Assumptions

- A drain acts on the top layer. A fixed head acts on every layer. A reach and a lake
  exchange with the cell that holds them.
- A drain is a seepage face: the head the drain itself needs to pass the recharge is small
  beside the thickness of the aquifer.
- The land inside a cell is flat, unless a band is declared.
- The sea is a fixed head, with the level of its period. It does not move inside a period.
- A river head is a fixed head. A river that exchanges through a bed is an SFR network.
- A stream reach is one cell wide, has one downstream cell (or the declared bifurcation),
  and has a rectangular section.
- The bed of a reach and its cell are one. The reach exchanges with the cell under it.
- A lake has one stage. The volume and the surface area follow the table.
- The recharge, the rain and the ETP are constant over a stress period.
- The descent D is a computation. It does not change a head.
- Water routed by `route_drainage` reaches its receiver in the same period.

## Limits

- **No overland flow beyond SFR and the mover.** A drain that is not routed discharges where
  it is, and the water leaves the model there. The water balance counts it, and no
  surface routing carries it on. The runoff of the soil reservoir and a loaded runoff go to
  the streams and the lakes directly, as a forcing, and not through the ground.
- **SFR, LAK and MVR need MODFLOW 6.** The check stops a file that lists them and names
  another solver in {toml}`solver.backend`, with a message that begins `solver.backend='modflow_nwt' does not support the
  'sfr' boundary`.
- **Stream heads need MODFLOW 6 or Boussinesq.** MODFLOW-NWT has the sea and the sides.
- **One SFR network per model.** A second one stops the build, with `one SFR network per
  model is supported`.
- **A lake in soil mode needs a stream network.** The check refuses a lake without `"sfr"`
  when the soil reservoir is declared, because the water that seeps out of the ground
  reaches the lake only through the streams.
- **A drain cell has one elevation.** The band is the one remedy. It applies to every drain
  cell alike, and classifies nothing.
- **The sea is not a density model.** There is no interface between fresh and salt water, and
  no tide inside a period.
- **The sea cells are selected by their DEM.** The two MODFLOW solvers do not select exactly
  the same cells: MODFLOW 6 tests `dem <= level`, and MODFLOW-NWT builds its constant-head
  rows with `dem < level`, and its `ibound` with `dem <= level`.
- **A declared drain conductance has a floor in MODFLOW 6 only.** MODFLOW-NWT takes it as it
  is.
- **A bed near the water table toggles.** MODFLOW 6 switches a reach between connected and
  disconnected at $z^{\mathrm{rtp}} - b_s$. A bed placed near the depth the water table
  reaches in a season changes state at every outer iteration. On the Nancon at 25 m one reach
  that stood above the land surface stalled the daily run on a two-state cycle. The solve
  of the bed keeps every reach inside its cell for this reason.
- **The active-shore mode is harder for the solver.** Many cells change between wet and dry at
  once. A larger {toml}`surfdep|flow.sinks_sources.lakes.<name>.surfdep` helps, and blurs the
  shoreline.
- **The accumulated flux is not a budget.** It counts the same water in every cell
  downstream.
- **The simulated active network is a mask computed on read.** It is not a stored line
  network.
- **Wells are not covered by this page.**

## Parameters of this page

The fields below are the ones that appear in the equations. Open a row for its card.

```{hmp-params}
flow.active_bc
flow.active_sinks_sources
flow.bc.<name>.value
flow.bc.<name>.support_label
solver.drain_bed_thickness_m
solver.drain_conductance_floor_m2_s
solver.drain_band_depth_m
solver.sink_fill
flow.sinks_sources.recharge.negative_to_evt
flow.sinks_sources.etp.extinction_depth
flow.sinks_sources.etp.surface_offset
modflow6.process_specific.evt_extinction_depth
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
flow.sinks_sources.lakes.<name>.bedleak
flow.sinks_sources.lakes.<name>.surfdep
flow.sinks_sources.lakes.<name>.bed_reconstruction.dynamic_area
flow.sinks_sources.lakes.<name>.outlets.mover.mvrtype
calibration.outputs.<name>.tau_specific_ratio
calibration.outputs.<name>.extent.visible_flow
simulation.results.derived.seepage_areas
simulation.results.derived.release_flux
simulation.results.derived.accumulation_flux
simulation.results.derived.outflow_drain
simulation.results.budget.spatial_fields
```

Example 04 declares the drains and no conductance, so every drain derives it from K:

```{hmp-resolved} flow.active_bc
:config: step4_transient.toml
```

## Checked by

The tests that import the code of this page. The box is generated: a new test appears here
on the next build.

```{hmp-tested-by}
hydromodpy.core.descent
hydromodpy.core.field_routing
hydromodpy.core.stream_network
hydromodpy.solver.modflow_common.mesh_descent
hydromodpy.solver.modflow_common.drain_conductance
hydromodpy.solver.modflow_common.boundary_roles
hydromodpy.solver.modflow6.builders.boundary_conditions
hydromodpy.solver.modflow6.builders.recharge
hydromodpy.solver.modflow6.builders.lake
hydromodpy.solver.modflow6.builders.sfr
hydromodpy.solver.modflow6.builders.mvr
hydromodpy.solver.modflow_nwt.nwt.payloads
hydromodpy.simulation.extraction.derivation.derived
hydromodpy.results.derive.views
```

## In the code

| What | Where |
|---|---|
| The order of the build | `hydromodpy/solver/modflow6/build.py` (`run_pre_processing`) |
| Sea, river and side heads | `hydromodpy/solver/modflow6/builders/boundary_conditions.py` |
| The descent D | `hydromodpy/core/descent.py` (`build_descent`) |
| D on a solver mesh, channel pins, sidecar | `hydromodpy/solver/modflow_common/mesh_descent.py` |
| D in the run store | `hydromodpy/solver/modflow_common/descent_store.py` |
| Recharge, EVTA, lake mask | `hydromodpy/solver/modflow6/builders/recharge.py` |
| Drain rows, conductance, band | `hydromodpy/solver/modflow6/builders/boundary_conditions.py`, `hydromodpy/solver/modflow_common/drain_conductance.py` |
| Drains and EVT under MODFLOW-NWT | `hydromodpy/solver/modflow_nwt/nwt/payloads/` |
| Lakes | `hydromodpy/solver/modflow6/builders/lake.py` |
| Stream network and bed | `hydromodpy/solver/modflow6/builders/sfr.py`, `_sfr_bed.py`, `sfr_rectify.py` |
| Hillslope drainage to the streams | `hydromodpy/solver/modflow6/builders/_sfr_drainage.py` |
| The water mover | `hydromodpy/solver/modflow6/builders/mvr.py` |
| Seepage mask, release flux, accumulation | `hydromodpy/core/field_routing.py` |
| Derived fields written after the run | `hydromodpy/simulation/extraction/derivation/derived.py` |
| Active masks and metrics | `hydromodpy/results/derive/views.py` |
| What a file may say about an exit | `hydromodpy/physics/flow/boundary_condition_registry.py`, `hydromodpy/physics/flow/sinks_sources/` |

## See also

- {doc}`../guides/route-streams-with-sfr` and {doc}`../guides/lakes-and-reservoirs`: how to
  set up the two networks.
- {doc}`soil-reservoir` and {doc}`forcing`: the recharge and the residual ETP that enter
  this page.
- {doc}`downslope-distance`: how a simulated network is scored against a mapped one.
- {doc}`index`: the other theory pages.
