# Boussinesq stationary strict Picard / L-scheme investigation

## Executive summary

This note documents proposal 1: a strict bounded Picard / L-scheme initializer for the
stationary Boussinesq head problem.

The prototype deliberately removes the previous numerical adaptations:

- no minimum saturated-thickness floor;
- no artificial surface or drainage conductance;
- no change to the default HydroModPy runtime selection;
- no claim that projected Picard is the target VI solution unless the strict projected
  residual, or the optional strict VI check, validates it.

The first implementation is intentionally conservative.  It is useful to diagnose whether
lagging transmissivity plus L-scheme damping can avoid bad Newton/SNESVI basins while
staying inside the original physical problem.  It is not expected to create lateral
connectivity when cells are exactly dry at the bottom, because the strict transmissivity is
then exactly zero.

## Current Implementation Status

Status on 2026-05-23:

- The strict Picard/L-scheme runtime is implemented behind the explicit
  `hydromodpy.solver.boussinesq.runtimes.stationary_picard_lscheme` facade.  It is still an
  investigation path and does not change the default HydroModPy Boussinesq runtime.
- The public facade now exposes the strict Picard loop, the Picard/VI cycling helper,
  shared option dataclasses, diagnostic constants, and diagnostic writers from the
  `picard` subpackage.
- `run_bouss_stationary_picard_matrix.py` can run three strict methods:
  `bounded_picard_lscheme`, `bounded_picard_lscheme_then_vi`, and
  `bounded_picard_vi_cycles`.
- The Picard matrix script now supports the transient verification probe from a converged
  stationary state, and writes CSV/JSON/Markdown matrix summaries plus per-case
  diagnostics.
- The case loader now preserves geology-derived heterogeneous per-cell K values from
  existing `bouss_candidate.toml` mesh bundles.  For external `[mesh_input]` bundles, it
  also injects scalar Sy from the TOML when the bundle does not carry storage coefficients.
- The Boussinesq stationary site-inventory tooling has been added separately:
  `build_bouss_stationary_site_inventories.py` builds auditable CSV/JSON/Markdown
  preflight inventories, and `build_bouss_stationary_site_maps.py` delegates map/HTML
  rendering to the shared site-selection reporting implementation.

What is not implemented as production behavior:

- no automatic selection of `bounded_picard_vi_cycles` from normal HydroModPy simulation
  configs;
- no change to `petsc_mixed.py` or the default PETSc VI behavior;
- no model regularization in the strict Picard path: no `b_min`, no invented drainage, no
  added surface conductance;
- no full ten-site-per-scale production campaign yet.

## Motivation

The natural stationary Boussinesq failures are not only initial-condition failures.  They
occur in stiff or degenerate configurations:

- `h` close to `z_bottom`;
- `T(h) = K b(h)` with `b(h)` tending to zero;
- lower obstacle `h >= z_bottom`;
- upper obstacle `h <= z_top`;
- unstable active sets;
- high `K`;
- zero drainage;
- large irregular natural meshes.

Earlier probes showed that adding a positive thickness floor can improve robustness.  That
is useful information, but it changes the operator: dry cells still carry a transmissive
film.  This proposal steps back to the strict problem and tests only an algorithmic
initialization strategy.

## Strict Problem Definition

The implemented residual uses:

```text
b_phys(h) = clip(h - z_bottom, 0, z_top - z_bottom)
T(h)      = K b_phys(h)
```

There is no `max(b_phys, eps)` term.  If a cell is exactly at the bottom, its physical
saturated thickness is zero.

The bounds are:

```text
z_bottom <= h <= z_top
```

Prescribed heads pin the corresponding cell by setting identical lower and upper bounds
after clipping the prescribed value into the physical interval.

Drainage is strict:

```text
q_drain = C_explicit max(h - z_top, 0)
```

where only explicitly positive conductance values are used.  Missing or zero conductance
does not trigger the existing auto-conductance fallback.  Under the strict upper obstacle,
this term is normally inactive.

## Method

At Picard iteration `k`, the algorithm computes the physical saturated thickness from
`h^k`, then assembles a linear lagged operator:

```text
A(T(h^k)) h^{k+1}
  + Lstab area (h^{k+1} - h^k)
  + strict lagged drainage
  = recharge area + wells
```

The L-scheme term is algorithmic damping only.  It is not reported as physical storage.

After the linear solve:

```text
h_trial   = linear solve result
h_relaxed = (1 - omega) h_old + omega h_trial
h_next    = clip(h_relaxed, z_bottom, z_top)
```

If the projected strict residual grows too much, `omega` is halved down to `omega_min`.
The method stops with one of:

- `converged_target_residual`;
- `converged_update_only`;
- `stagnated`;
- `max_iterations`;
- `linear_solve_failed`.

`converged_update_only` is intentionally not equivalent to a physical stationary solution.

## Final VI Check

The optional `bounded_picard_lscheme_then_vi` path runs a strict PETSc SNESVI check from
the Picard head.  This check uses the same physical bounds and strict residual as the
Picard diagnostics.  If the final VI check fails, the Picard field is kept as the returned
initializer and the failure is recorded in diagnostics.

This avoids silently converting a projected Picard field into an accepted target solution.

## Implementation

Primary files:

- `hydromodpy/solver/boussinesq/runtimes/stationary_picard_lscheme.py`;
- `tests/unit/solver/test_boussinesq_stationary_picard_lscheme.py`;
- `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py`.

The runtime is isolated and must be called explicitly.  It does not modify `petsc_mixed.py`
and does not alter default Boussinesq behavior.

## Diagnostics

Each run can write:

- `picard_lscheme_summary.json`;
- `picard_lscheme_iterations.csv`;
- `picard_lscheme_final_cells.csv`.

The summary records the strict flag, stop reason, final VI status, projected residual,
active top and bottom counts, physically dry cells, head range, physical saturated
thickness quantiles, transmissivity quantiles, `Lstab`, `omega`, and runtime.

The final cell CSV ranks cells by strict projected residual.  It reports physical saturated
thickness and transmissivity only; there is no effective thickness column.

## Unit Tests

The focused tests document these behaviors:

| test | expected behavior |
|---|---|
| options construction | no `picard_b_min`, no `picard_drainage_mode` |
| Picard/VI cycle options construction | default cycle settings are explicit and Picard subdiagnostics are off by default |
| single dry cell, zero recharge | admissible dry equilibrium and serializable diagnostics |
| two cells, flat bottom, dry | zero thickness, zero transmissivity, zero flux |
| two cells, sloping bottom, dry | zero film flux despite head difference |
| dry hillslope, zero drainage | admissible bounded initializer |
| dry single cell, positive recharge | not falsely converged under strict VI residual |
| Picard then strict VI, prescribed single cell | final strict VI can validate a trivial small case |
| Picard/VI cycles, prescribed single cell | cycling path converges and writes cycle diagnostics |

Run the local, lightweight test set from the repository root:

```bash
python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_stationary_picard_lscheme.py -q
```

Expected result on Windows or any environment without PETSc: the pure-Python tests pass and
the two `@pytest.mark.petsc` tests are skipped.  Expected result in the WSL PETSc
environment: all tests in that file pass.

Local check on 2026-05-23 from Windows: `7 passed, 2 skipped`.

Run the same focused test set in the WSL PETSc environment:

```bash
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_stationary_picard_lscheme.py -q"
```

Compilation smoke check for the developed scripts:

```bash
python -m py_compile hydromodpy/solver/boussinesq/runtimes/stationary_picard_lscheme.py \
  tests/unit/solver/test_boussinesq_stationary_picard_lscheme.py \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/build_bouss_stationary_site_inventories.py \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/build_bouss_stationary_site_maps.py
```

Expected result: no output and exit code 0.

Local check on 2026-05-23 from Windows: passed.

## Preliminary Interpretation

The strict method can damp iterations and provide diagnostics without changing the physics.
Its main limitation is structural: if the initial field is fully at the bottom over a
connected dry region, the lagged transmissivity is zero, so the linearized flow operator
does not create lateral connectivity in that region.  L-scheme damping stabilizes the
linear solve, but it does not create transmissivity.

This is an important distinction from the previous thickness-floor experiments.  If strict
Picard still falls into a dry basin on natural cases, the result supports the diagnosis that
the strict stationary problem itself is degenerate for those configurations, not merely that
Newton had a poor globalization strategy.

## Site 01 Results

Strict runs were executed on site 01 only.  Site 02 was not launched.

| case | method | omega | Lstab | Picard converged | final VI converged | Picard residual | final VI residual | active bottom | active top | interpretation |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| site_01_k_high drain_00 | Picard | 0.5 | auto | false | n/a | `2.115e-02` | n/a | 1 | 109 | residual decreases but stagnates |
| site_01_k_high drain_00 | Picard then strict VI | 0.5 | auto | false | false | `2.115e-02` | `1.668e-04` | 1 | 109 | VI improves residual but fails line search |
| site_01_k_high drain_01 | Picard | 0.5 | auto | false | n/a | `2.115e-02` | n/a | 1 | 109 | same strict result; drainage inactive under top obstacle |
| site_01_k_high drain_01 | Picard then strict VI | 0.5 | auto | false | false | `2.115e-02` | `1.668e-04` | 1 | 109 | same strict result |
| site_01_k_high drain_00 | Picard | 1.0 | auto | false | n/a | `1.358e-02` | n/a | 5 | 71 | faster, still not converged at 500 iterations |
| site_01_k_high drain_00 | Picard then strict VI | 1.0 | auto | false | false | `1.358e-02` | `1.668e-04` | 5 | 71 | VI still fails line search after 500 Picard iterations |
| site_01_k_high drain_00 | Picard, 2000 iter | 1.0 | auto | false | n/a | `7.646e-03` | n/a | 60 | 42 | Picard still slow, active set more mature |
| site_01_k_high drain_00 | Picard 2000 then strict VI | 1.0 | auto | false | true | `7.646e-03` | `5.655e-09` | 60 | 42 | strict VI converges in 7 iterations |
| site_01_k_high drain_00 | Picard | 0.5 | `1e-5` | false | n/a | `1.945e-02` | n/a | n/a | n/a | slight improvement over auto |
| site_01_k_high drain_00 | Picard | 0.5 | `1e-4` | false | n/a | `4.545e-02` | n/a | n/a | n/a | too much damping |
| site_01_k_high drain_00 | Picard | 0.25 | auto | false | n/a | `2.596e-02` | n/a | n/a | n/a | slower than default |

The important result is nuanced: strict Picard reduces the residual by one to two orders of
magnitude from the initial top guess, but it does not reach the target tolerance by itself.
At 500 iterations, the optional strict VI check still fails by PETSc line search.  At 2000
Picard iterations with `omega=1.0`, Picard still has a residual of `7.646e-03`, but the
active set is mature enough for the strict VI check to converge in 7 iterations with
projected residual `5.655e-09`.

Drainage `0.1` does not change the strict result in this setup because the method enforces
`h <= z_top` and does not relax the top obstacle into a Cauchy exchange.  This is expected
under the strict problem definition and confirms that the previous drainage-conductance
adaptation has not been reintroduced.

Current recommendation for proposal 1: keep the strict Picard prototype as a slow
diagnostic initializer, not as a standalone stationary solver.  The useful mode is
`Picard long enough to mature the active set -> strict VI finalization`.  The next strict
proposal should test better admissible initial guesses or continuation to reach the same VI
basin faster, before reintroducing any model regularization.

## Picard/VI Cycling Probe

Proposal 2 was tested as a strict composition:

```text
Picard block -> strict VI attempt -> accept VI only if converged or safely improved -> repeat
```

The VI is no longer only a final validator.  It is used as a local nonlinear corrector
between Picard blocks.  A failed VI state is accepted only when it respects the bounds and
reduces the projected residual by the configured factor.

| case | cycles | Picard steps/cycle | total Picard iterations | VI attempts | accepted failed VI | final residual | elapsed | interpretation |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| site_01_k_high drain_00 | 4 | 200 | 603 | 4 | 1 | `8.539e-08` | `8.2 s` | converges, fastest measured |
| site_01_k_high drain_00 | 2 | 100 | 200 | 2 | 1 | `1.676e-07` | `8.6 s` | converges with much less Picard work |
| site_01_k_high drain_00 | 6 | 50 | 203 | 6 | 2 | `1.452e-08` | `12.9 s` | converges but too many VI attempts |
| site_01_k_high drain_00 | 2 | 300 | 600 | 2 | 1 | `2.625e-07` | `9.6 s` | converges, not better than 200-step blocks |
| site_01_k_high drain_01 | 2 | 100 | 200 | 2 | 1 | `1.676e-07` | similar | same strict result; drainage remains inactive |

The 100-step cycle details are particularly informative:

| cycle | start residual | Picard residual | VI residual | accepted source |
|---:|---:|---:|---:|---|
| 1 | `4.549e-01` | `2.895e-02` | `3.08e-03` | failed VI accepted |
| 2 | `3.08e-03` | `7.41e-03` | `1.676e-07` | VI converged |

This confirms the hypothesis: Picard does not need to reach a very low residual by itself.
It only needs to move the state and active set far enough that a VI attempt becomes useful.
The failed VI after the first Picard block is already a better restart than Picard alone.

Current recommendation for proposal 2: the most promising strict initializer is
`bounded_picard_vi_cycles` with `omega=1.0`, 100 to 200 Picard steps per cycle, and strict VI
attempts of about 20 iterations.  It converges the first natural site 01 stress case without
`b_min` and without surface-conductance adaptation, and is much faster than Picard 2000 then
VI.

## Extended Case Matrix And Transient Probe

The cycling method was then run on the remaining priority cases.  For each converged
stationary result, a 30-day PETSc VI transient step was launched with the stationary head as
both `head_prev` and `head_initial_guess`.

| case | cycle settings | stationary converged | stationary residual | elapsed | transient probe | transient residual | note |
|---|---|---:|---:|---:|---:|---:|---|
| site_01_k_high drain_00 | `p100`, VI20 | true | `1.676e-07` | `3.6 s` | true | `1.676e-07` | transient accepts steady state in 0 iterations |
| site_01_k_high drain_01 | `p100`, VI20 | true | `1.676e-07` | `4.4 s` | true | `1.216e-10` | drainage case also passes transient |
| site_01_k_high drain_001 | `p100`, VI20 | true | `1.676e-07` | `4.0 s` | true | `8.914e-09` | drainage case also passes transient |
| site_01_k_base uniform rivers drain_00 | `p100`, VI20 | true | `3.267e-11` | `0.8 s` | true | `3.267e-11` | easy strict case |
| site_02_k_low drain_00 | `p100`, VI20 | true | `3.463e-07` | `39.1 s` | true | `3.463e-07` | large mesh passes |
| site_02_k_base drain_00 | `p100`, VI20 | true | `5.502e-09` | `41.2 s` | true | `5.502e-09` | large mesh passes |
| site_02_network same mesh | `p100`, VI20 | true | `2.900e-08` | `82.4 s` | true | `2.900e-08` | network candidate passes |
| site_02_k_high drain_00 | `p100`, VI20 | false | `1.895e-02` | `306 s` | skipped | n/a | too hard for short cycles |
| site_02_k_high drain_00 | `p200`, VI30 | true | `6.225e-10` | `529 s` | true | `6.225e-10` | hard case passes with longer blocks |
| site_02_k_high drain_00 | `p300`, VI30 | false | `7.238e-04` | `480 s` | skipped | n/a | longer blocks are not monotonically better |

The hard `site_02_k_high` case is qualitatively different.  With `p100`, the VI repeatedly
finds low residual states near `1.87e-04` but fails line search and is often rejected by the
strict acceptance policy.  With `p200` and VI30, three failed VI states are accepted during
the sequence and the 13th cycle finally converges with projected residual `6.225e-10`.

The transient probe is positive for every stationary state that converged.  For zero
drainage cases, the transient often accepts the stationary state immediately.  For positive
drainage site 01 cases, the transient runtime still converges, with residuals below the
stationary tolerance.

Current recommendation after the extended matrix:

1. Default experimental strict initializer candidate: `bounded_picard_vi_cycles`,
   `omega=1.0`, `picard_steps_per_cycle=100`, `vi_max_iterations_per_cycle=20`.
2. Hard fallback for high-K large site 02: increase to `picard_steps_per_cycle=200` and
   `vi_max_iterations_per_cycle=30`.
3. Keep the final VI validation mandatory.  The cycling method can traverse useful failed
   VI states, but only the converged strict VI result should be treated as the stationary
   solution.

## Homogeneous K And Mesh Regularity

The drainage/K/mesh matrix cases initially tested here are homogeneous in hydraulic
conductivity within each run.  The matrix varies the scalar K value between runs, but
`np.unique(mesh.hydraulic_conductivity_m_s).size == 1` for every inspected case:

| group | K values tested |
|---|---|
| site_01 | `1e-5`, `5e-5`, `2e-4` m/s |
| site_02 | `1e-5`, `5e-5`, `2e-4` m/s |

So the current failures and successes are not K-heterogeneity failures.  They are driven by
geometry, topography, active-set behavior, drainage setting, K magnitude, and mesh size.
The word "geology" in the campaign names refers to the natural-site setup, but the
Boussinesq K field used in these Picard runs is scalar.

There is no exact MF6 DISV regular mesh passed through this Boussinesq Picard runtime in the
current matrix.  The closest Boussinesq comparison available is the
`bouss_tri_uniform_rivers` mesh: a quasi-uniform triangular river-constrained mesh.  It is
not identical to a rectangular DISV grid, but it removes many very small irregular cells.

Inventory comparison:

| case family | mesh | n cells | area min | area median | area max |
|---|---|---:|---:|---:|---:|
| site_01 irregular | `bouss_tri_irregular` | 1250 | `195` | `8.17e3` | `2.15e4` |
| site_01 quasi-uniform | `bouss_tri_uniform_rivers` | 534 | `1.33e3` | `1.96e4` | `3.88e4` |
| site_02 irregular | `bouss_tri_irregular` | about 13200 | `5.48` | `4.48e3` | `2.24e4` |
| site_02 quasi-uniform | `bouss_tri_uniform_rivers` | about 5710 | `1.27e3` | `1.09e4` | `4.47e4` |

The quasi-uniform mesh is therefore both smaller and much less extreme in minimum cell
area.  This makes the linear algebra and active-set transitions easier, but it also means
the test does not isolate regularity from cell count.

Drainage 0.1 comparisons with the same strict `bounded_picard_vi_cycles` settings:

| case | mesh | K | stationary residual | elapsed | cycles | Picard iters | transient residual |
|---|---|---:|---:|---:|---:|---:|---:|
| site_01 high drain_01 | irregular | `2e-4` | `1.676e-07` | `4.4 s` | 2 | 200 | `1.216e-10` |
| site_01 high drain_01 | quasi-uniform | `2e-4` | `2.985e-08` | `4.1 s` | 3 | 300 | `3.787e-08` |
| site_02 low drain_01 | irregular | `1e-5` | `1.065e-10` | `23.7 s` | 1 | 100 | `2.616e-14` |
| site_02 low drain_01 | quasi-uniform | `1e-5` | `3.036e-11` | `9.4 s` | 1 | 100 | `7.895e-09` |
| site_02 base drain_01 | irregular | `5e-5` | `4.223e-07` | `199.3 s` | 10 | 1000 | `2.815e-08` |
| site_02 base drain_01 | quasi-uniform | `5e-5` | `3.912e-09` | `10.8 s` | 1 | 100 | `1.295e-12` |
| site_02 high drain_01 | irregular | `2e-4` | `5.494e-08` | `239.3 s` | 15 | 1401 | `3.979e-11` |
| site_02 high drain_01 | quasi-uniform | `2e-4` | `1.328e-10` | `61.0 s` | 9 | 803 | `2.142e-10` |

Interpretation:

1. The transient probe passes behind every converged stationary state in this comparison.
2. The quasi-uniform Boussinesq mesh is clearly easier on site_02 with drainage 0.1:
   roughly `2.5x` faster for low K, `18x` faster for base K, and `4x` faster for high K.
3. The effect is weaker on site_01 because the irregular problem is already small and
   converges quickly.
4. The conclusion should be stated carefully: a more regular mesh helps in these tests, but
   the comparison also changes cell count and minimum area.  The evidence supports
   "large irregular meshes with tiny cells are harder", not a pure theorem that DISV always
   solves the nonlinear difficulty.

## Heterogeneous K Probe On Other Sites

The matrix script was extended to load existing `bouss_candidate.toml` files whose mesh
bundles already carry geology-derived per-cell hydraulic conductivity.  In these cases the
loader no longer replaces K by a scalar; it preserves `mesh.hydraulic_conductivity_m_s`.
For 100 km2 mesh-input cases, the loader reads the external bundle declared in
`[mesh_input]` and injects the scalar Sy from the TOML when the external bundle does not
carry storage coefficients.

The strict Picard/VI cycling method was then run on additional heterogeneous-K sites:

| case | scale | drainage | n cells | K min | K median | K max | K unique | stationary residual | elapsed | cycles | transient residual |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| site_03 hetero N1 | 10 km2 | `0.0` | 2034 | `6.325e-06` | `6.325e-06` | `1.000e-05` | 44 | `3.045e-07` | `2.3 s` | 1 | `3.045e-07` |
| site_03 hetero PETSc regression | 10 km2 | `0.1` | 2034 | `6.325e-06` | `6.325e-06` | `1.000e-05` | 44 | `3.045e-07` | `2.0 s` | 1 | `5.934e-11` |
| site_08 hetero N1 | 10 km2 | `0.0` | 33696 | `1.000e-05` | `1.000e-05` | `3.915e-05` | 25 | `4.172e-08` | `43.3 s` | 1 | `4.172e-08` |
| site_08 hetero PETSc regression | 10 km2 | `0.1` | 33696 | `1.000e-05` | `1.000e-05` | `3.915e-05` | 25 | `4.172e-08` | `51.1 s` | 1 | `1.919e-12` |
| headwater_100km2_outlet_2 hetero | 100 km2 | `0.1` | 4216 | `4.309e-06` | `4.309e-06` | `1.000e-05` | 49 | `7.500e-07` | `8.2 s` | 2 | `3.342e-09` |

All five heterogeneous-K probes converge in stationary mode and the 30-day transient probe
also converges behind each stationary result.  This is a strong positive result for the
strict cycling initializer, but it should not be overgeneralized:

1. The tested heterogeneous K ranges are moderate, roughly a factor `1.6` on site_03,
   factor `3.9` on site_08, and factor `2.3` on the 100 km2 headwater case.
2. These cases are not the same stress class as the previous high-K homogeneous
   `site_02_k_high` drainage-zero case, which still required much longer cycling.
3. Heterogeneity by itself is not currently the dominant failure driver in these probes;
   large high-K, drainage-zero, irregular active-set configurations remain more difficult.

## Developed Matrix Test Cases

These are investigation cases, not unit tests.  They exercise real natural meshes and need
the Linux PETSc environment.

| group | command shape | expected result |
|---|---|---|
| site 01 strict smoke | run `site_01_k_high__bouss_tri_irregular_drain_00` with `bounded_picard_vi_cycles`, `omega=1.0`, `picard_steps_per_cycle=100`, `vi_max_iterations_per_cycle=20`, `--probe-transient` | stationary convergence around `1.7e-7`; transient probe converges from the stationary head |
| site 01 drainage comparison | same settings on `drain_00`, `drain_01`, `drain_001` | all pass; positive drainage cases also pass the transient probe, with drainage mostly inactive under the strict top obstacle |
| site 02 low/base/network | same default cycling settings on `site_02_k_low`, `site_02_k_base`, and `site_02_network` | low/base/network candidates converge, but runtimes are much longer than site 01 |
| site 02 high stress | `site_02_k_high__bouss_tri_irregular_drain_00` with default `p100/VI20`, then fallback `p200/VI30` | default short cycles fail or stagnate; fallback `p200/VI30` converges and the transient probe passes |
| quasi-uniform mesh comparison | `bouss_tri_uniform_rivers` variants on site 01/site 02 with drainage `0.1` | site 02 is substantially faster than the irregular mesh, but the result also changes cell count and minimum cell area |
| heterogeneous K probes | `site_03_hetero`, `site_08_hetero`, and `headwater_100km2_outlet_2_hetero` | all tested heterogeneous-K cases converge in stationary mode and pass the 30-day transient probe |

Minimal WSL command for the main strict cycling smoke:

```bash
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 20 --picard-steps-per-cycle 100 --vi-max-iterations-per-cycle 20 --probe-transient --probe-dt-days 30 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_smoke"
```

Expected artifacts:

- `stationary_strict_picard_lscheme_matrix.csv`;
- `stationary_strict_picard_lscheme_matrix.json`;
- `stationary_strict_picard_lscheme_matrix_summary.md`;
- `diagnostics/<case>/<method>/picard_vi_cycle_summary.json`;
- `diagnostics/<case>/<method>/picard_vi_cycles.csv`;
- `diagnostics/<case>/<method>/picard_lscheme_final_cells.csv`.

Use the CSV row as the first acceptance check: `converged=true`,
`probe_transient_converged=true`, and `residual_norm_inf` below the configured tolerance
or at least in the documented range for the specific stress case.

## Remaining Development

Near-term work:

1. Promote only selected `mesh_gallery_only` rows into `natural_regional_lab_sites.csv`, or
   regenerate that catalog from the upstream site-selection table.
2. Add a hard preflight gate in the campaign scripts so non-ready Boussinesq bundles are
   rejected before computation.
3. Run the broader strict `drain_00` campaign after the inventory gaps are closed: current
   hetero-ready gaps are 2 sites at 10 km2, 4 sites at 100 km2, and 8 sites at 1000 km2.
4. Keep `bounded_picard_vi_cycles` experimental until the ten-site-per-scale campaign has
   passed with final strict VI validation and transient probes.
5. Decide whether the production path should remain strictly unregularized or whether a
   documented model-regularized option (`b_min`, surface drain, or another continuation)
   is acceptable for operational natural cases.

Testing work still missing:

- unit or integration smoke tests for the new site-inventory builder;
- a small deterministic fixture for the map/HTML wrapper;
- a CI-friendly PETSc smoke that runs one tiny Picard/VI cycling case in Linux;
- regression thresholds for the matrix CSV outputs once the selected production candidate
  and site set are frozen.

## Matrix Script

The investigation script exposes only strict methods:

```text
bounded_picard_lscheme
bounded_picard_lscheme_then_vi
bounded_picard_vi_cycles
```

Example command:

```bash
python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py \
  --case site_01_k_high__bouss_tri_irregular_drain_00 \
  --case site_01_k_high__bouss_tri_irregular_drain_01 \
  --method bounded_picard_vi_cycles \
  --probe-transient \
  --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme_site01
```

Large site 02 cases should stay out of the first run until site 01 confirms the prototype
is mechanically correct.

## Recommended Next Proposals

If proposal 1 does not reduce the dry-basin failures, the next proposals should be tested
one by one, with the same diagnostics discipline:

1. strict Picard from wetter admissible initial guesses;
2. strict pseudo-transient continuation with controlled time stepping;
3. active-set continuation on recharge or top reaction;
4. homotopy on conductivity contrast;
5. only after those strict attempts, revisit explicit physical regularizations and document
   them as model changes, not solver-only changes.

## Limitations

- Projected Picard is not an exact VI solve.
- The method may converge by update while the target residual remains too large.
- Strict dry cells have zero transmissivity, so the method cannot rely on film flow.
- Positive drainage conductance is not invented when absent.
- The method is slower than direct SNESVI.
- The strict final VI check depends on PETSc and is Linux-only in the current project setup.

## Commands Executed

Initial implementation checks:

```bash
python -m py_compile hydromodpy/solver/boussinesq/runtimes/stationary_picard_lscheme.py \
  tests/unit/solver/test_boussinesq_stationary_picard_lscheme.py \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py
```

Unit and lint checks:

```bash
python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_stationary_picard_lscheme.py -q
python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_stationary_failure_diagnostics.py -q
python -m pytest -o addopts='' tests/unit/solver/test_petsc_vi_obstacle.py -q
python -m pytest -o addopts='' tests/unit/solver/test_petsc_ts_vi_obstacle.py -q
python -m ruff format hydromodpy/solver/boussinesq/runtimes/stationary_picard_lscheme.py \
  tests/unit/solver/test_boussinesq_stationary_picard_lscheme.py \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py
python -m ruff check hydromodpy/solver/boussinesq/runtimes/stationary_picard_lscheme.py \
  tests/unit/solver/test_boussinesq_stationary_picard_lscheme.py \
  examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py
```

WSL/PETSc checks:

```bash
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest -o addopts='' tests/unit/solver/test_boussinesq_stationary_picard_lscheme.py -q"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest -o addopts='' tests/unit/solver/test_petsc_vi_obstacle.py -q"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python -m pytest -o addopts='' tests/unit/solver/test_petsc_ts_vi_obstacle.py -q"
```

Site 01 matrix and parameter probes:

```bash
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --case site_01_k_high__bouss_tri_irregular_drain_01 --method bounded_picard_lscheme --method bounded_picard_lscheme_then_vi --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme_site01"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_lscheme --Lstab 1e-5 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme_site01_L1e-5"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_lscheme --Lstab 1e-4 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme_site01_L1e-4"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_lscheme --omega 0.25 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme_site01_omega025"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_lscheme --omega 1.0 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme_site01_omega1"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_lscheme_then_vi --omega 1.0 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme_site01_omega1_then_vi"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_lscheme --omega 1.0 --max-iterations 2000 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme_site01_omega1_it2000"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_lscheme_then_vi --omega 1.0 --max-iterations 2000 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme_site01_omega1_it2000_then_vi"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 10 --picard-steps-per-cycle 200 --vi-max-iterations-per-cycle 20 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_site01_c10_p200"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 20 --picard-steps-per-cycle 100 --vi-max-iterations-per-cycle 20 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_site01_c20_p100"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 30 --picard-steps-per-cycle 50 --vi-max-iterations-per-cycle 20 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_site01_c30_p50"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 10 --picard-steps-per-cycle 300 --vi-max-iterations-per-cycle 20 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_site01_c10_p300"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --case site_01_k_high__bouss_tri_irregular_drain_01 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 20 --picard-steps-per-cycle 100 --vi-max-iterations-per-cycle 20 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_site01_c20_p100_drain_compare"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_irregular_drain_00 --case site_01_k_high__bouss_tri_irregular_drain_01 --case site_01_k_high__bouss_tri_irregular_drain_001 --case site_01_k_base__bouss_tri_uniform_rivers_drain_00 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 20 --picard-steps-per-cycle 100 --vi-max-iterations-per-cycle 20 --probe-transient --probe-dt-days 30 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_site01_all_probe_transient"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_02_k_low__bouss_tri_irregular_drain_00 --case site_02_k_base__bouss_tri_irregular_drain_00 --case site_02_k_high__bouss_tri_irregular_drain_00 --case site_02_network__bouss_unstructured_same_mesh --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 20 --picard-steps-per-cycle 100 --vi-max-iterations-per-cycle 20 --probe-transient --probe-dt-days 30 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_site02_probe_transient"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_02_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 15 --picard-steps-per-cycle 200 --vi-max-iterations-per-cycle 30 --probe-transient --probe-dt-days 30 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_site02_high_c15_p200_vi30"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_02_k_high__bouss_tri_irregular_drain_00 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 10 --picard-steps-per-cycle 300 --vi-max-iterations-per-cycle 30 --probe-transient --probe-dt-days 30 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_site02_high_c10_p300_vi30"
```

Homogeneity and mesh-regularity probes:

An inline WSL Python inventory snippet loaded all candidate site_01/site_02 Boussinesq
generated configs and printed `n_cells`, unique K count, scalar K, drainage, and cell-area
quantiles.

```bash
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_01_k_high__bouss_tri_uniform_rivers_drain_01 --case site_02_k_low__bouss_tri_uniform_rivers_drain_01 --case site_02_k_base__bouss_tri_uniform_rivers_drain_01 --case site_02_k_high__bouss_tri_uniform_rivers_drain_01 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 20 --picard-steps-per-cycle 100 --vi-max-iterations-per-cycle 20 --probe-transient --probe-dt-days 30 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_uniform_rivers_probe_transient"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_02_k_low__bouss_tri_irregular_drain_01 --case site_02_k_base__bouss_tri_irregular_drain_01 --case site_02_k_high__bouss_tri_irregular_drain_01 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 20 --picard-steps-per-cycle 100 --vi-max-iterations-per-cycle 20 --probe-transient --probe-dt-days 30 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_site02_irregular_drain01_probe_transient"
```

Heterogeneous K probes:

```bash
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_03_hetero__n1_drain_00 --case site_03_hetero__petsc_regression_drain_01 --case site_08_hetero__petsc_regression_drain_01 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 20 --picard-steps-per-cycle 100 --vi-max-iterations-per-cycle 20 --probe-transient --probe-dt-days 30 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_heterogeneous_sites_probe_transient"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case site_08_hetero__n1_drain_00 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 20 --picard-steps-per-cycle 100 --vi-max-iterations-per-cycle 20 --probe-transient --probe-dt-days 30 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_heterogeneous_site08_drain00_probe_transient"
wsl -e bash -lc "cd /mnt/c/codes/HydroModPy && /home/dreuzy/miniforge3/envs/hydromodpy-wsl/bin/python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py --case headwater_100km2_outlet_2_hetero__petsc_regression_drain_01 --method bounded_picard_vi_cycles --omega 1.0 --cycle-max 20 --picard-steps-per-cycle 100 --vi-max-iterations-per-cycle 20 --probe-transient --probe-dt-days 30 --output-dir docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_vi_cycles_heterogeneous_100km2_probe_transient"
```

## Artifacts

Expected strict artifacts:

- `docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme*/`;
- per-method Picard JSON/CSV diagnostics under `diagnostics/<case>/<method>/`.
