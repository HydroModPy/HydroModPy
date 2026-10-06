# Downslope distance between two networks

A mapped stream network and a simulated one rarely coincide. This page defines
how far apart they are, measured along the paths the water takes, and the
criterion built on that distance: the method of {cite}`abherve2023`. It answers
one question. Given a model that makes a network of streams and a map that
draws another, how long is the walk downslope from one to the other, in each
direction, and at which parameter value do the two walks balance?

It gives the equations the code solves, what they assume, and where they stop
being true. It does not say how to set up a calibration: for that, see
{doc}`../guides/calibrate-on-the-stream-network`. For the plain-words story of
how a model makes streams, see {doc}`../understand/stream-network`.

:::{note}
**Scope.** The page covers the distances, the criterion and the way the mapped
network is drawn on the mesh. The search that moves a parameter until the
criterion reaches zero is only described where it shapes the criterion (see
[why the zero is a root](#why-the-zero-is-a-root)). The two-bound mode for a
transient run reuses the same pair of distances once per bound, and is in
{doc}`/guides/calibrate-on-the-stream-network`.
:::

## Notation

Every cell $c$ of the mesh has a centre $x_c$ and an area $a(c)$. A distance is
a length in metres along cell-to-cell links, centre to centre. Sets of cells
are written with capital letters.

| Symbol | Meaning | Unit | Read from |
|---|---|---|---|
| $z(c)$ | elevation of the model top | m | state, not a field |
| $\tilde z(c)$ | the same surface after the flood of step 1 | m | state, not a field |
| $\epsilon$ | slope added at each step inside a filled depression, a constant of the code | m | state, not a field |
| $N(c)$ | neighbours of $c$: the eight D8 neighbours of a quad mesh, or the cells sharing an edge | - | {toml}`diagonal_neighbors\|calibration.outputs.<name>.diagonal_neighbors` |
| $r(c)$ | receiver of $c$, the one cell it drains to | - | state, not a field |
| $\ell(c)$ | distance from $c$ to its receiver $r(c)$, centre to centre | m | state, not a field |
| $d_T(c)$ | downslope distance from $c$ to the set $T$ | m | state, not a field |
| $A(c)$ | area drained through $c$, $c$ included | m2 | state, not a field |
| $o$ | outlet cell that closes the catchment | - | state, not a field |
| $\Omega$ | catchment scored: the cells whose descent reaches $o$ | - | state, not a field |
| $L_{cap}$ | longest finite descent to $o$ inside $\Omega$ | m | state, not a field |
| $q(c)$ | water the aquifer releases to the surface in $c$, positive when it feeds the surface | m3/s | {toml}`variable\|calibration.outputs.<name>.variable` |
| $\bar R$ | mean recharge of the built model | m/s | state, read back from the model |
| $\tau_{ratio}$ | share of its own recharge a cell has to release to count as a source | - | {toml}`tau_specific_ratio\|calibration.outputs.<name>.tau_specific_ratio` |
| $\Sigma$ | seepage cells: the sources | - | state, not a field |
| $S$ | simulated network, the downslope closure of $\Sigma$ | - | state, not a field |
| $O$ | mapped network, drawn on the cells | - | {toml}`observed_rasterization\|calibration.outputs.<name>.observed_rasterization` |
| $E$ | water bodies: lakes and other cells whose surface water is an input | - | state, not a field |
| $\Omega^\ast$ | cells the two means are taken over: $\Omega$ without $E$ | - | state, not a field |
| $w(c)$ | weight of a cell in a mean: 1, or its area $a(c)$ | 1 or m2 | {toml}`weighting\|calibration.outputs.<name>.weighting` |
| $D_{so}$ | mean distance from the simulated network to the mapped one | m | state, not a field |
| $D_{os}$ | mean distance from the mapped network to the simulated one | m | state, not a field |
| $J$ | cost of the criterion, $\lvert D_{so} - D_{os}\rvert$ | m | state, not a field |
| $D_{optim}$ | half the sum of the two means | m | state, not a field |
| $h_{obs}$ | size of one cell where the mapped network lies | m | state, not a field |
| $r_{optim}$ | $D_{optim}$ divided by $h_{obs}$ | - | state, not a field |
| $\sigma$ | positional accuracy of the mapped network | m | {toml}`observed_position_accuracy\|calibration.outputs.<name>.observed_position_accuracy` |
| $V$ | validity length, the bound on $D_{optim}$ | m | {toml}`validity_length\|calibration.outputs.<name>.validity_length` |
| $f_{so}$, $f_{os}$ | share of a support whose descent never meets its target | - | state, not a field |
| $f_{max}$ | largest $f_{so}$ the criterion accepts | - | {toml}`max_unreachable_fraction\|calibration.outputs.<name>.max_unreachable_fraction` |
| $\rho$ | largest distance between a stream head and the cell it lands on | m | {toml}`heads_snap_radius\|calibration.outputs.<name>.heads_snap_radius` |
| $A_{min}$ | drained area a cell needs before a head may land on it | km2 | {toml}`heads_min_drained_area_km2\|calibration.outputs.<name>.heads_min_drained_area_km2` |
| $K$, $R$ | hydraulic conductivity and recharge, whose ratio the criterion calibrates | m/s | {toml}`flow.param.K.field.value` |
| $e$ | thickness of the drain bed in the drain conductance | m | {toml}`solver.drain_bed_thickness_m` |

## The equations, in code order

The code builds the geometry once, because it depends on the topography and on
the mapped network and not on the calibrated parameter. Only the distance
towards the network a trial has just simulated is recomputed, in one pass over
the cells. The steps below follow that order.

### 1. The surface is flooded on the mesh graph

A downslope distance follows a flow path, and a flow path exists only when the
depressions are resolved. On a raw surface a descent stops in a pit with no
hydrological meaning, and the cells behind it have no distance at all.

The conditioning has to happen on the graph the distances are measured on. A
raster made pit-free on its own grid grows new pits when it is read at mesh
centres. So the code floods the model top on the mesh, with the priority flood
of {cite}`barnes2014priority` written over an explicit neighbour list, so that it
applies to cells of any shape (`hydromodpy/core/depression_filling.py`,
`fill_depressions_on_graph`).

Water is walked inwards from the border of the active domain, always through
the lowest rim reached so far. The border cells $B$ are the active cells that
hold a face edge no other active cell shares (`domain_edge_cells` in
`hydromodpy/core/field_routing.py`). They keep their elevation. When a cell $c$
leaves the queue at level $\tilde z(c)$, each unvisited active neighbour $n$ is
set to

$$
\tilde z(n) =
\begin{cases}
z(n) & z(n) > \tilde z(c) \\
\tilde z(c) + \epsilon & z(n) \le \tilde z(c)
\end{cases}
$$

and joins the queue at that level. A cell below the rim is raised onto it. The
small slope $\epsilon$ keeps a filled floor draining instead of lying flat, which
a steepest-descent graph needs in order to leave it. A cell with no finite
elevation is inactive: it is never raised and never crossed.

The flood is seeded on the whole border, not on the outlet alone. The border is
where water leaves the model. Sealing one interior outlet would declare the
whole domain closed towards it, and a valley of the buffer that drains off the
domain would be filled up to a col of the divide.

The flood and the metric read the same neighbour graph. The flood guarantees a
lower neighbour only along the graph it walked: given the eight-neighbour graph
while the metric descends four neighbours, filled cells would spill over a
diagonal the metric cannot take. The graph is chosen once, in
`build_network_geometry` (`hydromodpy/core/stream_geometry.py`).

The criterion reads the model top and floods its own copy. It does not read the
descent $D$ that the solver build stores with each run, which follows the channel
tree and serves routing. The two surfaces answer two questions.

### 2. Each cell drains to one receiver

On the flooded surface $\tilde z$, a cell drains to the neighbour with the steepest
drop per metre:

$$
r(c) = \arg\max_{n \in N(c)} \frac{\tilde z(c) - \tilde z(n)}{\lVert x_c - x_n \rVert},
\qquad \ell(c) = \lVert x_c - x_{r(c)} \rVert .
$$

Only neighbours with a positive drop above a numerical tolerance are candidates.
A cell with none has no receiver. A diagonal step on a square grid is
$\sqrt{2}$ cells long, and it wins only when its slope is steeper
(`build_downhill_graph` in `hydromodpy/core/field_routing.py`, then
`build_downslope_metric` in `hydromodpy/core/topographic_distance.py`).

On a mesh whose faces are all quadrilaterals, {toml}`diagonal_neighbors|calibration.outputs.<name>.diagonal_neighbors`
selects the eight D8 neighbours, the paper's choice. Otherwise $N(c)$ holds the
cells that share an edge. On a Voronoi mesh the two graphs coincide.

### 3. The downslope distance to a set

For a target set $T$, the distance from a cell to $T$ is the length of its
descent path down to the first cell of $T$:

$$
d_T(c) =
\begin{cases}
0 & c \in T \\
\ell(c) + d_T\bigl(r(c)\bigr) & c \notin T,\ r(c) \text{ exists} \\
+\infty & c \notin T,\ r(c) \text{ does not exist}
\end{cases}
$$

The code visits the cells by ascending elevation, so each receiver is final
before its donors, and one pass is enough
(`downslope_distance_to_mask` in `hydromodpy/core/topographic_distance.py`).
Three consequences rule out implementations that look reasonable.

- **There is no shortest path to search for.** With one receiver per cell, exactly
  one descending path leaves a cell. A Dijkstra search has misread the
  definition.
- **It is not a Euclidean nearest distance.** A source fifty metres from a stream
  but on the far side of a divide is fifty metres away in the plane and far away
  downslope, because its water leaves into the other valley.
- **It is not symmetric.** $d_B(a)$ and $d_A(b)$ differ, and the asymmetry is what
  lets one cost compare an excess of simulated stream against a missing one.

An empty target gives $+\infty$ everywhere and does not raise: an empty simulated
network is the legitimate end of a search interval.

### 4. The outlet, the catchment and the saturation length

The outlet $o$ is the closing cell of the catchment, usually the gauging
station. With $A(c)$ the area drained through $c$ on the receiver graph,

$$
A(c) = a(c) + \sum_{c' : r(c') = c} A(c') ,
$$

the outlet is the most drained cell within two neighbour rings of the cell
nearest to the pour point the geographic step delineated from. Two cells is the
`SnapPourPoints` distance of the paper, read on the mesh. Without a pour point,
the most drained cell of the delineated polygon closes the catchment, and without
the polygon, the largest basin of the mesh does, with a warning
(`resolve_outlet` in `hydromodpy/core/stream_geometry.py`).

The catchment scored is read on the same graph:

$$
\Omega = \{\, c : d_{\{o\}}(c) < \infty \,\}, \qquad
L_{cap} = \max_{c \in \Omega,\ d_{\{o\}}(c) < \infty} d_{\{o\}}(c) .
$$

No descent from outside enters $\Omega$, and every cell of it reaches $o$ without
being raised towards it. The raster polygon of the geographic step builds the
domain and places the outlet. It is not the support. The gap between the two,
the area of their symmetric difference over the area of the polygon, is
published as `catchment_mismatch`, and a gap above five per cent is logged as a
warning.

$L_{cap}$ is static. It is the value an unreachable cell takes in the means
below (step 8).

### 5. The simulated network

The model does not produce a network. It produces sources. A cell where the
aquifer releases water to the surface is a point where water appears, not a
reach. The object comparable to a mapped network is what those sources generate
downslope.

The sources are the cells that release more than a threshold. The threshold is
a share of the recharge that falls on the cell itself:

$$
\Sigma = \{\, c : q(c) > \tau(c) \,\}, \qquad
\tau(c) = \tau_{ratio}\, \bar R\, a(c) .
$$

The test is strict, and it is made on the release flux $q$, never on the
condition that the head reaches the top. The flux is anchored by the mass
balance, and the geometric condition is not: the same model read geometrically
loses most of its mask when the drain conductance moves, while its median cell
flux holds. Zero for $\tau_{ratio}$ removes the threshold, which is the purely
geometric criterion of the paper. $\bar R$ is read back from the built model for
every trial, and a move between two builds is logged as a warning, because
$\tau$ is meant to be frozen over a search.

The simulated network is the downstream closure of the sources: every cell the
water of $\Sigma$ flows through, $\Sigma$ included.

$$
S = \{\, c : \text{some cell of } \Sigma \text{ drains through } c \,\}.
$$

One accumulation pass over the receiver graph gives it
(`build_simulated_network`, `downstream_closure` in
`hydromodpy/core/stream_network.py`). The release flux comes from the solver,
summed over every package that releases water to the surface. A steady phase
reads one state of the run.

### 6. The mapped network, drawn on the cells

The mapped network is a set of lines. The code draws it on the mesh cells with
one of three rules, chosen by
{toml}`observed_rasterization|calibration.outputs.<name>.observed_rasterization`.
The map is never burned into the surface: an observation never enters the
routing surface or the model top.

**Heads (the default).** The rule keeps only where the map says a stream starts,
and lets the receiver graph draw the rest. The path a field or a ditch gave the
mapped line is shaped by things a model on a DEM cannot reproduce, so drawn cell
by cell it would count as error. The steps are in the order of
`trace_from_heads` (`hydromodpy/core/stream_heads.py`).

1. The lines are noded at every intersection and merged between junctions and
   free ends. A free end is the endpoint of a merged reach that is met once
   (`network_head_candidates` in `hydromodpy/spatial/mesh/ops/network_heads.py`).
2. A free end is kept as a head when the largest drained area $A$ within the
   radius $\rho$ of it does not exceed the same quantity at the other end of its
   reach. A tie keeps it. The decision is made on the drained area, never on the
   orientation of the line. The window matters: the line runs beside the model
   talweg, and the cell nearest to a confluence is often a hillside cell.
3. A kept head lands on the nearest active cell within $\rho$ that drains at least
   $A_{min}$. With no such cell, the head is lost and draws nothing.
4. From each landing cell, the trace follows the receivers until the descent ends
   or meets a traced cell. It does not stop at the outlet: the map may continue
   into the buffer, and the supports are cut to $\Omega$ later (step 7).
5. The foot of each dam of a lake with a declared spillway is a forced head. The
   stream under a reservoir has no free end, and the flooded surface may spill
   the lake through a saddle instead of the dam, so the reach below the dam would
   be drawn by no head. A forced head is traced as given, without the landing
   rule, and it joins a map that already draws: it never makes one draw. Only the
   MODFLOW 6 build fills the dam feet. The NWT model leaves them empty.

The traced map is connected to the outlet by construction.

**Crossing.** A cell belongs to $O$ when it holds a point where a mapped line
crosses the segment that joins the centres of two cells sharing an edge. On a
structured grid those segments are the cell medians, which is what the
WhiteboxTools tool `VectorLinesToRaster` tests. The map is one cell wide, like
the simulated network, so a model that reproduces the map scores a zero gap. A
reach that crosses no segment marks the cell holding its midpoint instead, and
the count is published per trial as `n_observed_features_fallback`. This is the
rule for a map that is not a tree: canals, braids, polders, karst.

**Touch.** Every cell the line intersects, corners included. It thickens every
diagonal step, and it stays available only to replay a session recorded before
2026-09.

### 7. The supports and the targets

The two means are taken over the catchment, without the water bodies:

$$
\Omega^\ast = \Omega \setminus E, \qquad
S^\ast = S \cap \Omega^\ast, \qquad O^\ast = O \cap \Omega^\ast .
$$

The two supports are treated differently, and this is a definition and not a
convenience.

- **$S$ is closed downslope, $O$ is taken raw.** The mapped network already is a
  network. Closing it too would build observation out of the DEM, and it would
  erase the signal the validity bound exists to detect.
- **The target of $D_{so}$ is the mapped network, the water bodies and the outlet:**
  $T_{so} = O \cup E \cup \{o\}$. The outlet is added because mapped lines may stop
  short of it. Without it, the outlet cell would count as unmatched seepage for
  the sole reason that it is the exit of the basin.
- **The target of $D_{os}$ is the simulated network:** $T_{os} = S$.
- **Water bodies stay in the graph and leave both supports.** A hillslope cell
  upstream of a reservoir has to descend through it, and a source fifty metres
  from the bank stops at the bank. But a line drawn across a reservoir is not
  the observation of a stream, and a lake cell in the support of $D_{so}$ would
  inject one zero per cell and move the root with the size of the reservoir.

The intersection with $\Omega$ is not a detail. On a buffered model domain, a
tenth of the cells can drain outside the basin and never meet the mapped
network, and the unreachable guard below would refuse every real catchment.
The graph itself is not cut: the supports are.

### 8. The two mean distances

Write $\hat d$ for a distance in which an unreachable cell takes the value
$L_{cap}$:

$$
\hat d_T(c) = \begin{cases} d_T(c) & d_T(c) < \infty \\ L_{cap} & d_T(c) = \infty \end{cases}
$$

An unreachable cell is never dropped and never counted as infinite. Counting
$+\infty$ would make the mean infinite, and dropping the cell would move the
support with the parameter, a moving denominator. The means are

$$
D_{so} = \frac{\sum_{c \in S^\ast} w(c)\, \hat d_{T_{so}}(c)}{\sum_{c \in S^\ast} w(c)},
\qquad
D_{os} = \frac{\sum_{c \in O^\ast} w(c)\, \hat d_{T_{os}}(c)}{\sum_{c \in O^\ast} w(c)} .
$$

With $w = 1$, each cell has one vote, which is the paper. With $w = a$, the mean is
weighted by area. They differ as soon as the mesh is refined along the streams:
cell density is then highest where distances are smallest, so an unweighted mean
over-samples the river corridor. Both weightings are reported at every trial, as
`D_so_cell` and `D_so_area` beside `D_os_cell` and `D_os_area`, and their gap
measures the effect of the refinement. {toml}`weighting|calibration.outputs.<name>.weighting`
selects the pair that enters the criterion.

$D_{so}$ large means a simulated network spilling far outside the mapped one: an
excess. $D_{os}$ large means a simulated network that never grew to the mapped
one: a deficit. The tails matter. At a balanced point the two networks share a
common trunk, so most distances are zero and the means are carried by a few
cells. The code therefore also reports the median, the ninetieth percentile and
the share of the sum carried by the top five per cent of cells, as `D_so_median`,
`D_so_p90` and `D_so_top5_share`, and the same three for $D_{os}$.

The unreachable shares are reported on both sides, as `frac_unreachable_so` and
`frac_unreachable_os`:

$$
f_{so} = \frac{\lvert \{c \in S^\ast : d_{T_{so}}(c) = \infty\} \rvert}{\lvert S^\ast \rvert},
\qquad
f_{os} = \frac{\lvert \{c \in O^\ast : d_{T_{os}}(c) = \infty\} \rvert}{\lvert O^\ast \rvert}.
$$

The bound {toml}`max_unreachable_fraction|calibration.outputs.<name>.max_unreachable_fraction`
guards $f_{so}$ and only $f_{so}$. Its target does not move from trial to trial,
and on a conditioned catchment every cell reaches it. A larger share means the
surface is not conditioned, and the mean would rest on the saturation value.
The trial is refused. The bound does not guard $f_{os}$, and must not: its target
is the simulated network, which the calibration itself moves. At a high
conductivity the simulated network retracts into the talwegs, and mapped cells
legitimately have nothing left to descend into. That is the measurement
working, and it is the signal the root search reads.

### 9. The criterion

The criterion is Eq. 1 to 4 of {cite}`abherve2023`, as the code labels them
(`seepage_distance_cost` in `hydromodpy/calibration/metrics/downslope_network.py`).

$$
\begin{aligned}
J_{signed} &= D_{so} - D_{os} \\
J &= \lvert J_{signed} \rvert && \text{(Eq. 1)} \\
D_{optim} &= \tfrac{1}{2}\,(D_{so} + D_{os}) && \text{(Eq. 2)} \\
r_{optim} &= D_{optim} / h_{obs} && \text{(Eq. 3)}
\end{aligned}
$$

When the simulated network is empty, $D_{so}$ has no support. The residual is
then defined as $J_{signed} = -L_{cap}$, the negative value a root search needs at
the end of its interval where nothing seeps.

**The cost is $J$, and its zero is an intersection.** The two curves
$D_{so}$ and $D_{os}$, drawn against the calibrated parameter, cross, and the
crossing is the answer. $D_{optim}$ is large at both ends of a sweep, so it has an
interior minimum, and minimising it is a tempting substitute. It is a different
estimator: nothing places its minimum at the crossing. The two are needed and
they are not interchangeable. Inside one model structure, $J$ finds the
parameter, and $D_{optim}$ cannot separate two points that both balance. Between
structures already balanced at $J = 0$, only $D_{optim}$ separates them.

The code names them apart, so the substitution cannot be made by accident. In
{toml}`metric|calibration.objective_blocks.metric`, `distance_gap` is the cost
$J$, and `distance_mean` is $D_{optim}$, a diagnostic
(`hydromodpy/calibration/criteria/hydrographic_network_distance.py`). Only
`distance_gap` carries a signed residual. With two maps, each bound is this same
pair evaluated once, and the cost is the sum of the weighted gaps.

A run with a minimal (permanent) map beside the maximal one, in one state,
scores the state against the minimal map. The maximal map is scored at the same
state as a validation, and it never enters the cost.

**The length scale.** $h_{obs}$ is the median distance between the centres of
cells that share an edge, taken over the mapped cells of $\Omega$. It falls back to
$\Omega$ itself when the catchment holds no mapped cell, which the criterion refuses
further down. On a regular grid it is the cell size. On a mesh refined along the
streams, the fine cells where the map lies set the scale, and not the coarse
hillslope cells a catchment-wide median can land on. It is static: the map does
not move with $K$, and the simulated network, which does, must not set the bound.

**The validity bound (Eq. 4).** The paper reads $r_{optim} \le 2$: two cells, one of
which budgets for the error of the mapped network. The code writes it as a
length:

$$
D_{optim} \le V, \qquad V = 2\,\max(h_{obs}, \sigma) .
$$

With no declared accuracy, $V = 2 h_{obs}$, which is the paper's bound on a regular
grid. A declared accuracy $\sigma$ above $h_{obs}$ widens $V$ and leaves $r_{optim}$
alone: $r_{optim}$ stays $D_{optim} / h_{obs}$ so that it remains comparable with
the table of the paper. A declared {toml}`validity_length|calibration.outputs.<name>.validity_length`
replaces the computation. The bound is read once, on the trial the search returns.
It qualifies the value and does not replace it: a violation logs a warning and
the value comes back, and {toml}`on_roptim_violation|calibration.outputs.<name>.on_roptim_violation`
set to `error` turns the warning into a raise after the session is saved. Each
trial publishes `validity_length_m` and `validity_length_provenance` beside
`roptim` and `roptim_valid`.

**Reading the map against the surface.** The distances measure a disagreement
between two datasets, rather than hydrogeology, wherever the mapped lines do not
sit in the talwegs of the model top. The code publishes an indicator,
`alpha_obs_closure_catchment`:

$$
\alpha_\Omega = \frac{\lvert O \cap \Omega \rvert}{\lvert \mathrm{closure}(O) \cap \Omega \rvert},
$$

the share of the downstream closure of the mapped network that the network
itself holds, inside the catchment. The catchment matters: outside it the mesh is
a buffer, nothing there has to descend into the map, and mapped reaches beyond
the basin would lower a whole-mesh ratio for a reason that is not a defect of
registration. A value below {toml}`alpha_warning_threshold|calibration.outputs.<name>.alpha_warning_threshold`
logs a warning, once per process. The geographic step publishes its own ratio on
the D8 pointer of its routing DEM, so the two are measurements of two surfaces.

### Why the zero is a root

The calibrated parameter enters only through the simulated network $S$, and so
through the release flux $q$. Two properties of the criterion shape the search,
and each is a line of the implementation
(`hydromodpy/calibration/optim/adapters/bisection_adapter.py`).

**The residual is a step function.** The masks are discrete, so the means jump
when a cell switches, and $J_{signed}$ steps over zero instead of reaching it.
The stopping rule is therefore the width of the bracket in the calibrated
parameter, never the size of the residual. The search walks $\log_{10}$ of the
parameter, a relative tolerance $\varepsilon$ becomes a width $\log_{10}(1+\varepsilon)$ in
that variable, and the adapter refuses a parameter that does not declare
`transform = "log"`: on any other transform the width would read as an absolute
one and report convergence on a bracket orders of magnitude wide. The zero is
also a plateau, not a point. Its width, one cell at a time, sets how precisely
the parameter is known, whatever the tolerance asks for.

**Monotonicity is not assumed.** A coarse logarithmic sweep runs before the
bisection. It checks that the residual changes sign once, sees every crossing,
and several crossings are warned about, with the tightest one closed. A bracket
with no sign change is a result: the search widens the interval by a decade at a
time a fixed number of times, then raises and prints both residuals rather than
returning the better end, which would be a minimised mean distance in disguise.
The options are `sweep_points`, `bracket_expand`, `rel_tol` and `signed_component`
of the method options.

**Why the ratio is what gets calibrated.** For a steady water-table aquifer with
drains at the surface, whose conductance is derived from $K$, the balance of a
cell per unit area is

$$
\nabla \cdot \bigl( K\, d_{sat}\, \nabla h \bigr) + R = \frac{K}{e}\,\bigl(h - z_d\bigr)_+ ,
$$

where $d_{sat}$ is the saturated thickness, $z_d$ the drain elevation (by default
the cell top), and $K/e$ is the drain conductance $C = K\,a/e$ per unit area. When
the code builds the drain conductance itself, $C = K\,a/e$ with $e$ given by
{toml}`solver.drain_bed_thickness_m` (`hk_fallback_drain_conductance` in
`hydromodpy/solver/modflow_common/drain_conductance.py`). Dividing by $K$ gives

$$
\nabla \cdot \bigl( d_{sat}\, \nabla h \bigr) + \frac{R}{K} = \frac{1}{e}\,\bigl(h - z_d\bigr)_+ ,
$$

which depends on the ratio $R/K$ and on the geometry alone. So the head field,
and therefore the seepage mask and the criterion, depend only on $K/R$. That
proportionality is not a parasitic coupling to correct. It is what makes
calibrating $K/R$ a well-posed problem, and it is why a search that moves $K$ is
refused when the conductance does not follow $K$ (see the limits).

## Assumptions

- Water leaves a cell by one receiver only (single flow direction). A cell sending
  water to two neighbours would have no single descent path.
- The model top, flooded on the mesh graph, is the surface water follows. The
  surface that routes water in the solver build, the descent $D$, is a different
  object and the criterion does not read it.
- Distances are lengths along cell links, centre to centre. They are not
  straight-line distances: a path that crosses the grid is a staircase of links,
  and it can be longer than the straight line between its ends.
- The mapped network is independent of the DEM. It is never burned into the
  surface, and the distances measure a disagreement wherever it does not sit in
  the talwegs.
- The release flux is the whole of what leaves the aquifer for the surface. A
  package whose water the criterion cannot read would show as dry land exactly
  where it drains.
- For the $K/R$ reading: the state is steady, the drain conductance follows $K$,
  and $K$ is scaled by one factor everywhere while $R$ keeps its shape.
- The threshold $\tau$ and the mean recharge $\bar R$ are frozen over a search.
  A threshold that moved with the trial would cost $D_{so}$ its monotonicity.

## Limits

What the code refuses:

- A trial where more than {toml}`max_unreachable_fraction|calibration.outputs.<name>.max_unreachable_fraction`
  of the simulated support never reaches the mapped network. The refusal names
  `frac_unreachable_so` and says the surface still holds depressions.
- A mapped network that projects onto no active cell
  (`the mapped stream network projects onto no active cell`), or that holds no
  cell inside the catchment (`the observed stream network holds no cell inside the catchment`).
  Both messages name the CRS as the first suspect.
- A heads rule that draws no stream: no free end on an active cell, every free
  end draining more than the other end of its reach, or every head lost
  (`the mapped network draws no stream from its heads`). The message says to
  widen the radius, lower the drained area, or draw the map by `crossing`.
- A release record in the model budget that no declared package reads, which
  would report the water of that package as dry land. The same refusal covers a
  package that wrote its exchange to its own budget file and left none in the
  model budget.
- A search that moves a conductivity while a drain has a fixed conductance. The
  fallback conductance follows $K$ only when {toml}`flow.bc.drainage.value` is not
  strictly positive. A search driving another parameter gets a warning instead,
  because its result depends on the conductance chosen.
- A search that moves a conductivity while SFR or LAK is active. These packages
  build their own conductance from their own data, never from $K$, so the
  invariance of step 9 does not hold. The refusal comes before the first solve.
- A bisection on a parameter that does not declare a logarithmic transform, or on
  more than one parameter.

What the code does not represent:

- **Monotonicity.** The criterion does not prove that $J_{signed}$ varies in one
  direction with the parameter. It checks it on a sweep.
- **A calibrated value is a ratio.** What the criterion identifies depends on
  the parameter that drives it. With the homogeneous conductivity alone, at fixed
  geometry and recharge, it identifies $K/R$, and not $K$ itself. A $K$ read from
  it inherits the recharge series entirely: report $K/R$ and name the recharge
  beside it. The calibration returns $K$ and publishes the recharge that divides
  it as `R_mean_m_s` per trial. Forming the ratio is left to the author.
- **$r_{optim}$ is not a quality indicator.** It measures agreement with the map,
  not the correctness of the model, and it moves with the grid: because
  $h_{obs}$ is in the denominator, refining a mesh degrades it at a constant
  agreement. Two values on different meshes are not comparable. Two verdicts are,
  when their validity lengths are.
- **The two means are tail statistics.** Reading $r_{optim} \le 2$ as "the typical
  gap is under two cells" is wrong when the median distance is zero.
- **The size of the threshold.** $\tau$ is a share of a cell's own recharge. A
  cell that collects drainage from upslope releases more than the recharge that
  falls on it, so a small share excludes few cells. This page does not give a
  value to use. The reference the threshold is read against is not settled by
  the method.
- **The surface is not repaired.** {toml}`dem_correc_type|geographic.dem_correc_type`
  conditions the DEM before the catchment is delineated: `fill` is the tool of the
  paper, `breach` carves a path through a barrier ({cite}`lindsay2016breaching`),
  and `capped_breach` breaches within limits, then fills what they refused. The
  criterion itself always floods the model top on the mesh. A breached raster
  reaches the criterion only through the domain and the outlet, and
  `catchment_mismatch` measures that gap.
- **Meshes without diagonals.** On a mesh whose faces are not all quadrilaterals,
  {toml}`diagonal_neighbors|calibration.outputs.<name>.diagonal_neighbors` set to
  true falls back to shared edges. The fallback is logged, not refused.
- **Domain of validity.** The method was built for unconfined aquifers, a
  temperate humid climate, gentle gradients, a strong groundwater-stream
  connection, and a DEM whose resolution suits the positional accuracy of the
  map. Outside that, the criterion still computes, and it means less.

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

In example 04, the map the criterion scores is declared in
`run_calibration.toml`:

```{hmp-resolved} calibration.outputs.seepage_network.stream_geometry_path
:config: run_calibration.toml
```

A network output that weights by area, with a declared positional accuracy of
the map and a validity length given as a length. Its keys link to their card.

```toml
base_config = "run_calibration_by_hand.toml"

[calibration.outputs.seepage_network]
weighting = "area"
observed_position_accuracy = "50 m"
validity_length = "150 m"
on_roptim_violation = "error"
```

The heads rule with a wider landing radius and a larger drained area:

```toml
base_config = "run_calibration_by_hand.toml"

[calibration.outputs.seepage_network]
observed_rasterization = "heads"
heads_snap_radius = "150 m"
heads_min_drained_area_km2 = 0.05
```

The crossing rule, for a map that is not a tree:

```toml
base_config = "run_calibration_by_hand.toml"

[calibration.outputs.seepage_network]
observed_rasterization = "crossing"
```

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
| The priority flood on the mesh graph | `hydromodpy/core/depression_filling.py` (`fill_depressions_on_graph`) |
| The border cells that seed the flood | `hydromodpy/core/field_routing.py` (`domain_edge_cells`) |
| The receiver graph, edge lengths and the distance to a set | `hydromodpy/core/topographic_distance.py` (`build_downslope_metric`, `downslope_distance_to_mask`, `mean_downslope_distance`, `longest_descent_length`) |
| The neighbourhood, D8 or shared edges | `hydromodpy/core/topographic_distance.py` (`resolve_diagonal_neighbors`, `shared_node_adjacency`) |
| The outlet, the catchment, $h_{obs}$ and the validity length | `hydromodpy/core/stream_geometry.py` (`build_network_geometry`, `resolve_outlet`, `observed_cell_size_m`, `resolve_validity_length`) |
| The supports of the two means | `hydromodpy/core/stream_geometry.py` (`criterion_supports`) |
| The sources and the simulated network | `hydromodpy/core/stream_network.py` (`specific_seepage_threshold`, `build_simulated_network`, `downstream_closure`) |
| The heads rule | `hydromodpy/core/stream_heads.py` (`trace_from_heads`), `hydromodpy/spatial/mesh/ops/network_heads.py` (`network_head_candidates`) |
| The crossing and touch rules | `hydromodpy/spatial/mesh/ops/vector_cell_mask.py` (`line_crossing_cell_mask`, `vector_cell_mask`) |
| The two means and the criterion | `hydromodpy/calibration/metrics/downslope_network.py` (`seepage_distance_cost`, `score_on_geometry`) |
| The two estimators | `hydromodpy/calibration/criteria/hydrographic_network_distance.py` (`distance_gap`, `distance_mean`) |
| The refusal of an unreachable support | `hydromodpy/calibration/metrics/solver_extract.py` (`_refuse_an_unreachable_support`) |
| The refusals of a drain or package that does not follow $K$ | `hydromodpy/calibration/runners/cli_runner.py` (`_assert_network_conductance_proportional`, `release_package_conductance_conflict`) |
| The refusal of a release record no package reads | `hydromodpy/solver/modflow_common/calibration_extractors.py` |
| The root search | `hydromodpy/calibration/optim/adapters/bisection_adapter.py` |
| What the defaults of the criterion are | `hydromodpy/core/stream_criterion_defaults.py` |

## See also

- {doc}`../guides/calibrate-on-the-stream-network`: how to set up and read a calibration on the network.
- {doc}`/guides/calibrate-on-the-stream-network`: the two-bound mode for a transient run.
- {doc}`../understand/stream-network`: how the model makes streams, in plain words.
- {doc}`exits`: the drains that release the water the criterion reads.
- {doc}`bibliography`: the full list of references.
