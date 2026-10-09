# Scoring a simulated stream network

A model makes a network of streams. A map draws another one. To say how well they agree, you
need a number, and there are several ways to get one. This page tells what each way answers, and
separates two uses that look alike: a {term}`diagnostic`, which you read, and a {term}`criterion`,
which a calibration drives to a target.

It has no equation and no name of a metric. The equations of the downslope method are in
{doc}`../theory/downslope-distance`. The names of the metrics, and how to write them to a file,
are in the guides {doc}`../guides/compare-runs` and
{doc}`../guides/calibrate-on-the-stream-network`.

## The two networks

- The {term}`simulated network` is not computed by a river model. The model finds the cells where
  the water table reaches the ground, and the network extends these seepage cells downstream,
  following the slope of the ground ({doc}`what-it-computes`).
- The {term}`mapped network` is the network drawn on a map. In example 04, it is the permanent
  reaches of the {term}`BD TOPO`.

A score never gives the truth about the model. It gives the distance between two drawings, and
each drawing has its own errors. The mapped network holds the reaches someone chose to draw. The
simulated one depends on the cell size, on the threshold that decides what counts as seepage and,
in a run that changes with time, on the month you look at.

## Four ways to compare two networks

| Way | What it compares | What it answers |
|---|---|---|
| Overlap of lines | The two networks as lines | What share of the length of each network lies near the other? |
| Overlap of cells | The cells of the simulated network and the cells the map crosses | How many cells do the two share, miss or add? |
| Straight-line distance | The same two sets of cells | How far apart do the two patterns sit, as the crow flies? |
| Downslope distance | The two networks, along the paths the water takes | How far must the water walk to get from one network to the other, in each direction? |

### Overlap of lines

Both networks are treated as lines, with a small tolerance around each. A stretch of one network
is *matched* when it lies inside the tolerance of the other, and *missing* or *extra* when it
does not. The result is a set of lengths and shares, and the largest gap between the two
drawings.

Use it to compare two *maps*, such as the observed network and the one derived from the relief.
It does not read the model cells and it does not know where the water goes: a stretch near the
map counts as matched even if the water leaves it in another valley.

### Overlap of cells

This way works on the cells of the model. A cell is *simulated* when the model puts water there,
and *mapped* when the map crosses it. Then the cells are counted:

- the cells in both sets (the overlap);
- the mapped cells the model did not reach (missing);
- the simulated cells away from the map (extra).

From these counts come two shares: the *coverage*, the share of mapped cells that the model
found, and the *precision*, the share of simulated cells that are on the map. A low coverage
says the simulated network is under-developed. A low precision says it spreads where the map has
nothing. Two combined scores fold the two shares into one number.

One detail changes the numbers. This way marks every cell the map touches, so a line becomes a
ribbon of cells. The downslope method draws the map one cell wide, like the simulated network
({toml}`calibration.outputs.<name>.observed_rasterization`). The cell counts of the two ways are
therefore not comparable.

### Straight-line distance

Same cells, but now the question is *how far*. For each simulated cell, the code measures the
straight distance to the nearest mapped line. For each mapped cell, it measures the distance to
the nearest simulated cell. That gives two numbers, one per direction, each summarised by its
mean, its median, its high values and its maximum.

A distance gives more than a count. Two simulated cells that miss the map, one by a cell and one
by a kilometre, count the same in the overlap and weigh very differently here. But the distance
is straight, so it ignores the relief. It crosses a ridge as if it were not there.

### Downslope distance

This is the method of {cite}`abherve2023`. The distance is the length of the path the water
follows downslope, not the straight line.

- From each simulated cell, how far does the water go before it meets the mapped network? The
  mean is the *excess side*: if the model makes too much stream, simulated water travels far to
  reach a map that has no stream near it.
- From each mapped cell, how far does the water go before it meets the simulated network? The
  mean is the *deficit side*: if the model makes too little stream, mapped streams have no
  simulated stream to flow into.

The two directions are kept apart on purpose, because they tell opposite stories. The calibration
uses the gap between them, in absolute value, as its cost. It also keeps their average as a
diagnostic, and the three classes of cells that the confusion map draws: {term}`valid`,
{term}`excess` and {term}`missing`. The maps are explained on {ref}`reading-network`.

The average walk has a validity length. When it is longer than that length, the two networks are
further apart than the map can be trusted to place them, and the score says little about the
hydrogeology. By default the length is two cells, widened by the positional accuracy you declare
for the map ({toml}`calibration.outputs.<name>.validity_length`). A violation is a warning
unless you ask for an error, as the {doc}`guide <../guides/calibrate-on-the-stream-network>`
explains.

## Diagnostic or criterion

The same number can be read, or it can be minimised. The two uses have different needs.

A **diagnostic** describes. You read it, put it in a report, compare two runs with it. It has no
need to be symmetric or monotonic. The four ways above all work as diagnostics, and the overlap
and straight-line ways are only diagnostics.

A **criterion** is a cost that a search drives to a target, over many {term}`trials <trial>`. It
must behave well along that search. For the downslope method, the cost is the gap between the
excess side and the deficit side, and its target is zero. Zero does not mean that the two
networks coincide. It means that the simulated network has as much excess as deficit. A model can
reach it with a large excess and a large deficit that cancel, which is why the confusion map and
the average walk stay on the table next to it.

Why not use a straight-line distance as the criterion?

- A straight-line distance crosses divides. A seepage cell on the far side of a ridge counts as
  close to the map, when its water leaves into the other valley. The downslope distance follows
  the water, so it cannot cheat that way.
- A mean straight-line distance has no sign. It cannot say whether the model has too much stream
  or too little, and a search needs that sign to know which way to move the parameter.
- A count of cells moves in steps, and its best value depends on how the map is drawn on the
  grid.

Why not minimise the average walk, then? It is large at both ends of a parameter sweep, so it
does have a minimum in the middle. But nothing puts that minimum at the point where excess and
deficit balance. They are two different estimators. Use the average walk to compare two
structures that are both balanced, and the gap to find the parameter inside one structure.

## What moves a score

Before you compare two scores, check that they were computed the same way.

- **The seepage threshold.** A cell counts as seepage only above a share of its own recharge
  ({term}`seepage threshold`). Another threshold changes the simulated network, and so every
  score.
- **The way the map is drawn on the grid.** The rule for the mapped network
  ({toml}`calibration.outputs.<name>.observed_rasterization`) moves the number of mapped cells
  and where they sit. A one-cell gap can come from this rule and not from the model.
- **The cell size.** Distances are in metres, but they are measured from cell to cell. A coarse
  grid cannot place a stream closer than about a cell.
- **The state that is read.** A steady run gives one network. A run that changes with time gives
  one network per time step. A calibration can score one state, or two bounds: the complete
  network and the permanent one ({toml}`calibration.outputs.<name>.extent`). A cell is counted
  as flowing above a {term}`visible flow`.
- **The map.** The permanent network of a map does not hold the temporary streams. An "excess"
  can be a real stream the map ignores.

## Where to go next

- {doc}`reading-results`: the maps that show these scores for example 04.
- {doc}`stream-network`: how the model makes a network.
- {doc}`../theory/downslope-distance`: the equations, the assumptions and the limits of the
  downslope method.
- {doc}`../guides/calibrate-on-the-stream-network`: run a calibration on the network.
- {doc}`../guides/compare-runs`: write the overlap and distance scores for several runs.
