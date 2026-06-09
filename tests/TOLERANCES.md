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

The table below records the 42 tolerances enforced today. Every tolerance
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
| 12 | Dupuit fixed-head 1D (MF6) | head RMSE | `< 0.02 m` | Anderson et al. 2015 §6 | Newton default (`mf6_newton`): ~5 mm smoothed-saturation bias vs the idealized Dupuit profile (0.1% of the 5 m drop). Documented literature value; the prior 2e-4 m override fit the old standard formulation and was removed. `max-abs` tolerance 0.03 m |
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
| 23 | Geographic catchment golden | boundary area, elevation sum, and pixel-count drift | `0.06 km2`, `1000 m`, `10 px` | Whitebox D8/breach tie envelope on fixed DEM/outlet across mamba (conda-forge) and pip stacks; ~10 px on 75 m DEM | Shapes, CRS, elevation distribution, and counts remain constrained |
| 24 | Geographic DEM processing golden | D8/floating raster stat drift | `0.03 m` for elevation stats, `max(512, 0.03 * valid cells)` for integer sums, `20 m` for float sums | Whitebox D8 tie ordering on fixed DEM/outlet | Per-raster shape, dtype, nodata, counts, min/max, and quantiles remain constrained |
| 25 | Linearized transient recharge step 1D (MF6 irregular tri) | cross-row spread | `< 0.006 m` | Triangular mesh lateral asymmetry envelope | RMSE and max-abs thresholds stay identical to the structured transient benchmark |
| 26 | Linearized transient recharge periodic 1D (MF6 irregular tri) | cross-row spread | `< 0.006 m` | Triangular mesh lateral asymmetry envelope | RMSE and max-abs thresholds stay identical to the structured transient benchmark |
| 27 | Linearized transient boundary piecewise 1D (MF6 irregular tri) | cross-row spread | `< 0.012 m` | Triangular mesh lateral asymmetry envelope under multi-step boundary forcing | RMSE and max-abs thresholds stay identical to the structured transient benchmark |
| 28 | Linearized transient boundary step 1D (MF6 irregular tri) | cross-row spread | `< 0.005 m` | Triangular mesh lateral asymmetry envelope | RMSE and max-abs thresholds stay identical to the structured transient benchmark |
| 29 | Linearized transient recharge step deep 1D (MF6 irregular tri) | cross-row spread | `< 0.0007 m` | Triangular mesh lateral asymmetry envelope in the near-linear deep case | RMSE and max-abs thresholds stay identical to the structured transient benchmark |
| 30 | Brutsaert fast calibration golden | `x_best` component drift | `cma_es: [1e-4, 2.5e-2]`, deterministic methods tighter | Fixed-seed stochastic optimizer envelope across Optuna/cmaes versions | `cma_es` can choose nearby recession exponents with indistinguishable objective values |
| 31 | Boussinesq drying PETSc cell test | nonlinear residual and dry-cell flux closure | `residual <= 1e-10`, array `atol <= 1e-12` | Solver options request `tol_residual_inf=1e-10`; one-cell geometry has analytical dry equilibrium | Guards the PETSc drying path without mesh-discretization error |
| 32 | Boussinesq headwater 100 km2 PETSc validation | active surface threshold and complementarity diagnostics | `peak cells > 50`, `peak total > 1e3 m3/d`, complementarity floors `>= -1e-6` | Numerical-regime smoke envelope for the regional headwater benchmark | Ensures the PETSc surface interaction is active and respects non-negative gap/rate to solver precision |
| 33 | Reservoir calibration validation | recovered `log10(k)` and `n` drift from truth | `< 0.3` | Fixed-iteration optimizer recovery envelope on deterministic synthetic reservoirs | Wide enough for optimizer path variance, tight enough to reject wrong-order parameters |
| 34 | MF6 PRT uniform-velocity streamline | max relative position error `\|x-x_exp\|/\|x_exp-x0\|` | `< 1 %` | Pollock's method is exact for a uniform velocity field; small allowance for cell-crossing arithmetic | `x(t) = x0 + v*t`, `v = q / porosity`; single-layer constant-gradient flow |
| 35 | MF6 GWT first-order decay 0D | max relative concentration error vs `C0*exp(-k t)` | `< 1 %` | First-order decay is exact in MF6 MST with no advection or dispersion; small allowance for finite time-stepping | Guards the per-second decay contract: `rate_decay` is `1/s` on the SECONDS clock |
| 36 | Dupuit uniform-recharge 1D (MF6, Newton) | head RMSE / max-abs | `< 0.05 m` / `< 0.10 m` | 1.5x Newton bias, capped at the case benchmark (`tolerances.toml`) | Recharge bulge on a 40-cell grid; Newton 4.7 cm RMSE / 6.3 cm max-abs. RMSE sits at the benchmark ceiling |
| 37 | Dupuit circular-island ocean 2D (MF6, Newton) | radial RMSE / max-abs | `< 0.25 m` / `< 0.40 m` | 1.5x Newton bias, capped at the case benchmark (`tolerances.toml`) | 200 m island on a 10 m Cartesian grid; staircased coast dominates. Newton 0.22 m RMSE / 0.26 m max-abs. RMSE sits at the benchmark ceiling; azimuthal, ocean, and freeboard guards stay tighter |
| 38 | Boussinesq circular-island piecewise-K 2D (MF6, Newton) | radial RMSE / max-abs | `< 0.17 m` / `< 0.24 m` | 1.5x Newton bias (within the case benchmark) | Concentric-K coarse-grid radial regime; Newton 0.11 m RMSE / 0.16 m max-abs, well below the 0.35 m benchmark |
| 39 | Boussinesq divide fixed-head piecewise-K 1D (MF6, Newton) | head RMSE / max-abs | `< 0.05 m` / `< 0.08 m` | 1.5x Newton bias, capped at the case benchmark (`tolerances.toml`) | Divide with piecewise K on a 40-cell grid; Newton 3.8 cm RMSE / 5.1 cm max-abs |
| 40 | LAK ex-gwf-lak-p01 (Merritt & Konikow 2000) | final stage abs err / gross lake-aquifer flux rel err / LAK budget closure | `< 0.5 m` / `< 5 %` / `< 1 %` | HMP DISV LAK build vs upstream `get_lak_connections` on the shared single-layer footprint (`validation_cases/.../lak_merritt_konikow_p01/tolerances.toml`) | Two builds agree to 0.25 m stage and 1.1 % gross flux; net flux is a tiny difference of two near-equal terms so the gross magnitude is the stable signal. CONNECTIONDATA matches exactly (25 VERTICAL + 20 HORIZONTAL) |
| 41 | LAK transient multi-layer (Plainfield Lakes abacus) | per-period stage abs err / per-period LAK budget closure / min stage swing | `< 0.05 m` / `< 1 %` / `> 0.1 m` | HMP DISV LAK build pinned to its own converged transient golden, no external reference (`validation_cases/.../lak_pleasant_transient/tolerances.toml`) | One reservoir incised across the top two layers; per-period rainfall / evaporation / runoff swing the stage ~0.35 m over a steady-then-3-transient schedule. Per-period budget closes to ~0 %. CONNECTIONDATA matches exactly (25 VERTICAL + 20 HORIZONTAL layer 0 + 20 HORIZONTAL layer 1) |
| 42 | LAK grid equivalence (regular quad vs irregular triangle DISV) | max per-period stage abs diff / steady lake-aquifer exchange flux rel diff / per-grid LAK budget closure | `< 0.06 m` / `< 5 %` / `< 1 %` | Same lake-aquifer problem on the 15x15 quad DISV (225 cells) and a refined Delaunay triangle DISV (~772 cells), identical physics (`validation_cases/.../lak_pleasant_transient/tolerances_grid_equivalence.toml`) | Grid independence of the production LAK builder. Observed max stage diff 0.038 m (envelope ~1.5x); the storage-free steady exchange flux agrees to ~1e-8 (envelope reuses the row-40 5 % gross-flux band). The lake footprint area is held equal across grids by pinning triangle nodes on the lake boundary lines |
| 43 | MF6 runner parity (subprocess exe vs api libmf6) | lake stage / volume / GWF head agreement across engines | stage `rtol 1e-2, atol 0.05 m`; volume `rtol 2e-2, atol 1.0 m3`; heads `rtol 1e-2, atol 0.05 m` | Same written single-lake DISV simulation solved by the mf6 executable (6.6.3) and by libmf6 (6.7.0) via modflowapi (`tests/integration/tolerances_modflow6_runner_parity.toml`) | NOT bit-equivalence: two different MF6 builds. The stage envelope matches the sibling api-runner e2e test; volume gets a slightly wider band as a laktab-derived state; both engines write the identical .hds/.cbc/obs/stage filerecords, so extraction is structurally identical |
| 44 | SFR standalone budget closure (MF6) | GWF listing `PERCENT DISCREPANCY` | `abs <= 1 %` | IMS solver tolerance, same basis as row 2 (`tests/integration/solver/test_sfr_standalone.py`) | Global closure is necessary but NOT sufficient for SFR (a routing error hides inside a closed budget); row 45 covers the per-package identity |
| 45 | SFR routing identity (MF6) | terminal `EXT-OUTFLOW` vs `inflow + runoff [- gw exchange]` | pure routing `rtol 1e-6`; with streambed exchange `<= 1 %` of total inflow | Pure routing closes to solver arithmetic (no exchange term, `rtol 1e-6` is 2 orders above float accumulation); the connected band matches the IMS budget tolerance because the exchange enters the GWF residual | The per-SFR mass identity asserted from the obs CSV (`sfr` obs is positive when the stream loses to the aquifer; `ext-outflow` is reported negative). Guards mis-routing that row 44 cannot see |
| 46 | SFR -> LAK MVR reciprocity (MF6) | terminal reach `to-mvr` vs lake `from-mvr` | `rtol 1e-9` | At convergence the MVR provider and receiver terms are the SAME number copied across packages within one outer iteration; the band only absorbs the obs-CSV print rounding (`tests/integration/solver/test_sfr_lak_mvr.py`) | The one-outer-iteration MVR lag matters per iteration, not at the converged solution. The same test pins terminal `ext-outflow == 0` (MVR takes the full outflow) and re-uses the row-45 routed identity on `to-mvr` |

## Update policy

- Tightening a tolerance is always allowed when the underlying test
  still passes: record the change in this file in the same PR.
- Relaxing a tolerance **requires** a new rationale line.
- When a new benchmark is introduced, add its tolerance(s) here before
  merging the test.
- 2026-06: MODFLOW 6 adopted the Newton formulation by default
  (`mf6_newton=True`), the robust choice for unconfined catchment cells. The
  per-case MF6 analytical overrides that had been fit to the old standard
  formulation (sub-mm to cm) were re-derived to the case benchmark
  (`tolerances.toml`, shared with the NWT and Boussinesq backends) or the
  documented literature value. Newton's smoothed saturated thickness adds a
  bias of ~0.1% of head range on 1D cases and a few percent on the coarse-grid
  2D radial cases. Determinism is guaranteed by the pinned solver release
  (`DEFAULT_RELEASE = "23.0"`), so these benchmark margins stay stable.

## Cross-platform determinism

The tolerances above assume that tests run with:

- BLAS single-thread (`OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`,
  `OMP_NUM_THREADS=1`) - enforced by `tests/conftest.py`.
- Fixed RNG seed (42) - enforced autouse via `_deterministic_seeds`.
- No timestamps inside goldens (excluded from signature stats).

Deviating from those assumptions requires documenting the new
tolerance envelope alongside the failing test.
