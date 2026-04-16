# Boussinesq Solver Package

This directory contains the standalone Boussinesq flow backend used by
HydroModPy on triangular meshes.

The package has a deliberately narrow goal:

- start from a gmsh-derived `CatchmentMeshBundle`,
- build a compact solver-owned mesh view,
- assemble the nonlinear residual in terms of hydraulic head,
- delegate the nonlinear solve to one runtime backend,
- export the accepted state in a format that validation and post-processing
  helpers can already read.

## Architecture At A Glance

- `core/`
  Solver-owned state objects that should remain stable across runtime and
  formulation experiments.
- `discretization/`
  Explicit descriptors for the current space and time schemes.
- `formulations/`
  Explicit algebraic formulations, currently the historical head-only
  regularized-partition system and the mixed PETSc complementarity system.
- `methods/`
  Method catalog combining formulation and discretization into named,
  testable method families.
- `engines/`
  Execution-engine catalog describing how one method is solved numerically.
- `boussinesq.py`
  The orchestrator. It translates launcher objects (`flow`, `time_grid`,
  `domain`) into numeric arrays, calls the nonlinear runtime and exports the
  results.
- `mesh.py`
  The solver mesh view. It stores cell geometry, edge connectivity, hydraulic
  properties and a few spatial lookup helpers.
- `assembly.py`
  The physical core. This module computes saturated thickness, transmissivity,
  edge fluxes and the final residual that must vanish.
- `runtime_contract.py`
  The shared data contract between the `Boussinesq` driver and the runtime
  backends.
- `runtime_selection.py`
  The lightweight layer that resolves a method plus one execution engine, then
  exposes the corresponding solve callables.
- `forcing_resolution.py`
  The process-to-array adapter for recharge, wells, Dirichlet supports and
  drainage payloads.
- `ResolvedDirichletSupport`
  The explicit support record used to resolve one Dirichlet condition once,
  then project it either to the canonical cell-based runtime view or to the
  edge-based support view used by diagnostics.
- `export_payload.py`
  The export layer for `_postprocess` arrays and state-history
  payloads.
- `history_contract.py`
  The explicit transient time contract. It defines the canonical distinction
  between snapshot histories (`t0..tN`) and step histories (`dt1..dtN`), plus
  the helper used to write `.npy` time-series sidecars carrying explicit
  `elapsed_seconds`.
- `driver_state.py`
  The helper layer that accumulates transient histories and builds canonical
  `BoussinesqState` objects from steady and transient runs.
- `boundary_flux_reconstruction.py`
  The helper that rebuilds edge-based boundary-flux diagnostics from the
  canonical cell-prescribed runtime state.
- `head_only_runtime_common.py`
  Shared callback builders for the head-only runtime family
  (`local`, `scipy`, `scipy_sparse`, `petsc_partition`).
- `local_runtime.py`
  A dense, damped Newton solver implemented in-house.
- `scipy_runtime.py`
  A dense variant that uses `scipy.optimize.root` while keeping the same
  physical assembly.
- `scipy_sparse_runtime.py`
  A sparse Newton variant that keeps the same residual assembly but solves each
  Newton step with SciPy sparse matrices and `spsolve`, while grouping
  finite-difference columns through a greedy coloring.
- `petsc_runtime.py`
  A Linux-only PETSc backend that solves one mixed `(h, q_ex)` system with a
  complementarity closure for surface saturation. The nonlinear solve is
  carried by PETSc SNES while the time stepping remains backward Euler at the
  HydroModPy stress-period level.
- `petsc_partition_runtime.py`
  A Linux-only PETSc backend that keeps the head-only residual and solves the
  regularized partition surface law `q_ex = G_r(theta) R(balance)` with PETSc
  SNES on a sparse Jacobian.
- `jacobian_fd.py`
  Shared dense and sparse-oriented finite-difference Jacobian helpers,
  including the sparse column-coloring utilities.

## Process To Solver Contract

The Boussinesq backend now follows one explicit resolution chain that mirrors
what the MODFLOW adapters already do with their `_resolve_*` helpers.

Starting from one validated `Flow` process object:

1. `flow.flow_regime`
   selects the temporal problem kind (`steady` or `transient`);
2. `flow.runtime_backend`
   selects the requested execution family (`local`, `scipy`,
   `scipy_sparse`, `petsc`);
3. `flow.surface_interaction_model`
   selects or requests the groundwater/surface closure
   (`auto`, `regularized_partition`, `complementarity`);
4. `methods/`
   resolves the physical method family
   (formulation + space/time discretization);
5. `engines/`
   resolves the numerical execution engine
   (Newton/SNES flavor, matrix layout, Jacobian strategy, linear solver);
6. `runtime_selection.py`
   combines both axes into one concrete backend descriptor;
7. `boussinesq.py`
   turns launcher/process objects into arrays and delegates the nonlinear solve.

This is the intended hierarchy:

- `process.flow`
  defines the hydrological problem and user-facing solver choices;
- `formulations/`
  defines the algebraic unknowns and surface closure;
- `discretization/`
  defines the spatial and temporal schemes;
- `methods/`
  names physically coherent combinations of formulation + discretization;
- `engines/`
  names numerical solve implementations for a given method;
- `runtime_selection.py`
  resolves the final `(method, engine)` pair;
- `boussinesq.py`
  executes that resolved contract.

So the readable split is:

- hydrological definition: `process.flow`
- physical method: `formulations/` + `methods/`
- numerical scheme descriptors: `discretization/`
- solver engine: `engines/`
- orchestration: `boussinesq.py`

## Current Simplification Status

The package is now much clearer than it used to be on the structural points
that mattered most:

- the canonical Dirichlet representation is `prescribed_head_m_by_cell`;
- the active driver/runtime path solves only through that prescribed-cell
  representation;
- Dirichlet supports are resolved once as `ResolvedDirichletSupport` records,
  then projected either to cells for the solve or to supported edges for
  diagnostics;
- edge-based boundary diagnostics are rebuilt explicitly in
  `boundary_flux_reconstruction.py` instead of leaking into the active solve
  contract;
- method selection and engine selection are explicit through `methods/`,
  `engines/` and `runtime_selection.py`;
- `BoussinesqState` construction is centralized instead of being repeated in
  several runtime paths.

The main remaining readability debt is no longer semantic confusion around the
boundary conditions. It is mostly a matter of file size and repeated runtime
bookkeeping patterns.

### Canonical Internal Vocabulary

These concepts should now be considered the stable internal vocabulary of the
solver:

- boundary-prescribed head on cells: `prescribed_head_m_by_cell`;
- boundary-head support on edges: `boundary_head_m_by_edge`;
- reconstructed boundary diagnostic: `boundary_edge_flux_m3_s`;
- physical nonlinear state: `BoussinesqAssembly`;
- accepted runtime state: `BoussinesqState`;
- process-to-solver resolution: `BoussinesqSolverContract`;
- method taxonomy: `formulations/` + `methods/`;
- execution-engine taxonomy: `engines/`.

### Remaining Structural Debt

The remaining debt is now mostly organizational:

- `boussinesq.py`, `assembly.py`, `forcing_resolution.py` and
  `jacobian_semianalytic.py` are still large files;
- runtime modules still share more bookkeeping than they share helper code;
- the low-level assembly/Jacobian layers still accept both the canonical
  cell-prescribed representation and the optional edge-supported boundary view.

That last point is no longer a semantic bug. It is a conscious low-level
design choice used by diagnostics and a small number of focused tests.

## Simplification Review

The current review points to four meaningful simplification targets.

### 1. Keep The Driver As A Coordinator

The biggest structural split targets are now mostly in place:

- `forcing_resolution.py` carries process-to-array resolution;
- `driver_state.py` carries accepted-state assembly;
- `export_payload.py` carries NPZ/export payload generation;
- `boundary_flux_reconstruction.py` isolates the edge-flux reconstruction
  used by diagnostics and regression.

`boussinesq.py` remains the top-level entry point, but it should stay a
coordinator, not grow back into the place where every transformation lives.
The next safe rule is therefore simple: any new helper that is not pure
orchestration should land outside `boussinesq.py`.

### 2. Keep Boundary Semantics One-Way

The driver path is already one-way:

- resolve supports;
- project to `prescribed_head_m_by_cell` for the solve;
- rebuild `boundary_edge_flux_*` only for diagnostics.

The remaining simplification target is to keep low-level additions aligned with
that direction. New work should strengthen the canonical prescribed-cell path,
not reintroduce a second active boundary language.

### 3. Factor Common Runtime Loop Patterns

The runtime modules still repeat the same high-level pattern:

- build residual/Jacobian callbacks;
- run one nonlinear solve loop or delegate to SciPy/PETSc;
- assemble one `RuntimeSolveResult`.

The different numerical engines are real, but the surrounding glue is still
more duplicated than necessary. The next extraction target is a thin shared
runtime helper layer for:

- termination bookkeeping;
- residual-norm tracking;
- accepted-step packaging;
- steady vs transient callback wiring.

That would reduce the maintenance cost of `local_runtime.py`,
`scipy_runtime.py`, `scipy_sparse_runtime.py`, `petsc_partition_runtime.py`
and `petsc_runtime.py`.

### 4. Make The Documentation Mirror The Code Layers

The package structure is now explicit enough that the documentation should not
be a single mathematical narrative anymore. The useful documentation split is:

- README for local code navigation;
- scientific notes for equations;
- architecture UML for module boundaries and runtime handoffs.

That split is now reflected in the RTD architecture page
`architecture/solver/boussinesq-uml-diagrams`.

## Documentation Map

The recommended documentation set for this package is intentionally small:

1. this `README.md`
2. `boussinesq_math_notes.tex`
3. RTD architecture page
   `docs/readthedocs/source/architecture/solver/boussinesq-uml-diagrams.rst`
4. architecture audit
   `reporting/boussinesq_module_audit_2026-04-17.md`

The UML set is also intentionally limited to four diagrams:

- `boussinesq_context.wsd` for the package/context view;
- `boussinesq_core_classes.wsd` for the stable runtime objects;
- `boussinesq_process_to_backend_sequence.wsd` for the process-to-backend
  handoff;
- `boussinesq_transient_step_activity.wsd` for one transient step and export
  flow.

## Transient Export Contract

For transient runs, the canonical rule is now:

- state-like histories are snapshot histories on `t0..tN`;
- flux-like histories are step histories on `dt1..dtN`;
- `_postprocess/*.npy` time-series written by Boussinesq helpers may carry one
  sibling sidecar named `__time_axis.npy` storing explicit
  `{time_keys, elapsed_seconds}`.

The sidecar exists to prevent downstream code from silently reconstructing the
time axis from dictionary keys alone, especially when one workflow hides the
initial snapshot for plotting convenience.

The canonical disk payload now always keeps the full snapshot history,
including `t0`. Step-based comparisons that need `N` rows instead of `N+1`
must trim the leading snapshot at load time, using the explicit elapsed-time
axis rather than inferring semantics from integer dictionary keys.

## Extra Mathematical Documentation

If you want a more equation-driven explanation, the same directory now contains
`boussinesq_math_notes.tex`. It explains the notation, the finite-volume
balance, the steady and transient residuals, and the link between the formulas
and the main Python functions.

Typical compilation commands are:

```text
pdflatex -interaction=nonstopmode boussinesq_math_notes.tex
latexmk -pdf boussinesq_math_notes.tex
```

## Mental Model Of The Solve

The primary unknown is the cell-centered hydraulic head `h`. From that head,
the solver reconstructs:

- the saturated thickness `b(h)`,
- the transmissivity `T(h) = K b(h)`,
- lateral fluxes between cells,
- boundary-head exchanges,
- surface drainage,
- the selected surface-interaction term.

The nonlinear solver then searches for a head vector `h` such that the residual
is close to zero.

In transient mode the residual also contains the storage term:

`A S (h^{n+1} - h^n) / dt`

In plain words, the residual balances:

- what leaves or enters through cell interfaces,
- what is imposed by boundary stages,
- what drains upward to the surface,
- what enters through recharge,
- what wells inject or extract,
- and, in transient mode, what is stored in the aquifer.

## Current Scope

Today this package supports:

- 2D triangular meshes,
- head as the primary unknown,
- scalar recharge and heterogeneous recharge discretized on the planar mesh,
- XY-located wells,
- side, stream and ocean Dirichlet supports,
- simplified top drainage,
- dense nonlinear solves on small meshes,
- one sparse SciPy Newton path used as the cross-platform reference on larger meshes,
- one PETSc path on Linux using a mixed complementarity formulation for
  saturation excess.
- one PETSc path on Linux using the regularized partition surface law on the
  head-only system.
- committed real unstructured meshes in addition to the small validation cases.
- one committed real-basin transient cycling case where the mixed PETSc path
  resolves repeated on/off threshold windows while the regularized-partition
  paths keep one always-active seepage window under the same forcing.
- explicit `K` / `Sy` overrides on committed mesh bundles when those flow
  parameters are provided at launcher level, including heterogeneous mapping
  through domain supports such as `generated_rings`.
- one committed real-basin transient cycling case with strong lateral
  heterogeneity where both PETSc paths converge, but only the mixed closure
  cleanly turns the surface threshold fully off after the dry pulses.

It does not yet provide:

- the full historical MODFLOW boundary-condition catalog,
- distributed MPI PETSc execution,
- a full coupled overland-flow model,
- matrix-free Jacobians or graph-colored sparse finite differences yet.

## Recommended Reading Order

If you want to understand the code quickly, read the files in this order:

1. `README.md`
2. `mesh.py`
3. `assembly.py`
4. `runtime_contract.py`
5. `forcing_resolution.py`
6. `runtime_selection.py`
7. `local_runtime.py`
8. `driver_state.py`
9. `export_payload.py`
10. `boussinesq.py`

This separates the problem nicely into:

- geometry,
- physics assembly,
- explicit formulation / discretization / engine taxonomy,
- process-to-array resolution,
- nonlinear numerics,
- accepted-state/export shaping,
- application orchestration.
