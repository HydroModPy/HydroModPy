# results/derive/stream

This folder answers: what does a figure need from a finished run to draw the stream criterion, and
which inputs does the criterion read? Calibration scores the criterion per trial with the kernels of
`catchment/stream_network`. The modules here read the same inputs from a stored run, so a figure
draws the partition behind the number it illustrates. The figures in `display/` only draw what these
modules return.

## The criterion, as a trial scores it

The kernels live in `catchment/stream_network`: the simulated network (`network.py`), the flowing
cells and the extent masks (`extent.py`), the heads rule (`heads.py`), the geometry and its partition
(`geometry.py`) and the signed cost (`cost.py`). The free ends are found in
`catchment/algorithms/network_heads.py`, the visible-flow words and the numeric defaults are in
`core/scoring/stream_defaults.py`, and the graph, the flood and the routing are in `catchment/drainage/`.

1. `criterion_inputs.py` takes arrays, geometries and CRS and holds the one function for each input
   the trial and the figure both read: the cells a mapped line draws (`mapped_cells`), the free ends
   (`map_heads`), the outline cells (`catchment_cells`), the basin reference (`basin_reference`), the
   snapped outlet and the mean recharge (`criterion_recharge_of_run`). The trial calls it, and so does
   `workflow/steps/run_outputs.py`, which keeps the outline cells, the open water and the mean
   recharge beside the run.

## The criterion, read from a stored run

2. `criterion_settings.py` reads the settings a run sealed for a network output, and falls back to the defaults where a key is absent (`network_criterion_settings`).
3. `comparison.py` rebuilds the comparison of a run with its mapped network (`network_comparison_from_run`, `NetworkComparison`). It reads the solver centers, the open water, the outline cells and the mean recharge the run kept, and decides none of them. A run that kept no mean recharge is refused when the seepage threshold is above zero.
4. `run_extent.py` counts the flow extents of a transient run, chunk by chunk, with the rules of `catchment/stream_network/extent.py` (`network_extents_from_run`, `flow_geometry_from_run`). `NetworkExtents.scored` holds the cells the criterion scores.
5. `heads_view.py` gives the heads of the mapped network for the map that shows them (`network_heads_view_from_run`).
6. `routing_surface.py` builds the model top the routing figures explain, once per run (`routing_surface_from_run`, `RoutingSurface`).
7. `depressions.py` floods that surface twice, from every escape and from the outlet alone (`depression_fill`, `DepressionFill`, `Flood`).

## What other layers import from it

`display` (all the figures of the stream criterion and of the routing surface), `calibration`, `workflow` and `results` itself. `catchment`, `solver` and `model` do not: what they share with the criterion lives in `catchment/stream_network/`, `catchment/drainage/`, `model/forcing/` and `core/scoring/`.

## Where to add what

- A change to what counts as a stream: `catchment/stream_network/network.py` or `extent.py`, then both calibration and the redraw follow.
- A new input of the criterion: `criterion_inputs.py`, on arrays, called by the trial and by `run_outputs`.
- A new default of the criterion: `core/scoring/stream_defaults.py`, never a literal in a caller.
- A new computation a stream figure needs: a module here that takes a `Run`, never a figure that calls `catchment`.

The tests are in `tests/unit/results/stream/`, `tests/unit/catchment/stream_network/` and `tests/unit/results/`. `tests/unit/architecture/test_the_stream_criterion_reads_once.py` holds that each input has one writer.
