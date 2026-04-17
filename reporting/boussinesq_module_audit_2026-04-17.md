# Boussinesq Module Audit - 2026-04-17

## Scope

This audit reviews the current state of `hydromodpy/solver/boussinesq` after:

- the migration to cell-prescribed Dirichlet conditions;
- the removal of the executable `imposed_*` path from the active runtime;
- the cleanup of naming around boundary diagnostics;
- the extraction of forcing, export and state-building helpers out of the
  top-level driver.

Validation baseline used for this audit:

- Linux / WSL
- environment: `hydromodpy-petsc`
- targeted suites:
  - `tests/unit/solver/test_boussinesq_backend.py`
  - `tests/unit/simulation/test_boussinesq_flow_adapter.py`
  - `tests/unit/display/test_suites.py`
  - `tests/unit/display/test_figures.py`
  - `tests/unit/validation/test_boussinesq_history_contract.py`

## Executive Summary

The module is now in a good technical state.

The important cleanup objective has been reached:

- the active solve path is centered on `prescribed_head_m_by_cell`;
- the old `imposed_*` vocabulary is no longer part of the executable path;
- edge-based boundary quantities exist only as explicit diagnostics;
- the package structure is understandable without reverse-engineering the
  runtime behavior.

The remaining debt is no longer conceptual. It is mostly:

- the size of the physical core (`assembly_fluxes.py`,
  `assembly_residuals.py`);
- the size of the semianalytic Jacobian layer
  (`jacobian_operator_triplets.py`, `jacobian_partition_triplets.py`);
- ordinary numerical-backend glue that cannot be fully collapsed without
  harming readability.

## Module Map

The current structure is readable and largely coherent.

- `mesh.py`
  Solver-owned mesh view and geometric lookups.
- `assembly.py`
  Public assembly facade.
- `assembly_types.py`
  Assembly dataclasses.
- `assembly_inputs.py`
  Boundary/input normalization helpers.
- `assembly_fluxes.py`
  Transmissivity and flux operators.
- `assembly_surface.py`
  Surface-closure helpers.
- `assembly_residuals.py`
  Steady/transient residual builders.
- `jacobian_semianalytic.py`
  Public semianalytic Jacobian facade.
- `jacobian_common.py`
  Shared constraint, sparsity and regularization helpers for Jacobian builds.
- `jacobian_operator_triplets.py`
  Base head-only Jacobian triplets.
- `jacobian_partition_triplets.py`
  Regularized-partition Jacobian triplets.
- `runtime_contract.py`
  Small, clear runtime input/output contract.
- `runtime_selection.py`
  Method/engine resolution.
- `solver_contract.py`
  Process-to-runtime normalization for regime, closure and nonlinear options.
- `driver_steady.py`
  Steady solve orchestration.
- `driver_transient.py`
  Transient solve orchestration and history accumulation loop.
- `driver_forcing.py`
  Shared boundary/ocean/drainage preparation reused by the drivers.
- `runtime_summary.py`
  Runtime-summary bookkeeping and surface-threshold diagnostics.
- `runtime_execution_common.py`
  Shared residual norm and `RuntimeSolveResult` packaging helpers.
- `forcing_resolution.py`
  Thin public facade over the forcing-resolution package.
- `forcing/`
  Specialized forcing mixins split by responsibility:
  initial conditions, recharge, wells, Dirichlet supports, drainage and
  generic payload/support helpers.
- `driver_state.py`
  Accepted-state and history accumulation.
- `export_payload.py`
  Export and `_postprocess` shaping.
- `boundary_flux_reconstruction.py`
  Reconstruction of `boundary_edge_flux_*` diagnostics from the canonical
  runtime state.
- `local_runtime.py`, `scipy_runtime.py`, `scipy_sparse_runtime.py`,
  `petsc_partition_runtime.py`, `petsc_runtime.py`
  Numerical engines.
- `boussinesq.py`
  Top-level orchestration.

## Size Hotspots

The main maintainability issue is still concentration of logic in a few large
files.

Approximate line counts after the latest extraction pass:

- `boussinesq.py`: 441
- `solver_contract.py`: 154
- `assembly.py`: 163
- `assembly_types.py`: 45
- `assembly_inputs.py`: 134
- `assembly_fluxes.py`: 208
- `assembly_surface.py`: 82
- `assembly_residuals.py`: 348
- `forcing_resolution.py`: 38
- `jacobian_semianalytic.py`: 185
- `jacobian_common.py`: 119
- `jacobian_operator_triplets.py`: 267
- `jacobian_partition_triplets.py`: 145
- `driver_transient.py`: 147
- `driver_steady.py`: 86
- `driver_forcing.py`: 98
- `runtime_summary.py`: 279
- `runtime_execution_common.py`: 56
- `forcing/common.py`: 247
- `forcing/dirichlet_support_resolution.py`: 219
- `forcing/recharge_resolution.py`: 120
- `forcing/well_resolution.py`: 96
- `forcing/drainage_resolution.py`: 82
- `forcing/initial_conditions.py`: 28

Interpretation:

- the architectural skeleton is now cleaner than before;
- the big remaining hotspots are concentrated where expected:
  physical assembly and semianalytic Jacobian triplets;
- the driver and forcing facade are now at healthy sizes.

## Assessment

### 1. Clarity

Status: **good**

Strengths:

- the boundary-condition story is now unambiguous;
- the canonical solve representation is clearly cell-based;
- the edge-based diagnostic is clearly reconstructed, not solved directly;
- the package vocabulary is consistent:
  - `prescribed_head_m_by_cell`
  - `boundary_head_m_by_edge`
  - `boundary_edge_flux_m3_s`

Remaining weakness:

- `assembly_residuals.py`, `assembly_fluxes.py`,
  `jacobian_operator_triplets.py` and `jacobian_partition_triplets.py`
  still require careful reading
  because they mix physics and low-level linearization details.

### 2. Accessibility

Status: **good**

The module is now easy enough to enter in this order:

1. `README.md`
2. `mesh.py`
3. `assembly.py`
4. `runtime_contract.py`
5. `solver_contract.py`
6. `forcing_resolution.py`
7. `runtime_selection.py`
8. one runtime backend
9. `driver_state.py` / `export_payload.py`
10. `boussinesq.py`

That is a major improvement over the earlier state where the boundary
semantics were spread across the driver, the runtime and the exports.

### 3. Documentation

Status: **good**

The module now has a coherent documentation stack:

- local navigation in `hydromodpy/solver/boussinesq/README.md`
- equations in `boussinesq_math_notes.tex`
- architecture/UML in RTD
- this audit for maintainability and structure

What is still worth adding later:

- a short contributor note for "adding a new runtime backend";
- a short contributor note for "adding a new diagnostic without touching the
  active solve path".

### 4. Robustness

Status: **good**

Reasons:

- the runtime contract is small and explicit;
- the driver no longer has to reinterpret old boundary payloads on the fly;
- state/export shaping is centralized;
- the targeted Linux suites remain green after the cleanup.

This is a real robustness gain. The former boundary-condition ambiguity was a
source of regression risk because a small change in naming could silently
change the physical meaning of the solve.

### 5. Extensibility

Status: **good**

The extension points are now visible:

- new process-to-array mappings belong in `forcing_resolution.py`;
- new methods or closures belong in `formulations/` and `methods/`;
- new numerical engines belong in `engines/` and the runtime modules;
- new exports or views belong in `export_payload.py` or dedicated helpers;
- new edge-oriented diagnostics belong in `boundary_flux_reconstruction.py`.

The main caveat is file size:

- adding too many responsibilities back into `boussinesq.py` or `assembly.py`
  would quickly degrade the gains already made.

## What Was Actually Removed

The following debt has effectively been retired from the active code path:

- runtime use of `imposed_head_m_by_edge`;
- executable `imposed_head_edge_flux_*` naming;
- public `*_with_imposed_head_edges(...)` entry points in the active path;
- the bridge module dedicated to old edge-imposed Dirichlet conversion;
- the ambiguity between boundary-condition support and runtime representation.

## Remaining Technical Debt

This is what remains and still matters:

1. `assembly_residuals.py` is still large.
   This is now the main residual hotspot.

2. `jacobian_operator_triplets.py` and
   `jacobian_partition_triplets.py` still carry dense low-level details.
   The public `jacobian_semianalytic.py` facade is now small, but the
   underlying sparse operator layer remains substantial.

3. `assembly_fluxes.py` still gathers many low-level operators.
   It is clearer than before, but remains dense.

4. Runtime backends still duplicate some glue.
   A thin shared helper for:
   - residual norm tracking,
   - termination packaging,
   - accepted-step packaging
   has now been introduced, but only part of the repetition has been removed.

5. `assembly.py` and `jacobian_semianalytic.py` still expose both:
   - cell-prescribed boundary heads,
   - edge-supported boundary heads.

   This is no longer legacy debt in the previous sense. It is the remaining
   low-level duality that supports both the active solve and edge diagnostics.

## Recommended Next Steps

Priority order:

1. keep the canonical vocabulary stable;
2. avoid reintroducing any `imposed_*` naming in new code;
3. keep runtime mutualization incremental and only where wording/result
   packaging is truly shared;
4. if a future cleanup is needed, continue splitting
   `assembly_residuals.py` / `assembly_fluxes.py` and
   `jacobian_semianalytic.py` by sub-operators rather than regrowing the
   driver or forcing facade;
5. keep `forcing_resolution.py` as a stable facade over `forcing/`.

## Verdict

The Boussinesq module is now:

- clear enough to maintain;
- easy enough to navigate;
- documented well enough for contributors;
- robust on the validated path;
- extensible without architectural contortions.

The major conceptual debt is gone. What remains is ordinary engineering debt:
the size of the physical core, some backend scaffolding, and a few natural
low-level dual views kept for diagnostics.
