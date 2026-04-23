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

The table below records the 22 tolerances enforced today. Tolerances
marked **TO REVIEW** lack an independent rationale and are fitted to the
current implementation - they must be reassessed before v0.6.

## Table of tolerances

| # | Test / domain | Metric | Tolerance | Source | Notes |
|---|---|---|---|---|---|
| 1 | MODFLOW-NWT / MF6 head convergence | max head change per iteration | `1e-6 m` | Richardson + 2 orders-of-magnitude safety vs solver outer-loop | MODFLOW default HCLOSE |
| 2 | Global water-budget closure | relative error `|Σin-Σout|/Σin` | `1 %` | IMS / PCG solver tolerance | Matches MODFLOW 6 IMS default |
| 3 | Calibration NSE vs baseline | absolute NSE drift | `0.01` | Stochastic optimizer noise (Optuna TPE, 50 trials) | TO REVIEW - empirical |
| 4 | Theis confined pumping 2D | NSE vs analytical (9 probes) | `> 0.999` | Richardson, telescoping grid, 1 m near-well cell | r = 10/50/100 m, t = 1/3/10 d |
| 5 | Theis confined pumping 2D | max pointwise relative drawdown error | `< 1 %` | Near-well discretization, domain radius ≫ r_i(t = 10 d) | Governs probe-by-probe accuracy |
| 6 | Hantush leaky aquifer | NSE and max pointwise relative error | `NSE > 0.99`, `max_rel < 2 %` | Leaky-aquitard assumption, effective K'/b' leakance | r/B ∈ [0.1, 1], thin-conductive source layer |
| 7 | Ogata-Banks 1D transport | NSE and max pointwise relative error | `NSE > 0.95`, `max_rel < 3 %` | Zheng & Wang 1999; Péclet(Δx) = 1 | MF6 GWT TVD scheme, relative-error mask at c > 1e-3 |
| 8 | MMS Laplacian 1D | log-log slope | `\|p - 2\| < 0.2`  (∈ [1.8, 2.2]) | Second-order centred-FV theory | Order 2 with 10 % safety band |
| 9 | MMS diffusion transient 1D (space) | log-log slope | `\|p - 2\| < 0.2`  (∈ [1.8, 2.2]) | Second-order centred-FV, Crank-Nicolson in time | Time error saturated by fine Δt |
| 10 | MMS diffusion transient 1D (time) | log-log slope | `\|p - 1\| < 0.2`  (∈ [0.8, 1.2]) | Backward Euler, first-order in time | Spatial error saturated by fine Δx |
| 11 | Dupuit fixed-head 1D (NWT) | head RMSE | `< 0.05 m` | TO REVIEW | Fitted to reference run |
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

## Update policy

- Tightening a tolerance is always allowed when the underlying test
  still passes: record the change in this file in the same PR.
- Relaxing a tolerance **requires** a new rationale line (source: …).
  If the rationale is "TO REVIEW", the PR must carry a follow-up issue.
- When a new benchmark is introduced, add its tolerance(s) here before
  merging the test.

## Cross-platform determinism

The tolerances above assume that tests run with:

- BLAS single-thread (`OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`,
  `OMP_NUM_THREADS=1`) - enforced by `tests/conftest.py`.
- Fixed RNG seed (0) - enforced autouse via `_deterministic_seeds`.
- No timestamps inside goldens (excluded from signature stats).

Deviating from those assumptions requires documenting the new
tolerance envelope alongside the failing test.
