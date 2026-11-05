# core/scoring

This folder answers: how well does a simulated series match an observed one, and when are two costs
a tie? Every layer must compute these the same way, so they live here.

## Modules, in the order a caller uses them

1. `metrics.py` has the fit metrics in pure NumPy: `align` first (it drops pairs with NaN), then `nse`, `log_nse`, `kge`, `rmse`, `mae`, `bias`, `pbias`, `correlation`, and the variants `nse_delta`, `kge_delta` and `nse_seasonal`. They return plain floats.
2. `cost_margin.py` reads the margin that a cost may sit from the best before a trial stops being tied with it (`parse_cost_margin`, `CostMargin`). A margin has a unit: `"5%"` is a share of the best cost, `"75 m"` is an absolute distance.

## What other layers import from it

`display`, `calibration`, `results` and `simulation`.

## Where to add what

- A metric: `metrics.py`, NumPy only, a float out.
- A new kind of margin: `cost_margin.py`, with its unit check.
- A score that needs a solver or a config: in the layer that owns it.

The tests are in `tests/unit/`. The layer rules are checked by `tests/unit/architecture/`.
