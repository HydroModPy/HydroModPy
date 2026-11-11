# Metric table

This folder answers how well a simulated series matches an observed one, and when two costs are a tie. Every layer must compute these the same way, so they live in `core`, and `display`, `calibration`, `results` and `catchment` read them. The metric names form a closed table, `METRIC_SPECS` of `metric_table.py`, where a new metric is a row added in the code and never a plugin.

## What a row holds

A `MetricSpec` row holds the name, the direction (`max`, `min`, `zero` or `one`), the sentence that documents the name, and flags for the clipping of negatives, a cost without a unit and a stream network. The table has sixteen rows: ten that calibration scores a trial on, eleven that a sealed run is scored on, five in both. `TRIAL_METRIC_NAMES`, `RUN_METRIC_NAMES`, `NETWORK_METRIC_NAMES` and `METRIC_SENSE` are cut from the rows, and the `Literal` of the names a TOML may write is built from them, so a name is written once. The two orders differ on purpose, since the files that read them keep the order they had.

## How a metric is added

A new metric is a row in `metric_table.py`, then its kernel where it is scored, `calibration/criteria/series.py` for a trial and `results/score.py` for a run. The kernel itself is a NumPy function of `metrics.py` that returns a float. A score that needs a solver or a configuration lives in the layer that owns it.

## What is refused and what tests it

A metric name outside the rows is refused when the file is read, by the `Literal` built from the table, with the names it accepts. `tests/unit/core/scoring/test_metric_table.py` fails when a kernel and a row disagree. This is a science folder under rule 6, and the imports it needs beyond numpy and one neighbour are listed in `ALLOWED_OUTSIDE` of `tests/unit/architecture/test_science_module_imports.py`, a table that only shrinks.
