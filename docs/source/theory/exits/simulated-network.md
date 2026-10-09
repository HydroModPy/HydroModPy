# Where the water table reaches the surface

The model produces sources, not a stream network. A cell where the aquifer
releases water to the surface is a point where water appears, not a reach. The
simulated network is built from those points, in four levels that should not be
confused:

1. the cells where the water table reaches the drain: the seepage mask;
2. how much water the aquifer releases in each cell: the release flux;
3. where the water goes on the descent $D$: the accumulated flux;
4. the cells a stream criterion counts as flowing: the simulated network.

The last section lists the diagnostics that compare a network with a mapped one.
The criterion a calibration minimises is on {doc}`../downslope-distance`.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

```{eval-rst}
.. plot:: theory/figures/exits_toy_network.py
   :alt: Four maps of a toy valley of 24 by 24 cells. The seepage mask covers the valley floor; the release is largest downstream; the accumulated flux grows along the valley; the last map shows the sources and the cells added by the downstream closure.

   The four levels on a toy valley. The water table is a subdued copy of the
   top, not a solve; every step after it is a call of the code:
   ``seepage_mask``, the outflow of a drain, ``accumulate_on_downhill_graph`` on
   :math:`D`, and ``build_simulated_network`` with :math:`\tau_\mathrm{s} = 0.5`.
   In the last map, the light cells join the sources downstream: they carry water
   and release none.
```

(network-seepage)=
## 1. The seepage mask

The water table of a cell is the head of its uppermost layer with a finite
head. A cell seeps in period $t$ when the water table reaches the drain:

$$
m_n(t) = \begin{cases} 1 & h^{\mathrm{wt}}_n(t) \geq z_{\mathrm{top},n} - \delta/2,\\ 0 & \text{otherwise.}\end{cases}
$$ (eq-seepage-mask)

With no band, $\delta = 0$ and the test is against the top
({doc}`drains-and-et`). A solver that reports a surface release flux of its own,
the Boussinesq solver, uses that flux instead: the cell seeps where the flux is
positive. The mask says that the water table reached the ground, not how much water left.

In the code: `seepage_mask`.

(network-release)=
## 2. The release flux

The budget gives the flow $\Phi_{n,p}$ of each package into each cell, negative
when the aquifer loses water. The drain outflow $q^\mathrm{drn}_n$ is the drain flow
added to the part handed to the mover, then clipped to its positive part in each
layer and summed over the layers.
A run whose streams are an SFR network sends most of its water through that
package, so the drain alone misses it. The release flux is the union of every
path from the aquifer to the surface:

$$
q^\mathrm{rel}_n(t) = q^\mathrm{drn}_n(t) + \max(-\Phi_{n,\mathrm{sfr}}, 0) + \max(-\Phi_{n,\mathrm{lak}}, 0)
+ \max(-\Phi^{\mathrm{stream}}_{n,\mathrm{chd}}, 0) + \max(q^{\mathrm{ex}}_n, 0).
$$ (eq-release-flux)

$\Phi^{\mathrm{stream}}_{n,\mathrm{chd}}$ is the fixed-head flux of the cells
that carry the river role ({doc}`head-boundaries`), stored as
`constant_head_stream`. The last term is the surface excess of the Boussinesq
solver, the only path out of that solver, already an outflow. The plain
fixed-head term stays out: a sea or a side boundary is water leaving sideways,
not a release to the surface.

The stream-network criterion reads the same union off the budget, so the network
a calibration scores and the network the maps draw come from one quantity. A run
stored before the river share of the fixed head was stored lacks that one term.

The release flux is rebuilt on read from the per-cell budget, which the run keeps
only with {toml}`simulation.results.budget.spatial_fields`.

In the code: `release_flux_stack`.

(network-accumulation)=
## 3. The accumulated flux, on D

The drain outflow is routed downstream on the stored descent $D$
({doc}`routing-on-the-mesh`): the accumulated flux $F_n$ of a cell is its own
outflow plus that of every cell upstream, the usual flow accumulation on a
single-flow-direction graph {cite:p}`ocallaghan1984`. High values mark the
confluences and the persistent branches. $F_n$ is a routed diagnostic: the same
water is counted again in every cell downstream, so the sum of $F$ over the cells
is not a water budget. Use the budget for a mass balance. $F$ is stored as
`accumulation_flux`, and the same routing applied to the release flux gives
`release_accumulation_flux`. The Boussinesq solver, whose store holds a top and no
mesh connectivity, routes on a D8 raster of WhiteboxTools instead.

A cell is active in period $t$ when a field, $F$ for instance, exceeds a
threshold. A time rule reduces the periods to one mask:

| Mode | Active when |
|---|---|
| `last` | the cell is active at the chosen period, the last by default |
| `any` | the cell is active at least once |
| `persistent` | the cell is active in at least a given share of the periods |
| `always_active` | the cell is active in every period (`perennial` is a synonym) |
| `persistence` | not a mask: the share of the periods where the cell is active |

A steady run uses `last` by default, since it has one state. A transient run uses
`persistent`, with a share of one half unless another is given. An always-active
mask is active at every period of the window analysed, which is not a steady
network.

The derived fields are written only when asked, with the keys
`simulation.results.derived.*` and {toml}`simulation.results.budget.spatial_fields`
(see {doc}`[simulation] <../../reference/parameters/simulation>`).

In the code: `accumulate_on_downhill_graph`.

(network-flowing)=
## 4. The simulated network

The network that a calibration scores, and that the stream maps draw, is not a
threshold of $F$. It is built from the release flux on the graph of the stream
criterion ({ref}`routing-criterion-graph`), in two steps.

**The sources.** A cell is a source in period $t$ when its release exceeds a
share of its own recharge, strictly:

$$
\Sigma(t) = \{\, n : q^\mathrm{rel}_n(t) > \tau_\mathrm{s}\,\bar N\,a_n \,\} .
$$ (eq-sources)

$\bar N$ is the unweighted mean of the finite recharge rates over the periods
and the cells. The threshold is a flux per unit of area, not a discharge, so
that the network follows the physics and not the refinement of the mesh: a fixed
discharge would be nine times harsher on a cell three times smaller. A value of
zero is the purely geometric criterion. The test is made on the flux, not on the
head, which moves a lot when the drain conductance moves. $\bar N$ is read back from
the built model at every trial of a calibration, and a change between two builds is
logged as a warning: the threshold is meant to be frozen over a search.

**The closure.** The simulated network $\mathcal{S}$ is the downstream closure
of the sources: every cell the water of $\Sigma$ flows through, $\Sigma$
included. When a visible flow $\Phi_\mathrm{vis}$ is set, a cell of the closure
must also carry it, as the release of the sources routed down the same graph:

$$
\Phi_n(t) = \sum_{m\,:\,m \rightsquigarrow n} q^\mathrm{rel}_m(t)\,\mathbb{1}[\,m \in \Sigma(t)\,] \;\geq\; \Phi_\mathrm{vis} ,
\qquad \Phi_n(t) > 0 .
$$ (eq-visible-flow)

The sum runs over the sources whose chain passes through $n$. The visible flow
is a discharge with its unit, or a share of the discharge at the outlet in the
same period; zero is the geometric definition. The routed discharge never falls
downstream, so the network stays closed downstream whatever the threshold. It is
a routed seepage discharge, not a river discharge: no runoff and no bed loss
enter it.

The flowing cells are the field `simulated_active_network`, 1 where a stream
flows and 0 elsewhere. It is rebuilt on read from the stored release flux and
from a stored network on which the graph is rebuilt. It is never stored, and it
needs {toml}`simulation.results.derived.release_flux`.

Over a transient run, the criterion counts, for each complete calendar year, the
periods each cell flows, and builds a maximal and a minimal extent from those
counts. Durations are counted in periods, never in days. How a network is
scored against a mapped one is on {doc}`../downslope-distance`.

In the code: `build_simulated_network`.

(network-diagnostics)=
## Comparing a network with a map

A run stores up to three line networks, each under a role:

| Role | The network |
|---|---|
| `reference` | the mapped network read from {toml}`data.hydrography` |
| `reference_permanent` | the reaches of the mapped network that flow all year, when the source says which |
| `generated` | the network traced on the routing of the DEM, {toml}`geographic.river_network` |

The roles `simulated_active` and `mesh_constraint` are reserved names that no run
writes today: the simulated network is the cell field above. A mapped network is
never a model input: it enters a criterion, a figure or a diagnostic, never the
model top or the routing.

Three families of diagnostics compare a mask of active cells $A$ with a network.
None of them is the criterion of a calibration.

**Overlap of cells.** $M$ is the set of catchment cells a network crosses, within
an optional buffer, and $A$ the active cells of a field (by default the
accumulated flux above zero, with the time rule above). The scores are the usual
set scores of $A$ against $M$, published as `network_coverage_ratio` (the share
of $M$ in $A$), `active_precision_ratio` (the share of $A$ in $M$),
`cell_f1_ratio` (their harmonic mean) and `cell_jaccard_ratio` (the intersection
over the union), by `cell_field_network_overlap_metrics`.

**Planar distance.** The straight-line distance from each active cell centre to
the nearest line of the network is $\delta_{A\to M}$, and from each network cell
centre to the nearest active cell $\delta_{M\to A}$. Each direction gives its
mean, median, 95th percentile and maximum, then

$$
\bar\delta = \tfrac12\bigl(\overline{\delta_{A\to M}} + \overline{\delta_{M\to A}}\bigr),
\qquad
\rho_\delta = \frac{\overline{\delta_{A\to M}}}{\overline{\delta_{M\to A}}} ,
$$ (eq-planar-distance)

published as `bidirectional_distance_mean_m`, `planar_distance_ratio` and its
logarithm `planar_distance_log10_ratio` (`cell_field_network_distance_metrics`).
A planar distance ignores the divides. The downslope distance of
{doc}`../downslope-distance` does not.

**Overlap of lines.** Between two line networks, a reference $R$ and a candidate
$G$ (by default the mapped and the generated networks), each buffered by a
tolerance of 50 m by default. The metrics are the share of the reference length
inside the buffer of the candidate (`reference_coverage_ratio`), the share of the
candidate length inside the buffer of the reference (`candidate_match_ratio`),
the length ratio `length_balance_ratio`, the missing and extra shares, their
harmonic mean `length_f1_ratio` and the Hausdorff distance of the two networks
(`Run.hydrographic_network_comparison_metrics`).

## Assumptions

- The release flux is the whole of what leaves the aquifer for the surface.
- The threshold $\tau_\mathrm{s}$ and the mean recharge $\bar N$ are frozen over
  a search.

## Limits

- **The accumulated flux is not a budget.** It counts the same water in every
  cell downstream.
- **The simulated network is a mask computed on read.** It is not a stored line
  network.
- **The size of the threshold.** $\tau_\mathrm{s}$ is a share of a cell's own
  recharge. A cell that collects drainage from upslope releases more than the
  recharge that falls on it, so a small share excludes few cells. No value is
  given here as the one to use.

## Parameters of this page

```{hmp-params}
simulation.results.derived.seepage_areas
simulation.results.derived.release_flux
simulation.results.derived.accumulation_flux
simulation.results.derived.outflow_drain
simulation.results.budget.spatial_fields
calibration.outputs.<name>.tau_specific_ratio
calibration.outputs.<name>.extent.visible_flow
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.core.field_routing
hydromodpy.core.stream_network
hydromodpy.core.stream_extent
hydromodpy.simulation.extraction.derivation.derived
hydromodpy.results.derive.views
```

## In the code

| What | Where |
|---|---|
| Seepage mask, release flux, accumulation | `hydromodpy/core/field_routing.py` |
| Sources and closure | `hydromodpy/core/stream_network.py` |
| Flowing cells, yearly extents | `hydromodpy/core/stream_extent.py` |
| Derived fields written after the run | `hydromodpy/simulation/extraction/derivation/derived.py` |
| Active masks and the diagnostics | `hydromodpy/results/derive/views.py` |
| Overlap of lines | `hydromodpy/spatial/geographic/core/hydrographic_network_comparison.py` |
