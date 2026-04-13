# Mesh Catchment Launcher

`launchers/mesh_catchment/` is the dedicated launcher family for catchment
meshing workflows.

Use it when you want to generate:

- one planar catchment mesh,
- QA figures,
- one optional exchange bundle,
- or one batch of outlet-specific mesh runs,

without running a full `process_simulation` workflow.

## Start Here

If you only want one first runnable example, start with:

`python -m launchers mesh-catchment run launchers/mesh_catchment/scenarios/config_example.toml`

If you want the batch version directly, start with:

`python -m launchers mesh-catchment run launchers/mesh_catchment/scenarios/config_headwater_100km2.toml`

## Choose The Right Entry Point

| Goal | Entry point | Main config blocks | Notes |
| --- | --- | --- | --- |
| Generate one mesh only | `python -m launchers mesh-catchment run ...` | `[mesh_catchment]` | Dedicated launcher, no solver execution |
| Generate several meshes from one outlets table | `python -m launchers mesh-catchment run ...` | `[mesh_catchment]` + `[mesh_catchment_batch]` | Batch reuses the same mono-catchment mesh runtime for each outlet |
| Run a simulation with one mesh computed at runtime | `python -m launchers simulation run ...` | `[simulation]` + `[mesh_catchment]` | Embedded mono-run mesh phase only |
| Run a simulation on one precomputed mesh | `python -m launchers simulation run ...` | `[simulation]` + `[mesh_input]` | Reuses an existing `.msh` and/or bundle |

Rules worth remembering:

- `[mesh_catchment]` and `[mesh_input]` are mutually exclusive in `process_simulation`.
- `[mesh_catchment_batch]` is rejected in `process_simulation`.
- Runtime Gmsh meshes are intended for `boussinesq` and `modflow6`, not `modflownwt`.

## First Commands

Generate a minimal launcher template:

`python -m launchers mesh-catchment template --profile user`

Generate the batch template:

`python -m launchers mesh-catchment template --batch --profile user`

Run the bundled mono-catchment example:

`python -m launchers mesh-catchment run launchers/mesh_catchment/scenarios/config_example.toml`

Run the bundled batch example:

`python -m launchers mesh-catchment run launchers/mesh_catchment/scenarios/config_headwater_100km2.toml`

Run the curated smoke sequence:

`python -m launchers.mesh_catchment.tools.run_all_configs`

This smoke runner is a local regression convenience tool, not the primary
public entry point. The public contract stays the launcher CLI plus the
versioned TOML scenarios.

## Minimal Configs

Minimal mono-catchment config when your TOML sits next to
`config_common.toml`:

```toml
base_config = "config_common.toml"

[mesh_catchment]
constraints_mode = "geology_rivers"
```

If the same TOML lives under `scenarios/`, use:

```toml
base_config = "../config_common.toml"

[mesh_catchment]
constraints_mode = "geology_rivers"
```

Minimal batch overlay when your TOML sits next to `config_batch_common.toml`:

```toml
base_config = "config_batch_common.toml"

[workspace]
project_root = "~/HydroModPy/mesh_headwater_100km2"

[mesh_catchment_batch]
outlets_table_path = "~/HydroModPy/catchment_identification_scan/headwater_100km2/exutoires_headwater_100km2.csv"
```

The shared batch base already provides:

- `enabled = true`,
- default output filename patterns,
- the wider DEM and geology raster reference used by bundled batch scenarios.

## Profiling And Fast Iteration

For end-to-end `process_simulation` profiling, disable outputs that are
expensive but not required to measure the solver and mesh path:

```toml
[mesh_catchment]
figures_enabled = false
export_exchange_bundle = false

[geographic]
reuse_existing_outputs = true

[postprocess]
profile = "solver_only"

[display]
enabled = false
show = false
save = false
```

`reuse_existing_outputs = true` is opt-in and fingerprinted. The first run still
builds the geographic artifacts; following runs in the same workspace reuse
them only when the DEM, outlet/polygon inputs and geographic settings match.

`export_exchange_bundle = false` skips the mesh exchange bundle export. Use it
only for mesh/profiling runs that do not need downstream solver bundle metadata.

`postprocess.profile = "solver_only"` applies to `process_simulation`. It
disables launcher-managed reports, displays, native mesh exports, NetCDF and
timeseries exports while leaving the numerical solvers enabled.

## Package Map

- `launcher.py`: dedicated launcher entry point and bootstrap logic.
- `runtime.py`: public facade shared by the dedicated launcher and embedded integrations.
- `runtime_single_run.py`: concrete mono-catchment execution path.
- `batch.py`: multi-outlet orchestration layer.
- `batch_io.py`: outlet-table loading and raster-coverage validation.
- `batch_reporting.py`: manifest row and final batch summary persistence.
- `config.py`: schema parsing and normalized launcher contracts.
- `templates.py`: template rendering from Pydantic schemas.
- `config_common.toml`: shared mono-catchment bootstrap.
- `config_batch_common.toml`: shared batch overlay.
- `scenarios/`: versioned runnable examples.
- `tools/run_all_configs.py`: curated smoke runner for bundled scenarios.

## Versioned Contract

Versioned package content should stay in one of these buckets:

- runtime code: `*.py`
- launcher contract and templates: `config_*.toml`
- runnable examples: `scenarios/*.toml`
- local regression helper: `tools/run_all_configs.py`

Treat these as local-only artifacts, not versioned launcher contract:

- `outputs/`
- `scratch_tests/`
- temporary `._run*.toml`
- temporary or ad hoc `._debug*.toml`

## Current Docs Vs Design Notes

Read these first for the current public contract:

- `launchers/README.md`
- `launchers/mesh_catchment/scenarios/README.md`
- `docs/readthedocs/source/architecture/launchers/`

Treat these as background design notes, not the canonical current contract:

- `docs/developers/gmsh_mesh_integration_note.md`
- `docs/developers/unified_mesh_pivot_architecture.md`
