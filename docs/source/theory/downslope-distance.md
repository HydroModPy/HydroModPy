# Downslope distance between two networks

A mapped stream network and a simulated one rarely coincide. This page defines
how far apart they are, measured along the paths the water takes, and the
criterion built on that distance, the method of {cite:t}`abherve2023`. It
answers one question. Given a model that makes a network of streams and a map
that draws another, how long is the walk downslope from one to the other, in
each direction, and at which value of the calibrated ratio do the two walks
balance?

How a model makes streams in plain words is on
{doc}`../understand/stream-network`. The keys of a calibration on a network are
in {doc}`../reference/parameters/calibration/outputs`.

:::{note}
**Scope.** The page covers the distances, the criterion, what it identifies, and
how the mapped network is drawn on the mesh. The simulated network itself, from
the release flux to the flowing cells, is on {doc}`exits/simulated-network`. The
search that moves a parameter until the criterion reaches zero is described only
where it shapes the criterion.
:::

::::{dropdown} Notation of this page
Every cell $n$ has a centre $x_n$ and an area $a_n$. A distance is a length in
metres along cell-to-cell links, centre to centre. Sets of cells are written with
capital letters.

```{hmp-notation}
```
::::

(downslope-graph)=
## The graph the distances follow

A distance follows a flow path, and a flow path exists only where the
depressions are resolved. The code floods the model top on the mesh with the
priority flood of {doc}`exits/routing-on-the-mesh`, {eq}`eq-flood`, seeded on
the border of the active domain, and reads the receivers $r(n)$ of
{eq}`eq-receiver` on the flooded copy. The edge length $\ell(n)$ is the distance
from the centre of $n$ to the centre of $r(n)$.

The flood is seeded on the whole border, where water leaves the model, not on
the outlet alone: sealing one outlet would fill a valley of the buffer up to a
col of the divide. The criterion does not read the descent $D$ the build stores
({ref}`routing-criterion-graph`). The map is never burned into the surface: an
observation never enters the routing surface or the model top.

(downslope-distance-to-set)=
## 1. The downslope distance to a set

For a target set $T$, the distance from a cell to $T$ is the length of its
descent down to the first cell of $T$:

$$
d_T(n) =
\begin{cases}
0 & n \in T, \\
\ell(n) + d_T\bigl(r(n)\bigr) & n \notin T,\ r(n) \text{ exists}, \\
+\infty & n \notin T,\ r(n) \text{ does not exist.}
\end{cases}
$$ (eq-downslope-distance)

With one receiver per cell, exactly one descending path leaves a cell, so there
is no shortest path to search for. The distance is not a Euclidean nearest
distance: a source fifty metres from a stream but across a divide is far away
downslope. And it is not symmetric: $d_{\mathcal{O}}$ on the simulated cells and
$d_{\mathcal{S}}$ on the mapped cells differ, which is what lets one cost weigh an
excess of simulated stream against a missing one. An empty target gives
$+\infty$ everywhere and does not raise: an empty simulated network is the
legitimate end of a search interval.

```{eval-rst}
.. plot:: theory/figures/downslope_toy_grid.py
   :alt: Two copies of an 8 by 8 grid with receiver arrows. Squares mark the mapped network along the valley, dots the simulated network, which stops halfway up and adds two hillside cells. Numbers give the distance of each cell to the other network.

   Two networks on an 8 by 8 grid of 10 m cells, with the receivers of the
   flooded top. Left: from each simulated cell down to the map, the two hillside
   cells walk 42 m. Right: from each mapped cell down to the simulated network,
   the three upper cells walk 10, 20 and 30 m. The two means differ, and so do
   the cells that carry them. Every number is a call of
   ``downslope_distance_to_mask``.
```

In the code: `downslope_distance_to_mask`.

(downslope-catchment)=
## 2. The outlet, the catchment and the saturation length

The outlet $o$ closes the catchment, usually at the gauging station. With
$A_d(n) = a_n + \sum_{m : r(m) = n} A_d(m)$ the area drained through $n$, the
outlet is the most drained cell within two neighbour rings of the cell nearest
to the pour point the catchment was delineated from (two cells is the
`SnapPourPoints` distance of the paper, read on the mesh). Without a pour point,
the most drained cell of the delineated polygon closes the catchment, and without
the polygon the largest basin of the mesh does, with a warning.

The catchment scored, and the longest descent in it, are read on the same graph:

$$
\Omega_o = \{\, n : d_{\{o\}}(n) < \infty \,\}, \qquad
L_{cap} = \max_{n \in \Omega_o} d_{\{o\}}(n) .
$$ (eq-catchment)

The delineated polygon builds the domain and places the outlet; it is not the
support. Their symmetric difference over the area of the polygon is published as
`catchment_mismatch`, with a warning above five per cent. $L_{cap}$ is static: it
is the value an unreachable cell takes in the means ({ref}`downslope-means`).

In the code: `resolve_outlet`.

(downslope-networks)=
## 3. The two networks on the cells

**The simulated network** $\mathcal{S}$ is the downstream closure of the
sources $\Sigma$, the cells whose release flux exceeds a share of their own
recharge, {eq}`eq-sources`. The release flux is the union of
{eq}`eq-release-flux`, the same union for the criterion and for the stored
field. A steady phase reads one state of the run.

**The mapped network** $\mathcal{O}$ is a set of lines, drawn on the cells by
one of two rules chosen by
{toml}`observed_rasterization|calibration.outputs.<name>.observed_rasterization`.

*Heads* (the default) keeps only where the map says a stream starts, and lets the
receiver graph draw the rest: the path a ditch gave a mapped line is something a
model on a DEM cannot reproduce, and drawn cell by cell it would count as error.

1. The lines are merged between junctions and free ends.
2. A free end is a head when the largest drained area within the radius $r_s$ of
   it does not exceed the same quantity at the other end of its reach. The
   drained area decides, never the direction the line was drawn in.
3. A head lands on the nearest active cell within $r_s$ that drains at least
   $A_{d,\min}$, or is lost.
4. From each landing cell, the trace follows the receivers until the descent ends
   or meets a traced cell.
5. The foot of each dam of a lake with a declared spillway is a forced head: the
   stream under a reservoir has no free end. Only the MODFLOW 6 build stores the
   dam feet.

The traced map is connected to the outlet by construction.

```{eval-rst}
.. plot:: theory/figures/downslope_heads.py
   :alt: A toy valley with three mapped lines running beside the talweg. Two upstream free ends are kept as heads with their snap radius; the downstream free end is rejected. The drawn map follows the talweg from the two landing cells to the outlet.

   The heads rule on a toy valley of 25 m cells, from one call of
   ``trace_from_heads``. The two upstream free ends drain less than the
   confluence and are kept; the downstream end drains more and is not a head.
   The drawn map follows the descent of the model, not the line.
```

*Crossing* keeps a cell when a mapped line crosses the segment joining the
centres of two cells that share an edge: on a structured grid, the cell medians,
which is what the WhiteboxTools tool `VectorLinesToRaster` of the paper tests.
The map is one cell wide, like the simulated network. A reach that crosses no
segment marks the cell holding its midpoint instead, and the count is published
per trial as `n_observed_features_fallback`. This is the rule for a map that is
not a tree: canals, braids, polders, karst.

In the code: `trace_from_heads`.

(downslope-supports)=
## 4. The supports and the targets

The means are taken over the catchment, without the water bodies $\mathcal{E}$:

$$
\Omega_o^\ast = \Omega_o \setminus \mathcal{E}, \qquad
\mathcal{S}^\ast = \mathcal{S} \cap \Omega_o^\ast, \qquad
\mathcal{O}^\ast = \mathcal{O} \cap \Omega_o^\ast .
$$ (eq-supports)

- $\mathcal{S}$ is closed downslope, $\mathcal{O}$ is taken as drawn: closing the
  map would build observation out of the DEM.
- The target of $D_{so}$ is $T_{so} = \mathcal{O} \cup \mathcal{E} \cup \{o\}$.
  The outlet is added because mapped lines may stop short of it.
- The target of $D_{os}$ is $T_{os} = \mathcal{S}$.
- Water bodies stay in the graph and leave both supports: a lake cell in a
  support would add one zero per cell and move the root with the size of the
  lake.

The supports split the cells into three classes, published per trial:
`n_valid` ($\mathcal{S}^\ast \cap \mathcal{O}$, simulated where the map has a
stream), `n_excess` ($\mathcal{S}^\ast \setminus \mathcal{O}$, simulated where it
has none) and `n_missing` ($\mathcal{O}^\ast \setminus \mathcal{S}$, mapped where
the model makes none).

The graph is not cut to $\Omega_o$, the supports are: on a buffered domain many
cells drain out of the basin and never meet the map.

(downslope-means)=
## 5. The two mean distances

Write $\hat d_T(n)$ for the distance in which an unreachable cell takes the
value $L_{cap}$. An unreachable cell is never dropped and never counted as
infinite: $+\infty$ would make the mean infinite, and dropping it would move the
support with the parameter. With $\mu(n)$ the weight of a cell,

$$
D_{so} = \frac{\sum_{n \in \mathcal{S}^\ast} \mu(n)\, \hat d_{T_{so}}(n)}{\sum_{n \in \mathcal{S}^\ast} \mu(n)},
\qquad
D_{os} = \frac{\sum_{n \in \mathcal{O}^\ast} \mu(n)\, \hat d_{T_{os}}(n)}{\sum_{n \in \mathcal{O}^\ast} \mu(n)} .
$$ (eq-means)

With $\mu = 1$, each cell has one vote, as in the paper; with $\mu = a_n$ the
mean is weighted by area, which matters on a mesh refined along the streams.
Both pairs are reported at every trial, and
{toml}`weighting|calibration.outputs.<name>.weighting` selects the one the
criterion reads.

$D_{so}$ large means a simulated network spilling far from the mapped one, an
excess. $D_{os}$ large means a simulated network that never grew to the mapped
one, a deficit. At a balanced point most distances are zero, so the means are
carried by a few cells: they are tail statistics.

The unreachable shares $f_{so}$ and $f_{os}$ are reported on both sides. The bound
{toml}`max_unreachable_fraction|calibration.outputs.<name>.max_unreachable_fraction`
guards $f_{so}$ only: its target does not move between trials, and a large share
means the surface is not conditioned. The target of $f_{os}$ is the simulated
network the calibration moves: at a high conductivity it retracts into the
talwegs, and mapped cells legitimately have nothing left to descend into.

In the code: `mean_downslope_distance`.

(downslope-criterion)=
## 6. The criterion

The criterion is equations 1 to 4 of {cite:t}`abherve2023`:

$$
\begin{aligned}
J_{signed} &= D_{so} - D_{os}, &
J &= \lvert J_{signed} \rvert, \\
D_{optim} &= \tfrac{1}{2}\,(D_{so} + D_{os}), &
r_{optim} &= D_{optim} / h_{obs} .
\end{aligned}
$$ (eq-criterion)

When the simulated network is empty, $D_{so}$ has no support, and the residual
is set to $J_{signed} = -L_{cap}$: the negative value a root search needs at the
end of its interval where nothing seeps.

**The cost is $J$, and its zero is a crossing.** The two curves $D_{so}$ and
$D_{os}$, drawn against the calibrated parameter, cross, and the crossing is the
answer. $D_{optim}$ is large at both ends of a sweep, so it has an interior
minimum, and minimising it is a tempting substitute. It is a different estimator:
nothing places its minimum at the crossing.

```{eval-rst}
.. plot:: theory/figures/downslope_crossing.py
   :alt: Two curves against the calibrated ratio on a log axis. The distance from the simulated to the mapped network falls as the ratio grows, the distance from the mapped to the simulated network rises, and they cross where J is zero. The dotted mean of the two has its minimum further right.

   :math:`D_{so}` and :math:`D_{os}` against :math:`K/\bar N` on a toy
   catchment of 60 by 60 cells of 20 m. No solver runs: a cell is a source when
   the recharge it drains exceeds what a 30 m saturated thickness carries down
   its slope, :math:`\bar N A_d > K B s\,w`, and the map holds the cells
   draining more than 0.03 km². Every distance is a call of the code. The curves
   are steps, because the masks are discrete. The minimum of :math:`D_{optim}`
   (dotted) is not at the crossing.
```

The two estimators are needed and are not interchangeable. Inside one model
structure, $J$ finds the parameter, and $D_{optim}$ cannot separate two points
that both balance. Between structures already balanced at $J = 0$, only
$D_{optim}$ separates them. The code names them apart in
{toml}`metric|calibration.objective_blocks.metric`: `distance_gap` is the cost
$J$ and carries the signed residual; `distance_mean` is $D_{optim}$, a
diagnostic. With two maps, each bound is this same pair evaluated once, and the
cost is the sum of the weighted gaps. A run with a permanent map beside the full
one, in one state, scores the state against the permanent map; the full map is
scored at the same state as a validation and never enters the cost.

In the code: `seepage_distance_cost`.

(downslope-validity)=
## 7. When a result is valid

**The length scale.** $h_{obs}$ is the median distance between the centres of
cells that share an edge, over the mapped cells of $\Omega_o$: the cell size on a
regular grid, the size of the fine cells on a mesh refined along the streams. It
is static, since the map does not move with $K$.

**The bound.** The paper reads $r_{optim} \leq 2$: two cells, one of which
budgets for the error of the map. The code writes it as a length:

$$
D_{optim} \leq V, \qquad V = 2\,\max(h_{obs},\ \sigma_o) .
$$ (eq-validity)

With no declared accuracy, $V = 2 h_{obs}$, the bound of the paper. A declared
accuracy $\sigma_o$ above $h_{obs}$ widens $V$ and leaves $r_{optim}$ comparable
with the paper. A declared
{toml}`validity_length|calibration.outputs.<name>.validity_length` replaces the
computation. The bound is read on the trial the search returns, and qualifies the
value without replacing it: a violation logs a warning, or is refused after the
session is saved when
{toml}`on_roptim_violation|calibration.outputs.<name>.on_roptim_violation` is
`"error"`. Each trial publishes `roptim` and `roptim_valid`.

**The map against the surface.** Wherever the mapped lines do not sit in the
talwegs of the model top, the distances measure a disagreement between two
datasets rather than hydrogeology. The code publishes the share of the
downstream closure of the map that the map itself holds, inside the catchment:

$$
\alpha_o = \frac{\lvert \mathcal{O} \cap \Omega_o \rvert}{\lvert \mathrm{closure}(\mathcal{O}) \cap \Omega_o \rvert},
$$ (eq-alpha)

as `alpha_obs_closure_catchment`. A value below
{toml}`alpha_warning_threshold|calibration.outputs.<name>.alpha_warning_threshold`
logs a warning, once per process.

(downslope-identifies)=
## What the criterion identifies

Take a steady water-table aquifer with drains at the surface whose conductance
is derived from $K$, {eq}`eq-drain-conductance`. Per unit area, the balance of a
cell is

$$
\nabla \cdot \bigl( K\, B\, \nabla h \bigr) + N = \frac{K}{b_d}\,\bigl(h - z^d\bigr)_+ ,
$$ (eq-k-over-n)

with $B$ the saturated thickness ({eq}`eq-saturated-thickness`) and $z^d$ the
drain elevation, the cell top by default. Dividing by $K$ gives

$$
\nabla \cdot \bigl( B\, \nabla h \bigr) + \frac{N}{K} = \frac{1}{b_d}\,\bigl(h - z^d\bigr)_+ ,
$$

which depends on $N/K$ and on the geometry alone. When $K$ is scaled by one
factor everywhere and $N$ keeps its shape, the head field, and so the seepage
mask, the release flux and the criterion, depend only on $K/\bar N$. What the
criterion calibrates is that ratio, not $K$. A $K$ read from it inherits the
recharge series entirely: report $K/\bar N$ and name the recharge beside it.

When the search moves the homogeneous conductivity alone, the report publishes
the ratio with what it rests on: `k_over_r` ($K/\bar N$), `k_optim_m_s`,
`R_mean_m_s` ($\bar N$), `d_sat_m` (the saturated thickness averaged over the
catchment, $\bar B$), and `t_over_r_m` ($T/\bar N = K \bar B / \bar N$, a length).
For any other search they are not published.

This is why a search that moves $K$ is refused when a conductance does not
follow $K$ (see the limits).

(downslope-search)=
## How a search reaches the zero

The masks are discrete, so $J_{signed}$ steps over zero instead of reaching it,
and the zero is a plateau whose width sets how precisely the parameter is known.
A bisection therefore stops on the width of its bracket, on a logarithmic
transform, never on the size of the residual. A coarse sweep runs first and sees
every crossing; a bracket with no sign change is reported, not closed. The
options are on {doc}`../reference/calibration-methods`.

## Assumptions

- Water leaves a cell by one receiver (single flow direction).
- The model top, flooded on the mesh graph, is the surface water follows.
- Distances are lengths along links between cell centres, not straight lines.
- The mapped network is independent of the DEM. It is never burned into the
  surface.
- The release flux is the whole of what leaves the aquifer for the surface.
- For the reading of $K/\bar N$: the state is steady, the drain conductance
  follows $K$, and $K$ is scaled by one factor while $N$ keeps its shape.
- The threshold $\tau_\mathrm{s}$ and the mean recharge $\bar N$ are frozen over a
  search.

## Limits

What the code refuses:

- a trial where more than the bound of the simulated support never reaches the
  map: the surface still holds depressions;
- a mapped network that lands on no active cell, or on no cell of the catchment.
  The message names the CRS as the first suspect;
- a heads rule that draws no stream: no free end on an active cell, every free
  end draining more than the other end of its reach, or every head lost;
- a release record in the budget that no declared package reads, which would
  report its water as dry land;
- a search that moves a conductivity while a drain has a fixed conductance, or
  while SFR or LAK is active: those conductances do not follow $K$, so
  {eq}`eq-k-over-n` does not hold. A search driving another parameter gets a
  warning instead;
- a bisection on more than one parameter, or on a parameter without a
  logarithmic transform.

What the code does not represent:

- **Monotonicity.** The criterion does not prove that $J_{signed}$ varies one way
  with the parameter. It checks it on a sweep.
- **$r_{optim}$ is not a quality indicator.** It measures agreement with the map,
  and it moves with the grid: refining a mesh lowers $h_{obs}$ and raises
  $r_{optim}$ at constant agreement. Two verdicts are comparable when their
  validity lengths are.
- **Tail statistics.** Reading $r_{optim} \leq 2$ as "the typical gap is under
  two cells" is wrong when the median distance is zero.
- **The surface is not repaired.** {toml}`dem_correc_type|geographic.dem_correc_type`
  conditions the DEM before the catchment is delineated (`fill`, the tool of the
  paper, or `breach` {cite:p}`lindsay2016breaching`, or `capped_breach`). The
  criterion always floods the model top on the mesh; a breached raster reaches it
  only through the domain and the outlet.
- **Domain of validity.** The method was built for unconfined aquifers in a
  temperate humid climate, with gentle gradients and a strong groundwater-stream
  connection. Outside that, the criterion still computes, and it means less.

## Parameters of this page

```{hmp-params}
calibration.objective_blocks.metric
calibration.outputs.<name>.variable
calibration.outputs.<name>.observed_network
calibration.outputs.<name>.stream_geometry_path
calibration.outputs.<name>.minimal_stream_geometry_path
calibration.outputs.<name>.tau_specific_ratio
calibration.outputs.<name>.weighting
calibration.outputs.<name>.diagonal_neighbors
calibration.outputs.<name>.observed_rasterization
calibration.outputs.<name>.heads_snap_radius
calibration.outputs.<name>.heads_min_drained_area_km2
calibration.outputs.<name>.observed_position_accuracy
calibration.outputs.<name>.validity_length
calibration.outputs.<name>.on_roptim_violation
calibration.outputs.<name>.max_unreachable_fraction
calibration.outputs.<name>.alpha_warning_threshold
calibration.method_options
geographic.dem_correc_type
solver.drain_bed_thickness_m
```

The keys of a calibration on a network are in
{doc}`[calibration.outputs] <../reference/parameters/calibration/outputs>`.

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.core.topographic_distance
hydromodpy.core.depression_filling
hydromodpy.core.stream_geometry
hydromodpy.core.stream_heads
hydromodpy.core.stream_network
hydromodpy.calibration.metrics.downslope_network
hydromodpy.calibration.criteria.hydrographic_network_distance
```

## In the code

| What | Where |
|---|---|
| The flood on the mesh graph | `hydromodpy/core/depression_filling.py` |
| The receivers and the distance to a set | `hydromodpy/core/topographic_distance.py` |
| The outlet, the catchment, $h_{obs}$, $V$, the supports | `hydromodpy/core/stream_geometry.py` |
| The heads rule | `hydromodpy/core/stream_heads.py` |
| The crossing rule | `hydromodpy/spatial/mesh/ops/vector_cell_mask.py` |
| The means and the criterion | `hydromodpy/calibration/metrics/downslope_network.py` |
| The two estimators | `hydromodpy/calibration/criteria/hydrographic_network_distance.py` |
| The root search | `hydromodpy/calibration/optim/adapters/bisection_adapter.py` |

## See also

- {doc}`../reference/parameters/calibration/outputs`: the keys of a calibration on
  the network, the two-bound mode of a transient run included.
- {doc}`exits/simulated-network`: the sources, the closure and the diagnostics
  against a map.
- {doc}`../understand/stream-network`: how the model makes streams, in plain
  words.
- {doc}`bibliography`: the full list of references.
