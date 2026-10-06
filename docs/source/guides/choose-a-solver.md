# Choose a solver

HydroModPy solves groundwater flow with one of three solvers: MODFLOW 6, MODFLOW-NWT or
the in-house Boussinesq solver. This guide helps you pick one for your model, tells you
which mesh it needs, and shows the lines that select it. The three solvers read the same
`[flow]` section, but they do not support the same boundaries, packages or meshes.

## What you need first

- A project file that runs. The blocks below are merged onto a file of example 04 and
  validated: `step1_minimal.toml` for the solver line, `step4_transient.toml` for the meshes.
- The solver executable, for MODFLOW 6 (`mf6`) and MODFLOW-NWT (`mfnwt`). `hmp doctor`
  lists the ones it finds. `hmp install-binaries` downloads them; they are also fetched
  the first time a solver needs one. The Boussinesq solver is part of HydroModPy and
  looks for no executable.

## 1. Pick the solver from what the model needs

Read the table from the top. The first row you need that a solver lacks rules it out.

| The model needs | MODFLOW 6 | MODFLOW-NWT | Boussinesq |
|---|---|---|---|
| Grid | Structured grid cut from the DEM, or a Gmsh mesh | Structured grid only | Gmsh mesh only |
| Ocean, drainage, the four side boundaries | yes | yes | yes |
| The `stream` boundary | yes | no | yes |
| Lakes, reservoirs, SFR streams | yes | no | no |
| Flow barriers and dam cutoff walls | yes | no | no |
| Recharge and wells | yes | yes | yes |
| A loaded ETP as a sink (`etp` in {toml}`flow.active_sinks_sources`) | only in soil mode; elsewhere ignored with a warning | yes, through the EVT package | refused |
| Recharge from the soil reservoir | yes | refused | refused |
| A hotstart ({toml}`flow.restart_from`) | yes | refused | refused |
| A cyclic spin-up inside the run | yes | refused | refused |
| Transport | GWT and PRT | MODPATH and MT3DMS | refused |

On both MODFLOW solvers, a negative recharge value is taken out of the recharge and sent
to an EVT sink.

Where a cell says "no" or "refused", the file stops instead of running without the
feature. Most of these checks run in `hmp config check` and read {toml}`solver.backend`,
which is why step 2 writes the solver name twice. The soil reservoir check reads the flow
process instead. The Boussinesq limits below stop the run itself.

Two limits belong to the Boussinesq solver alone:

- It supports recharge, wells, side Dirichlet boundaries, `stream`, `ocean` and top
  drainage. Any other boundary or sink stops the run.
- With its default runtime it accepts small meshes only. Step 3 gives the way out.

Without a reason to leave it, stay on MODFLOW 6. It is the default of the
{toml}`solver.backend` key, and the solver of every example 04 file. The equations and
assumptions of each solver are in {doc}`../theory/solvers`. What differs between
MODFLOW 6 and MODFLOW-NWT is in {doc}`../theory/mf6-vs-nwt`.

## 2. Name the solver twice

Two keys hold the solver name, and they do different jobs.

- {toml}`simulation.process.solvers` decides which solver runs. The run reads the first
  name of the `flow` process.
- {toml}`solver.backend` is the fallback when no `flow` process names a solver. It is also
  the key the compatibility checks read: an unsupported boundary, a hotstart, a cyclic
  spin-up and a flow barrier are refused against it.

```{hmp-params}
simulation.process.solvers
solver.backend.backend
```

Write both with the same name. For MODFLOW 6, step 1 of example 04 already carries the
process, and the backend is its default:

```toml
base_config = "step1_minimal.toml"

[solver]
backend = { backend = "modflow6" }

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]
```

For MODFLOW-NWT:

```toml
base_config = "step1_minimal.toml"

[solver]
backend = { backend = "modflow_nwt" }

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]
```

For Boussinesq, add the mesh of step 3 as well:

```toml
base_config = "step4_transient.toml"

[solver]
backend = { backend = "boussinesq" }

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["boussinesq"]
```

A file that writes the process and leaves {toml}`solver.backend` at its default loads
without a complaint, whatever it asks of the solver:

```toml
# not checked: shows a file that loads and is not checked against its solver
base_config = "step1_minimal.toml"

[flow]
active_bc = ["drainage", "sfr"]

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]
```

Here `sfr` exists only in MODFLOW 6, and the file passes `hmp config check`. Add the
`[solver]` block above and the same file is refused.

Backend-specific options live in their own sections: `[modflow6]`, `[modflownwt]` and, for
Boussinesq, the `flow.runtime_*` keys. Their cards are in
{doc}`../reference/parameters/modflow6`, {doc}`../reference/parameters/modflownwt` and
{doc}`../reference/parameters/flow/index`.

## 3. Pick the mesh

### MODFLOW 6 on the structured grid

This is the default. The grid follows the DEM pixels, and
{toml}`modflow6.sgrid.planar.mode` keeps them or resamples to a shape you give. MODFLOW 6
writes every grid as a DISV grid, structured or not.

```{hmp-params}
modflow6.sgrid.planar.mode
```

### MODFLOW 6 on a Gmsh mesh

Add a `[mesh_catchment]` section. {toml}`mesh_catchment.constraints_mode` is required:
the file is refused without it. Example 04 has no geology layer, so the mesh follows the
rivers only. Gmsh does not give the same mesh twice, so {toml}`mesh_catchment.cache` pins
the first one.

```toml
base_config = "step4_transient.toml"

[mesh_catchment]
constraints_mode = "rivers_only"
cache = true

[mesh_catchment.zone_meshing]
global_size = 150.0
```

```{hmp-params}
mesh_catchment.constraints_mode
mesh_catchment.cache
mesh_catchment.zone_meshing.global_size
```

The full list of mesh keys is in {doc}`../reference/parameters/mesh_catchment`. An existing
mesh is declared under `[mesh_input]` instead, and the two sections exclude each other
({doc}`../reference/parameters/mesh_input`).

The XT3D terms improve accuracy on a mesh that is far from orthogonal, or with anisotropic
K. When you leave the key below unset, HydroModPy decides. The reason for XT3D is in {doc}`../theory/solvers/xt3d-on-irregular-disv-meshes`.

```{hmp-params}
modflow6.runtime.mf6_enable_xt3d
```

### MODFLOW-NWT

MODFLOW-NWT builds its own structured grid. A `[mesh_catchment]` section does not change
that: the solver stays on the grid it builds from the DEM
(`hydromodpy/solver/modflow_nwt/nwt/nwt_solver.py`).

### Boussinesq

The solver needs a Gmsh mesh, from `[mesh_catchment]` or `[mesh_input]`. Its default
runtime assembles a dense Jacobian, and it stops on a mesh above 400 cells. Choose a
sparse runtime for a catchment mesh.

```toml
base_config = "step4_transient.toml"

[solver]
backend = { backend = "boussinesq" }

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["boussinesq"]

[mesh_catchment]
constraints_mode = "rivers_only"
cache = true

[flow]
runtime_backend = "scipy_sparse"
```

```{hmp-params}
flow.runtime_backend
```

## Check that it worked

1. Run `hmp config check` on the file. It refuses a boundary, a hotstart, a cyclic
   spin-up or a barrier that the solver named in {toml}`solver.backend` does not support.
2. Run `hmp doctor` and read the solver executables it found.
3. Run `hmp run` on the file.
4. Add `watershed_id_card` to {toml}`display.figures`, as step 1 of example 04 does. Its
   Solver row names the solver of the run. A figure the solver did not produce is reported
   as unavailable, not drawn empty.

For the checks the solvers pass against a reference, see {doc}`../theory/validation`.

## What can go wrong

| Message | Cause |
|---|---|
| `Unsupported simulation process/solver pair: flow/<name>.` | The name in `solvers` is not a registered flow solver. The names are `modflow6`, `modflow_nwt` and `boussinesq`. `hmp config check` does not catch it. |
| `solver.backend='modflow_nwt' does not support the 'sfr' boundary (supported by: modflow6)` | A boundary in {toml}`flow.active_bc` that the solver does not build. The same message exists for `lake` and `reservoir`. |
| `does not read flow.restart_from` | A hotstart on a solver that cannot read one. Use MODFLOW 6. |
| `does not support flow barriers / dam cutoff walls (HFB); they require the 'modflow6' backend.` | A flow barrier or a dam cutoff wall on another solver. |
| `[flow.sinks_sources.recharge.soil] is wired to MODFLOW 6 only` | The soil reservoir with another solver. Write `solvers = ["modflow6"]`. |
| `constraints_mode is required.` | A `[mesh_catchment]` section without {toml}`mesh_catchment.constraints_mode`. |
| `flow/boussinesq requires either a runtime planar mesh` | A Boussinesq run with no `[mesh_catchment]` or `[mesh_input]`. |
| `still assembles a dense Jacobian and is limited to small meshes (<= 400 cells)` | The default Boussinesq runtime on a larger mesh. Set {toml}`flow.runtime_backend` to a sparse runtime. |
| `The current boussinesq backend slice supports recharge, XY wells` | A boundary or a sink that Boussinesq does not build. |
| `Boussinesq runtime_backend='petsc' requires petsc4py to be installed` | The `petsc` runtime without the `petsc4py` package. |
| `requires an earlier process using flow/modflow_nwt` | A MODPATH or MT3DMS process that comes before its flow process, or follows a flow process of another solver. List the flow process first. MODFLOW 6 transport asks for `flow/modflow6` the same way. |

A run that does not converge is a different problem: see {doc}`non-convergence`.

## Where to go next

- {doc}`../theory/solvers` for the equations of the three solvers.
- {doc}`../theory/mf6-vs-nwt` for what changes between the two MODFLOW solvers.
- {doc}`../theory/validation` for the checks against reference solutions.
- {doc}`lakes-and-reservoirs`, {doc}`route-streams-with-sfr` and
  {doc}`add-a-flow-barrier` for the packages that need MODFLOW 6.
- {doc}`recharge` for the soil reservoir.
- {doc}`track-particles` for the transport solvers.
