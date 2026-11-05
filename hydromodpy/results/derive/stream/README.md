# results/derive/stream

This folder answers: which cells does a run call a stream, how is that compared with the mapped
network, and what does a figure need from a finished run to draw it? Calibration scores the criterion
per trial with the first group of modules. The second group rebuilds the same numbers from a stored
run, so a figure cannot contradict the score it illustrates. The figures in `display/` only draw what
these modules return.

## The criterion, as a trial scores it

1. `network.py` turns a per-cell release flux into a simulated network (`build_simulated_network`, `specific_seepage_threshold`, `downstream_closure`).
2. `extent.py` says when a cell flows and how often in a year, and builds the extent masks (`extent_masks`, `calendar_years`, `YearlyFlowCounts`, `VisibleFlow`, `parse_visible_flow`).
3. `heads.py` draws the mapped network from its heads, down the model's own descent (`trace_from_heads`, `HeadsSettings`). The free ends themselves are found in `spatial/geographic/core/network_heads.py`, which also defines `HeadCandidates`.
4. `geometry.py` builds the static geometry of the comparison from the topography and the mapped network (`build_network_geometry`, `NetworkGeometry`, `CriterionSupports`, `VALIDITY_PROVENANCE_BY_CODE`).

The numeric defaults are in `core/scoring/stream_defaults.py`. The mean recharge the criterion divides by is in `spatial/forcing/recharge_rates.py`. The graph, the flood and the distances are in `spatial/drainage/`.

## The criterion, read from a stored run

5. `criterion_settings.py` reads the settings a run sealed for a network output, and falls back to the defaults where a key is absent (`network_criterion_settings`).
6. `comparison.py` rebuilds the comparison of a run with its mapped network (`network_comparison_from_run`, `NetworkComparison`). It is the one place that decides which recharge a redraw divides by.
7. `run_extent.py` counts the flow extents of a transient run, chunk by chunk, with the rules of `extent.py` (`network_extents_from_run`, `flow_geometry_from_run`).
8. `heads_view.py` gives the heads of the mapped network for the map that shows them (`network_heads_view_from_run`).
9. `routing_surface.py` builds the model top the routing figures explain, once per run (`routing_surface_from_run`, `RoutingSurface`).
10. `depressions.py` floods that surface twice, from every escape and from the outlet alone (`depression_fill`, `DepressionFill`, `Flood`).

## What other layers import from it

`display` (all the figures of the stream criterion and of the routing surface), `calibration`, and `results` itself. `spatial`, `solver` and `simulation` do not: what they share with the criterion lives in `spatial/drainage/`, `spatial/forcing/` and `core/scoring/`.

## Where to add what

- A change to what counts as a stream: `network.py` or `extent.py`, then both calibration and the redraw follow.
- A new default of the criterion: `core/scoring/stream_defaults.py`, never a literal in a caller.
- A new computation a stream figure needs: a module here that takes a `Run`, never a figure that calls `spatial` or `core/drainage`.

The tests are in `tests/unit/results/stream/` and `tests/unit/results/`. The layer rules are checked by `tests/unit/architecture/`.
