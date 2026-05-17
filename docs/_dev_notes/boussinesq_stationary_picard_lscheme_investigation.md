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
| single dry cell, zero recharge | admissible dry equilibrium and serializable diagnostics |
| two cells, flat bottom, dry | zero thickness, zero transmissivity, zero flux |
| two cells, sloping bottom, dry | zero film flux despite head difference |
| dry hillslope, zero drainage | admissible bounded initializer |
| dry single cell, positive recharge | not falsely converged under strict VI residual |
| Picard then strict VI, prescribed single cell | final strict VI can validate a trivial small case |

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

## Matrix Script

The investigation script exposes only strict methods:

```text
bounded_picard_lscheme
bounded_picard_lscheme_then_vi
```

Example command:

```bash
python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/run_bouss_stationary_picard_matrix.py \
  --case site_01_k_high__bouss_tri_irregular_drain_00 \
  --case site_01_k_high__bouss_tri_irregular_drain_01 \
  --method bounded_picard_lscheme \
  --method bounded_picard_lscheme_then_vi \
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
```

## Artifacts

Expected strict artifacts:

- `docs/_dev_notes/diagnostics/boussinesq_stationary_strict_picard_lscheme*/`;
- per-method Picard JSON/CSV diagnostics under `diagnostics/<case>/<method>/`.
