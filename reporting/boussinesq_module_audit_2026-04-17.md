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

- file size;
- repeated runtime bookkeeping;
- a few low-level places where both cell and edge support views remain useful.

## Module Map

The current structure is readable and largely coherent.

- `mesh.py`
  Solver-owned mesh view and geometric lookups.
- `assembly.py`
  Residual assembly and physical flux operators.
- `jacobian_semianalytic.py`
  Analytic/sparse Jacobian builders for the head-only formulations.
- `runtime_contract.py`
  Small, clear runtime input/output contract.
- `runtime_selection.py`
  Method/engine resolution.
- `forcing_resolution.py`
  Process-to-array translation for recharge, wells, Dirichlet supports and
  drainage.
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

Approximate line counts:

- `boussinesq.py`: 1014
- `assembly.py`: 1004
- `forcing_resolution.py`: 848
- `jacobian_semianalytic.py`: 682
- `driver_state.py`: 276
- `runtime_contract.py`: 108
- `runtime_selection.py`: 126

Interpretation:

- the architectural skeleton is clean;
- the orchestration and algebra files remain large enough to deserve ongoing
  discipline;
- the small contract/selection modules are already at a good size.

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

- `assembly.py` and `jacobian_semianalytic.py` still require careful reading
  because they mix physics and low-level linearization details.

### 2. Accessibility

Status: **good**

The module is now easy enough to enter in this order:

1. `README.md`
2. `mesh.py`
3. `assembly.py`
4. `runtime_contract.py`
5. `forcing_resolution.py`
6. `runtime_selection.py`
7. one runtime backend
8. `driver_state.py` / `export_payload.py`
9. `boussinesq.py`

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

1. `boussinesq.py` is still large.
   The file is now better layered, but it still mixes:
   - steady orchestration,
   - transient orchestration,
   - runtime summary shaping,
   - launcher-facing glue.

2. `forcing_resolution.py` is also large.
   It may eventually deserve internal sub-splits such as:
   - recharge resolution,
   - well resolution,
   - Dirichlet support resolution,
   - drainage resolution.

3. Runtime backends still duplicate some glue.
   A thin shared helper for:
   - residual norm tracking,
   - termination packaging,
   - accepted-step packaging,
   - steady/transient solve scaffolding
   would reduce repetition.

4. `assembly.py` and `jacobian_semianalytic.py` still expose both:
   - cell-prescribed boundary heads,
   - edge-supported boundary heads.

   This is no longer legacy debt in the previous sense. It is the remaining
   low-level duality that supports both the active solve and edge diagnostics.

## Recommended Next Steps

Priority order:

1. keep the canonical vocabulary stable;
2. avoid reintroducing any `imposed_*` naming in new code;
3. factor runtime bookkeeping shared by `local/scipy/scipy_sparse/petsc*`;
4. consider a future internal split of `forcing_resolution.py`;
5. split `boussinesq.py` only if a new responsibility would otherwise make it
   grow again.

## Verdict

The Boussinesq module is now:

- clear enough to maintain;
- easy enough to navigate;
- documented well enough for contributors;
- robust on the validated path;
- extensible without architectural contortions.

The major conceptual debt is gone. What remains is ordinary engineering debt:
file size, repeated scaffolding and a few natural low-level dual views kept for
diagnostics.
