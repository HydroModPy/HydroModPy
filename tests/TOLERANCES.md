# Numerical tolerances used in HydroModPy tests

This document justifies every numerical tolerance used across the test
suite. Tolerances without a rationale here are considered a defect of
this document and should be tightened or justified in a follow-up PR.

## Principle

Each tolerance comes from one of three sources:

1. **Richardson extrapolation** - discretization error bound as `h → 0`.
2. **Machine epsilon** - `10 · ε · ‖f‖` for analytical solutions
   evaluated without discretization.
3. **Reference literature** - value published in a peer-reviewed
   benchmark (USGS, MODFLOW documentation, textbooks listed below).

References frequently cited:

- MacDonald & Harbaugh 1996, USGS OFR 96-485 (MODFLOW reference run).
- Zheng & Wang 1999, MT3DMS v5 documentation.
- Anderson, Woessner & Hunt 2015, *Applied Groundwater Modeling*, 2nd ed.
- ASME V&V 20-2009 terminology (verification vs validation).

The table below records the 29 tolerances enforced today. Every tolerance
must carry a rationale before it is merged.

## Table of tolerances

| # | Test / domain | Metric | Tolerance | Source | Notes |
|---|---|---|---|---|---|
| 1 | MODFLOW-NWT / MF6 head convergence | max head change per iteration | `1e-6 m` | Richardson + 2 orders-of-magnitude safety vs solver outer-loop | MODFLOW default HCLOSE |
| 2 | Global water-budget closure | relative error `|Σin-Σout|/Σin` | `1 %` | IMS / PCG solver tolerance | Matches MODFLOW 6 IMS default |
| 3 | Calibration NSE vs baseline | absolute NSE drift | `0.01` | Fixed-seed stochastic optimizer envelope (Optuna TPE, 50 trials) | Guards optimizer drift while allowing TPE sampling variance |
| 4 | Theis confined pumping 2D | NSE vs analytical (9 probes) | `> 0.999` | Richardson, telescoping grid, 1 m near-well cell | r = 10/50/100 m, t = 1/3/10 d |
| 5 | Theis confined pumping 2D | max pointwise relative drawdown error | `< 1 %` | Near-well discretization, domain radius ≫ r_i(t = 10 d) | Governs probe-by-probe accuracy |
| 6 | Hantush leaky aquifer | NSE and max pointwise relative error | `NSE > 0.99`, `max_rel < 2 %` | Leaky-aquitard assumption, effective K'/b' leakance | r/B ∈ [0.1, 1], thin-conductive source layer |
| 7 | Ogata-Banks 1D transport | NSE and max pointwise relative error | `NSE > 0.95`, `max_rel < 3 %` | Zheng & Wang 1999; Péclet(Δx) = 1 | MF6 GWT TVD scheme, relative-error mask at c > 1e-3 |
| 8 | MMS Laplacian 1D | log-log slope | `\|p - 2\| < 0.2`  (∈ [1.8, 2.2]) | Second-order centred-FV theory | Order 2 with 10 % safety band |
| 9 | MMS diffusion transient 1D (space) | log-log slope | `\|p - 2\| < 0.2`  (∈ [1.8, 2.2]) | Second-order centred-FV, Crank-Nicolson in time | Time error saturated by fine Δt |
| 10 | MMS diffusion transient 1D (time) | log-log slope | `\|p - 1\| < 0.2`  (∈ [0.8, 1.2]) | Backward Euler, first-order in time | Spatial error saturated by fine Δx |
| 11 | Dupuit fixed-head 1D (NWT) | head RMSE | `< 0.05 m` | First-order finite-volume grid and NWT head tolerance | Looser than MF6 because NWT uses coarser legacy DIS setup in this case |
| 12 | Dupuit fixed-head 1D (MF6) | head RMSE | `< 0.02 m` | Anderson et al. 2015 §6 | Well-posed analytical solution |
| 13 | Boussinesq vs Marçais 2017 | recession slope error | `< 5 %` | Published benchmark | Marçais et al. 2017 Fig. 4 |
| 14 | Regression goldens (arrays) | `rtol` | `1e-4` | Cross-platform BLAS variability | Pre-v0.5 convention |
| 15 | Regression goldens (arrays) | `atol` | `1e-6` | Machine epsilon for float64 | Pre-v0.5 convention |
| 16 | Signature stats (post-v0.5) | `rtol` | `1e-4` | Docstring `_helpers/signatures.py` | Per-field override possible |
| 17 | Signature stats (post-v0.5) | `atol` | `1e-6` | Same | Same |
| 18 | Direct solver outputs | `rtol` | `1e-8` | Well-posed linear system | Iterative is relaxed to `1e-4` |
| 19 | Twin calibration K recovery | `|K-K_true|/K_true` | `< 0.05` | Signal-to-noise ratio at σ=5% | Dupuit 1D twin |
| 20 | Provenance float-stat SHA | exact equality | `n/a` | Hash equality | No tolerance |
| 21 | Mesh vertex/connectivity | exact equality | `n/a` | Integer connectivity | No float tolerance |
| 22 | Bootstrap CI on metrics | bootstrap `rtol` | `2 %` | Sampling noise | 1000 resamples |
| 23 | Geographic catchment golden | boundary area, elevation sum, and pixel-count drift | `0.03 km2`, `1000 m`, `5 px` | Whitebox raster boundary tie envelope on fixed DEM/outlet | Shapes, CRS, elevation distribution, and counts remain constrained |
| 24 | Geographic DEM processing golden | D8/floating raster stat drift | `0.03 m` for elevation stats, `512` for integer sums, `20 m` for float sums | Whitebox D8 tie ordering on fixed DEM/outlet | Per-raster shape, dtype, nodata, counts, min/max, and quantiles remain constrained |
| 25 | Linearized transient recharge step 1D (MF6 irregular tri) | cross-row spread | `< 0.006 m` | Triangular mesh lateral asymmetry envelope | RMSE and max-abs thresholds stay identical to the structured transient benchmark |
| 26 | Linearized transient recharge periodic 1D (MF6 irregular tri) | cross-row spread | `< 0.006 m` | Triangular mesh lateral asymmetry envelope | RMSE and max-abs thresholds stay identical to the structured transient benchmark |
| 27 | Linearized transient boundary piecewise 1D (MF6 irregular tri) | cross-row spread | `< 0.012 m` | Triangular mesh lateral asymmetry envelope under multi-step boundary forcing | RMSE and max-abs thresholds stay identical to the structured transient benchmark |
| 28 | Linearized transient boundary step 1D (MF6 irregular tri) | cross-row spread | `< 0.005 m` | Triangular mesh lateral asymmetry envelope | RMSE and max-abs thresholds stay identical to the structured transient benchmark |
| 29 | Linearized transient recharge step deep 1D (MF6 irregular tri) | cross-row spread | `< 0.0007 m` | Triangular mesh lateral asymmetry envelope in the near-linear deep case | RMSE and max-abs thresholds stay identical to the structured transient benchmark |

## Update policy

- Tightening a tolerance is always allowed when the underlying test
  still passes: record the change in this file in the same PR.
- Relaxing a tolerance **requires** a new rationale line.
- When a new benchmark is introduced, add its tolerance(s) here before
  merging the test.

## Cross-platform determinism

The tolerances above assume that tests run with:

- BLAS single-thread (`OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`,
  `OMP_NUM_THREADS=1`) - enforced by `tests/conftest.py`.
- Fixed RNG seed (42) - enforced autouse via `_deterministic_seeds`.
- No timestamps inside goldens (excluded from signature stats).

Deviating from those assumptions requires documenting the new
tolerance envelope alongside the failing test.
