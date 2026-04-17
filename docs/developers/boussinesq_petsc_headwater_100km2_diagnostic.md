# Diagnostic: real headwater 100 km2 case with Boussinesq PETSc regularized partition

## Scope

This note describes one real unstructured-triangular catchment case that is
used to test the new PETSc Boussinesq runtime with the
`regularized_partition` surface-interaction model.

The goal is to have one self-contained technical note that can be reused for:

- external literature search,
- PETSc / nonlinear-solver discussions,
- future bug reports or benchmark tickets,
- comparison against other groundwater solvers.

## Reproduction

Main run command:

```bash
python -m hydromodpy run examples/projects/launcher_simulation/run_headwater_100km2_outlet_2_boussinesq_petsc_partition_mesh_input.toml
```

Main config:

- `examples/projects/launcher_simulation/run_headwater_100km2_outlet_2_boussinesq_petsc_partition_mesh_input.toml`

Base config:

- `examples/projects/launcher_simulation/run_headwater_100km2_outlet_2_boussinesq_mesh_input.toml`

Mesh bundle reused by the run:

- `examples/mesh_gallery/100km2/mesh_headwater_100km2_outlet_2_geology_rivers_buffer30/bundle`

Typical failed-output summary path:

- `examples/projects/launcher_simulation/results_reused_real_meshes/headwater_100km2_outlet_2/results_simulations/flow_main__boussinesq/_boussinesq_summary.json`

## Physical problem actually solved

### Domain

This is a real small headwater basin extracted on an unstructured triangular
mesh, but the computational domain is not exactly the watershed itself. It is
a buffered watershed-envelope domain.

Mesh/bundle metadata:

- CRS: `EPSG:2154`
- mesh type: 2D triangular Gmsh mesh
- `n_cells = 4216`
- `n_edges = 6344`
- `n_nodes = 2129`
- buffered computational domain area: `366463125 m2`
- cells inside watershed: `3692`
- cells outside watershed but inside the buffered envelope: `524`
- river-tagged edges present in the mesh: `699`
- boundary edges: `40`
- interior edges: `6304`

Cell-scale geometry statistics from the committed bundle:

- cell area min: about `1.16e2 m2`
- cell area max: about `2.06e6 m2`
- cell area mean: about `8.69e4 m2`
- top elevation min/max: about `72.42 m / 354.12 m`
- bottom elevation min/max: about `22.42 m / 304.12 m`

Important consequence:

- the real mesh is highly irregular,
- the cell-size spread is very large,
- this is numerically much harder than the small validation strips.

### Vertical geometry

The depth model is a constant-thickness aquifer:

- top surface: from DEM/bundle topography
- bottom surface: `z_bottom = z_top - 50 m`

So the aquifer thickness is fixed to `50 m` everywhere.

### Hydraulic conductivity

Hydraulic conductivity is heterogeneous and comes from the mesh bundle,
already averaged by geology fractions.

Observed bundle statistics:

- `K_min ~= 4.31e-6 m/s`
- `K_max ~= 1.00e-5 m/s`
- around `49` distinct conductivity values appear in the committed bundle

### Storage coefficient

The committed bundle does not carry per-cell storage values.

Because this run is steady:

- the Boussinesq adapter now completes missing `storage_coefficient` with `0.0`
- this is intentional and does not affect the steady residual

This is important for external discussions because the steady nonlinear problem
is effectively solved without a storage term.

### Active forcing and boundary conditions

This exact run uses:

- steady regime
- active source term: uniform recharge only
- active boundary condition: top drainage only
- no wells
- no imposed head boundary
- no ocean boundary
- no stream boundary

Numerical values from the config:

- uniform recharge: `1.0e-8 m/s`
- top drainage conductance: `1.0e-6 m2/s`
- regularization radius for surface interaction: `0.05 m`

Interpretation:

- laterally, the domain boundary is effectively no-flow because no Dirichlet or
  stage boundary is activated,
- the only release mechanism is the top drainage term plus the
  regularized-partition surface flux,
- stream-tagged edges exist in the mesh but are inactive in this run.

### Initial condition

The declared flow initial condition in the config is:

```toml
[flow.ic]
type = "top"
```

Historically this means:

- initial head guess is set at the cell top elevation `h = z_top`

However, for the PETSc `regularized_partition` steady solve, the current code
does one extra stabilization step before Newton starts:

- if the initial guess is exactly at `z_top` or `z_bottom`, that cell is moved
  to the aquifer midpoint `0.5 * (z_top + z_bottom)`

Reason:

- exact top or bottom plateaus produce poor or nearly singular Jacobians for
  the regularized-partition formulation on large real meshes.

So the effective steady Newton initial guess is not the raw `top` field anymore
for cells lying exactly on the top or bottom surfaces.

## Governing discrete problem

This run uses the head-only Boussinesq formulation with regularized partition
for groundwater/surface interaction.

Primary unknown:

- hydraulic head `h_i` for each cell `i`

Steady residual assembled per cell:

```text
R_i(h) =
  lateral_flux_i(h)
  + imposed_head_flux_i(h)
  + drainage_i(h)
  + A_i q_ex,i(h)
  - A_i recharge_i
  - well_i
```

For this specific run:

- `imposed_head_flux_i = 0`
- `well_i = 0`

So the active steady balance is effectively:

```text
lateral_flux_i(h) + drainage_i(h) + A_i q_ex,i(h) - A_i recharge_i = 0
```

with:

- `A_i` the cell area,
- `drainage_i(h) = C_i max(h_i - z_top,i, 0)`,
- `q_ex` the regularized-partition surface rate.

The regularized-partition closure is:

```text
q_ex = G_r(theta) R(balance)
```

where:

- `theta = saturated_thickness / aquifer_thickness`,
- `G_r(theta) = exp(-(1-theta)/r)`,
- `R(u) = max(u, 0)`,
- `balance = - lateral_flux_residual / area + max(recharge, 0)`.

So this is not the mixed complementarity formulation. It is a head-only,
piecewise-regularized surface-release law.

## Numerical method currently used

### Runtime selected

Current resolved runtime summary:

- `runtime_backend = "petsc"`
- `surface_interaction_model = "regularized_partition"`
- runtime kind:
  `petsc_snes_newtonls_sparse_semianalytic_regularized_partition`

Main code paths involved:

- config parsing:
  `hydromodpy/process/flow/flow_config.py`
- runtime selection:
  `hydromodpy/solver/boussinesq/runtime_selection.py`
- regularized-partition PETSc runtime:
  `hydromodpy/solver/boussinesq/runtimes/petsc_partition.py`
- PETSc solver defaults:
  `hydromodpy/solver/boussinesq/runtimes/petsc_common.py`
- residual assembly:
  `hydromodpy/solver/boussinesq/assembly/`
- semianalytic Jacobian:
  `hydromodpy/solver/boussinesq/jacobian/semianalytic.py`
- steady-guess / Jacobian-shift helpers:
  `hydromodpy/solver/boussinesq/runtimes/partition_utils.py`
- bundle-to-solver-mesh adapter:
  `hydromodpy/simulation/adapters/flow/boussinesq.py`

### Unknown layout

This runtime solves only for `h`:

- number of nonlinear unknowns: `4216`
- sparse Jacobian format: PETSc `AIJ`
- execution communicator: `PETSc.COMM_SELF`

This means:

- sparse yes,
- distributed MPI solve no,
- current execution is serial PETSc on one process.

### Nonlinear solve

Current PETSc nonlinear stack in code:

- nonlinear solver: `SNES newtonls`
- line search: backtracking (`bt`)

### Linear solve

The partition backend now prefers a direct linear solve in serial:

- `KSP preonly`
- `PC lu`

This was introduced deliberately to remove `GMRES + ILU` fragility from the
first-line diagnosis on this real case.

Also:

- `setFromOptions()` is now called on line search, KSP, PC and SNES,
- so PETSc runtime options can override these defaults when available in the
  execution environment.

### Jacobian

The Jacobian is sparse and semianalytic:

- base hydraulic part derived analytically almost everywhere,
- regularized-partition contribution derived analytically almost everywhere,
- residual still remains piecewise because of `max`/`clip`.

This is much better than the earlier finite-difference correction approach, but
the problem is still not globally smooth in the strict Newton sense.

### Additional stabilization already added

Two stabilizations are already active for the regularized-partition runtime:

1. Interiorization of the steady initial guess

- exact `z_top` / `z_bottom` guesses are moved to the midpoint

2. Adaptive diagonal shift of the Jacobian

- lightweight pseudo-transient / Levenberg-like diagonal regularization
- the shift decays as the residual decreases

### Iteration budget and tolerance

Current example config now sets:

- `runtime_max_iterations = 200`
- `runtime_tol_residual_inf = 1.0e-7`

The old failing run in the committed output had:

- `runtime_max_iterations = 80`

so the previous failure was reached with a smaller nonlinear budget.

## Failures observed so far

### 1. Wrong launcher command

At one point the case was started with:

```bash
python -m launchers.process_simulation.launcher ...
```

This does not run the launcher correctly here and can appear to no-op.

The correct entrypoint is:

```bash
python -m hydromodpy run <config>
```

### 2. PETSc `Mat.shift()` called on an unassembled matrix

Observed failure:

- PETSc error code `73`
- message: `Not for unassembled matrix`

Cause:

- the code called `matrix.shift(...)` before `matrix.assemble()`

Fix now applied:

- values are inserted,
- matrix is assembled,
- only then is the diagonal shift applied.

### 3. Poor initial guess on large real meshes

Observed behavior on this real case:

- the raw steady initial guess lies on the top surface everywhere,
- this creates large plateau regions exactly at the switching surface,
- the regularized-partition Jacobian becomes badly conditioned or nearly singular.

Fix now applied:

- exact top/bottom initial heads are interiorized to the aquifer midpoint.

### 4. Remaining nonlinear failure after the crash fix

The last failed PETSc summary observed on WSL reported:

- `steady_residual_norm_inf = 3.305489606979413e-06`
- `steady_nonlinear_iterations = 80`
- `steady_termination_reason = "petsc SNES failed reason -5; residual_inf=3.305e-06 exceeds tol_residual_inf=1.000e-07"`

From the PETSc manual:

- `-5` corresponds to `SNES_DIVERGED_MAX_IT`

Source:

- PETSc `SNESConvergedReason` manual page:
  `https://petsc.org/main/manualpages/SNES/SNESConvergedReason/`

Interpretation:

- PETSc no longer crashed,
- the solve progressed,
- the residual decreased to the `1e-6` range,
- but the solve stopped at the iteration limit before reaching `1e-7`.

## Comparison point already available

The same real case has already been made to converge locally with the
`scipy_sparse` runtime after the initial-guess and Jacobian-shift fixes.

Observed local result during development:

- `steady_residual_norm_inf ~= 2.32e-08`
- `steady_nonlinear_iterations = 32`

This is important diagnostically:

- the physical residual and semianalytic Jacobian are not obviously broken,
- the difficult part is the PETSc nonlinear path on this large real mesh,
- after switching the partition backend to direct LU, a fresh WSL rerun is
  needed to see whether PETSc now also converges.

## Main numerical difficulties of this case

This case is numerically hard for several reasons at once.

### No strong lateral Dirichlet anchor

There is:

- recharge,
- top drainage,
- regularized surface release,
- but no imposed-head lateral boundary.

So the free-surface steady problem is weakly anchored compared with classical
benchmark strips with fixed-head boundaries.

### Highly irregular real mesh

The cell-size range is very wide:

- about `1e2 m2` to `2e6 m2`

This directly hurts:

- scaling,
- Jacobian conditioning,
- line-search robustness,
- uniform nonlinear progress across the domain.

### Piecewise regularized physics

The residual uses several clipped operators:

- saturated thickness clipping,
- drainage activation only for `h > z_top`,
- regularized-partition activation based on `max(balance, 0)`.

So even with a semianalytic Jacobian, the nonlinear map is not globally smooth.

### Surface-dominated steady configuration

This specific run is driven by:

- uniform recharge,
- top drainage,
- surface release law,
- no storage term in steady mode.

That tends to create:

- broad nearly saturated areas,
- weakly changing regions,
- Jacobians with small or poorly balanced diagonal terms.

### Buffered-envelope domain

The computational domain contains outside-watershed cells.

This means the run is not only a clean internal watershed drainage problem. It
also contains a surrounding envelope that may create additional weakly active
regions and alter conditioning.

## What has been corrected in code

The current local code base now includes the following corrections or
improvements for this case:

1. Bundle reuse for real triangular meshes without remeshing
2. Completion of missing bundle storage values in steady mode
3. Correct PETSc CSR integer typing
4. Assembly-before-shift ordering for PETSc matrices
5. Interiorized steady initial guess for regularized partition
6. Adaptive Jacobian diagonal shift for regularized partition
7. Partition backend default linear solve switched to direct LU in serial
8. PETSc `setFromOptions()` enabled on SNES/KSP/PC/line-search
9. More explicit PETSc reason labels in termination diagnostics
10. Increased iteration budget in the real-case PETSc example config

## Immediate rerun to perform

After the latest local fixes, rerun exactly:

```bash
python -m hydromodpy run examples/projects/launcher_simulation/run_headwater_100km2_outlet_2_boussinesq_petsc_partition_mesh_input.toml
```

Then inspect:

- stdout / stderr trace
- `_boussinesq_summary.json`

Most useful fields:

- `steady_residual_norm_inf`
- `steady_nonlinear_iterations`
- `steady_termination_reason`
- `runtime_solver_kind`
- `runtime_tol_residual_inf`

## External-search angles worth exploring

The most relevant external-search topics are probably:

- PETSc SNES stagnation on groundwater free-surface problems
- regularized seepage / saturation-excess Newton methods on unstructured meshes
- pseudo-transient continuation for steady groundwater solves
- trust-region SNES versus line-search SNES for poorly conditioned Jacobians
- scaling strategies for nonlinear groundwater residuals on irregular meshes
- Jacobian regularization / diagonal shifting for dry-saturated switching problems
- free-surface Boussinesq or Dupuit solves with no strong Dirichlet boundary
- continuation strategies on recharge or drainage conductance

Suggested search phrases:

- `PETSc SNES_DIVERGED_MAX_IT groundwater unstructured mesh`
- `PETSc nonlinear groundwater regularized seepage Jacobian`
- `pseudo transient continuation steady groundwater Newton`
- `free surface groundwater line search stagnation`
- `irregular triangular mesh groundwater nonlinear scaling`
- `Levenberg regularization singular Jacobian seepage`
- `trust region Newton groundwater PETSc`

## Working hypothesis at this stage

The current main hypothesis is:

- the remaining issue is no longer a low-level PETSc interface bug,
- it is now primarily a nonlinear-convergence problem on a difficult real mesh,
- likely driven by scaling + globalization + weak anchoring + piecewise surface
  physics,
- not primarily by the linear solver anymore, since the partition backend now
  defaults to direct LU in serial.

If the rerun still fails after the latest fixes, the next likely directions are:

- stronger globalization strategy,
- variable / residual scaling,
- continuation on recharge or drainage conductance,
- trust-region or pseudo-transient solve,
- additional smoothing of the switching operators,
- or a different steady initial guess strategy.
