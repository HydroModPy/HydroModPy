# Choose a solver

```{hmp-task}
Task
: Pick MODFLOW 6, MODFLOW-NWT or the Boussinesq solver for a model, and write the line that selects it.

Time
: Five minutes to choose. The run time is that of the model.

Needs
: A project file that runs, and the solver executable for the two MODFLOW solvers.

Gives
: A file that runs on the solver you picked, or a refusal that names what the solver lacks.
```

HydroModPy solves groundwater flow with one of three solvers: MODFLOW 6, MODFLOW-NWT or
the in-house Boussinesq solver. The three read the same `[flow]` section, but they do not
support the same boundaries, packages or meshes. This guide helps you pick one and shows
the one line that selects it.

## What you need first

- A project file that runs. The blocks below are merged onto a file of example 04 and
  validated: `step1_minimal.toml` for the solver line, `step4_transient.toml` for
  Boussinesq.
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
feature. `hmp config check` refuses most of these combinations before any data is loaded.
The Boussinesq limits below stop the run itself.

Two limits belong to the Boussinesq solver alone:

- It supports recharge, wells, side Dirichlet boundaries, `stream`, `ocean` and top
  drainage. Any other boundary or sink stops the run.
- With its default runtime it accepts small meshes only. Section 3 gives the way out.

Without a reason to leave it, stay on MODFLOW 6. It is the solver of every example 04
file. The equations and assumptions of each solver are in {doc}`../theory/solvers`. What
differs between MODFLOW 6 and MODFLOW-NWT is in {doc}`../theory/mf6-vs-nwt`.

## 2. Write the solver in the flow process

The flow process names the solver that runs, in {toml}`simulation.process.solvers`.
Write it there, and nowhere else. {toml}`solver.backend` follows it: when the file does not
set it, the backend is derived from the first flow process, and every compatibility check
reads the solver that runs.

```{hmp-params}
simulation.process.solvers
```

Example 04 already names MODFLOW 6 in step 1. For MODFLOW-NWT, replace the process:

```toml
base_config = "step1_minimal.toml"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow_nwt"]
```

A list written in a file replaces the inherited one, so this block replaces the process
list of step 1. A file that adds a transport process writes both entries, or uses
`[[simulation.process__append]]` (see {doc}`inheritance`).

The names are `modflow6`, `modflow_nwt` and `boussinesq`. A file that still sets
{toml}`solver.backend.backend` must name the same solver as the process, or it is refused:

```text
$ hmp config check nwt.toml
Config invalid: 1 validation error(s) in nwt.toml:
  nwt.toml: <root>: Value error, solver.backend names 'modflow_nwt' and the flow process 'flow_main' of [[simulation.process]] names 'modflow6' in solvers. ...
```

Remove the backend line. Backend-specific options live in their own sections:
`[modflow6]`, `[modflownwt]` and, for Boussinesq, the `flow.runtime_*` keys. Their cards
are in {doc}`../reference/parameters/modflow6`, {doc}`../reference/parameters/modflownwt`
and {doc}`../reference/parameters/flow/index`.

## 3. Check that the mesh suits the solver

Each solver takes one kind of mesh. How to build each kind is in
{doc}`choose-and-build-the-mesh`.

- **MODFLOW 6** runs on the structured grid cut from the DEM, which is the default, or on
  a Gmsh mesh from `[mesh_catchment]` or `[mesh_input]`.
- **MODFLOW-NWT** builds its own structured grid from the DEM. A `[mesh_catchment]`
  section does not change that: the solver stays on the grid it builds.
- **Boussinesq** needs a Gmsh mesh, from `[mesh_catchment]` or `[mesh_input]`. Its default
  runtime assembles a dense Jacobian, and it stops on a mesh above 400 cells. Choose a
  sparse runtime for a catchment mesh:

```toml
base_config = "step4_transient.toml"

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
   spin-up or a barrier that the solver of the flow process does not support.
2. Run `hmp doctor` and read the solver executables it found.
3. Run `hmp run` on the file.
4. Add `watershed_id_card` to {toml}`display.figures`, as step 1 of example 04 does. Its
   Solver row names the solver of the run. A figure the solver did not produce is reported
   as unavailable, not drawn empty.

For the checks the solvers pass against a reference, see {doc}`../theory/validation`.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `solver.backend names 'modflow_nwt' and the flow process 'flow_main' of [[simulation.process]] names 'modflow6' in solvers.` | The file still sets {toml}`solver.backend.backend`, to another solver. | Remove the backend line: it follows the process. |
| `solver.backend='modflow7' does not support the 'drainage' boundary (supported by: modflow6, modflow_nwt, boussinesq)` from `hmp config check` | A name in `solvers` that is not a solver. The check reads it as a plugin solver and refuses its first boundary, so the message does not say that the name is wrong. | Write `modflow6`, `modflow_nwt` or `boussinesq`. |
| `solver.backend='modflow_nwt' does not support the 'sfr' boundary (supported by: modflow6)` | A boundary in {toml}`flow.active_bc` that the solver does not build. The same message exists for `lake` and `reservoir`. | Use MODFLOW 6, or remove the boundary. |
| `does not read flow.restart_from` | A hotstart on a solver that cannot read one. | Use MODFLOW 6. |
| `does not support flow barriers / dam cutoff walls (HFB); they require the 'modflow6' backend.` | A flow barrier or a dam cutoff wall on another solver. | Use MODFLOW 6. |
| `[flow.sinks_sources.recharge.soil] is wired to MODFLOW 6 only` | The soil reservoir with another solver. | Write `solvers = ["modflow6"]`. |
| `flow/boussinesq requires either a runtime planar mesh` | A Boussinesq run with no `[mesh_catchment]` or `[mesh_input]`. | Add a mesh, as in section 3. |
| `still assembles a dense Jacobian and is limited to small meshes (<= 400 cells)` | The default Boussinesq runtime on a larger mesh. | Set {toml}`flow.runtime_backend` to a sparse runtime. |
| `The current boussinesq backend slice supports recharge, XY wells` | A boundary or a sink that Boussinesq does not build. | Remove it, or use MODFLOW 6. |
| `Boussinesq runtime_backend='petsc' requires petsc4py to be installed` | The `petsc` runtime without the `petsc4py` package. | Install `petsc4py`, or take `scipy_sparse`. |
| `requires an earlier process using flow/modflow_nwt` | A MODPATH or MT3DMS process that comes before its flow process, or follows a flow process of another solver. MODFLOW 6 transport asks for `flow/modflow6` the same way. | List the flow process first. |

A run that does not converge is a different problem: see {doc}`non-convergence`.

## Where to go next

- {doc}`choose-and-build-the-mesh` for the structured grid and the Gmsh mesh.
- {doc}`../theory/solvers` for the equations of the three solvers.
- {doc}`../theory/mf6-vs-nwt` for what changes between the two MODFLOW solvers.
- {doc}`lakes-and-reservoirs`, {doc}`route-streams-with-sfr` and
  {doc}`add-a-flow-barrier` for the packages that need MODFLOW 6.
- {doc}`recharge` for the soil reservoir.
- {doc}`transport-and-particles` for the transport solvers.
