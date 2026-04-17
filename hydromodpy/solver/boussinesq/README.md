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
  The top-level orchestrator. It now delegates steady/transient execution,
  runtime-summary shaping and forcing translation to dedicated helpers instead
  of carrying all of that logic inline.
- `mesh.py`
  The solver mesh view. It stores cell geometry, edge connectivity, hydraulic
  properties and a few spatial lookup helpers.
- `assembly/`
  The public physical-assembly package. It exposes the main facade in
  `__init__.py` and groups:
  - `types.py` for assembly dataclasses;
  - `inputs.py` for boundary/input normalization;
  - `fluxes.py` for transmissivity and flux operators;
  - `surface.py` for regularized surface closures;
  - `residuals.py` for steady/transient residual builders;
  - `boundary_flux_reconstruction.py` for edge-based diagnostics.
- `runtime_contract.py`
  The shared data contract between the `Boussinesq` driver and the runtime
  backends.
- `runtime_selection.py`
  The lightweight layer that resolves a method plus one execution engine, then
  exposes the corresponding solve callables.
- `drivers/`
  Runtime orchestration helpers:
  - `steady.py` prepares one stationary solve and updates runtime state;
  - `transient.py` loops over periods and accumulates accepted histories;
  - `forcing.py` centralizes shared boundary/ocean/drainage preparation;
  - `state.py` builds canonical `BoussinesqState` objects and histories.
- `runtime_summary.py`
  Shared summary builders for backend selection, elapsed-time axes and
  surface-threshold diagnostics.
- `runtimes/`
  Shared runtime utilities and supported execution backends:
  - `execution_common.py` for residual norms and runtime-result packaging;
  - `head_only_common.py`, `newton_common.py`, `partition_utils.py`,
    `petsc_common.py` for shared backend helpers;
  - `local.py`, `scipy_dense.py`, `scipy_sparse.py`,
    `petsc_partition.py`, `petsc_mixed.py` for the concrete engines.
- `solver_contract.py`
  The explicit process-to-runtime normalization layer for flow regime,
  surface-interaction closure and nonlinear options.
- `forcing_resolution.py`
  The thin public façade for process-to-array translation.
- `forcing/`
  The specialized forcing-resolution package:
  - `common.py` for generic payload/series/support helpers;
  - `initial_conditions.py` for initial head resolution;
  - `recharge_resolution.py` for homogeneous/heterogeneous recharge;
  - `well_resolution.py` for localized wells;
  - `dirichlet_support_resolution.py` for side/stream/ocean Dirichlet supports;
  - `drainage_resolution.py` for ocean support masks and drainage conductance.
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
- `jacobian/`
  Jacobian helpers grouped by responsibility:
  - `fd.py` for dense and sparse-oriented finite differences;
  - `semianalytic.py` for the public semianalytic facade;
  - `common.py` for shared constraint and sparsity helpers;
  - `operator_triplets.py` for the base head-only operator triplets;
  - `partition_triplets.py` for the regularized-partition extensions.

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
  `assembly/boundary_flux_reconstruction.py` instead of leaking into the active solve
  contract;
- method selection and engine selection are explicit through `methods/`,
  `engines/` and `runtime_selection.py`;
- `BoussinesqState` construction is centralized instead of being repeated in
  several runtime paths.

The main remaining readability debt is no longer semantic confusion around the
boundary conditions. It is now mostly concentrated in:

- `assembly/residuals.py`, which is now the main physical hotspot;
- `assembly/fluxes.py`, which still carries a dense set of operators;
- `jacobian/operator_triplets.py` and `jacobian/partition_triplets.py`, which
  now carry most of the sparse linearization details;
- the coexistence of several numerical engines, which naturally keeps some
  duplicated backend glue even after extraction.

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

- `assembly/residuals.py`, `assembly/fluxes.py`,
  `jacobian/operator_triplets.py` and `jacobian/partition_triplets.py`
  are still the larger files in the physical core;
- runtime modules still share more bookkeeping than they share helper code,
  even after `runtimes/execution_common.py`;
- the low-level assembly/Jacobian layers still accept both the canonical
  cell-prescribed representation and the optional edge-supported boundary view.

That last point is no longer a semantic bug. It is a conscious low-level
design choice used by diagnostics and a small number of focused tests.

## Simplification Review

The current review points to four meaningful simplification targets.

### 1. Keep The Driver Thin

The large driver split targets are now in place:

- `drivers/steady.py` and `drivers/transient.py` carry solve orchestration;
- `runtime_summary.py` carries runtime summary shaping;
- `forcing_resolution.py` is now only the facade over `forcing/`;
- `drivers/state.py` carries accepted-state assembly;
- `export_payload.py` carries NPZ/export payload generation;
- `assembly/boundary_flux_reconstruction.py` isolates the edge-flux reconstruction
  used by diagnostics and regression.

`boussinesq.py` is now back within a reasonable size and should stay a
coordinator, not regrow into the place where every transformation lives.

### 2. Keep Boundary Semantics One-Way

The driver path is already one-way:

- resolve supports;
- project to `prescribed_head_m_by_cell` for the solve;
- rebuild `boundary_edge_flux_*` only for diagnostics.

The remaining simplification target is to keep low-level additions aligned with
that direction. New work should strengthen the canonical prescribed-cell path,
not reintroduce a second active boundary language.

### 3. Continue Runtime Mutualization Gradually

One meaningful runtime mutualization layer now exists:

- `runtimes/execution_common.py` for residual norms and result packaging;
- `runtimes/head_only_common.py` for callback wiring;
- `runtime_summary.py` for backend/diagnostic summaries.

This removed a real amount of repetition. The remaining duplication is mostly
the numerical heart of each backend, which should not be forced into one
generic helper too early.

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
3. `assembly/`
4. `runtime_contract.py`
5. `solver_contract.py`
6. `forcing_resolution.py`
7. `runtime_selection.py`
8. `runtimes/local.py`
9. `drivers/state.py`
10. `export_payload.py`
11. `boussinesq.py`

This separates the problem nicely into:

- geometry,
- physics assembly,
- explicit formulation / discretization / engine taxonomy,
- process-to-array resolution,
- nonlinear numerics,
- accepted-state/export shaping,
- application orchestration.
