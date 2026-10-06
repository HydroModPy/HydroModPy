# Scoring a simulated stream network

A model makes a network of streams. A map draws another one. To say how well they agree, you
need a number, and there are several ways to get one. This page lists the families of
metrics HydroModPy offers to compare two networks, says what each one answers, and
separates two uses that look alike: a **diagnostic**, which you read, and a **criterion**,
which a calibration drives to a target.

No equation here. The equations of the downslope criterion are in
{doc}`../theory/downslope-distance`, and the way to run a calibration on it is in
{doc}`../guides/calibrate-on-the-stream-network`.

## The two networks

- The **simulated network** is not computed by a river model. The model finds the cells where
  the water table reaches the ground, and the network extends these seepage cells downstream,
  following the slope of the ground ({doc}`what-it-computes`).
- The **mapped network** is the network drawn on a map. In example 04, it is the permanent
  reaches of the BD TOPO. HydroModPy stores a hydrographic network under a role. The roles are
  `reference` (the observed network loaded with the run), `reference_permanent` (its permanent
  reaches), `generated` (derived from the relief), `mesh_constraint` and `simulated_active`
  (the simulated network). A comparison reads one role against another.

A metric never gives the truth about the model. It gives the distance between two drawings,
and each drawing has its own errors. The mapped network holds the reaches someone chose to
draw. The simulated one depends on the cell size, on the threshold that decides what counts as
seepage and, in a transient run, on the month you look at.

## Four families of metrics

| Family | What it compares | What it answers |
|---|---|---|
| Overlap of lines | The two networks as vector lines | What share of the length of each network lies near the other? |
| Overlap of cells | The cells of the simulated network and the cells the map crosses | How many cells do the two share, miss or add? |
| Planar distance | The same two sets of cells, by straight-line distance | How far apart do the two patterns sit? |
| Downslope distance | The two networks, along the paths the water takes | How far must the water walk to get from one network to the other, in each direction? |

### Overlap of lines

This family treats both networks as lines and puts a tolerance, in metres, around each. A
stretch of one network is *matched* when it lies inside the tolerance of the other, and
*missing* or *extra* when it does not. The record holds lengths and ratios, and the largest gap
between the two drawings (the Hausdorff distance). The names are `reference_coverage_ratio`,
`candidate_match_ratio`, `missing_reference_ratio`, `extra_candidate_ratio`,
`length_balance_ratio`, `length_f1_ratio` and `hausdorff_distance_m`.

It is the family to use to compare two *maps*, such as the observed network and the one derived
from the relief. It is also the only one that does not read the mesh. It does not know where the
water goes: a stretch near the map counts as matched even if the water leaves it in another
valley. In Python it is `Run.hydrographic_network_comparison_metrics()`.

### Overlap of cells

This family works on the cells of the mesh. A cell is *simulated* when a field of the run is
above zero there: `accumulation_flux` by default, or `release_flux` and
`release_accumulation_flux`, each written to its own file by a comparison. No seepage
threshold and no downstream closure apply, so these cells are not exactly the network that
{doc}`stream-network` describes and that the downslope criterion reads. In a transient run, a
cell is simulated when the field is above zero in at least half of the timesteps by default,
and in a steady run it is the cells of the last state. A cell is *mapped* when the map crosses
it. Then the cells are counted:

- the cells in both sets (overlap);
- the mapped cells the model did not reach (missing);
- the simulated cells away from the map (extra);
- the *coverage* (`network_coverage_ratio`), the share of mapped cells the model found;
- the *precision* (`active_precision_ratio`), the share of simulated cells that are on the map;
- the F1 score (`cell_f1_ratio`) and the Jaccard index (`cell_jaccard_ratio`), which fold the
  two into one number.

A low coverage says the simulated network is under-developed. A low precision says it spreads
where the map has nothing. The function is `cell_field_network_overlap_metrics` in
`hydromodpy.results.derive.views`, and a comparison file writes it to
`simulated_active_network_overlap_metrics.csv` ({doc}`../guides/compare-runs`).

One detail changes the numbers. This family marks every cell the map touches, so a line
becomes a ribbon of cells. The downslope criterion draws the map one cell wide, like the
simulated network ({toml}`calibration.outputs.<name>.observed_rasterization`). The cell counts
of the two families are therefore not comparable.

### Planar distance

Same cells, but now the question is *how far*. For each simulated cell, the code measures the
straight-line distance from its centre to the nearest mapped line. For each mapped cell, it
measures the distance to the nearest simulated cell. That gives two numbers, one per
direction, as a mean, a median, a 95th percentile and a maximum. The record also holds their
mean (`bidirectional_distance_mean_m`), their ratio (`planar_distance_ratio`) and its decimal
logarithm (`planar_distance_log10_ratio`). The function is `cell_field_network_distance_metrics`
in `hydromodpy.results.derive.views`, and its output file is
`simulated_active_network_distance_metrics.csv`.

A distance gives more than a count. Two simulated cells that miss the map, one by a cell and
one by a kilometre, count the same in the overlap and weigh very differently here. The
distance is straight, and so it ignores the relief. It crosses a ridge as if it were not there.

### Downslope distance

This is the method of {cite}`abherve2023`. The distance is the length of the path the water
follows downslope, not the straight line.

- From each simulated cell, how far does the water go before it meets the mapped network? The
  mean is `D_so` (simulated to observed).
- From each mapped cell, how far does the water go before it meets the simulated network? The
  mean is `D_os` (observed to simulated).

If the model makes too much stream, `D_so` is large: simulated water travels far to reach a
map that has no stream near it. If the model makes too little, `D_os` is large: mapped
streams have no simulated stream to flow into. The two directions are kept apart on purpose,
because they tell opposite stories. The calibration reads, for each trial:

| Name | What it is |
|---|---|
| `D_so`, `D_os` | The two mean distances, in metres. |
| `J_signed` | `D_so` minus `D_os`. Positive for an excess of simulated stream, negative for a deficit. |
| `J` | The absolute value of `J_signed`. This is the cost. |
| `Doptim` | The mean of `D_so` and `D_os`, in metres. A diagnostic. |
| `roptim` | `Doptim` divided by the cell size on the mapped network. |
| `roptim_valid` | Whether `Doptim` stays under the validity length (see below). |
| `n_valid`, `n_excess`, `n_missing` | The three classes of cells: simulated and mapped, simulated only, mapped only. |

The three counts are what the map `seepage_network_confusion_map` draws, and the map
`downslope_distance_map` draws the distances themselves. Both are explained on
{ref}`reading-network`.

The validity length is a length. When `Doptim` is above it, the two networks are further apart
than the map can be trusted to place them, so the score says little about the hydrogeology. By
default the length is two cells, widened by the positional accuracy you declare for the map
({toml}`calibration.outputs.<name>.validity_length`,
{toml}`calibration.outputs.<name>.observed_position_accuracy`). A violation is a warning
unless you ask for an error ({toml}`calibration.outputs.<name>.on_roptim_violation`).

## Diagnostic or criterion

The same number can be read, or it can be minimised. The two uses have different needs.

A **diagnostic** describes. You read it, put it in a report, compare two runs with it. It has
no need to be symmetric or monotonic. The four families above all work as diagnostics, and
the overlap and planar families are only diagnostics.

A **criterion** is a cost that a search drives to a target, over many trials. It must behave
well along that search. For the downslope method, the cost is `J`, the gap between an excess
and a deficit, and its target is zero. Zero is not "the two networks coincide". It is "the
simulated network has as much excess as deficit". A model can reach it with a large excess and
a large deficit that cancel, which is why the confusion map and `Doptim` stay on the table
next to it.

Why not use a planar distance as the criterion?

- A planar distance crosses divides. A seepage cell on the far side of a ridge counts as close
  to the map, when its water leaves into the other valley. The downslope distance follows the
  water, so it cannot cheat that way.
- A mean planar distance has no sign. It cannot say whether the model has too much stream or
  too little, and a search needs that sign to know which way to move the parameter.
- A count of cells moves in steps, and its best value depends on how the map is drawn on the
  mesh.

Why not minimise `Doptim`, then? It is large at both ends of a parameter sweep, so it does have
a minimum in the middle. But nothing puts that minimum at the point where excess and deficit
balance. They are two different estimators. The code keeps them apart: in a calibration, the
metric `distance_gap` is the cost `J`, and `distance_mean` is `Doptim`
({toml}`calibration.objective_blocks.metric`). Use `Doptim` to compare two structures that are
both balanced, and `J` to find the parameter inside one structure.

```{hmp-params}
calibration.objective_blocks.metric
```

## What moves a score

Before you compare two scores, check that they were computed the same way.

- **The seepage threshold.** A cell counts as seepage only above a share of its own recharge
  ({toml}`calibration.outputs.<name>.tau_specific_ratio`). Another threshold changes the
  simulated network, and so every score.
- **The way the map is drawn on the mesh.** The rule for the mapped network
  ({toml}`calibration.outputs.<name>.observed_rasterization`) moves the number of mapped cells
  and where they sit. A one-cell gap can come from this rule and not from the model.
- **The cell size.** Distances are in metres, but they are measured from cell to cell. A
  coarse mesh cannot place a stream closer than about a cell.
- **The state that is read.** A steady run gives one network. A transient run gives one
  network per timestep. A calibration can score one state, or two bounds: the complete network
  and the permanent one ({toml}`calibration.outputs.<name>.extent`). A cell is counted as
  flowing above a visible discharge ({toml}`calibration.outputs.<name>.extent.visible_flow`).
- **The map.** The permanent network of a map does not hold the temporary streams. An
  "excess" can be a real stream the map ignores.

## Where to go next

- {doc}`reading-results`: the maps that show these metrics for example 04.
- {doc}`stream-network`: how the model makes a network.
- {doc}`../theory/downslope-distance`: the equations, the assumptions and the limits of the
  downslope criterion.
- {doc}`../guides/calibrate-on-the-stream-network`: run a calibration on `J`.
- {doc}`../guides/compare-runs`: write the overlap and planar metrics for several runs.
