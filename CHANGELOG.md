# Changelog

All notable changes to HydroModPy are listed here, newest first. The file follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

Each release lists what was added, changed, deprecated, removed, fixed or secured. Under
`Numbers` it also lists every change that moves a stored or printed number, with its size.

During development, write each change under `[Unreleased]`, in a line or two that a user can act
on. At a release, rename that section to `## [vX.Y.Z] - YYYY-MM-DD` and open a new empty
`[Unreleased]`. The long development notes of 2.0.0 are kept in
`docs/source/about/changes-during-the-alphas.md`.

<!-- releases start here -->

---

## [Unreleased]

### Added

- `hydromodpy.model.supports` holds the closed set of traits a solver backend lists in `supports`: the boundary kinds,
  the fields of `ModelOptions` and the initial states `head_rule`, `steady_start`, `cyclic_start` and `prior_state`.
- `solver.sink_fill = true`, `solver.drain_band_depth_m` and `solver.drain_conductance_floor_m2_s` away from their
  defaults, and `[flow.sinks_sources.etp]` are refused under Boussinesq, which reads none of them.
- A lake with `flow.ic.kind = "spinup_cyclic"` is refused: the cycle carries the heads and not the lake stage. Run
  `hmp spinup`, which carries both, or start from `flow.restart_from`.
- A transport run behind a steady start whose heads did not converge stops with `SolverDivergedError`, where it used
  to start with a warning. The replay of a sealed run still warns.
- MODFLOW 6 can rerun a solved model for a new K or Sy. It copies the input files of the solved run, rewrites only NPF
  and DRN for K, STO for Sy, and the file of the properties, and the result is bit-identical to a new build. A start
  from a steady or cyclic solve, a change that turns XT3D on or off, a change of the drain cells, other binaries or
  another shared forcing folder still rebuild.
- `[solver.boussinesq] exchange_mesh` names a mesh bundle folder that the Boussinesq solver reads as its cells, with
  their conductivity and storage. It is a developer option for the validation cases. A relative path is read from the
  folder of the TOML file.
- The `catchment` mesh engine meshes the catchment as one polygon cell, for a global model. It
  declares the `lumped` capability, and a solver that accepts any planar engine does not read
  it.
- `MeshRequest` carries the catchment outline. The planner fills it for a lumped engine only,
  so the hash of every other request is unchanged.
- The `center_kind` attribute of a mesh can say `interior_point`, the center of the one cell of
  the `catchment` engine, a point inside it from shapely's `point_on_surface`.
- The terrain port accepts the conditioning method `"provided"`, and
  `ConditionedDem.provided(path)` wraps a DEM that another tool conditioned. Both engines route
  it like any conditioned DEM, and `condition_dem` refuses it with `TerrainRequestError`. The
  port does not check that the DEM has no depression.

### Changed

- `hydromodpy.analysis.compare` is now `hydromodpy.project.compare`, and `hydromodpy.examples` is now
  `hydromodpy.project.examples`. The rows behind `hmp example list` and `show` are `hydromodpy.project.examples.rows`.
- `masstransfer` of MODFLOW-NWT moved to `hydromodpy.solver.modflow_nwt.mt3dms.masstransfer`.
- `hydromodpy.solver.modflow_nwt.modpath._resolvers` is now the public module
  `hydromodpy.solver.modflow_nwt.modpath.resolvers`.
- The code behind `hmp catalog`, `data`, `lock`, `privacy`, `project`, `viz` and `workspace` moved from
  `hydromodpy.cli._workers` into the package each verb serves (`results.catalog.listing`, `results.catalog.liveness`,
  `results.catalog.privacy`, `results.catalog.indexer`, `results.catalog.federation`, `data.request.cache_verbs`,
  `data.workspace.folders`, `project.lock`, `display.catalog_figures`). The old paths are gone. Every command prints
  and exits as before.
- `find_workspace`, `find_data_workspace` and `find_workspace_root` moved from `hydromodpy.cli.helpers` to
  `hydromodpy.core.workspace.resolve`. `path_size` moved to `hydromodpy.core.io.filesystem`, `project_root_at` and
  `sites_project_root` to `hydromodpy.core.state.result_dirs`, and `remove_for_good` to `hydromodpy.results.trash`.
- `hmp run script.py` now says to run the script with `python`.
- `hmp dev test`, `hmp dev run-script` and `hmp dev examples` left the wheel. In a source checkout, run
  `python -m tools.dev test`, `python -m tools.dev run-script` or `python -m tools.dev examples manifest`. `hmp dev`
  answers with the new form.
- `hydromodpy.model` is new. It holds what a solver receives: `domain` (from `spatial.domain` and `spatial.lake_bed`,
  whose modules are now `model.domain.lake_bed_abacus` and `lake_bed_regrid`), `properties` (from `spatial.field`, with
  `physics.flow.physical_properties` and `property_ids`, and `solver.base.properties` now
  `model.properties.property_table`), `forcing` (from `spatial.forcing` and `physics.forcing`, with `physics.base.forcing`
  now `model.forcing.dated_forcing`, `physics.flow.time_forcing` now `model.forcing.time_forcing` and
  `physics.hydrology.synthetic.forcing` now `model.forcing.synthetic`), `boundaries` (the boundary conditions and the
  binders of `physics.flow`, with `binders.payloads` now `model.boundaries.binder_payloads`), `sinks_sources`, `initial`
  (`physics.flow.initial_conditions` as `initial.config`, `solver.base.initial_conditions` as `initial.heads`, and
  `simulation.spinup_config`), `time` (`regime`, `history_contract`), `soil` (`physics.hydrology.soil_reservoir` and
  `simulation.soil`) and `transport`.
- `Flow` is now in `hydromodpy.model.flow`. `FlowConfig` and its TOML loader are one module,
  `hydromodpy.model.flow_config`, which also holds `from_toml_section`, `normalize_bc_payloads` and
  `resolve_forcing_paths`. `physics.contracts`, `physics.base.payloads`, `physics.base.process_spatial`,
  `physics.flow.runtime_config` and `physics.flow.toml_examples` are modules at the top of `hydromodpy.model`.
- `hydromodpy.physics` and `hydromodpy.simulation` are gone, with every name their package files exported. Import a name
  from the module that defines it. `hmp.physics` and `hmp.simulation` no longer open a package.
- The plan, the planner, the plan runner and the `[simulation]` models moved from `hydromodpy.simulation` to
  `hydromodpy.solver.base`: `plan`, `planner`, `runner`, `transport_runs`, `simulation_config` (was `planning.config`),
  `observation_config` and `results_config`.
- `simulation.post_run` is now `hydromodpy.workflow.steps.run_outputs`, `simulation.catchment_aggregation` is
  `hydromodpy.results.derive.catchment_aggregation`, and `simulation.observation_ingest` is
  `hydromodpy.data.ingest.observations`.
- `spatial.geographic.structure_binders` is now `hydromodpy.model.domain.structure_binders`. `hydromodpy.spatial` no
  longer exports `Domain`, `DomainConfig` and `FieldParam`.
- The schema exported for a bare model class is named after its new module, for example
  `urn:hmp:schema:model.properties.physical_properties.FlowPhysicalProperties`.
- The config schema digest that a lockfile records changes once, because two descriptions name a module that moved.
  `hmp lock verify` reports it and still passes.
- `hydromodpy.mesh` is new. It holds what `hydromodpy.spatial.mesh` held: the mesh request and the `[mesh]` config, the
  planner, the engines, the cells and the exchange formats. Import `hydromodpy.spatial.mesh.<module>` as
  `hydromodpy.mesh.<module>`. `planning`, `engines`, `cells`, `io` and the modules at the top keep their names.
- The mesh objects moved from `hydromodpy.spatial.mesh.model` to `hydromodpy.mesh.planar` (`HydroMesh`,
  `PlanarCellMesh`, `CellType`, the geometry, the quality report and the regular grid), so the folder no longer reads
  like `hydromodpy.model`.
- `watershed_cell_mask` moved from `hydromodpy.spatial.geographic.delineated_catchment` to
  `hydromodpy.mesh.cells.in_polygons`, next to the cell mask it calls.
- `hydromodpy.spatial` no longer exports `CellBlock`, `CellType` and `HydroMesh`. Import them from
  `hydromodpy.mesh.planar.hydro_mesh` and `hydromodpy.mesh.planar.cell_types`.
- The entry-point group of mesh engines is still `hydromodpy.mesh.engine`.
- `hydromodpy.catchment` is new. It holds what was left of `hydromodpy.spatial` once `model` and `mesh` had their own
  package: `terrain`, `delineation`, `drainage` and `administrative`, unchanged inside, and the geographic pipeline in
  three parts. `algorithms` was `spatial.geographic.core`, and also holds `dem_metadata`, `geographic_paths` and
  `river_network_config`. `synthetic` was `spatial.geographic.synthetic`, with `synthetic_config`. `preprocess` is the
  rest of `spatial.geographic` (configuration, cache, pipeline, store ingestion, subbasin, regional flow job), with
  `pipeline_steps`. So `hydromodpy.spatial.geographic.core.pipeline_steps` is now
  `hydromodpy.catchment.preprocess.pipeline_steps`, and `hydromodpy.spatial.geographic.synthetic_config` is now
  `hydromodpy.catchment.synthetic.synthetic_config`.
- `RasterSupport`, `Surface`, `PreparedSurfaceSampler` and the geology source protocol are now in
  `hydromodpy.catchment.raster_support`, `surface`, `surface_sampling` and `protocols`. `spatial.job_inputs` is now
  `hydromodpy.model.domain.job_inputs`, next to the `domain-build` worker.
- `hydromodpy.spatial` is gone, with every name its package file exported. Import a name from the module that defines
  it. `hmp.spatial` no longer opens a package.
- `hydromodpy.catchment.terrain` no longer re-exports the terrain port. Import `TerrainEngine`, `CappedBreach` and the
  other port names from `hydromodpy.catchment.terrain.port`, and the two engines from `numpy_engine` and
  `whitebox_engine`. The entry-point group of terrain engines is still `hydromodpy.terrain.engine`.
- The bundled `departement.gpkg` moved with `administrative` to `hydromodpy/catchment/administrative/`.
- The solver backends read a frozen `hydromodpy.model.model.Model`: the geometry, the properties as profiles, the
  boundaries, the recharge, the ETP, the wells, the lakes, the SFR networks, the barriers, the start state, the time and
  four `[solver]` options. The `prepare_solver` step builds it once per run with `model_from_flow` and puts it on
  `setup.model`. `Modflow6`, `ModflowNwt` and `Boussinesq` keep it in `inputs` and never change it.
- `Modflow6` and `ModflowNwt` no longer take the geographic object, and their `pre_processing(model, options)` takes the
  `Model` in place of the flow, the domain and the cell mesh. `Boussinesq(model=..., runtime=...)` reads the `Model`
  and the `[flow.runtime]` options.
- `Flow` loses the fifteen Boussinesq settings it copied from `[flow.runtime]` (`runtime_backend`,
  `surface_interaction_model`, `partition_release_depth_m`, `runtime_max_iterations`, `runtime_tol_residual_inf`,
  `runtime_tol_state_update_inf`, `vi_substeps_per_period`, `vi_substep_on_failure`, `vi_max_adaptive_substeps`,
  `ts_vi_steps_per_period`, `ts_vi_adapt`, `ts_vi_dt_min_fraction`, `ts_vi_dt_max_fraction`, `ts_vi_type`,
  `ts_vi_snes_type`) and the unread `initial_condition_types` and `boundary_condition_application_domains`. Boussinesq
  reads `[flow.runtime]`.
- The start of a run is one of five records of `hydromodpy.model.initial.state`: `HeadRule`, `SteadyStart`,
  `CyclicStart`, `PriorState` and `SolvedState`. The models of the steady start and of a spin-up cycle are
  `steady_variant` and `cycle_variant` of `hydromodpy.model.model`, which return a new model. They replace
  `steady_flow_copy_for_initialization`, `cyclic_flow_copy_for_initialization`,
  `flow_uses_steady_state_initial_condition`, `flow_uses_cyclic_spinup` and `resolve_head_initial_condition`.
- `hydromodpy.model.initial.config` and `spinup_config` are one module, `hydromodpy.model.initial_config`. It also holds
  the `[flow.ic]` strategy readers (`initial_state_of`, `steady_state_strategy_of`, `cyclic_spinup_strategy_of`), which
  leave `hydromodpy.model.initial.heads`. `heads.py` keeps the numpy kernels and gains `restart_start_heads`.
- The soil reservoir modules other than the kernel move to `hydromodpy.model.forcing`: `soil.config`, `soil.columns`,
  `soil.grids`, `soil.recharge` and `soil.budget` are now `forcing.soil_config`, `soil_columns`, `soil_grids`,
  `soil_forcing` and `soil_budget`. `hydromodpy.model.soil` keeps `kernel`.
- The earlier run that `flow.restart_from` names is read once, before the solve, by
  `hydromodpy.results.storage.prior_state`. A run solved on another mesh is refused there with the same message as
  before, and the lake stages of the restart come from the `PriorState` of the model. `verify_restart_mesh`,
  `read_restart_lake_stages` and `read_final_head` move there from
  `hydromodpy.solver.modflow6.builders.initial_conditions`, with `written_step` and `reoriented_rows` from
  `hydromodpy.solver.modflow6.support.written_grid`, which is gone.
- `map_flow_properties`, `resolve_flow_property_arrays`, `require_positive_conductivity` and `require_positive_storage`
  take `profiles=` instead of `flow=`. A per-cell property override is set with `Model.with_properties`, which refuses a
  name that sets no property, and a `properties` key in the per-run overrides of the run context is refused by name.
- `ensure_flow` moves from `hydromodpy.solver.base.runner` to `hydromodpy.workflow.steps.data`. The runner no longer
  builds a `Flow`, and a flow run without the `Model` of the `prepare_solver` step stops with a `ConfigError` that names
  the step.
- `build_preprocess_options`, `require_cell_mesh` and `run_flow_model` read `setup.model` instead of `setup.flow`,
  `setup.domain`, `setup.cell_mesh` and `cfg.solver`. `channel_tree_for_run` takes the `ChannelRasters` that
  `channel_rasters_for_run` chooses, `run_basin` and the catchment functions take a `CatchmentGeometry`,
  `networks_route_drainage` takes a `Model`, `resolve_first_period_steady` takes `model=` and `step_persist_params` takes
  the parameter profiles of the `Model` instead of a `Flow`.
- The MODPATH and MT3DMS models read the DEM grid and the catchment polygon from `Model.geometry` through the MODFLOW-NWT
  solver. `get_geographic` of `hydromodpy.solver.modflow_nwt.modpath.resolvers` is replaced by `get_raster` and
  `get_catchment`.
- The auxiliary steady solve of MODFLOW 6 and MODFLOW-NWT always starts from the top of the model. It started 0.01 m
  below the top when `[flow.runtime]` set `backend = "petsc"` and `surface_interaction_model = "vi_obstacle"`, two
  Boussinesq settings. See the recipe `modflow_steady_start_ignores_boussinesq_runtime` of `changes.toml`.
- Every plugin surface (solver backends and extractors, data sources, mesh and terrain engines, trial evaluators,
  forward models) resolves through one registry class, `hydromodpy.core.plugin_registry.PluginRegistry`, with the calls
  `register`, `get` and `names`. A registry keys a class on one or more of its attributes joined by `_`, and an
  entry-point name is compared with that join and never split. The seven entry-point groups keep their names.
- Each registry module exposes its registry object and no module function: `solvers` and `extractors` in
  `hydromodpy.solver.base.registry`, `data_sources` in `hydromodpy.data.source.registry`, `mesh_engines` in
  `hydromodpy.mesh.registry`, `terrain_engines` in `hydromodpy.catchment.terrain.registry`, `evaluators` in
  `hydromodpy.calibration.evaluation.registry` and `forward_models` in
  `hydromodpy.calibration.evaluation.forward_registry`. Write `mesh_engines.get(name)`, `terrain_engines.create(name)` or
  `evaluators.register(cls)` where the module functions `get`, `create`, `register`, `unregister` and `load_plugins`
  were called, `mesh_engines.names()` for `list_*_ids()`,
  `mesh_engines.names(shipped_only=True)` for `builtin_*_ids()`, `name in mesh_engines.names()` for
  `is_registered(name)`, and `evaluators.get(name).evaluator_id` for `resolve_id(name)`.
- A solver backend declares on its adapter class `name`, `process_type`, `accepted_meshes`, `geometry`, `writes`,
  `reads`, `supports`, `options`, `category`, `native_step`, `mutable` and `requires`. `solver_name` becomes `name`,
  `capabilities` is split into `writes` and `supports`, and the category moves from the extractor to the adapter. The
  registry refuses a backend that lacks one of them or declares one with the wrong type, and names it.
- An unknown solver key raises `SolverInputError` instead of `KeyError`.
- The category a run records in its manifest is the one its solver backend declares. The shipped backends keep theirs,
  and a third-party backend records its own where it recorded none.
- The refusals of `flow.restart_from` and of a cyclic spin-up read the traits `prior_state` and `cyclic_start` in the
  `supports` of the backend, and their message names the trait.
- `primary_solver_for_simulation` of `hydromodpy.workflow.steps.prepare_solver.facts` is now
  `primary_run_for_simulation` and returns the process type with the solver.
- The solver catalog of the reference shows what each backend declares (category, grid, meshes, what it writes and the
  traits it supports) in place of the capability names.
- `solver.backend` is a string, the name of a registered flow solver, for example `solver.backend = "modflow6"`. The
  table form `[solver.backend] kind = "..."`, and `kind = "custom"` with `name`, still loads with a warning, and
  `hmp doctor --fix-config` rewrites it. An unknown name is refused with the names this installation serves. A run under a
  plugin solver no longer lists `solver.backend` among its experimental keys.
- The settings of a flow solver are written under `[solver.<name>]`: `[modflow6]` is now `[solver.modflow6]`,
  `[modflownwt]` is now `[solver.modflow_nwt]` and `[flow.runtime]` is now `[solver.boussinesq]`. The old tables load
  with a warning, and `hmp doctor --fix-config` moves them. A plugin solver gets its own table, checked by its options
  class. A run sealed with the old tables reads back in silence, and `hmp run --frozen` compares them where they are
  now.
- `config.resolved.toml` holds the settings table of the flow solver the run used and the tables the file wrote, not
  the table of every shipped solver. A table of a solver that did not run counts for no drift on a replay.
- A name in `[[simulation.process]] solvers` is refused when the file is read if no solver of that process serves it,
  with the names this installation serves.
- A key the chosen flow solver does not honor is refused when the file is read, from the supports the solver declares,
  and the refusal names the solvers that honor it. A sealed run still reads and only warns. The K tensor, the
  pass-through cells of `[domain.layers]` and a layering under Boussinesq are now refused with
  `IncompatibleCapabilitiesError`, like a boundary, a restart or a soil reservoir the solver does not read.
- A transport solver is refused when the file is read if its `requires` does not name the flow solver of the run, with
  the flows it follows. A MODFLOW 6 flow with MODPATH or MT3DMS used to be refused only when the plan was built.
- An unknown key of `[flow.bc]` is refused with the seven boundaries the table holds, `drainage` included.
- The metric names a file may write come from one table, `hydromodpy.core.scoring.metric_table.METRIC_SPECS`. The
  names accepted do not change. `METRIC_SENSE` and `MetricSense` moved there from
  `hydromodpy.results.catalog.constants`, `METRIC_NAMES` of `hydromodpy.results.metric_rule` became `RUN_METRIC_NAMES`
  there, and `LOG_METRICS`, `DIMENSIONLESS` and `CLIPPED_METRICS` became flags of the table rows.
- `calibration.evaluator`, `calibration.forward_model`, `mesh.engine` and `geographic.terrain_engine` are refused with
  one sentence that names the key, the value and the names this installation serves.
- A solver backend is called through `validate`, `build`, `run`, `extract` and `cleanup`. It receives a frozen `Model`,
  its options and a `RunSlot` that names its folder, its run name, its solver binaries, whether to stop before the
  solve, and the folder of the forcing files a calibration trial shares. `execute` is gone, and `RunExecutionResult` is
  now `SolverRun`, with `primary_model` renamed `solver_model` and `solver_output_dir` renamed `output_dir`.
- `extract` receives a `Retention` of `hydromodpy.results.storage.kept`, built from `keep_per_cell_budget` and
  `keep_solver_files`, instead of keywords read from its signature. The extractor port `OutputAdapter` moved to
  `hydromodpy.solver.base.adapter_protocol`, and an extractor answers `extract(solver_run, store, retention)`. The
  dry-cell sentinels of MODFLOW-NWT come from its own options, and the start date and the vertical layout from the
  `Model` of the run.
- `extract_observables(ctx, store, requests)` of a flow adapter is now `observables(solver_run, requests)`,
  `locate_cell` and `top_active_layer` take the `SolverRun`, and `declared_observables` receives the ids of the active
  conditions of `[flow]` instead of the configuration.
- The runner of a plan records one `SolverRun` per run in `execution.solver_runs`, which replaces `models_by_run_id` and
  `output_dirs_by_run_id`. A consumer reads the product of its run as `RunContext.solver_run`, and a transport run reads
  its flow run as `RunContext.upstream`.
- A calibration trial asks for its run name, its stop before the solve and its forcing folder through a typed
  `SlotRequest` on the setup, which replaces `setup.flow_runtime_overrides`. The solver no longer recognises a trial by
  the name of its folder. `TrialSandbox.flow_overrides` is now `TrialSandbox.slot_request()`.
- The flow adapters moved to `solver/<backend>/adapter.py` for `modflow6`, `modflow_nwt` and `boussinesq`, and
  `solver/boussinesq/adapters/` is gone. The transport adapters stay in `adapters/`.
- The Boussinesq settings class `FlowRuntimeConfig` of `hydromodpy.model.runtime_config` is now `BoussinesqOptions` of
  `hydromodpy.solver.boussinesq.options`, the table `[solver.boussinesq]`. `FLOW_RUNTIME_KEYS` now lives in
  `hydromodpy.model.flow_config`.
- The Boussinesq scratch folder is named after the run like the other backends, so parallel calibration trials each get
  their own folder. Its extractor writes the diagnostics of the variational inequality solve into the diagnostics folder
  of the run store when it extracts.
- The auxiliary steady solve and the spin-up cycles of MODFLOW 6 solve in a slot derived from the run, with its binaries
  and its shared forcing folder.
- A resumed run puts back one `SolverRun` per solver folder it recorded, and a missing solver output folder raises
  `NothingThereError`. A per-cell budget that `keep_per_cell_budget = false` leaves out raises `ConfigError`.
- `hmp catalog rerun` calls `hydromodpy.project.dispatch.rerun.rerun_config` directly.
- `engine_accepted` moves from `hydromodpy.mesh.port` to `hydromodpy.mesh.registry` and
  resolves the engine itself.
- The terrain port is shorter. `require_batch`, `require_rank_preserving`,
  `require_snap_method` and `require_untransformed` are folded into `require_delineable` and
  `require_stream`, and the refusals of an engine are `require_conditioning`,
  `require_accumulation`, `require_stream` and `require_delineable`. A refusal keeps its
  exception class, and some messages are shorter. `terrain.port` has no `__all__`.
- `get_whitebox_backend`, `clear_whitebox_backend_cache`, `resolve_delineation_backend` and
  `backend_has_callables` are defined in `hydromodpy.catchment.delineation`. The classes
  `WhiteboxWorkflowsBackend`, `WhiteboxRasterBackend`, `WhiteboxFlowBackend` and
  `WhiteboxDelineationBackend` are no longer attributes of that package. Import them from
  `hydromodpy.catchment.delineation.whitebox_workflows_backend`.
- The channel tree and the per-cell discharge routing move from
  `hydromodpy.solver.modflow_common` to `hydromodpy.catchment.drainage.channel_tree` and
  `hydromodpy.catchment.drainage.routing`. `project_channel_tree` is split in two:
  `channel_exits` reads the cell numbers of the pixels of A, and `pin_channel` reads the active
  columns and the lakes of a backend. `upstream_area` takes the cell areas and returns the
  areas with the largest drainable share, in place of `upstream_area_m2`.
  `channel_rasters_for_run` moves to `hydromodpy.model.domain.geometry`.
  `routing_graph_for_model` and `flat_cell_index` move to
  `hydromodpy.solver.modflow_common.observable_extraction`.
- `Model.geometry.channel_exits` carries the river network A read on the mesh cells.
  `prepare_solver` reads it once, when the river network step ran or an SFR network was
  delineated from A and the three rasters exist.
- `build_solver_mesh_descent` takes `channel_exits` in place of `channel_tree`.
  `channel_exits_for_build` of `hydromodpy.solver.modflow_common.flow_directions` replaces
  `channel_tree_for_run`: it keeps the rule of a build (A off, no folder, rasters missing, or
  an SFR network that needs A) and returns the exits of the `Model`, and a `Model` that did not
  read an A the build needs is refused.

### Removed

- PyHELP, the Picard solver of Boussinesq, the TIFF maps of MODFLOW-NWT, the MODPATH post-processing and the job
  chain moved to `hydromodpy_annex/`, which is not in the wheel. `ModflowNwt.post_processing`,
  `Modpath.post_processing` and `Modpath.filt_processing` are gone; call `run_post_processing`, `write_shapefiles` and
  `filter_pathlines` of the annex. `hydromodpy.physics.hydrology.pyhelp` and the chain names of `hydromodpy.schema.job`
  are gone.
- `hmp dev manage` is gone and has no replacement yet.
- `is_boundary_condition_active` and `active_side_dirichlet_boundary_ids` of
  `hydromodpy.model.boundaries.boundary_condition_registry` are gone. A backend reads `Model.boundaries`.
- The solver functions `get_solver_adapter`, `get_extractor`, `get_extractor_instance`, `capabilities`,
  `accepted_meshes`, `list_pairs`, `list_extractor_pairs`, `pairs_for_process`, `required_bindings`, `is_supported`,
  `is_adapter`, `known_process_types`, `register_extractor` and `load_extractor_plugins` of
  `hydromodpy.solver.base.registry`, and `MeshReadingAdapter` and `missing_adapter_members` of
  `hydromodpy.solver.base.adapter_protocol`, are gone. Use `hydromodpy.solver.base.registry.solvers` and `extractors`.
- `hydromodpy.core.contracts.solver_registry` is gone. The callers read `hydromodpy.solver.base.registry` directly.
- `missing_class_members` of `hydromodpy.data.source.port` is gone. `data_sources.register()` refuses a class
  member that is absent or `None`.
- `builtin_ids`, `list_ids`, `is_registered` and `resolve_id` of `PluginRegistry` are gone, with the module functions
  `list_source_ids`, `builtin_source_ids`, `list_engine_ids`, `builtin_engine_ids`, `list_evaluator_ids`,
  `builtin_evaluator_ids`, `list_model_ids`, `builtin_model_ids`, `is_registered`, `resolve_id` and
  `resolved_engine_id`. Use `names()`, `names(shipped_only=True)`, `x in names()` and `get(x).<id attribute>`.
- `RESTART_CAPABILITY` and `CYCLIC_SPINUP_CAPABILITY` of `hydromodpy.config.hydromodpy_config` and
  `SURFACE_EXCESS_CAPABILITY` of `hydromodpy.workflow.steps.planning` are gone with the capability names they held.
- `Modflow6Backend`, `ModflowNwtBackend`, `BoussinesqBackend`, `CustomBackend`, `SolverBackendConfig`,
  `BUILTIN_BACKENDS`, `backend_for_solver`, `solver_name_of_backend` and `SolverConfig.validate_registry` of
  `hydromodpy.solver.base.solver_config`; the `runtime` field of `FlowConfig`; `validate_registry` of the process
  models of `hydromodpy.solver.base.simulation_config`.
- The columns `supported_backends` and `backend_packages` of `FlowBoundaryDefinition`,
  `supported_boundary_ids_for_backend` and `FlowBoundaryBackend` of
  `hydromodpy.model.boundaries.boundary_condition_registry`, and `layering_refusal` of
  `hydromodpy.solver.boussinesq.solver_contract`. A solver says what it builds through its `supports`.
  `BoundaryConditionBundle.unsupported_active_ids(backend)` is now `active_ids_outside(supports)`.
- `RunResult`, `STOP_BEFORE_THE_SOLVE`, `post_run_results`, `resolve_run_model_name`, `resolve_base_model_name` and
  `flow_model_name`, and the re-exports of `hydromodpy.solver`, `hydromodpy.solver.base` and
  `hydromodpy.solver.modflow6.adapters`. The run name is chosen once by the runner.
- `PRIVATE_TRIAL_RECHARGE_KEY` and `TRIAL_RECHARGE_DIRNAME` of `hydromodpy.solver.modflow6.builders.recharge`. The
  calibration sandbox names the forcing folder of a trial.
- `hydromodpy.results.run.rerun_contract` and `ProjectRerunProvider` of `hydromodpy.project.dispatch.rerun`.
- `resolve_mesh_bundle` of `hydromodpy.solver.boussinesq.flow_to_boussinesq_adapter`, the mesh summary key
  `output_exchange_bundle_dir` and `SetupContext.mesh_bundle`. A mesh bundle comes from the `exchange_mesh` option.
- `hydromodpy.catchment.delineation.registry` (`get_backend`, `register_backend`,
  `available_backends`, `clear_backend_cache`) and the `kind` argument of
  `get_whitebox_backend`. `get_whitebox_backend()` returns the one Whitebox environment of the
  process, and a caller passes another backend by argument.
- `get_whitebox_backend` and `clear_whitebox_backend_cache` of
  `hydromodpy.catchment.delineation.whitebox_workflows_backend`.
- `last_largest_drainable_share`, a module value written during a run. `upstream_area` returns
  the value.

### Fixed

- The steady start of a transient Boussinesq run with the `petsc` backend and `ts_vi_obstacle` stopped with
  `AttributeError` in 2.0.0. It runs again, with `regularized_partition` for the auxiliary solve, as in 2.0.0a5.
- A `flow.restart_from` given as a run name or a sim_id is now read on a resume and in a calibration trial, as it is on
  a first run. Before, only a path worked there.

## [v2.0.0] - 2026-11-07

This is version 2.0.0. It is written for a reader who comes from version 1 or from an alpha. The development notes are in
[Development notes of 2.0.0](https://github.com/HydroModPy/HydroModPy/blob/main/docs/source/about/changes-during-the-alphas.md).

Since the last alpha, calibration gained a validation window, trials in worker processes and stricter checks of its files.

### What to do when you update

- Runs and sessions stored by an alpha are refused. Run them again with this version.
- A TOML file written for an alpha or for version 1 may use old keys. Run
  `hmp doctor --fix-config` on it. It rewrites the renamed keys and says what it changed.
- If you come from version 1, read `docs/source/get-started/from-v1.md`.
- The keys and commands that moved are listed in `docs/source/reference/changes.md`, "What changed in the TOML".
- A file that does not say which calibration protocol it wants follows protocol 1.3.

### Added

- Contributors: `tests/regression/frozen_documents/v2.0.0/` keeps the documents of 2.0.0 that `frozen_runs` does not hold (publication, install index, plan, lockfile, sidecars, data caches, trial series, the six documents of a sealed job, site catalog), written on a synthetic island by `python -m tools.freeze_documents`, and a test reads each one with the readers of this version.
- A page for users of version 1, with the table of old keys and commands.
- A `NOTICE` file with the licences of PyHELP and of the data, and `version` in `CITATION.cff`.
- `hydromodpy_version_min` in `workspace.toml` is enforced.
- A sha256 for each file of a run. `hmp doctor` reports a sealed file that is missing or changed.
- `--format table|json|csv` on the commands that print a result, and a `HMPY.Exxx` code at the start of each error line.
- JSON Schemas for `manifest.json`, `provenance.json` and the output of `hmp calibrate`.
- A transient Boussinesq run writes a `storage` budget term, so its domain budget closes.
- `[calibration] validation_window = {start, end}` keeps dates apart from the search. Each trial is also scored on them, under `validation.cost`. The promoted run stores the period and the score in `checks.calibrated_by`.
- `[metrics] window` minus the validation window is the default calibration window. A validation window that overlaps it, leaves a bound open or has no dated record is refused by name.
- `Project.calibrate()` takes `protocol`, `case`, `resume`, `dry_run`, `workspace`, `project`, `project_label`, `metric_fn` and `objective` by name on every route. `dry_run=True` returns the plan.
- `flow.sinks_sources.recharge.factor` multiplies the recharge in force. The default of 1 changes nothing. A calibration reaches it as `recharge.factor`, searched in log space between 0.5 and 2.
- `vka` can be calibrated under MODFLOW 6 as `[calibration.parameters.vka]`, in log space. It is not offered when the project declares `Kv`.
- `hmp campaign promote CASE` without `--trial` lists the five best completed trials. `hmp config targets` shows the search space, the draw and the default bounds of each target.
- `hmp config check` refuses `normal` sampling on `lhs` and `optuna`, and a calibrated recharge factor when the run has no recharge to multiply.

### Changed

- Soil reservoir defaults: `alpha` goes from 0.6 to 0.45 (FAO-56 table 22, cereals and maize).
  `flow.sinks_sources.etp.extinction_depth` goes from 1 m to 2 m. A file that writes these keys reads as before.
- The soil reservoir gives each SAFRAN cell its share of the catchment in the basin mean it prints. Without a catchment polygon, cells keep equal weight. The grids given to MODFLOW 6 do not change.
- Each stored format declares the oldest version that reads it. Every later 2.x reads every 2.0.0 run.
- A calibration with no pin on the protocol follows 1.3. The map is cut to the catchment and the network is rasterized from the heads of the observed streams.
- A tie on the cost in the last phase of a search promotes the trial that the search answered.
- A date written on a stamp belongs to the period `(s, e]` that the stamp closes.
- `hmp.run` returns a `Run`, and a calibration goes through `hmp.calibrate`. Overrides go through `set=`.
  `Project.run` is now `Project.launch`. A name that left is refused with its new path.
- A boundary condition is active when its table is declared, and `enabled = false` turns it off. Boussinesq and PETSc settings move to `[flow.runtime]`, and the discriminator is `kind` everywhere.
- On the command line, `-w` works on every verb. `hmp replay` is removed, `hmp test` is now `hmp dev test`, and `hmp campaign` holds the verbs of a plan of cases.
- A budget flux is negative when water leaves the aquifer, for every solver.
- A time series has a `source` column (`simulated` or `observed`), and the catchment row is named `catchment`.
- NetCDF and VTU write one variable with a layer dimension. Opening a NetCDF in QGIS needs `layer=` on the export.
- With `parallel` above 1, trials of a HydroModPy search run in worker processes that last, not in threads. A script that calibrates this way needs the `if __name__ == "__main__":` guard. A `metric_fn` must be defined at the top level of a module.
- `[modflow6.runtime] mf6_api_timeout_s` now limits one whole trial of a parallel search. The default stays 2400 s, so a longer trial now ends `crashed`.
- With `parallel` above 1, grid, Latin hypercube and random searches feed one queue of workers, and the progress bar moves as each trial ends. `multistart` restarts run side by side. `linearized` derivatives run in workers.
- `scipy_de` accepts `parallel` above 1 and scores a whole generation at once. Optuna `tpe` counts trials in flight as the worst cost so far. At `parallel = 1` nothing changes.
- Calibration refuses old keys of `[calibration]` and names the new one, for example `scoring_window`, `max_iter`, `tolerance` and `roptim_max`. `hmp doctor --fix-config` rewrites them. A sealed `config.toml` is still read.
- Changing the validation window starts a new cache scope and session. A file without the key keeps its cache keys.
- `Project.calibrate()` names its case like `hmp calibrate` (`[simulation] name`, else the project file stem), so both share one session and `resume` finds it. A call with phases writes `sessions/<case>.toml`, overwritten by the next call.
- The preflight refuses a minimiser on one parameter scored on two network bounds of positive weights. It also refuses a steady network-only search that moves K and the recharge factor, and `factor` beside `[flow.sinks_sources.recharge.soil]`.
- The preflight warns when `distance_gap` enters a cost beside another parameter or metric, and when two roots lie more than half a decade apart. Bisection needs every block to publish a signed residual.
- A raw residual cost in a unit, such as an RMSE in m3/s, beside pure-number costs is refused unless `normalize_cost = true`. `sampling = "normal"` is refused by the Optuna engine.
- A run stores the series at each observed station under the station id. A gauge the mesh cannot place is listed as unscored with a warning. `hmp.read(run, "head")` or a lake stage with several stations needs `station=`.
- `hmp run` ends a calibration with the same lines as `hmp calibrate`, which now prints units. `hmp calibrate --dry-run` shows the widest `parallel` of the phases.
- A `[sites]` campaign that holds a calibration can run up to 8 solves side by side without `--force`, up from 2.
- Several modules of `hydromodpy.core`, `project` and `workflow` moved to the layer that uses them. A plugin that
  imports one of them from its old path must follow it. The public names of `hydromodpy.__all__` do not move.
- Example 04 `run_calibration_api_daily.toml` calibrates on 2016-2018 and validates on 2019-2020. The composite example scores its network block on `distance_mean`.
- The layer matrix of `tests/unit/architecture` no longer grants 20 import edges that no code uses, nor the `calibration -> display` tolerance. Its rows go from the lowest layer to the highest, and a test keeps them so.
- Contributors: fourteen scripts of `tools/` that nothing called, five of them broken, left the repository. Script coverage runs through one wrapper, `tools/ci/coverage_runner.py`, and now measures `hydromodpy.examples`. The contributor docs name one environment, `hydromodpy-dev`.
- Contributors: the data tests live in `tests/unit/data/`, laid out like the package, and `tests/unit/data_managers/` is gone. The SIM2 grid configs share one base and the lake chronicle configs another, with the `[data]` schema unchanged. `attach_read_only` lives once, in `hydromodpy.core.io.db_retry`.
- The calibration session report draws the best run with the registered figures, lake level included, and names each image after its figure, for example `hydrograph_sim_obs.png` instead of `best_obs_vs_sim.png`.
- The `reporting` layer is gone. The calibration report is `hydromodpy.display.calibration_report` and the campaign summary `hydromodpy.results.export.campaign_summary`. `hmp.compare_pair` now sits beside `Catalog.diff`, and `hydromodpy.analysis.comparison.compare` is now `hydromodpy.analysis.compare`.
- `hydromodpy.schema.config_schema` replaces `hydromodpy.config.schema_export` and `hydromodpy.schema.export`. The plan of a `[sites]` project moved to `hydromodpy.project.launch.sites`, the check behind `hmp config check` to `hydromodpy.project.check`, the resolution of a `[site]` to `hydromodpy.data.sites.single_site`, `MetricsConfig` to `hydromodpy.results.metric_rule` and `PublicationConfig` to `hydromodpy.results.publication`. No row of the layer matrix cites a row below it any more.
- `simulation` is flat, the soil reservoir moved to `simulation/soil/` and `OutputAdapter` to `hydromodpy.simulation.post_run`. The data binders of a `Flow` moved to `physics/flow/binders/`, the field-parameter schema to `hydromodpy.core.config_kit.field_param` and the TOML examples of the dynamic flow blocks to `physics/flow/toml_examples.py`. `physics` no longer imports `spatial`, `simulation` no longer imports `data`, and the layer matrix keeps no tolerance for them.
- Contributors: `-q`, `-v` and `--debug` set the console level once in `cli/main.py`, so a new command no longer calls `apply_verbosity`. `cli/_workers/dev.py` is now `cli/_workers/lock.py`.
- Contributors: one registry, `hydromodpy.core.plugin_registry`, serves the evaluator, forward-model, terrain and mesh engines. `calibration/runners/cli_runner.py` is split into `document.py`, `session_scope.py` and `search.py`.
- The recession cloud and the Brutsaert-Nieber coefficient moved to `hydromodpy.results.derive.recession`, `particle_travel_years` to `hydromodpy.results.run.particles`, and the metric CRS helpers to `hydromodpy.core.io.crs`. `hydromodpy.display.report_blocks` and `hydromodpy.display.maps.geo` are single modules, and `GeoFigureMixin` is gone. `hydromodpy.display.catchment_report` holds nine modules instead of fourteen. Figures draw the same pixels.
- The helpers every solver shares moved into `hydromodpy.solver.base` (`properties`, `initial_conditions`, `drain_conductance`), the MODFLOW-NWT post-processing to `hydromodpy.solver.modflow_nwt.postprocess` and the Boussinesq catalogs to `boussinesq/catalog.py`. The MODFLOW 6 build runs as named steps, its solver options live in `modflow6/builders/solver_options.py`, the LAK builder is split in four modules and `modflow6.builders` no longer re-exports names. No input file and no result changes.
- Contributors: `hmp_log_records` is a fixture of `tests/conftest.py`, and `tests/_helpers/transport_guard.py` and `tests/validation/helpers/petsc.py` hold helpers that several test folders used to copy.
- `Catalog.read_geographic_feature`, `list_geographic_features` and `read_geographic_metadata` read the run directory instead of the index, and `Catalog.query_timeseries`, `query_budget` and `query_mass_balance` read through the run. `SimulationZarr` binds the writes and reads of the store as its methods. `record_derived_file` moved to `hydromodpy.results.ledger`. Run files are unchanged.
- `Catalog.load_dataset` builds its cohort with `Catalog.find` and shares the parameter pivot and the field stack of `RunSet`, and returns the same dataset. `DatasetLoader` is replaced by `hydromodpy.results.catalog.dataset_loader.load_dataset`, and `hydromodpy.results.export.run_identity` moved to `hydromodpy.results.run_identity`.
- The version is 2.0.0, set in `pyproject.toml`, `CITATION.cff` and `hydromodpy/core/version.py`.
- A TOML key or table that only a pre-release wrote still loads in 2.0.x with a warning, and `hmp doctor --fix-config <file>` rewrites it. From 2.1.0 it is refused. The rule of two minor versions holds for a TOML key or table changed from 2.0.0 on. A name of Python, an `hmp` command or a flag that leaves in 2.1.0 or earlier has no alias: it is refused with a message that names its new form. The alias with a `FutureWarning` holds for a change from 2.2.0 on. The warning of an old form no longer states a delay.
- The two irregular-mesh runs of example 06 (`run_selune_mf6_irregular.toml` and `run_vire_mf6_irregular.toml`) use the current keys. They resolve to the same configuration.
- `hmp doctor --fix-config` rewrites the TOML keys that only a pre-release wrote. The old and the new forms are `flow.active_bc` and `flow.active_sinks_sources` (tables of `flow.bc` and `flow.sinks_sources`, active when declared), `flow.bc.<name>.forcing.mode` (`kind`), `flow.ic.type` and `flow.ic.h.type` (`kind`), `flow.param.<id>.field_vertical_profile.mode` (`kind`), `flow.sinks_sources.lakes.<id>.outlets[*].couttype` (`kind`), `flow.sinks_sources.lakes.<id>.stageinit` (`initial_stage`), `flow.surface_interaction_model` (`flow.runtime.surface_interaction_model`), `geographic.catchment.catch_def` (`kind`), `simulation.process[*].type` (`kind`) and `solver.backend.backend` (`kind`). Four keys have no new form and the doctor drops them: `transport.active_bc`, `transport.active_sinks_sources`, `workspace.catalog_path` and `workspace.runs_dir`, because no solver read the first two and the storage layout fixes the other two.

### Removed

- The commands and flags that left before 2.0.0 have no alias. They are refused with a message.
- `catchment_mismatch` as it was. The old number is now called `basin_mismatch`.
- A network output can no longer score against `geographic.river_network`, because the DEM-derived network is no observation. `hmp doctor --fix-config` says to write `map.complete = "data.hydrography"` or a vector file.
- `hydromodpy.core.Workspace`, which never resolved. Use `Workspace` from `hydromodpy.project.accessors`. `hydromodpy.core.io.crs.haversine_km` is gone, use `hydromodpy.data.common.geo_helpers.haversine_km`.
- The B0 network and transient case left the package for `validation_cases/calibration/network_transient_b0/`.
- Helpers that nothing called: the re-export modules at the root of `physics/hydrology/pyhelp/`, `apply_simulation_time_to_flow_wells`, `apply_simulation_time_to_flow_boundary_conditions`, `SimulationPlan.is_empty` and the `Transport.update_*_parameters` helpers.
- Modules that nothing called: `modflow_common/recharge_evt_routing.py`, `boussinesq/assembly/residual_facade.py` and `boussinesq/forcing_resolution.py`.
- The unused `balanced` option and the `streambed_top` and `streambed_connection` arguments of `write_mesh`.

### Fixed

- A project whose DEM comes from a `[data.dem]` source alone, with no `dem_init_path`, opens again.
- The MODFLOW 6 `discharge` of a run with a lake and no SFR, the Boussinesq `discharge` and the Boussinesq budget terms. Sizes are in Numbers.
- A network output whose `time` falls on a stamp, and a window that ends on a stamp, now read the right period.
- The soil reservoir citations are checked against the sources. The description of `curve_number` no longer claims an explanation that no source supports.
- `load_to_numpy` reports a GeoTIFF without a CRS instead of raising `AttributeError`. `load_to_xarray` labels the real axes after a reprojection to degrees.
- `select_within_polygon_points` now filters the grid. PyHELP ERA5 preprocessing with `nearest_filter=False` receives only the points inside the polygon.
- Unit types such as `LengthMeters` give a pydantic `ValidationError` for a boolean, a list or a table without `value`. A TOML error in a later `[[table]]` block points at that block.
- `Project.calibrate()` refuses `method`, `max_trials`, `save_runs`, `seed`, `outputs`, `objective_blocks` and `phases` when the calibration comes from a file. `resume=True` works on the programmatic routes.
- `Project.calibrate` without phases honours `uncertainty.method = "linearized"` and returns `parameter_uncertainty`. A phased calibration from a project in memory no longer fails when a phase overrides the regime.
- `hmp doctor --fix-config` reads inherited files for the timestep, `start_datetime` and `[site] gauge`. It keeps the weights of each map and refuses dotted-key network outputs with a clear message.
- A sealed run config with `roptim_max` other than 2 reads and replays. Two parameters on one path, `path` with `target`, and `mode = "scale"` on a zero value are refused at load.
- A worker that dies marks its trial `crashed` and the search goes on. A stuck `mf6` is killed with its worker. Ctrl-C or SIGTERM at `parallel` above 1 ends the solves at once.
- Warnings say a value reached a bound only when it is on it. A minimiser on one parameter and two bounds is refused only for signed residuals. A calibration that scores different blocks in different phases is accepted.
- The `calibration_progress` figure of a staged calibration shows the value a phase froze, so the best run reads `K = 7.96e-05 m/s` instead of `K = nan`.
- `hmp report compare` writes a `variable` column in `scores.csv` and `by_site.csv`, so two variables scored at one station no longer give two rows that cannot be told apart. `hmp.compare_pair` finds the project from `project.toml`, like `hmp.compare`.
- A retired root section such as `[modflow]` is refused by its sentence when a mapping is validated directly, as it already was in a TOML file. `hmp config check` no longer lists a `ResourceWarning` among the warnings of a file.
- The Hub'Eau client no longer lists `HmnJ`, a product the API refuses, and the `product` example shows `HIXnJ`.
- `hmp dev test` refuses an option it does not take with its `HMPY.E` code first, and sees a `--basetemp` anywhere in `PYTEST_ADDOPTS` instead of adding a second one. An interrupted `hmp run`, `hmp calibrate` or `hmp spinup` prints `Interrupted.` like every other command, still with exit code 130.
- A mesh or terrain engine registered by hand can no longer take the id of a built-in engine that is not imported yet. The calibration preflight writes a window bound with its time when it is not at midnight, like the scoring.
- The parameter cost profile reads search bounds stored as JSON text, like the calibration progress card. The Piper, Schoeller and Stiff diagrams refuse an unreadable source with the same message.
- `import_zarr_field` refuses a field store whose schema version is outside the read window, like every other reader. A NetCDF export refuses a time step outside the axis of a field rebuilt on read instead of wrapping it. The STAC, RO-Crate and PROV views written outside a run directory are written atomically, and a NetCDF export no longer uses a fixed temporary file name.
- `RunSet.to_xarray` warns about a run whose field store cannot be opened instead of skipping it silently. `Catalog.describe`, `variables`, `metrics` and `stations` no longer hide errors other than a missing table or view of the index.
- A bisection search no longer stops with `TypeError` when a cut point whose solve failed is asked again and solves. Intervals from other curves are unchanged.
- `manifest.json` gives the sha256 of `fields.zarr`, and `hmp doctor` reports a field store changed since the seal. A seal written before has none and still reads. The STAC and RO-Crate views give no checksum for the store, because it is a directory and not a file.
- `hmp run --frozen` replays a completed run without `--force`. It used to be skipped as identical to the run it replays.
- The matching card of a calibration now reads the unit of K from the session journal (`bounds.<name>.units`) before the session config, so its axis no longer shows `K (-)` when the journal says `m/s`.
- `hmp report catchment` draws the run figures it needs (`hydrograph`, `piezometric_map`, `water_budget`, `seepage_map` and the active network overlay) when the run did not draw them, with the `[display]` the run sealed, instead of showing empty "Required figure missing" blocks.
- `hmp report catchment` accepts a run that kept the simulated discharge at several stations and reads the one named by `[context.observed_discharge] station_id`.
- The docstring of `hydromodpy.data.workspace.custom_scan` no longer says `hmp run` scans the custom data files.
- `hmp data ls` no longer says that `hmp run` indexes the files dropped in `data/<variable>/`. A run indexes the custom files its `[data]` sources read, and `hmp data add` indexes one file.

### Security

- `Pillow` now starts at 13.0.0, the first version with the 2026 security fixes.

### Numbers

Sizes come from example 04 unless another case is named. Runs of older versions are not comparable on these quantities.

- Soil recharge on example 04, 2015 to 2020, for a capacity of 50, 100, 150, 200 and 250 mm. It was 443, 392, 356, 325 and 295 mm/year and is now 443, 389, 350, 315 and 280 mm/year.
- Discharge of step 6 of example 04 (K = 3.16e-5 m/s, Sy = 0.04). NSE log goes from 0.903 to 0.932, KGE from 0.911 to 0.947 and NSE from 0.904 to 0.929. The July to September bias goes from +0.022 to 0.000 m3/s.
- MODFLOW 6 with a lake and no SFR, `discharge` over a three-month valley with a buffer. It was about 3.855e-05 m3/s and is now 0.087693 to 0.143696 m3/s, 2 600 to 3 700 times more. The old number was the lake outlet alone. SFR runs do not move.
- Boussinesq `discharge` on the test island, three months. It was 4.2e-9, 9.6e-10 and 4.2e-11 m3/s and is now 0.012709, 0.025505 and 0.010800 m3/s. MODFLOW 6 on the same mesh reads 0.011417, 0.023888 and 0.009734 m3/s.
- Boussinesq calibration trial on a mesh wider than its catchment. The old series was 2.0 times the published one on an island cut in half. It now equals it. With no buffer nothing moves.
- Boussinesq `budget/drain` and `budget/surface_excess` change sign, the size stays. The signed fields now close against the change of storage, to 3.7e-7 of the recharge on the steady period. Steady runs and the MODFLOW solvers do not move.
- A network output whose `time` falls on a stamp reads one period earlier. With `time = "2002-10-01"`, `distance_gap` goes from 86.32 to 79.08 m and `D_optim` from 142.4 to 139.2 m. A date inside a period does not move.
- A window that ends on a stamp keeps one period fewer. `2001-01-01` to `2002-01-01` on a monthly run is 12 periods, it was 13.
- A tie on the cost in a last phase. On the shipped mesh the promoted K goes from 8.058e-5 to 7.962e-5 m/s (-1.2 %). On 30 x 30 it goes from 1.4678e-4 to 1.5034e-4 m/s (+2.4 %).
- The cut to the catchment under `heads`. On the shipped mesh every K and cost is the same, and the heads examined fall from 154 to 29. On 30 x 30, J at the best trial goes from 11.0 to 50.3 m.
- `catchment_mismatch` changes meaning and enters no cost. On the shipped mesh of 21 406 cells 0 becomes 0.37 %, and on 30 x 30 it becomes 11.0 %.
- Every cache key of a calibration changes once, so the trials of an earlier session are solved again.
- No number moves for MODFLOW 6 on example 04 (the 55 arrays, `timeseries`, `budgets` and the 11 scores, NSE 0.9345), nor for a run with no override.
- A Python calibration without phases and with a `linearized` width now pays one model run per parameter plus one at the optimum. Search results and costs are unchanged.
- Example 04 calibrated Sy goes from 0.04411 to 0.04296 and `1 - nse_log` from 0.083976 to 0.083988, with two solves less. K does not move. `calibration.precision` now writes a relative `fatol`.
- `run_calibration_api_daily.toml` ranks its five K on 2016-2018 instead of 2016-2020. The size of the change was not measured.
- At `parallel` above 1 trial costs are equal to the last digit, with 63 trials checked at widths 2, 4 and 8 on example 04. Peak memory at width 8 is 6.5 GiB.
- `scipy_de` at width 4 needs more evaluations than at width 1 for the same late precision, up to 1.5 to 5 times, and wins when solves dominate. `tpe` with `constant_liar` is neutral at width 2 and better from 4.

## [v2.0.0a5] - 2026-10-13

This alpha adds a daily soil reservoir for the recharge, a new way to draw the observed network from its heads, and a computational top for MODFLOW 6. It also removes the burn of the mapped network into the DEM and fixes many Boussinesq and validation errors.

### Added
- `[flow.sinks_sources.recharge.soil]` computes the recharge from a daily soil reservoir fed by the rain and the ETP, instead of the SIM2 drainage. It works with MODFLOW 6 only. Main keys: `ru` (required, calibratable as `soil.ru`), `alpha`, `kc`, `impervious_fraction`, `bypass_fraction`, `transit_time`, `spinup`.
- `hmp run <file> --until load_data` checks the soil alone. It prints the budget in mm/year and the recharge for `ru` from 50 to 250 mm, and writes no run. The section refuses what would count water twice and says what to write instead.
- Soil reservoir options: `curve_number` adds a runoff in the manner of HELP, with `runoff_time` and `runoff_lag`. All are calibratable and off by default. `[data.soil_capacity]` spreads `ru` over ten classes inside each SAFRAN cell. Example 04 gains `step6_soil_reservoir.toml`.
- `[geographic.catchment].dem_resolution` aggregates the DEM to a coarser cell size (for example `"75 m"`) before anything is delineated. A value finer than the DEM pixel is refused.
- `observed_rasterization = "heads"` draws the mapped network from its heads only, so the path of a field, a ditch or a rectified reach no longer counts as model error. Each trial publishes `n_heads`, `n_heads_lost`, `head_snap_p90_m` and `heads_trace_near_map_share`. The figure `observed_network_heads_map` shows the result.
- The dam foot of a lake with a declared spillway is a forced head of the heads rule. It comes from the model, never from the observed map, and is counted in `n_forced_heads`.
- `source = "explore2"` for `[data.precipitation]` and `[data.etp]` reads a local DRIAS Explore2 NetCDF.
- `[[data.dem.sources]] source = "ign_geoplateforme_dem"` takes `dataset = "rge-alti"`, the RGE ALTI at 5 m (default) or 1 m. Large requests are refused with their size.
- `[data.crossings]` lists roads, railways (BD TOPO), ROE obstacles or a custom file. `[geographic.crossings]` notches the generated river network at each road, railway or bridge crossing, except where a dam or weir is declared.
- `[geographic.bed_regularization]` makes the channel bed of the model top never rise downstream. It is off by default and serves both DRN and SFR.
- `[geographic] dem_correc_type = "capped_breach"` conditions the routing DEM with a bounded breach (`max_depth` 0.5 m, `max_distance` 200 m). `fill` stays the default.
- `[modflow6.sgrid.top_sampling] mode = "zonal"` now also works on a structured grid coarser than its DEM.
- Calibration: `method = "lhs"` (Latin hypercube, sized by `method_options.n_samples`, `max_iter = "auto"` budgets exactly `n_samples`). `extinction_depth`, `impervious_fraction`, `runoff_lag` and the depth profile `K.characteristic_depth` can be calibrated.
- `[calibration] persist_trial_series = true` writes the simulated and observed series of every scored trial under `sessions/<name>/trial_series/`. It is off by default.
- `hmp calibrate --check` refuses an `observes` station that no data source lists and a scoring window with no date of the run (exit 14). It warns when `da_mh_gp` is scored on a metric other than `rmse`.
- `hmp config resolve FILE` prints the TOML a `base_config` chain resolves to. The directive `key__merge = [...]` merges a list of tables with the inherited one.
- `hmp config schema --editor [--out FILE]` writes a JSON Schema for editors. It accepts `base_config`, `__append`, `__delete`, `__merge` and quantities with units.
- `hmp viz show --opt NAME=VALUE` sets any figure option. Every figure takes `title` and `show_run_name`.
- `hmp catalog import --as NAME` names the project of an imported run.
- Python API: `hmp.run(path, name=...)` names a run from a TOML path. `hmp.read(run, field, time=...)` takes a date, `"first"`, `"last"` or an integer. `hmp.read(run, "particles")` returns the particle paths. The `sfr_reaches` table has a `downstream` column.
- `flow.partition_release_depth_m` sets the depth scale of the regularized partition of the Boussinesq solver (0.05 m by default).
- Exit code 23: a testbed or regional lab with a failed case ends with `FailedCasesError`, after writing every artifact.
- `[context.geology] path` in a catchment report names the geological map for the legend.
- Validation: new cases `stream_depletion_glover_balmer_2d`, `hantush_recharge_mound_2d` and `linearized_unconfined_boundary_periodic_1d`, new variants `modflow6_voronoi` and `boussinesq_local`, and a nightly PETSc job. The Validation page shows the measured value, threshold and error maps of each case.
- Documentation: Understand pages, a glossary, reference pages for calibratable parameters, minimal files, exceptions and exit codes, and a Get started quick start. Every `hmp` command shows an example in `--help`. The data-source registry states each licence.

### Changed
- A run keeps its whole per-cell budget by default, storage terms included. The developer key `[simulation.results] keep_per_cell_budget = false` keeps only what the run's figures, exports and outputs read. A calibration that saves runs keeps the whole budget for the best run only.
- `[simulation.results.derived]` and `[simulation.results.budget]` are dropped on load with one line. `hmp doctor --fix-config` removes them from the file. Every derived field is now rebuilt on read.
- MODFLOW 6 reads a computational top, so every top-layer cell has the same thickness. Under Newton, a thickness that varied between cells gave too low a transmissivity. Package elevations, initial heads and the stored run keep the ground.
- `observed_rasterization` now defaults to `"heads"`. Write `"crossing"` to reproduce the rule of the paper.
- Every MODFLOW 6 and MODFLOW-NWT build makes the descent D, and every flow path reader follows it. D is stored in `fields.zarr/mesh/descent_*` and read by `Run.descent`. Boussinesq also stores D for a raster run.
- A steady run (`flow_regime = "steady"`) is one stress period over the whole `[simulation.time]` window, whatever `step_value` says.
- A list of tables in a child TOML replaces the inherited list. Write `key__merge = [...]` to merge tables or `key__append` to extend.
- `solver.backend` follows the flow process of `[[simulation.process]]` when the file does not set it. Two different names are refused.
- `flow.runtime_backend` defaults to `"auto"`. Boussinesq runs the dense `local` engine up to 400 cells and `scipy_sparse` above. An explicit `local` or `scipy` on a larger mesh stops with `IncompatibleCapabilitiesError`.
- MODFLOW-NWT defaults to the chi-MD linear solver (`linmeth = 2`). With GMRES a stiff recession could be accepted as converged with a frozen head. `fluxtol` is now in m3/s, with a default of 500 m3/day.
- `[modflownwt.sgrid.top_sampling] mode = "zonal"` needs `channel_source = "none"`.
- The run identity that decides whether `hmp run` skips an identical completed run now covers every input file hash and the package version, and no longer the run name. `hmp.run(cfg)` without `name=` uses `[simulation] name` and skips an identical run like `hmp run`. `force=True` computes it again.
- `hmp.run` raises `CatalogError` when the catalog cannot be opened after a finished run. `hmp.calibrate(path)` returns a `CalibrationReport` for a file without phases (`return_report=False` gives the dict).
- A pipeline step failure exits with the code of its cause (16 for data, 15 for solver) instead of 1.
- The NSE on log discharge is named `nse_log` everywhere. `hmp catalog reindex` renames stored rows, and `@best:log_nse` is refused.
- `@best`, `@worst` and `Catalog.best/worst/rank` follow the direction of the metric. A metric with no declared direction is refused.
- Under `coverage_policy = "warn"` or `"ignore"`, a period before the first sample takes that sample instead of stopping the run.
- `hmp config check` refuses a type in `data.types` without its `[data.<type>]` section. `[testbed]` and `hmp report catchment` files refuse unknown keys (exit 14 for the report).
- `hmp data get <variable>` without `--source` takes the one source that downloads.
- A calibration that samples a recharge parameter writes the RCHA of each trial in its own folder and removes it with the trial.
- Example 21 loses the burn and the top conditioning keys. Every calibration of example 21 must be redone.
- A negative numeric `first_clim` is refused when `negative_to_evt` is false.
- The reports and figures of the comparison, network, overview and catchment pages are written in English.
- The technical note is cited as HESS 30, 5571-5592 (2026).

### Removed
- `[geographic.enforce_streams]`, the burn of the mapped network into the routing DEM, with its drift check and download. A file that declares it is refused. The geographic cache changes for every project, so each rebuilds its geographic tree once.
- `[geographic.snap_streams]` and everything built for it. A file that declares it is refused.
- `[modflow6.sgrid] condition_top`, `condition_top_epsilon`, `network_safety_net` and `max_channel_lowering_m` (and their `[modflownwt.sgrid]` copies). The solver top is never conditioned. `rectify_on_mesh` no longer needs `condition_top`.
- `stream_threshold_km2` and `stream_threshold_cells` of `[flow.sinks_sources.sfr.<id>]`. SFR traces its reaches on the network whose threshold is in `[geographic.river_network]`.
- `diagonal_neighbors` of point and cell calibration outputs. The network outputs keep it.
- The top-level `[persistence]` table. Write `[simulation.results.persistence]` or `[calibration.persistence]`.
- `calibration.outputs.<name>.cell_id`, which every run refused. Use `row` and `col`, or `support = "point"` with `x` and `y`.
- `transport.modpath.parameters.track_dir = "custom"`, `fill_method` of the CSV forcings, the `id` of `[data.lake_bathymetry]` and `[data.lake_geometry]`, and several site_selection keys. Each is refused with what to write.
- The one-way pass that lowered the downstream top of SFR reaches, by up to 29.8 m.
- The `geology_field` keyword of `discretize_fieldparam_on_sgrid`. Use `support_field`.
- The user guide pages of the documentation. Old URLs redirect to the matching reference, Understand or Theory page.

### Fixed
- Time steps: a stress period cut into steps now stores the head of its last step and every flux as the length-weighted mean of its steps, for MODFLOW 6, MODFLOW-NWT and Boussinesq. A run of one step per period is unchanged. A MODFLOW 6 run with a lake or stream network and several steps per period no longer fails at extraction.
- A transient Boussinesq run now solves its first period at steady state (`flow.first_period_steady`, true by default), stamps each period at its end, and honors `simulation.time.substeps_per_period` with every engine.
- A Boussinesq cell with an imposed head takes no recharge and no surface release. A well or drain on such a cell does nothing, as in MODFLOW, and the run warns. Heads are unchanged.
- The default Boussinesq surface closure released water far below the ground. It now follows the depth of the water table with `flow.partition_release_depth_m`.
- Boussinesq derives an undeclared drain conductance as `K * cell_area / solver.drain_bed_thickness_m`, like MODFLOW. Its `budget/constant_head` field is now signed positive into the aquifer.
- With `grid_dual = "voronoi"` (default on a Gmsh mesh), MODFLOW 6 places wells, side boundaries and the stream boundary on the Voronoi cells it solves. Before, a run could stop on an out-of-range cell or put a well in the wrong cell.
- The channel mask of the zonal top covered the whole catchment. A zonal run now gets a higher top on its hillslopes.
- The water budget of a MODFLOW-NWT run is read, so a calibration threshold on the budget now applies to it.
- `first_clim` sets the rate of every steady stress period and no other, under all three solvers.
- `simulation.time.coverage_policy` applies to every forcing record. A record that ends early stops the run under the default `"error"`.
- A forcing record whose time index is not in nanoseconds took the last sample for every period. It now takes its own samples.
- A forcing value written with its unit (`'100 m**3/day'`) is no longer scaled a second time by `units`. Lake and SFR rainfall and evaporation are read as rates in length per time. A negative lake rainfall, evaporation, runoff, inflow or withdrawal is refused.
- A calibration of `flow.sinks_sources.recharge.values` reads its bounds in the unit of `recharge.units`, not in m/s.
- `hmp run` now skips an identical completed run as documented. A resume in another process no longer stops on a changed workspace fingerprint.
- A data variable in `[data]` that cannot be loaded stops `hmp run` with exit code 10, 14 or 16, where it used to be logged with exit code 0. `hmp run --frozen` stops with exit 16 on a missing lock entry, cache miss or digest mismatch for every variable.
- A custom DEM, geology file or river network without a CRS is refused (exit 16) with the command that writes one. It used to be labeled EPSG:2154 or EPSG:4326.
- A side, ocean or stream constant head below the bottom of its cell stops the run before the solver, for MODFLOW 6 and MODFLOW-NWT.
- `hmp calibrate` prints the calibrated values, their interval and the cost for a file without phases. `--list-phases` prints one line for the single search.
- `hmp dev rank` works again. `hmp catalog watch` no longer shows live runs as `[STALE]`, and a run stopped by Ctrl+C or SIGTERM is marked `failed`.
- `nse_seasonal` and `reservoir` scored NaN on a monthly series. The summary columns `nse`, `kge`, `rmse` and `r2` of `v_simulation_summary` were empty for runs scored on discharge.
- Network and seepage figures render again on a run with several layers, and `sfr_longitudinal_profile`, `difference_map` and `side_by_side` are repaired.
- A run on an unstructured mesh keeps its K, Sy and Ss fields under `derived/` again.
- Wells declared without `"wells"` in `flow.active_sinks_sources` are refused by `hmp config check`. A mesh along the rivers without a `[geographic.river_network]` threshold is refused with the key to set.
- Runs recorded before the new refusals rerun and resume again, because their stored configuration is migrated when read.
- Validation references and thresholds were corrected for the drainage, island, pumping, Brutsaert and Ogata-Banks cases. Their errors now compare what the model computes.

### Numbers
- MODFLOW 6 heads change on every model whose thickness varies (`flat_substratum`, `raster_substratum`, `raster_thickness`, a zonal top). The head RMSE against MODFLOW-NWT on the Nançon was 0.16 to 0.31 m before. MODFLOW 6 calibrations made on such geometries are not comparable. Example 04 is unchanged.
- Soil reservoir on the Nançon, daily 2015-2020: the KGE of the gauged discharge goes from 0.65 (SIM2 drainage) to 0.79 (`ru = 150 mm`). The mean yearly recharge stays within 3 % of the SIM2 drainage plus runoff.
- Descent D: on example 04 the gauge cell now drains 99.89 % of the catchment, against 0.17 % on the former face graph.
- Boussinesq: heads of the first period of a transient run now differ from MODFLOW 6 by 0.23 m (RMSE) on the natural-mesh test, against 2.6 m. On the natural basin the exported recharge matches MODFLOW 6 to 1e-8, where it was 13.1 % above the forcing. The pumping of a well on a fixed-head side reads 1000 m3/day, not 2000.
- The default Boussinesq closure lost 3.6 % of the recharge of a water table 10 m under the top of a 60 m aquifer. It now loses 2e-9 at 1 m depth.
- Zonal top on the Flume Voronoi mesh: the channel mask now holds 4,197 pixels instead of 146,384. The weekly Flume v2 run no longer converges with its solver settings.
- Example 21 with the breach routing DEM: 97.92 % of the catchment drain cells routed to the river (99.62 % with the burn), outlet discharge 1.127 m3/s (1.147).
- MODFLOW-NWT with GMRES could report a budget off by 200 %. With chi-MD the recession is computed again.
- `capped_breach` against `fill`: the catchment moves by less than 0.1 %, and the agreement with BD Topage moves by 1.74 points on example 04 and 1.22 points on the 25 m Nançon DEM.
- Per-cell budget on the six-year daily Nançon run (21,406 cells): 299 MB, 3.7 times the head. The seepage mask reads in 0.3 s instead of 9.4 s.
- Network heads rule on the Flume Voronoi run: one piece of 5078 cells to the outlet, where `"crossing"` left 1989 pieces.
- Stored values: the budget and derived fields of a stress period cut into steps are now the period mean. A run of one step per period is bit for bit unchanged.

## [v2.0.0a4] - 2026-09-29

This alpha makes stored results smaller and calibration promotion faster.

### Changed
- Time-varying fields are stored in float32 with a rounded mantissa. This is the default
  (`[simulation.results.persistence] field_precision = "compact"`). Use `"exact"` to keep float64.
- A calibration promotes a trial from the solve it already ran. It no longer writes the inputs and
  solves again. The promoted run is the same bit for bit and carries the tag `promoted_from_trial:<N>`.
- Flow-state figures read a field over a range of timesteps with the store opened once
  (`results.run.geographic.field_range`, `field_steps`).
- The CLI banner draws each letter whole in its own color.
- Every file of example 04 draws more figures and writes exports to `share/<run>/` with `[[export]]`
  blocks. The composite calibration draws a cost profile and a distance crossing against K.

### Fixed
- The scan of `data/<variable>/` removes an orphan sidecar when its data file is gone. A sidecar with
  a stated licence or notes is kept. `hmp data check` tells which case applies.
- A calibration whose gauge comes from an API cache promotes its runs again. It failed on the second
  launch because a station location held numpy values the catalog could not write as JSON.

### Numbers
- Compact storage costs at most 2**-17 of the value, under 1 mm on a 130 m head. The NSE of example 04
  moves by 7e-8. A daily 6-year run goes from 1375 to 397 MB and a monthly one from 16 to 5.5 MB.
- The 15 figures of a daily example 04 run render in 17 s instead of about 2 min, with the same pixels.
- A promotion on the daily API grid of example 04 saves about 7 min of solve.


## [v2.0.0a3] - 2026-09-29

This alpha fixes concurrent runs, parallel calibration and several wrong budgets and figures.

### Changed
- On a terminal, a console log line starts with a glyph for its level: `✗` error, `!` warning,
  `›` milestone, `·` debug. A pipe keeps the `[WARNING]` labels.

### Fixed
- Several runs of one project can run at once. Each run or calibration session works in its own
  `.hmp/scratch/<config>.p<pid>/`. Before, concurrent runs lost each other's files.
- A calibration whose promotion fails now exits 21 (`CalibrationError`) from `hmp run` and
  `hmp calibrate`. It used to print "done" and exit 0.
- `hmp example add 04` merges its stations into `data/<variable>/<variable>_custom_LOC.csv`. Without
  them the hydrometry, recharge and runoff loads failed. Existing rows stay unless you pass `--force`.
- `parallel` alone now runs calibration trials side by side, and a phase takes the `[calibration]`
  `parallel` and `batch_size` unless it sets its own. `scipy_nelder_mead` and the root search use it.
- `flux_timeseries`, `water_budget` and the testbed budget metrics read one budget zone, the
  catchment or the domain. They used to sum both and count the catchment water twice.
- The calibrated discharge adds a gridded runoff such as SIM2 with `extent = "watershed"`. The
  objective scored the drain alone against the total gauged flow and pushed K to the lower bound.
- Every run a calibration promotes keeps its watershed, and a network output whose `time` is a date
  is redrawn at that date. Both used to make the promotion or its figures fail.
- A figure that does not apply raises `FigureNotApplicable`, and the batch skips it with its reason.
- Calibration figures read the session journal, mark the returned trial and carry axis units. The
  `rise` option of `parameter_cost_profile` is removed.
- A GeoPackage or Shapefile export of `simulated_active_network` holds the active cells only.
- `hydromodpy.__version__` reads the checkout's `pyproject.toml`, and `Run completed` prints the run
  duration. The `if_exists = "replace"` help now describes what `replace` does.

### Numbers
- A budget that summed both zones drew 1.68 m3/s of recharge for 1.09 on the domain and 0.59 on the
  catchment. It now reads one zone.
- On the Nancon bounds, a root search at `parallel = 4` takes 6 rounds (20 solves) instead of 15,
  and two roots take 8 rounds (26) instead of 24. With `parallel = 1` the search is unchanged.
- On the composite of example 04, 8 trials at `parallel = 4` take 278 s for 695 s of solves.


## [v2.0.0a2] - 2026-09-28

This alpha adds a general `[[export]]` mechanism and a two-bound, transient network calibration.

### Added
- `[[export]]`: one block per export request (`variables`, `time`, `period`, `format`, `folder`,
  `file`, `crs`, `resolution`, `layer`, `nodata`). The format follows the data. `format` also takes
  `package`, `stac`, `rocrate` and `prov`.
- `hmp export SIM_REF [variables...]` takes the same options. `--list` prints what a run can export.
  The catchment, mapped networks, `watershed_dem`, the water budget and `simulated_active_network`
  are exportable.
- `[display] time` and a per-figure `time` name the instant a map draws, as a date, `first` or `last`.
  `hmp.figure(..., time=...)` and `hmp viz show --time` take it too.
- A network calibration output takes an ISO date in `time`, and `normalize_cost = true` on
  `distance_gap` and `distance_mean` divides by the validity length.
- A network output takes a minimal (permanent) map beside the maximal one, as a file
  (`minimal_stream_geometry_path`) or with `minimal_observed_network = "data.hydrography"`.
- The transient two-bound mode `[calibration.outputs.<name>.extent]` scores a maximal and a minimal
  extent per calendar year. The bisection closes one root per bound and returns their weighted
  geometric mean (`weights`). `max_iter = "auto"` budgets both roots.
- `validity_length` on a network output, `"auto"` or a length such as `"150 m"`, sets the Eq. 4 bound.
- `[geographic.snap_streams]` (`off` by default, `diagnose`, `apply`) moves the mapped network onto
  the talwegs of the criterion graph, with two figures that show what moved.
- Figures `network_extent_bounds_map` and `hydrographic_network_permanence`. A calibration ends with
  a short recap and writes `methods.md`.

### Changed
- `optimizer_kwargs` is now `method_options` and `*_engine_options` are `*_method_options`. The
  per-figure `timestep` is now `time`. Old names load, and `hmp doctor --fix-config` rewrites them.
- An old `[export]` table or `[[export.artifacts]]` loads as `[[export]]` blocks.
- `[geographic].dem_correc_type` defaults to `"fill"` instead of `"breach"`. A file that writes
  `"breach"` keeps it.
- `matching_hydrographic_network` is version 1.2, and a pin on 1.1 is refused.
- With both maps, a one-state network output is scored on the minimal map, and the maximal map is
  published as a validation outside the cost. roptim is always Doptim / h_obs.
- Promoted calibration runs are named `<simulation name>_<phase>`.
- `hmp config template` without `--modules` writes every module, `[calibration]` included.

### Removed
- `hmp data export`, `hmp data export-package` and `hmp catalog export`. Use `hmp export`.
- The `[export]` format toggles, `output_dir` and `[[export.artifacts]]`.
- `roptim_max`. Loading drops `roptim_max = 2` and refuses other values.
- `geometry_from_run`. Use `network_maps_from_run`.

### Fixed
- `hmp calibrate --check` names an option a phase-two method refuses before phase one spends its budget.
- `flux_timeseries` draws each flux over its own period instead of one period late.
- Exported NetCDF files carry the mesh size and ACDD metadata. The simulated discharge is exported
  under `catchment` instead of `_catchment`.
- A station read back from the data cache keeps its variable. A Hub'Eau gauge was lost from the
  second run on. A station named in `station_ids` survives the watershed mask.
- An IGN BD ALTI DEM sets its sea to nodata, so the breach step can route it.

### Numbers
- The default `dem_correc_type = "fill"` changes the DEM, so calibration results move. The renames
  change every calibration `params_hash` once.

## [v2.0.0a1] - 2026-09-28

Version 2 rebuilds HydroModPy around a project TOML, the `hmp` command line and a catalog of runs.
It adds lakes, streams and flow barriers in MODFLOW 6, a calibration engine and a data layer.
This first alpha adds the stream-network calibration.

### Added
- MODFLOW 6 Lake (LAK) with stage, bathymetry abacus and bed leakance, a bathymetry raster that
  lowers the cell bottoms under a lake, and `variable = "lake_level"` for calibration.
- Streamflow Routing (SFR) with water movers (MVR) that feed a lake, and horizontal flow
  barriers (HFB) such as a dam cutoff wall.
- A top-level `[export]` section, `domain_extent` (`box`, `watershed_buff`, `watershed`) and a
  mesh `lake_refinement` block.
- `geographic.catchment.buff_area = "N%"` enlarges the catchment by N per cent, as in
  Abherve et al. (2023). A distance reads `"150.0 m"`. `from_outlet` and `from_polygon` default to `"10%"`.
- A raster substratum. `[data.substratum]` holds one raster in meters, read by the depth models
  `kind = "raster_substratum"` and `kind = "raster_thickness"`. Both take `offset` and
  `min_thickness`. The raster must cover every cell of the domain.
- The aquifer geometry can be calibrated with `[calibration.parameters.thickness]` and
  `[calibration.parameters.substratum_elevation]`. `hmp config targets` lists what is available.
- Stream-network calibration reports more. Each trial publishes `d_sat_m`. A search on K alone also
  gives `k_over_r`, `k_optim_m_s`, `t_over_r_m` and `t_optim_m2_s`. The report gives the Eq. 4
  verdict (`roptim_verdict`), the final `bracket` of a bisection and whether the search converged.
- Network outputs take `observed_rasterization`. The default `"crossing"` scores J = 0 for a model
  that reproduces the map. `"touch"` replays older sessions.
- A phase declares `regime = "steady"` or `"transient"` instead of overriding the time grid. It also
  takes its own `uncertainty` keys, and `objective_blocks` accepts a table of shares.
- `hmp calibrate` prints the share of the cost each objective block took. On the example 04
  by-hand session, the best trial takes 37 % hydrograph and 63 % network.
- `hmp calibrate --list-phases` shows the method, uncertainty width and objective blocks of each
  phase. `hmp calibrate FILE --expand` prints what a protocol unfolds into.
- `snap_radius` on a discharge output of `support = "point"` or `"cell"` moves the gauge onto the
  most accumulated cell within that radius. It is off by default.
- `hmp data get` serves data without a project, from a request file or from
  `hmp data get <variable> --bbox ... --crs ... --out DIR`. It writes one file per variable and
  source, plus a `request.json` with sha256, CRS, box and period. The `data-request` process
  (`hmp process run data-request --job DIR`) is its job form.
- Figures `recession_power_law`, `residence_time_distribution`, `mass_balance_error` and
  `concentration_boxplot`, and six calibration figures such as `calibration_convergence`.
- The twelve v1 examples run again in the current format.

### Changed
- `hmp run <calibration.toml>` now runs real MODFLOW simulations. `save_runs = "best_n"` promotes
  only the best trials to full runs.
- `[simulation].run_id` and `on_collision` are refused. Use `[simulation].name` and
  `[simulation].if_exists`, which now defaults to `version`. `hmp doctor --fix-config FILE.toml`
  migrates the old keys.
- Unstructured MODFLOW 6 grids now build a Voronoi/PEBI dual by default, with about half the cells.
  Set `grid_dual = "triangle"` for the old grid. MODFLOW-NWT and Boussinesq are unaffected.
- Raster, VTU and shapefile auto-export now writes the last timestep. Set `[export].times = "first"`
  for the old behavior.
- `method` no longer defaults to `grid`. Calibration picks `bisection` for one log-space parameter
  scored by signed network distances, `scipy_nelder_mead` otherwise. `optimizer_kwargs` need `method`.
- `max_iter` and `steady_max_iter` default to `"auto"`, the worst-case count of a bisection. A
  search that hits `max_iter` gets one extension of half its budget. If still open, it is reported
  not converged, freezes nothing, and a phase that depends on it is refused.
- A network output reads one state, `time = "last"` or `"first"`. `"all"` and date lists are refused.
- The network criterion descends D8 by default (`diagonal_neighbors = true`) and reads one surface.
  Each trial publishes `catchment_mismatch`.
- `[calibration.uncertainty]` `tolerance` and `mode` follow what is scored. A network-only phase
  gets one mesh cell. Other phases get 5 % of the best cost.
- `objective=` must be a `module.path:callable`. Any other value is refused at entry. In Python
  mode, give the metric in `objective_blocks=[...]`.
- `[[data.hydrography.sources]] source = "bdtopage"` now downloads every reach. The old layer
  missed 441 of 694 km over the upper Ille. `typename` is ignored with a warning, and older
  BD Topage downloads are not served again.
- A NetCDF export writes one variable per layer (`<var>_layer<N>` above one layer) so that QGIS
  can read it. `import_netcdf_fields` stacks the layers back.
- `simulation.time.substeps_per_period` stays at 1. One step per period moves monthly discharge by
  4 to 28 % against a refined run, and a discharge calibration absorbs it into the parameters.

### Removed
- `hmp migrate`, `reference_values` in calibration protocols and the `hydromodpy.optimizer`
  entry-point group. Pass your own `Optimizer` to `CalibrationEngine(optimizer=...)`.
- `[modflownwt.tgrid]` and chronicle-driven stress periods (`genmtd = "from_chron"`, per-period
  `ntsp`/`tsmult`). `hmp doctor --fix-config` drops the section.
- `geographic.bottom_path`. `hmp doctor --fix-config` moves it to `[[data.substratum.sources]]`.
- The `data-fetch` process. `data-request` replaces it and serves every `[data]` variable. Its
  report is `outputs/request.json`, and a chain links `extent.mask`.
- The sources `hubeau-piezometry`, `ign-bdalti` and `sim2-precipitation`. Use their `[data]` section.
- `DataManagers` and the analytical mock evaluator. Custom metrics use `objective = "module.path:fn"`.
- `[[testbed.variant]]` and `[[testbed.variant_from_catalog]]`, with the outputs `variant_id`,
  `variant_label` and `variant_count`. Use `[[testbed.case]]` and `case_id`, `case_label`, `case_count`.
- The Chèze lake project `19_cheze_reservoir` and the `new_to_sort` projects leave `examples/`.

### Fixed
- A stress-period stamp is the end of its period. Fluxes are now compared with the mean of the
  previous period and states at the stamp. Fit metrics, scores and figures follow.
- MODFLOW 6 adaptive time stepping hit the wrong stress period and ignored the requested
  sub-stepping. RMSE against the erfc closed form falls from 0.0481 m to 0.0035 m.
- MODPATH times from MODFLOW-NWT were labeled days but stored in seconds. Travel times and
  residence-time figures were off by a factor 86400.
- Geology is requested over the buffered box. A zero or non-finite K on an active cell is refused
  with its cause.
- The data cache no longer depends on where `hmp` starts. `hmp data prune`, `remove` and
  `check --fix` delete what they should, and orphan sidecars show in `hmp data check`.
- The BD Topage download no longer drops pages after the first short one, and the hydrography
  cache no longer serves an answer fetched for another question.
- `hmp data export` accepts per-cell budget fields such as `drain` and `recharge`.
- A NetCDF export loads in QGIS in EPSG:2154. Re-exporting onto an open file no longer truncates it.
- The PyHELP NetCDF export uses `recharge` and loads. A custom gridded source passes only its variable.
- A phase that lists an already calibrated parameter starts from the frozen value, on `cma_es` and
  `scipy_nelder_mead`. The later phase wins and the report names it re-opened.
- `hmp example add 04` works again, and `hmp viz show --output X` says it wrote `X.png`.
- `hmp list` can run beside `hmp run` because `SimulationCatalog` retries on DuckDB lock errors.

### Numbers
- Discharge NSE of the stored example 04 run moves from 0.531 to 0.665, and the stage-two
  `nse_log` from 0.595 to 0.731, because of the end-of-period stamp. A monthly run on the Nancon
  was off by 0.167 m3/s on average through the daily product, on a mean of 0.97 m3/s.
- Unstructured MODFLOW 6 heads and budgets change with the Voronoi default. Rebuild calibration caches.
- With `buff_area = "N%"` on the Nancon, the margin falls from 825 m to 150 m and the box domain
  from 151.9 to 120.4 km2.
- MODFLOW-NWT particle travel times and residence times change by a factor 86400.
- The geographic cache rebuilds once, and the uncertainty width leaves the params hash, so
  calibration caches rebuild once.

---

## [v1.0.0] - 2026-08-10

First stable release of HydroModPy, and the version described in the technical
note submitted to *Hydrology and Earth System Sciences*
([EGUsphere preprint](https://doi.org/10.5194/egusphere-2026-868)). This is the
reference cited by the paper. The `v1.0` branch stays open for `1.0.X` bug fixes
so the paper link always points to a working release, while feature development
continues on `main` as HydroModPy v2.

Install the maintained paper version with `pip install "hydromodpy==1.0.*"`,
which resolves to the latest `1.0.X` patch and never upgrades to the v2 series.

### Added
- First PyPI release published from GitHub, with MODFLOW, MODPATH and MT3D-USGS binaries bundled in the wheel.
- Release pipeline on GitHub Actions: tag/version guard, build, `twine check --strict`, PyPI Trusted Publishing (OIDC) and a GitHub release carrying the changelog notes.
- Weekly cross-platform install and example smoke tests on Linux, Windows, macOS x86 and macOS arm, for Python 3.11 to 3.13.
- Multi-version documentation served at <https://docs.hydromodpy.fr/v1.0/>, rebuilt on every push to the `v1.0` branch.

### Changed
- Repository, issues and CI moved from GitLab to GitHub.
- Documentation moved from ReadTheDocs to GitHub Pages under the `docs.hydromodpy.fr` domain.
- README leads with the pip installation path; authors, affiliations and title aligned with the preprint.
- Upper pin on `numpy` (`<2.5`) for `pysheds` compatibility, and `dask` added for multi-file xarray merges.
- Development status classifier raised to `5 - Production/Stable`.

### Fixed
- MODPATH particle flux is sampled with `rasterio` instead of `whitebox`.
- Interactive matplotlib backend detected through `backend_registry`.
- Watershed object is rebuilt when the stored pickle cannot be read.
- Transport and PyHELP examples run headless, without user interaction.

### Removed
- GitLab CI pipeline and ReadTheDocs configuration.

---

## [v0.3.5] - 2026-01-28
### Changed
- Pinned pandas to `<3.0` across pip/conda install files and docs to avoid breaking changes from pandas 3.0.

---

## [v0.3.4] - 2026-01-04
### Added
- Added `install/requirements-docker-light.txt` for pip-only Docker/server installs without IDE or visualization dependencies.
- Added optional Dask handling in SIM2 (chunked xarray only when Dask is available).

### Changed
- HydroModPy now loads display modules only when display features are invoked.
- Dockerfile updated for a light production flow using pip requirements.

### Fixed
- Improved PROJ database detection and fallback (including rasterio data dirs) to reduce `proj.db` layout errors in containers.

---

## [v0.3.3] - 2025-12-03
### Added
- Lightweight conda environment option (`env_hydromodpy_light.yml`) and matching light dependency set in `pyproject.toml` for setups without VTK or Jupyter kernels.

### Changed
- Replaced the former `downslope` helper with `masstransfer` as the single surface routing engine.
- Standardized raster reads on `imageio.v2` and removed deprecation warnings.
- Refactored SIM2 processing for leaner memory use.
- Simplified vedo imports in visualization routines and centralized PyHELP imports inside `watershed_root`.
- HELP3O loading now retries/resolves paths more reliably during PyHELP runs.
- Replace 'imageio' by 'rasterio' to resolve deprecation.

### Fixed
- Pandas warnings in PyHELP CSV ingestion and daily output aggregation (removed deprecated args and axis-based groupby).
- Multiprocessing pools in PyHELP now use a spawn context to avoid fork-in-multithreaded warnings on Python 3.11-3.13.

### Removed
- `hydromodpy.modeling.downslope` module (functionality consolidated into `masstransfer`).

---

## [v0.3.2] - 2025-11-28
### Changed
- Reworked SIM2 workflow: coarse clip without reprojection to trim inputs, resample on that reduced dataset, then final clip/mask with reprojection for clean outputs without wasted time or RAM.
- `disk_clip` now accepts `.shp`, `.gpkg`, and `.geojson`, and SIM2 filename parsing keeps the full variable name before `_SIM2_`.

### Fixed
- `toolbox.load_to_xarray` reprojects when `dst_crs` is provided even without a mask, matching the new SIM2 flow and avoiding extra memory use.
- SIM2 resampling preserves encodings and applies masking with the reprojected DEM consistently.

---

## [v0.3.1] - 2025-11-14
### Changed
- Installation guide reorganized with ready-made command recipes, dual YAML options (runtime vs editable), and clearer guidance for conda-versus-pip setups.
- README now flags v0.3.1 as the stable release and the conda YAMLs pin Python 3.11-3.13 explicitly.
- Add spyder package to the conda environment for users of that IDE.

### Fixed
- `pyproject.toml` now lets setuptools auto-discover all `hydromodpy*` packages so `pip install hydromodpy` (and ReadTheDocs builds) no longer fail if optional submodules such as `hydromodpy.modeling.gr4j` are absent from the current branch.
- Pinned NumPy to >= 2.0 and restricted supported Python to >= 3.11, < 3.14 to avoid incompatibilities with other packages.

---

## [v0.3.0] - 2025-11-06
### Compatibility
- Runtime baseline jumps from Python 3.8.10 to the Python 3.11-3.13 series. Tested on Linux, macOS, and Windows.

### Added
- Logging system with `LogManager` class (replaces all `print()` statements).
- GitHub Actions pipeline for automated builds and PyPI publication.
- Single cross-platform conda environment file (`environment-conda.yml`) for Linux, macOS, and Windows.
- Automatic download of HELP3O binaries on first use (no Fortran compiler needed).
- `MANIFEST.in` for packaging executables, examples, and documentation.
- Pin `PROJ_DATA` and `PROJ_LIB` to the active pyproj data folder to avoid stale `proj.db` files.
- Override external `PROJ_DATA` paths that leave the environment or miss `proj.db` so the environment copy always loads (problem often caused by gdal).
- `pyhelp` CLI now exports `PYHELP_WORKDIR` and `help_example.py --workdir` to stop the Windows crash on Example 10.

### Changed
- Renamed package from `src` to `hydromodpy` following standard Python conventions.
- Replaced GDAL with rasterio for pip-only installation (tested with Python 3.13).
- First version available via `pip install hydromodpy`.
- Conda installation now fully automatic with single environment file (with only conda-forge channels, no pip dependencies).
- Updated all imports in examples (00-11) from `src` to `hydromodpy`.
- PyHELP now downloads pre-compiled binaries instead of requiring Fortran compilation.
- Logging supports three modes: "dev" (DEBUG), "verbose" (INFO), "quiet" (WARNING).
- Replaced deepdish with pickle for serialization.

### Removed
- Platform-specific environment files (`env_pyhelp-0.1_windows.yml`, `environment-crossplatform-3119.yml`).
- Fortran compilation requirements for PyHELP.
- Unused FTP-AQUIFER utility scripts.
- Hard-coded GDAL dependencies.
- Removed obsolete third-party packages (e.g., hydroeval, deepdish) to ensure compatibility with Python 3.11+.

### Fixed
- Normalized example folder names.
- Cross-platform file path handling.
- Suppressed verbose logging from third-party libraries (matplotlib, flopy, etc.).
- PROJ data synchronization in PyHELP NetCDF writer.
- macOS HELP3O binary extraction.

---

## [v0.2.0] - 2025-11-05
### Added
- Added MT3D-USGS support with new `Mt3dms`, `Masstransfer`, and `watershed.transport` modules, included Example 09, and provided executables for Linux, macOS, and Windows.
- Added the GR4J rainfall-runoff calibration toolbox with scripts, figures, and sample data under `src/modeling/gr4j`.
- Added the PyHELP land-surface coupling (API, CLI, preprocessing) together with Example 10 resources and a Windows-only environment file.
- Added Example 11 to run the full workflow from scratch without plots.
- Added the `test/01_test_non-regression` suite and reference outputs for regression testing.
- Added yearly intermittency plus MT3D seepage concentration and accumulated mass to the timeseries exports.
- Added platform-specific conda environment files for HydroModPy 0.1.

### Changed
- Updated `modflow.py` to support elevation-driven decay parameters, optional EVT extinction depth, and creation of the LMT link file when using MT3DMS.
- Updated the hydraulic configuration so it keeps the new decay settings and `exdp` value.
- Updated `modpath.py` particle seeding to center start points, respect `model_folder`, and align forward and backward runs.
- Expanded the `watershed_root` workflow with transport functions, a calibration results folder, MT3DMS helper modules, and the PyHELP preprocessing function.
- Improved `timeseries` handling so recharge and runoff accept scalars, series, or dicts while exposing the new MT3D metrics.
- Updated geographic and hydrography helpers to fall back on existing DEM rasters and clip optional stream inputs.

### Fixed
- SIM2 climate ingestion now uses the current Météo-France variable names and units and exposes the soil drought index.
- Watershed visualizations restore the DEM color bar, scale bar, and labeled watershed overlay.
---

## [v0.1.0] - 2025-10-31
### Added
- **First official release** of the HydroModPy package.
- Established the initial project structure for hydrological/hydrogeological modeling workflows.
- Defined the versioning convention following **Semantic Versioning (vX.Y.Z)**.

---

[Unreleased]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0...dev
[v2.0.0]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0a5...v2.0.0
[v2.0.0a5]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0a4...v2.0.0a5
[v2.0.0a4]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0a3...v2.0.0a4
[v2.0.0a3]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0a2...v2.0.0a3
[v2.0.0a2]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0a1...v2.0.0a2
[v2.0.0a1]: https://github.com/HydroModPy/HydroModPy/compare/v1.0.0...v2.0.0a1
[v1.0.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.5...v1.0.0
[v0.3.5]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.4...v0.3.5
[v0.3.4]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.3...v0.3.4
[v0.3.3]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.2...v0.3.3
[v0.3.2]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.1...v0.3.2
[v0.3.1]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.0...v0.3.1
[v0.3.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.2.0...v0.3.0
[v0.2.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.1.0...v0.2.0
[v0.1.0]: https://github.com/HydroModPy/HydroModPy/releases/tag/v0.1.0
