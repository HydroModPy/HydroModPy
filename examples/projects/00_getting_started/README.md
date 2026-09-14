# 00 - Getting started

Synthetic 1D Dupuit aquifer, steady-state flow, solved with MODFLOW-NWT. The
grid is 400 m by 50 m (40 by 5 cells), homogeneous K = 1e-4 m/s, fixed heads
of 5.0 m on both banks, uniform recharge. Self-contained: no DEM, no
external data, no download.

## Run

```bash
hmp run examples/projects/00_getting_started/project.toml
```

Runtime: about 9 s.

## What it shows

The `[geographic.synthetic]` domain mode: a rectangular grid built from
parameters instead of a DEM or a catchment delineation. Use this shape when
testing a solver or a config feature without any real dataset.
