# Boussinesq Module Review - 2026-04-16

Superseded by
`reporting/boussinesq_module_audit_2026-04-17.md`, which reflects the
post-cleanup state after the final removal of the executable `imposed_*`
surface from the active Boussinesq path.

## Scope

This note reviews `hydromodpy/solver/boussinesq` after the recent cleanup of:

- process-to-solver contract resolution;
- driver/state/export refactoring;
- canonical Dirichlet handling on prescribed boundary cells;
- legacy `imposed_head_*` compatibility isolation.

## Executive Summary

The module is now **substantially clearer and safer** than before.

Main improvements:

- the active driver path is now aligned with the intended conceptual model:
  Dirichlet heads are prescribed on boundary cells;
- the historical edge-based diagnostics are no longer the active runtime path;
- the process-to-backend mapping is explicit;
- accepted-state construction is centralized;
- forcing resolution, export payload assembly and boundary-flux reconstruction
  are split into dedicated modules;
- targeted Linux tests remain green.

The package is now in a **good maintainable state** and the old
`imposed_*` vocabulary is no longer part of the executable code path.

What was completed:

- runtime contracts no longer expose `imposed_head_m_by_edge`;
- head-only runtime helpers accept only `prescribed_head_m_by_cell`;
- public low-level `*_with_imposed_head_edges(...)` entry points were removed;
- `boundary_edge_flux_*` is now the only runtime/export/display diagnostic
  name for edge-based boundary fluxes;
- targeted solver/simulation/display/history tests were migrated and remain
  green under Linux/WSL;
- the prescribed-row bug in the regularized-partition semianalytic Jacobian
  was fixed by excluding identity-row enforcement from the saturation-specific
  Jacobian block.

## Retirement Path For `imposed_*`

The original retirement path is now essentially complete for the Boussinesq
solver module itself:

1. the driver and exports are centered on resolved Dirichlet supports plus
   `prescribed_head_m_by_cell`;
2. displays/regressions use `boundary_edge_flux_*`;
3. low-level runtime and assembly contracts no longer expose the old
   edge-imposed API at their public boundary.

## Assessment

### 1. Clarity

Status: **good**

What is now clear:

- `process.flow` defines hydrological intent;
- `formulations/`, `methods/`, `engines/` and `runtime_selection.py` define
  the solver resolution path;
- `boussinesq.py` acts mainly as an orchestrator;
- `forcing_resolution.py` owns process-to-array mapping;
- `driver_state.py` owns accepted-state construction;
- `export_payload.py` owns export normalization;
- `boundary_flux_reconstruction.py` owns the edge-based diagnostic reconstruction.

What is still less clear than ideal:

- some low-level helpers still expose both edge-based and cell-based boundary
  views;
- the diagnostic reconstruction still lives in a module whose filename
  contains `legacy`;
- a few internal helper names still mention "imposed" although the active
  solver path is fully cell-prescribed.

### 2. Accessibility

Status: **good**

The module is much easier to enter than before because there is now a readable
layering:

1. `mesh.py`
2. `assembly.py`
3. `runtime_contract.py`
4. `runtime_selection.py`
5. `forcing_resolution.py`
6. `boussinesq.py`

This is reinforced by:

- the package README;
- the UML page under `docs/readthedocs/source/architecture/solver/`;
- the process-to-backend contract made explicit in the driver.

The biggest accessibility weakness is still file size:

- `boussinesq.py` remains large, even if much better structured;
- `assembly.py` and `jacobian_semianalytic.py` still require careful reading.

### 3. Documentation

Status: **good**

Documentation is now coherent across three levels:

- local package navigation in `hydromodpy/solver/boussinesq/README.md`;
- architecture/UML in RTD;
- mathematical notes in `boussinesq_math_notes.tex`.

This is enough for maintainers and contributors.

What would further improve documentation:

- one short glossary page for the three main boundary concepts:
  prescribed head, prescribed-head flux, reconstructed boundary edge flux;
- one short developer note on how to add a new runtime backend cleanly.

### 4. Robustness

Status: **good**

Evidence:

- targeted Linux tests remain green after the refactor;
- the active driver/runtime path now uses the canonical prescribed-cell
  representation;
- edge-based diagnostics are rebuilt explicitly rather than inferred
  accidentally from the active solve path.

This is a real robustness gain because it reduces the risk of reintroducing
the old semantic ambiguity between:

- boundary condition support;
- active solve representation;
- diagnostic/export representation.

Residual robustness risk:

- dual support in low-level APIs means a future contributor can still extend
  the legacy path by convenience instead of strengthening the canonical one.

### 5. Extensibility

Status: **good, with one important caveat**

The module is now extensible in the right places:

- new forcing logic can go into `forcing_resolution.py`;
- new runtimes can reuse `runtime_contract.py` and runtime-selection layers;
- new export views can stay outside the active solve path;
- new formulations still fit the current taxonomy.

The caveat is boundary-condition extensibility:

- as long as low-level assembly/Jacobian keep both edge-based and cell-based
  Dirichlet interfaces, every extension has to decide whether to support both.

This is the main place where future complexity could grow back.

## Recommended Next Steps

### Priority 1

Keep the active canonical path strict:

- new work should use `prescribed_head_m_by_cell`;
- `imposed_head_*` should remain compatibility-only.

### Priority 2

Reduce dual low-level APIs gradually:

- move more tests and displays to `prescribed_*` or reconstructed diagnostics;
- once regression consumers are migrated, narrow the low-level contracts.

### Priority 3

Factor shared runtime bookkeeping further:

- result packaging;
- residual norm bookkeeping;
- repeated steady/transient solve scaffolding.

### Priority 4

Add a very short developer note:

- "How to add a new Boussinesq backend"
- "How to add a new boundary diagnostic without touching the active solve path"

## Conclusion

The Boussinesq module is now:

- clearer;
- easier to navigate;
- better documented;
- more robust than before;
- reasonably extensible.

It is not yet minimal, but it has crossed an important threshold: the main
conceptual ambiguity around Dirichlet boundary handling is no longer in the
active runtime path. The remaining debt is now mostly contained and explicit.
