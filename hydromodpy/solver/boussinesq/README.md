# solver/boussinesq

The in-house Boussinesq flow solver on triangular meshes. The unknown is the cell-centered hydraulic head `h`. From it the solver rebuilds the saturated thickness `b(h)`, the transmissivity `T(h) = K b(h)`, the fluxes between cells and through the Dirichlet supports, the drainage to the surface and the surface closure, then looks for the head that sets the finite-volume residual to zero. A transient step adds the storage term `A S (h^{n+1} - h^n) / dt`. The equations, their notation and the functions that compute them are in `boussinesq_math_notes.tex`.

## How a run picks its method and engine

1. `Model.time.regime` chooses a steady or a transient problem.
2. `[solver.boussinesq] backend` chooses the execution family: `local`, `scipy`, `scipy_sparse` or `petsc`.
3. `[solver.boussinesq] surface_interaction_model` chooses the surface closure: `auto`, `regularized_partition`, `complementarity`, `vi_obstacle` or `ts_vi_obstacle`.
4. `catalog.py` resolves the method (formulation, space and time scheme) and the engine (nonlinear and linear solver), and loads the runtime module (`resolve_runtime_backend`).
5. `boussinesq.py` turns the `Model` and the mesh into arrays and hands the solve to the drivers.

Seven engines are declared: dense Newton (`local`), SciPy hybrid root (`scipy`), sparse SciPy Newton (`scipy_sparse`), and four PETSc engines: regularized partition, mixed complementarity, SNESVI obstacle and TS with SNESVI obstacle. The PETSc ones run on Linux with `petsc4py`.

## Parts

1. `boussinesq.py` is `Boussinesq`, the top of the solve. `mesh.py` and `_mesh_builders.py` build the solver mesh view from the cell mesh bundle. `state.py` is the state the solver keeps between steps.
2. `catalog.py` holds the specs of the space and time schemes, the formulations, the methods and the engines, and resolves a run's choice. `solver_contract.py` turns the `Model` and the `[solver.boussinesq]` options into the solver contract, `runtime_contract.py` holds the inputs and results of one runtime solve, `runtime_summary.py` the summary a run writes.
3. `forcing/` maps the forcing of the `Model` on the mesh: initial head, recharge, wells, Dirichlet supports and drains. `BoussinesqForcingResolver` joins them.
4. `assembly/` is the physics: fluxes, surface closure, residuals and the reconstruction of the boundary fluxes. `jacobian/` linearizes it, by finite differences or semi-analytically.
5. `drivers/` run the steady solve and the transient time loop.
6. `runtimes/` are the engines, see its README.
7. `flow_to_boussinesq_adapter.py`, `property_mapping.py`, `smoothing.py`, `export_payload.py` and `calibration_extractors.py` connect the solver to the rest of HydroModPy. `adapters/` and `extractors/` are its registry entries.

## What the solver reads

The solver reads two objects. The frozen `Model` of the run gives the cell mesh and the domain (`geometry`), the K and Sy profiles and their per-cell overrides (`properties`), the boundaries, the recharge and the wells, the start state (`initial`), the regime and the time grid (`time`), and the drain bed thickness (`options`). The options of the nonlinear solve are the `FlowRuntimeConfig` of `[solver.boussinesq]`, which the adapter reads with `state.cfg.solver.options_of("boussinesq")`. The catchment outline and its CRS, which the discharge extraction reads, come from `Model.geometry.catchment`.

The solver never writes the `Model`. A `steady_state` start solves its steady problem on a second solver built over `steady_variant(model)`. That variant has one steady period, the mean recharge of the start strategy and a start at the top. The second solver shares the mesh and the head of the first one, and hands back the head state and the summary it reaches. With `backend = "petsc"` and `surface_interaction_model = "ts_vi_obstacle"`, PETSc integrates the closure in time, so the steady solve runs `regularized_partition` and the main solve keeps `ts_vi_obstacle`.

A Boussinesq run reads no restart. A start read from a run or a solve is refused by name.

Its `supports` lists the side, stream, ocean and drainage boundaries, recharge, wells, `drain_bed_thickness_m`, and the `head_rule` and `steady_start` states. It lists no lake, SFR, ETP, layering, `sink_fill` or `drain_band_depth_m`, so a file that asks for one is refused when it is read, with the solvers that honour it.

## What a transient run writes

State histories (heads) are snapshots on `t0..tN`, flux histories are steps on `dt1..dtN`. The run writes `_boussinesq_state_history.npz` with the full snapshot history, `t0` included, and the extractor derives the water table fields from it. A comparison that needs `N` rows trims the first snapshot with the elapsed-time arrays of the payload.

## Import rules

`boussinesq` imports `base` and the shared layers (`core`, `model`, `catchment`), never `modflow_common`, `modflow_grid`, `modflow6` or `modflow_nwt`.
