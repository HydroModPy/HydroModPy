# Boussinesq backend

The in-house Boussinesq flow solver on triangular meshes. The unknown is the cell-centred head `h`, from which the solver rebuilds the saturated thickness, the transmissivity `T(h) = K b(h)`, the fluxes between cells and through the Dirichlet supports, the drainage and the surface closure, then looks for the head that sets the finite-volume residual to zero. A transient step adds the storage term `A S (h^{n+1} - h^n) / dt`. The equations and the functions that compute them are in `boussinesq_math_notes.tex`. It is a backend of the solver port of `solver/base`, and it reads `base`, `core`, `model`, `catchment`, `mesh` and `results`, never a MODFLOW package.

## What it receives

`build` receives the frozen `Model` and the `BoussinesqOptions` of `[solver.boussinesq]` (`options.py`). The `Model` gives the cell mesh and the domain, the K and Sy profiles and their per-cell values, the boundaries, the recharge, the wells, the start state, the regime, the time grid and the drain bed thickness. The option `exchange_mesh` names a mesh bundle that stands for the cell mesh and the properties of the `Model`, read against the folder of the TOML, so a per-cell override of a property is refused with it. `[solver.boussinesq] backend` picks the engine family (`local`, `scipy`, `scipy_sparse` or `petsc`) and `surface_interaction_model` the surface closure. The four PETSc engines run on Linux with `petsc4py`.

## What it returns

`run` writes `_boussinesq_state_history.npz`, the head snapshots on `t0..tN`, in the folder `slot.directory`, and returns the `SolverRun` with the wall time of the solve as `solve_s`. The extractor derives the water table fields from the snapshots, writes the diagnostics of a variational inequality solve to `exports/solver_diagnostics/` and writes `final_state/` with the head of the last period in float64. State histories are snapshots on `t0..tN` and flux histories steps on `dt1..dtN`, so a comparison that needs `N` rows trims the first snapshot.

## What it declares

`name = "boussinesq"`, `process_type = "flow"`, `accepted_meshes = {"triangle"}`, `geometry = "cells"`, `category = "integrated"`, no `native_step`, an empty `mutable` (so no `rerun`) and no `requires`. Its `supports` lists the side, stream, ocean and drainage boundaries, recharge, wells, `drain_bed_thickness_m` and the `head_rule` and `steady_start` states. It lists no lake, SFR, ETP, layering, `sink_fill` or `drain_band_depth_m`.

## How it registers and what it refuses

It is the built-in path `flow_boussinesq` of `_BUILTIN_PATHS` in `solver/base/registry.py`, with its extractor under the same key. A file that asks for a trait outside `supports` is refused when it is read, with the solvers that honour it. A layered domain is refused by `build`, because the solver computes one layer. A start read from a run or a solve is refused by name, because a Boussinesq run reads no restart. The transient driver reads the stop flag of the slot between two periods.

## What tests it

`tests/ports/test_solver.py` holds it to the port with every other backend, and `tests/unit/solver/boussinesq/` holds its kernels.
