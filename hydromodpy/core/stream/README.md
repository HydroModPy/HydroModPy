# core/stream

This folder answers: which cells does a run call a stream, and how is that compared with the mapped
network? It is written once because calibration scores it per trial and `results` redraws it from a
finished run.

## Modules, in the order a caller uses them

1. `criterion_defaults.py` has the numeric defaults of the criterion in one model (`StreamCriterionDefaults`, `STREAM_CRITERION_DEFAULTS`).
2. `recharge.py` gives the mean recharge the criterion divides by (`criterion_mean_recharge`, `mean_recharge_m_s`), so trials and figures use one R.
3. `network.py` turns a per-cell release flux into a simulated network (`build_simulated_network`, `specific_seepage_threshold`, `downstream_closure`).
4. `extent.py` says when a cell flows and how often in a year, and builds the extent masks (`extent_masks`, `calendar_years`, `YearlyFlowCounts`).
5. `geometry.py` builds the static geometry of the comparison from the topography and the mapped network (`build_network_geometry`, `CriterionSupports`).
6. `heads.py` draws the mapped network from its heads, down the model's own descent (`trace_from_heads`, `HeadsSettings`).

## What other layers import from it

`calibration`, `display`, `results`, `spatial`, `solver` and `simulation`. It reads `core/drainage/`.

## Where to add what

- A new default of the criterion: `criterion_defaults.py`, never a literal in a caller.
- A change to what counts as a stream: `network.py` or `extent.py`, then both calibration and results follow.

The layer rules are checked by `tests/unit/architecture/`.
