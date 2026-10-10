# Boussinesq engines and experimental closures

The equations of the Boussinesq solver are on {doc}`/theory/boussinesq`. This page is
for the contributor who works on how they are solved: the method and engine catalogs,
each engine step by step, the two experimental obstacle closures, and the diagnostics
a run writes. The module diagrams are on {doc}`boussinesq-uml-diagrams`.

## Methods and engines

Two choices are independent. The method is the physics: the unknowns, the closure,
the space scheme and the time scheme. The engine is the numerics: the nonlinear
solver, the matrix layout, the Jacobian and the linear solver. Two runs can share a
method and differ by the engine. The keys are
{toml}`flow.surface_interaction_model` for the closure and
{toml}`flow.runtime_backend` for the engine.

### The method

The closure and the runtime backend resolve to one method
(`resolve_method_spec` in `methods/catalog.py`):

| Method | Unknowns | Closure | Time scheme | Runtime backends |
|---|---|---|---|---|
| `head_only_regularized_partition` | $h$ | `regularized_partition` | steady, backward Euler | `local`, `scipy`, `scipy_sparse`, `petsc` |
| `mixed_complementarity` | $h, q^{\mathrm{ex}}, q^{\mathrm{dry}}$ | `complementarity` | steady, backward Euler | `petsc` |
| `head_only_vi_obstacle` | $h$ | `vi_obstacle` | steady, backward Euler | `petsc` |
| `head_only_ts_vi_obstacle` | $h$ | `ts_vi_obstacle` | backward Euler | `petsc` |

With `auto`, the closure is `complementarity` on PETSc and
`regularized_partition` on every other backend. A closure that the backend does
not implement is refused when the solve starts: the message says
`The requested Boussinesq surface-interaction model is not implemented`. The
space scheme is the same for all four methods.

```toml
base_config = "step4_transient.toml"

[solver]
backend = { backend = "boussinesq" }

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["boussinesq"]

# The rivers the mesh follows: every cell that drains more than 0.5 km2.
[geographic.river_network]
enabled = true
threshold_area_km2 = 0.5

[mesh_catchment]
constraints_mode = "rivers_only"
cache = true

[flow]
runtime_backend = "scipy_sparse"
surface_interaction_model = "regularized_partition"
```

The block selects the solver and the closure. The mesh section is the one the
solver needs: it reads a triangular mesh, from {toml}`mesh_catchment` or from
{toml}`mesh_input`. Example 04 as shipped runs on MODFLOW 6.

The same file with the mixed closure:

```toml
base_config = "step4_transient.toml"

[solver]
backend = { backend = "boussinesq" }

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["boussinesq"]

# The rivers the mesh follows: every cell that drains more than 0.5 km2.
[geographic.river_network]
enabled = true
threshold_area_km2 = 0.5

[mesh_catchment]
constraints_mode = "rivers_only"
cache = true

[flow]
runtime_backend = "petsc"
surface_interaction_model = "complementarity"
```

The pair below loads, and the run then refuses it, because the complementarity
closure is implemented only on PETSc:

```toml
# not checked: shows a pair that loads and that the run refuses
base_config = "step4_transient.toml"

[solver]
backend = { backend = "boussinesq" }

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["boussinesq"]

[flow]
runtime_backend = "scipy_sparse"
surface_interaction_model = "complementarity"
```

### The engine

The runtime backends are numerical engines for one method. They are not separate
hydrological models. The rows are the pairs of the engine catalog
(`engines/catalog.py`):

| Backend | Method | Nonlinear solver | Jacobian | Linear solver |
|---|---|---|---|---|
| `local` | head-only partition | damped Newton, dense | forward finite differences | NumPy dense solve |
| `scipy` | head-only partition | SciPy `root`, method `hybr` | semi-analytic, dense | MINPACK `hybr` |
| `scipy_sparse` | head-only partition | damped Newton, sparse | semi-analytic, plus coloured finite differences for the release | SciPy `spsolve` |
| `petsc` | head-only partition | PETSc SNES `newtonls` | semi-analytic, sparse | direct LU |
| `petsc` | mixed complementarity | PETSc SNES `newtonls` on the three unknowns | semi-analytic, sparse blocks | direct LU |
| `petsc` | `vi_obstacle` | PETSc SNESVI `vinewtonrsls` | semi-analytic, sparse | direct LU |
| `petsc` | `ts_vi_obstacle` | PETSc TS backward Euler with SNESVI | semi-analytic, sparse | direct LU, with a shift |

The PETSc engines run only on Linux and need `petsc4py`: on another system the run
stops with a message that starts `Boussinesq runtime_backend='petsc' is only
supported on Linux.` They run in serial, on `PETSc.COMM_SELF`.

## The nonlinear solve

Every engine looks for a head $h$ such that the residual vector is zero. The
vector it tests is the solver residual: the balance in m³/s on a free cell,
and $h_j - H^D_j$ in metres on a constrained cell. The tolerance
{toml}`flow.runtime_tol_residual_inf` applies to the largest absolute entry. The
iteration budget is {toml}`flow.runtime_max_iterations`; when the key is not set,
the runtime has its own budget, larger on `scipy_sparse` than on the others
(`build_runtime_options` in `solver_contract.py`). A step that does not converge
ends the run.

### The local engine

The `local` engine is a damped Newton loop (`_newton_loop_template` in
`runtimes/newton_common.py`), written to be read:

1. start from the initial guess and assemble the residual;
1. build a dense Jacobian by forward finite differences, with a step of
   $10^{-7}\max(1, \lvert h \rvert)$ on each head in turn
   (`build_dense_fd_jacobian`);
1. solve $J\,\delta = -R$ with a dense solve;
1. halve the step, from 1 down to a minimum factor, until the largest residual entry
   falls; if it never does, the solve stops and is not converged;
1. stop when the largest residual entry is below the tolerance.

The method is transparent and fit for small validation meshes. A dense engine assembles
a dense Jacobian, so an explicit `local` or `scipy` refuses a mesh of more than 400
cells (`_assert_runtime_mesh_size_supported` in `boussinesq.py`). The default `auto`
runs `local` up to 400 cells and `scipy_sparse` above, and logs the engine once
(`resolve_runtime_backend_name` in `solver_contract.py`).

### The SciPy engine

The `scipy` engine keeps the same residual. It gives SciPy a semi-analytic dense
Jacobian and lets `scipy.optimize.root` with the `hybr` method drive the solve
(`runtimes/scipy_dense.py`). SciPy stops on its own criterion on the step, set
from {toml}`flow.runtime_tol_state_update_inf`, and the run then checks the residual
against the tolerance: a solve that SciPy calls successful but whose residual is
above the tolerance is reported as not converged. It has the same limit of 400
cells.

### The SciPy sparse engine

The `scipy_sparse` engine runs the same Newton loop as `local` with a sparse
Jacobian (`runtimes/scipy_sparse.py`):

1. the smooth terms, which are the internal fluxes, the storage, the drain and the
   constraints, are differentiated analytically;
1. the release $s_i$ is completed by finite differences, with columns of the
   matrix that do not share a row perturbed together (graph colouring);
1. the Newton step is solved with `spsolve`.

If the matrix is singular, the step is solved again with a diagonal shift that grows
by a factor of ten at each of up to six tries. For a steady solve the initial guess
is moved to the middle of the cell wherever the head sits exactly on the top or the
bottom, because the partition Jacobian can be singular there
(`interiorize_regularized_partition_initial_guess`). This is the reference engine
for larger meshes on every system.

### The PETSc engines

The PETSc partition engine solves the same head-only residual with PETSc SNES, a
Newton method with a backtracking line search, on a sparse semi-analytic Jacobian
(`runtimes/petsc_partition.py`). The linear systems are solved by a direct LU
factorisation with a small shift of the diagonal against zero pivots
(`_configure_default_snes` in `runtimes/petsc_common.py`). The absolute
tolerance of SNES is the residual tolerance, and its relative and step tolerances
are off. The Jacobian also receives a diagonal shift that decays with the residual,
a light pseudo-transient regularisation for large meshes:

$$
\mathrm{shift} = \max\Bigl(10^{-8},\ 0.2\;\mathrm{median}_{J_{ii} \neq 0}\,
\lvert J_{ii}\rvert\ \min\bigl(1,\ \lVert R\rVert_\infty / \lVert R_0\rVert_\infty\bigr)\Bigr)
$$

where $R_0$ is the residual of the first iterate. The shift vanishes as the
solve converges. The residual does not contain it, so the solution is the one of the
unshifted system (`regularized_partition_jacobian_shift` in
`runtimes/partition_utils.py`).

The mixed engine solves the system of $3n$ unknowns of
{ref}`bq-lower-obstacle`, with the rates scaled by $q_s$
(`_solve_mixed_problem` in `runtimes/petsc_mixed.py`). The residual has three
blocks: the balance with $-a_i q^{\mathrm{dry}}_i$, the Fischer-Burmeister
equation of the surface, and the Fischer-Burmeister equation of the bottom. The run
converges when SNES reports a convergence and the largest entry of the full residual
is below the tolerance.

The starting point of the mixed solve is a numerical choice, not a physical one. The
head is clipped between the bottom and the top. A free cell whose balance at the
bottom still asks to lose water starts at the bottom. In a transient run, the first
guess of $q^{\mathrm{ex}}$ is the release the regularised partition would
give when the recharge is positive or a well flux is negative, and zero otherwise
(`_initial_transient_q_ex_guess`). That guess uses a depth scale of 5 % of the head
scale $h_s$, not {toml}`flow.partition_release_depth_m`, so that it starts off the
kink of the Fischer-Burmeister function. The choice changes the path to the
solution, not the equations.

The VI engines solve the bounded system of {ref}`bq-engines-obstacle`.

(bq-engines-obstacle)=
## The experimental obstacle closures

Two more closures exist and are marked experimental on their cards. Both run on
PETSc only, and both keep the head as the only unknown.

- `vi_obstacle` solves the balance with the head bounded between the bottom and
  the land surface, as a variational inequality (PETSc SNESVI). The release is not
  in the system: $s_i = 0$ while the solver iterates. After convergence, the
  balance left on a cell at its upper bound is read as the saturation excess, and
  on a cell at its lower bound as the unmet demand (`reconstruct_obstacle_reactions`
  in `runtimes/petsc_vi/obstacle.py`):

  $$
  q^{\mathrm{ex}}_i = \frac{\max(-R_i,\ 0)}{a_i},
  \qquad
  q^{\mathrm{dry}}_i = \frac{\max(R_i,\ 0)}{a_i}
  $$

  The first expression is used on a cell at its upper bound and the second on a cell
  at its lower bound. The upper bound is relaxed when a positive drain conductance
  is declared, so that the drain carries the exchange at the surface
  (`runtimes/vi_bounds.py`). Each time step can be cut into substeps, with
  {toml}`flow.vi_substeps_per_period`, and a failed time step can be retried with more
  substeps.
- `ts_vi_obstacle` hands the time stepping to PETSc TS with a backward Euler
  scheme, inside each time step, and keeps the same bounds. The storage term is
  $a_i S_{y,i}\,\dot h_i$, because the head is bounded. The number of steps and
  the adaptivity are set by the `ts_vi_*` keys listed below.

A steady solve for the initial state of a `ts_vi_obstacle` run uses the regularised
partition (`steady_state_initialization_surface_interaction_model` in
`solver/steady_initial_conditions.py`).

A file that chooses the experimental closure and cuts each period into substeps:

```toml
base_config = "step4_transient.toml"

[solver]
backend = { backend = "boussinesq" }

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["boussinesq"]

# The rivers the mesh follows: every cell that drains more than 0.5 km2.
[geographic.river_network]
enabled = true
threshold_area_km2 = 0.5

[mesh_catchment]
constraints_mode = "rivers_only"
cache = true

[flow]
runtime_backend = "petsc"
surface_interaction_model = "vi_obstacle"
vi_substeps_per_period = 4
vi_substep_on_failure = true
```

## What the run reports

The run writes `_boussinesq_state_history.npz` and `_boussinesq_summary.json` in
the solver folder. The summary carries diagnostics of the surface and of the bottom,
computed on the accepted snapshots (`runtime_summary.py`):

| Key family | Meaning |
|---|---|
| `surface_threshold_*` | Cells where the surface release is active, the number of windows in which it turns on and off, the peak rate and the peak head above the surface. |
| `bottom_threshold_*` | Accepted heads below the bottom of the aquifer, and the negative storage volume they would imply. |
| `bottom_constraint_*` | Cells where the dry deficit is active, its peak rate and its integrated volume. |
| `dry_deficit_history_m_s` | The state history of $q^{\mathrm{dry}}$, in the npz file. |

Read the dry deficit apart from the discharge terms. It says where the bottom
constraint was active and how much demand the storage could not meet.

## Parameters of this page

The keys of the engines and of the experimental obstacle runtimes.

```{hmp-params}
flow.runtime_backend
flow.surface_interaction_model
flow.runtime_max_iterations
flow.runtime_tol_residual_inf
flow.runtime_tol_state_update_inf
flow.vi_substeps_per_period
flow.vi_substep_on_failure
flow.vi_max_adaptive_substeps
flow.ts_vi_steps_per_period
flow.ts_vi_adapt
flow.ts_vi_dt_min_fraction
flow.ts_vi_dt_max_fraction
flow.ts_vi_type
flow.ts_vi_snes_type
```

## In the code

| What | Where |
|---|---|
| Method and engine choice | `hydromodpy/solver/boussinesq/methods/catalog.py` (`resolve_method_spec`), `engines/catalog.py` (`resolve_engine_spec`), `runtime_selection.py` |
| Newton loop and the engines | `hydromodpy/solver/boussinesq/runtimes/newton_common.py`, `local.py`, `scipy_dense.py`, `scipy_sparse.py`, `petsc_partition.py`, `petsc_common.py` |
| Mixed system | `hydromodpy/solver/boussinesq/runtimes/petsc_mixed.py` (`_solve_mixed_problem`) |
| Experimental obstacle closures | `hydromodpy/solver/boussinesq/runtimes/petsc_vi_obstacle.py`, `runtimes/petsc_ts_vi_obstacle.py`, `runtimes/petsc_vi/obstacle.py`, `runtimes/vi_bounds.py` |
| Options and supported subset | `hydromodpy/solver/boussinesq/solver_contract.py` (`build_runtime_options`, `assert_supported_runtime_subset`) |
| Diagnostics | `hydromodpy/solver/boussinesq/runtime_summary.py` |
