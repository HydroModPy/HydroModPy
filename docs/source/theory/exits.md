# How water leaves the aquifer

Water enters the saturated zone as recharge and leaves it through a few exits.
Each exit is a boundary package of the solver, with its own law: a drain where
the water table reaches the ground, a fixed head at the sea, a stream that routes
what it receives, a lake that stores it. These pages give the law of each exit,
the way HydroModPy builds it, and how the cells where the water table reaches
the surface become a simulated network. To set up a run, see
{doc}`../guides/route-streams-with-sfr` and
{doc}`../guides/lakes-and-reservoirs`.

:::{note}
**Scope.** MODFLOW 6 builds every exit below. MODFLOW-NWT builds the drains, the
sea, the side heads and the evapotranspiration package, and no stream, lake or
water mover: a file that lists `"sfr"`, `"lake"` or `"reservoir"` in
{toml}`flow.active_bc` with another solver in {toml}`solver.backend` is refused
when it is read. The Boussinesq solver has its own surface exchange, on
{doc}`boussinesq`.
:::

::::{dropdown} Notation of this page
Heads and elevations are in metres above the datum. A flux through a cell is in
m³/s, a flux per unit of area in m/s. Every symbol of the site is on
{doc}`notation`.

```{hmp-notation}
```
::::

(exits-table)=
## The exits in one table

| Exit | Law | MODFLOW 6 | MODFLOW-NWT | Switched on by | Page |
|---|---|---|---|---|---|
| Drain at the ground surface | one-sided, head dependent | DRN | DRN | `"drainage"` in {toml}`flow.active_bc` | {doc}`exits/drains-and-et` |
| Evapotranspiration from the water table | linear in depth | EVTA | EVT | `"etp"` in {toml}`flow.active_sinks_sources`, or a negative recharge | {doc}`exits/drains-and-et` |
| Sea | fixed head | CHD | BAS and CHD | `"ocean"` in {toml}`flow.active_bc` | {doc}`exits/head-boundaries` |
| River head, lateral heads | fixed head | CHD | lateral heads only | `"stream"`, `"west_side"` and the other sides | {doc}`exits/head-boundaries` |
| Lake or reservoir | storage, head dependent bed and banks | LAK | none | `"lake"` or `"reservoir"` | {doc}`exits/lakes` |
| Stream network | routed flow, head dependent streambed | SFR | none | `"sfr"` | {doc}`exits/streams-and-mover` |
| Transfer between exits | a rule on a provider flow | MVR | none | a mover key of an exit | {doc}`exits/streams-and-mover` |

Wells are a prescribed flux and are not an exit of these pages. Recharge is not
an exit either, but the evapotranspiration it leaves behind is drawn by an exit
package, so both are on {doc}`exits/drains-and-et`.

```{eval-rst}
.. plot:: theory/figures/exits_column.py
   :alt: Cross-section of five columns of three layers. The first holds a fixed head in every layer, the second a drain below the top and the extinction depth of the evapotranspiration, the third a stream reach with its bed inside its cell, the last two a lake over an inactive top layer with a vertical and a bank connection.

   One cross-section, five columns, each with the exit the build gives it. A fixed
   head holds every layer of its column. A drain sits at the top of its cell, or
   half a band lower. A reach replaces the drain of its cell and keeps its bed
   inside the cell. A lake makes its top layer inactive and exchanges with the
   cells below and beside it.
```

Where the water goes once a drain has released it, and why a mesh needs a
routing surface of its own, is on {doc}`exits/routing-on-the-mesh`. Which cells
count as flowing streams is on {doc}`exits/simulated-network`.

(exits-order)=
## The order the build assembles them

The order matters, because each exit masks the others.

1. The lake cells are made inactive in their top layers, so that every other
   exit sees the aquifer without them.
2. The fixed heads are placed: sea, river, sides.
3. The descent $D$ is built from the model top, the fixed-head cells and the
   lakes.
4. The recharge and the evapotranspiration are written, with no recharge on a
   lake cell.
5. The drains are written on every cell, minus the cells that host a reach or a
   lake bed.
6. The lake, then the stream network, then the water mover, which names the
   packages above.

In the code: `run_pre_processing`.

(exits-budget)=
## The budget closes

Every exit has a budget term $\Phi_{n,p}$, the flow into cell $n$ from package
$p$, positive into the aquifer. Over the cells and a period of length
$\Delta t$, the terms close against the change of storage $\Delta S$:

$$
\sum_n N_n\,a_n + \sum_n \sum_{p} \Phi_{n,p} = \frac{\Delta S}{\Delta t} ,
\qquad p \in \{\mathrm{evt},\ \mathrm{drn},\ \mathrm{drn\to mvr},\ \mathrm{sfr},\ \mathrm{lak},\ \mathrm{chd},\ \mathrm{wel}\} .
$$ (eq-exits-budget)

The terms are stored as `recharge`, `evapotranspiration`, `drain`,
`drain_to_mover`, `stream`, `lake`, `constant_head`, `well` and `storage`. The
part of the drain handed to the mover leaves the aquifer through its own record
and enters the stream or the lake as water from the mover, so the package budgets
of SFR and LAK close the rest. The solver reports the percent discrepancy of this
sum, {eq}`eq-discrepancy`.

## Assumptions common to every exit

- A drain acts on the top layer. A fixed head acts on every layer of its column.
  A reach and a lake exchange with the cells that hold them.
- The recharge, the rain and the ETP are constant over a stress period.
- Water routed by the mover reaches its receiver in the same period.
- No overland flow is solved. A drain that is not routed discharges where it is,
  and the water leaves the model there. The water balance counts it, and no
  surface routing carries it on.

```{toctree}
:maxdepth: 1

exits/head-boundaries
exits/routing-on-the-mesh
exits/drains-and-et
exits/lakes
exits/streams-and-mover
exits/simulated-network
```

## Parameters of this page

```{hmp-params}
flow.active_bc
flow.active_sinks_sources
solver.backend
```

Example 04 declares the drains alone:

```{hmp-resolved} flow.active_bc
:config: step4_transient.toml
```

## In the code

| What | Where |
|---|---|
| The order of the build | `hydromodpy/solver/modflow6/build.py` |
| What a file may say about an exit | `hydromodpy/physics/flow/boundary_condition_registry.py`, `hydromodpy/physics/flow/sinks_sources/` |

## See also

- {doc}`soil-reservoir` and {doc}`forcing`: the recharge and the ETP that reach
  the exits.
- {doc}`downslope-distance`: how a simulated network is scored against a mapped
  one.
- {doc}`solvers`: the stress packages each solver builds.
