# 01 - Calibration

Synthetic Dupuit aquifer (400 m x 50 m, 40x5 grid, one layer, EPSG-free
synthetic domain), steady flow solved with MODFLOW-NWT. `[workflow].mode =
"calibration"` drives an Optuna ask/tell loop that searches hydraulic
conductivity K in [1e-6, 1e-3] m/s against a single twin-synthetic
observation: the analytical Dupuit head at the domain midpoint for the true
K = 1e-4 m/s. No external data and no piezometry source are needed.

## Run

```bash
hmp run examples/projects/01_calibration/project.toml
```

Runtime: about 11 s for 20 Optuna trials on this grid.

## What it shows

The calibration recovers K within 10% of the truth (K = 8.997e-05 m/s
against 1e-4 m/s) from a single observed head value, which is the minimum
possible test of the ask/tell wiring: parameter bounds, the flow-parameter
path into `[flow.param.K.field.value]`, the point observable at (200 m,
25 m), and RMSE as the objective for a one-element series where NSE would be
undefined.
