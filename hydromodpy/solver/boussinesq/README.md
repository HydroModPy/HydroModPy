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
  The lightweight layer that selects the `local`, `scipy`, `scipy_sparse`, or
  Linux-only `petsc` backend together with the requested surface-interaction
  formulation.
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
- imposed-head exchanges,
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
- homogeneous recharge,
- XY-located wells,
- side, stream and ocean Dirichlet supports,
- simplified top drainage,
- dense nonlinear solves on small meshes,
- one sparse SciPy Newton path intended as the bridge toward larger meshes.
- one PETSc path on Linux using a mixed complementarity formulation for
  saturation excess.
- one PETSc path on Linux using the regularized partition surface law on the
  head-only system.

It does not yet provide:

- large production meshes,
- heterogeneous recharge in this first slice,
- the full historical MODFLOW boundary-condition catalog,
- matrix-free Jacobians or graph-colored sparse finite differences yet.

## Recommended Reading Order

If you want to understand the code quickly, read the files in this order:

1. `README.md`
2. `mesh.py`
3. `assembly.py`
4. `runtime_contract.py`
5. `local_runtime.py`
6. `boussinesq.py`

This separates the problem nicely into:

- geometry,
- physics assembly,
- nonlinear numerics,
- application orchestration.
