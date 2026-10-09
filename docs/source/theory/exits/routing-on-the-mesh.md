# Routing on the mesh: the descent D

A drain releases water in its cell. Where that water goes next, and which cells
the water of a cell flows through, is a question of routing. A mesh top has pits
that a DEM routed on its own grid never had, and a pit holds the water it
receives. Routing needs a surface on which every cell has a way down. The model
top is not that surface, and raising it would change the ground the solver sees.
The descent $D$ solves this on a copy: the copy is filled, the receivers of every
cell are read on it, and it never goes back to the solver. The drain elevations,
the streambeds and the reach tops keep reading $z_\mathrm{top}$.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(routing-flood)=
## The flood

$D$ is the result of a priority flood {cite:p}`barnes2014priority`. Its seeds
are the cells of the rim of the routable domain and the fixed-head cells
({doc}`head-boundaries`). The flood visits the cells in order of their filled
level, from the lowest seed up. A cell $m$ reached from a cell $n$ of filled level
$\tilde z_n$ takes

$$
\tilde z_m =
\begin{cases}
\tilde z_n + \epsilon_m & \text{if } z_{\mathrm{top},m} \leq \tilde z_n + \eta,\\
z_{\mathrm{top},m} & \text{otherwise.}
\end{cases}
$$ (eq-flood)

The step $\epsilon_m$ is 1 mm. When the run has a channel network (below), the
step is 1 mm on the channel cells and 2 mm elsewhere, so that a filled flat
climbs faster away from the channel than along it and its steepest descent heads
into the channel.

The tolerance $\eta$ is twice the drop under which the receiver graph sees no
descent. With $\Delta z$ the range of the top over the routable cells, in metres,

$$
\eta = 2 \max\bigl(10^{-9},\ 10^{-9} \max(\Delta z,\ 1)\bigr)\ \mathrm{m},
$$ (eq-flood-tolerance)

that is $2 \times 10^{-9}$ m when the relief is under a metre, and
$2 \times 10^{-9}$ times the relief above. A cell within $\eta$ of the flood
level is raised too, so that no link of the receiver graph drops by less than the
tolerance of that graph.

A lake is crossed, never used as a seed. Its cells keep their top and are
flooded to their spill level like any depression. The lake drains through its
outlet, and the cells below a dam keep draining downstream. The role of a sink
belongs to the walks that read $D$: they stop at the first lake cell.

In the code: `build_descent`.

(routing-receivers)=
## The receivers

On the filled copy, the receiver $r(n)$ of a cell is the neighbour with the
steepest drop per metre, among the neighbours lower by more than the tolerance
$\eta_r = 10^{-9} \max(\Delta\tilde z,\ 1)$ m, where $\Delta\tilde z$ is the
range of the filled copy:

$$
r(n) = \underset{m \in \mathcal{N}_D(n),\ \tilde z_n - \tilde z_m > \eta_r}{\arg\max}\
\frac{\tilde z_n - \tilde z_m}{\lVert x_n - x_m \rVert},
\qquad r(n) = -1 \text{ if there is none.}
$$ (eq-receiver)

The filled range is a little wider than the range of the top, and the factor 2
of {eq}`eq-flood-tolerance` covers that difference.

The distance is between cell centres, so a diagonal step on a square grid is
$\sqrt 2$ cells long and wins only when it is steeper. The neighbours
$\mathcal{N}_D(n)$ are the cells that share a node with $n$ on a quad mesh (the
D8 descent, diagonals included) and the cells that share a face on any other
mesh. A seed keeps its steepest descent too, so that an accumulation passes
through a fixed-head cell. The walks that must end where water leaves the model
read the receiver with $-1$ on the fixed-head cells.

Every link of $D$ descends, so the receiver chains never cycle and every
routable cell reaches a seed. The build refuses a $D$ where a cell has no way
down.

(routing-pit)=
## A pit, by hand

A 3 by 3 grid of squares of 10 m, with a pit in the middle and a lower cell on
the south side. The seeds are the eight rim cells, and a seed keeps its top. The
flood starts at the lowest, the south cell at 4 m, and reaches the centre. The
centre is below the flood level, so it takes $4 + 0.001$ m.

```{eval-rst}
.. plot:: theory/figures/exits_pit.py
   :alt: Two 3 by 3 grids. On the left, the tops: 5 m everywhere except 3 m in the centre and 4 m on the south side. On the right, the filled copy, where the centre holds 4.001 m, and arrows from each cell to its receiver.

   The model top, and the filled copy with the receiver of each cell, from one
   call of ``build_descent``. The five northern cells drain to the centre, now
   the lowest neighbour. The two southern corners drain to the south cell: it
   drops 1 m over 10 m, the centre 0.999 m over 14.1 m. The centre drains south.
   The south cell has no lower neighbour, and water leaves the model there. The
   pit is raised on :math:`D` only: its top in the solver stays 3 m.
```

(routing-channel)=
## The channel tree

When the run generates a stream network (see
{doc}`streams-and-mover`), $D$ follows it. That network was
traced on the D8 pointer of the DEM routing. On the mesh, a cell that holds a
pixel of it is a channel cell, and it is pinned to the next channel cell along
the network. A pinned cell drains to its pin, adjacent or not, even where the top
climbs along the channel. Without the pins, $D$ would descend its own flats by
flood order and run beside the channel, and the hillslope would join the river
lower down. A cell outside the channel keeps its steepest descent. A run with
{toml}`geographic.river_network.enabled` off has no pinned cell.

(routing-uses)=
## What D is used for

- The stream reaches are re-derived as a single-flow-direction channel on its
  receivers ({doc}`streams-and-mover`).
- With `route_drainage`, each drain cell hands its outflow to the first reach or
  lake its chain meets ({doc}`streams-and-mover`).
- The outflow of each cell accumulates on it ({doc}`simulated-network`).
- The flow direction figure reads its receivers, and the heads rule of the
  stream criterion reads the foot of each dam stored with it.

Both MODFLOW solvers build it at every run and store it with the mesh. A run
stored without it gets one rebuilt on read from the stored top, without pins,
fixed-head seeds or lakes, and the log says so. MODFLOW-NWT seeds $D$ on the
cells it writes as a fixed head, and builds no stream head and no lake.

(routing-criterion-graph)=
## The graph of the stream criterion

The stream-network criterion ({doc}`../downslope-distance`) does not read $D$.
It floods its own copy of the model top with the same flood, and reads its
receivers with {eq}`eq-receiver`. The two answer two questions: $D$ routes water
in the model, the criterion graph measures distances on the top. They differ in
these ways.

| | The descent $D$ | The criterion graph |
|---|---|---|
| Seeds | the rim of the routable domain and the fixed-head cells | the border of the active domain |
| Lakes | crossed, flooded to their spill level | part of the graph, removed from the supports of the means |
| Channel | pinned to the generated network | free |
| Raised cells | below the flood level, or within $\eta$ above it | below the flood level |
| Neighbours | D8 on a quad mesh | D8 on a quad mesh unless {toml}`diagonal_neighbors\|calibration.outputs.<name>.diagonal_neighbors` is false |

Both use the step $\epsilon$ of 1 mm off a channel. The flood and the receivers
always read the same neighbour graph: a flood that walked eight neighbours while
the receivers read four would leave filled cells that spill over a diagonal the
receivers cannot take.

## Assumptions

- Water leaves a cell by one receiver (single flow direction).
- The filled copy is a computation. It changes no head and no elevation the
  solver reads.

## Limits

- **Meshes without diagonals.** On a mesh whose faces are not all quadrilaterals,
  the neighbours are the cells sharing a face, whatever the key asks.
- **A run stored before $D$ was kept** routes on a $D$ rebuilt without pins,
  fixed-head seeds or lakes.

## Parameters of this page

```{hmp-params}
geographic.river_network.enabled
calibration.outputs.<name>.diagonal_neighbors
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.core.descent
hydromodpy.core.depression_filling
hydromodpy.solver.modflow_common.mesh_descent
```

## In the code

| What | Where |
|---|---|
| The flood, the receivers, the pins | `hydromodpy/core/descent.py` |
| The flood of the criterion | `hydromodpy/core/depression_filling.py` |
| $D$ on a solver mesh, the channel pins | `hydromodpy/solver/modflow_common/mesh_descent.py` |
| $D$ in the run store | `hydromodpy/solver/modflow_common/descent_store.py` |
