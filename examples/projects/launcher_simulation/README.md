# `launcher_simulation` configs

- `config_common.toml` contains the cross-solver and cross-tier settings shared
  by all launcher regression variants.
- `config_fast_common.toml` and `config_extensive_common.toml` specialize the
  common base for the fast and extensive tiers.
- `config_fast_nwt.toml` is the reduced NWT / MODPATH / MT3DMS regression
  variant.
- `config_fast_mf6.toml` is the reduced MODFLOW 6 / GWT regression variant.
- `run_fast_boussinesq_mesh_input.toml` is the reduced pure-flow Boussinesq
  example kept for the fast tier; despite its historical name, it still
  rebuilds the catchment mesh through the embedded `[mesh_catchment]` profile.
- `run_fast_mf6_mesh_catchment.toml` is the matching end-to-end MODFLOW 6 /
  GWT example using that same embedded `[mesh_catchment]` path before solving.
- `run_fast_boussinesq_petsc_mesh_input.toml` is the same reduced Boussinesq
  example but forces `runtime_backend = "petsc"` with
  `surface_interaction_model = "complementarity"`; it is intended for Linux
  environments where `petsc4py` is available.
- `run_fast_boussinesq_petsc_partition_mesh_input.toml` is the PETSc variant
  using `surface_interaction_model = "regularized_partition"`.
- `run_fast_boussinesq_precomputed_mesh_input.toml` replays the fast Boussinesq
  case on the committed triangular mesh stored under `results_stable/mesh/`,
  without remeshing.
- `run_fast_mf6_precomputed_mesh_input.toml` is the matching MODFLOW 6 / GWT
  example on that same committed triangular mesh, still through the standard
  `process_simulation` launcher.
- `run_method_comparison_mf6_vs_nwt_same_regular_mesh.toml` compares
  `modflow6` and `modflownwt` on the same regular `60x60` structured grid,
  using shared cell-index observables plus a last-step head map and an
  outlet-flux time series for visual comparison outputs.
- `run_method_comparison_mf6_vs_nwt_different_meshes.toml` compares
  `modflow6` on the committed triangular mesh against `modflownwt` on the
  regular `60x60` structured grid, using map observables that still feed the
  side-by-side visual comparison even when scalar metrics stay domain-reduced.
- `config_demonstrative_annual_common.toml` is a stronger one-year flow-only
  example12 base with lower `K`, lower `Sy`, stronger recharge seasonality,
  and more permissive drainage to produce clearer head and overflow contrasts.
- `run_demonstrative_annual_mf6_precomputed_mesh_input.toml` and
  `run_demonstrative_annual_nwt.toml` are the matching MF6 and NWT variants of
  that demonstrative annual case.
- `run_method_comparison_mf6_vs_nwt_different_meshes_demonstrative.toml`
  compares that demonstrative annual case across the committed triangular MF6
  mesh and the regular `60x60` NWT grid, with three head chronicle points,
  outlet flux, drainage maps, and fine-raster outputs enabled.
- `method_comparison_points.toml` stores reusable XY anchors for the real-case
  method-comparison configs.
- `run_method_comparison_example12_fast_shared_mesh.toml` compares the real
  `example12_fast` forcing chain between `modflow6` and `boussinesq` on the
  same committed triangular mesh.
- `run_method_comparison_example12_extensive_mf6_vs_nwt.toml` compares the real
  extensive `example12` baseline between `modflow6` and `modflownwt`, using
  anchor-based XY observables on the structured grid.
- `run_method_comparison_headwater_100km2_outlet_2_backends.toml` compares the
  historical real `headwater_100km2_outlet_2` basin between the SciPy sparse,
  PETSc regularized-partition, and PETSc mixed-complementarity Boussinesq
  runtimes on the same versioned gallery mesh.
- `run_headwater_100km2_outlet_2_boussinesq_transient_pulsed_recharge.toml`
  is a short transient Boussinesq replay on that same real mesh, driven by a
  pulsed synthetic recharge chronology and an explicit homogeneous `Sy`.
- `run_headwater_100km2_outlet_2_boussinesq_petsc_partition_transient_pulsed_recharge.toml`
  is the PETSc regularized-partition replay of that transient real case.
- `run_headwater_100km2_outlet_2_boussinesq_petsc_transient_pulsed_recharge.toml`
  is the PETSc mixed-complementarity replay of that transient real case.
- `run_headwater_100km2_outlet_2_boussinesq_transient_cycling_recharge.toml`
  is the drier wetting/dry-down variant on that same real mesh, tuned to
  trigger repeated threshold activation and deactivation windows.
- `run_headwater_100km2_outlet_2_boussinesq_petsc_partition_transient_cycling_recharge.toml`
  is the PETSc regularized-partition replay of that cycling real case.
- `run_headwater_100km2_outlet_2_boussinesq_petsc_transient_cycling_recharge.toml`
  is the PETSc mixed-complementarity replay of that cycling real case.
- `run_headwater_100km2_outlet_2_boussinesq_transient_cycling_recharge_heterogeneous.toml`
  keeps the same cycling chronology but adds strong generated-rings
  heterogeneity on `K` and `Sy` over the committed 100 km2 basin.
- `run_headwater_100km2_outlet_2_boussinesq_petsc_partition_transient_cycling_recharge_heterogeneous.toml`
  is the PETSc regularized-partition replay of that heterogeneous cycling case.
- `run_headwater_100km2_outlet_2_boussinesq_petsc_transient_cycling_recharge_heterogeneous.toml`
  is the PETSc mixed-complementarity replay of that heterogeneous cycling case.
- `run_headwater_100km2_outlet_2_boussinesq_transient_cycling_recharge_heterogeneous_10day.toml`
  keeps the same heterogeneous cycling case but reduces the time step to
  `10 day` for easier temporal-dynamics reading.
- `run_headwater_100km2_outlet_2_boussinesq_petsc_partition_transient_cycling_recharge_heterogeneous_10day.toml`
  and `run_headwater_100km2_outlet_2_boussinesq_petsc_transient_cycling_recharge_heterogeneous_10day.toml`
  are the PETSc regularized-partition and mixed-complementarity counterparts.
- `run_headwater_100km2_outlet_2_mf6_transient_cycling_recharge_heterogeneous_10day.toml`
  is the MODFLOW 6 counterpart of that same 10-day heterogeneous cycling case.
- The committed-mesh MF6 headwater family samples DEM surfaces from the
  versioned polygon
  `examples/mesh_gallery/100km2/mesh_headwater_100km2_outlet_2_geology_rivers_buffer30/domain_bbox.geojson`
  so the geographic support stays aligned with the reused triangular mesh.
- `run_method_comparison_headwater_100km2_outlet_2_transient_pulsed_recharge_backends.toml`
  compares the SciPy sparse and both PETSc Boussinesq backends on that
  transient real-case forcing.
- `run_method_comparison_headwater_100km2_outlet_2_transient_cycling_recharge_heterogeneous_backends.toml`
  compares the same three Boussinesq backends on the stronger heterogeneous
  cycling real case.
- `config_headwater_100km2_mf6_transient_common.toml` is the shared 3-year
  MF6 flow-only base used for the new committed-mesh 100 km2 scenario family.
- `run_headwater_100km2_outlet_2_mf6_transient_reference.toml` is the
  reference 3-year MF6 replay on that same 100 km2 mesh, with curated gallery
  publication enabled.
- `run_headwater_100km2_outlet_2_mf6_transient_forcing_extremes.toml` keeps the
  same geometry and hydraulic reference setup but stresses recharge with a
  stronger drought/rewetting sequence.
- `run_headwater_100km2_outlet_2_mf6_transient_heterogeneous_decay.toml` is the
  flagship complex case: lateral heterogeneity on generated hydrofacies plus an
  exponential depth decay on hydraulic properties.
- `run_method_comparison_headwater_100km2_outlet_2_mf6_transient_scenarios.toml`
  compares the MF6 reference and heterogeneous-decay scenarios with map and
  outlet-flux observables.
- `realistic_campaign/` contains a multi-case manifest plus a batch runner used
  to organize broader realistic studies across existing examples, regressions,
  and flagship 100 km2 scenarios.
- `regional_lab/` contains a first site-catalog-driven example for the new
  `regional_lab` launcher family, starting from the committed
  `headwater_100km2_outlet_2` real case and expanding generic recipes into
  concrete `simulation` and `method-comparison` runs.
- `run_fast_boussinesq_petsc_partition_precomputed_mesh_input.toml` is the
  Linux/PETSc regularized-partition counterpart of that exact precomputed-mesh
  replay.
- `run_headwater_100km2_outlet_2_boussinesq_mesh_input.toml` revives the
  historical real-case headwater 100 km2 outlet-2 trial on the committed mesh
  gallery bundle.
- `run_headwater_100km2_outlet_2_boussinesq_petsc_partition_mesh_input.toml`
  is the PETSc regularized-partition replay of that headwater real case.
- `run_headwater_100km2_outlet_2_boussinesq_petsc_mesh_input.toml` is the
  PETSc mixed-complementarity replay of that same headwater real case.
- To generate a fresh commented mesh section from the schema instead of copying
  an example, use: `python -m launchers mesh-catchment template`
- `config_extensive_nwt.toml` is the canonical default launcher config for
  example12. It keeps the historical long-run NWT / MT3DMS baseline behavior.
- `config_extensive_mf6.toml` is the long-run MODFLOW 6 / GWT counterpart of
  the canonical baseline.
- Runtime Gmsh meshes (`[mesh_input]` or embedded `[mesh_catchment]`) stay in
  the same launcher family. They are currently intended for `boussinesq` and
  `modflow6`; `modflownwt` remains on the structured `sgrid` backend.
- For profiling the embedded mesh path without figure/export noise, add a
  local overlay with `mesh_catchment.figures_enabled = false`,
  `mesh_catchment.export_exchange_bundle = false`,
  `geographic.reuse_existing_outputs = true`, and
  `postprocess.profile = "solver_only"`. The cache is fingerprinted and only
  reuses geographic artifacts after a first successful run in the same
  workspace.
- Historical aliases have been removed. Update external scripts to the
  canonical names directly: `config_fast_nwt.toml`, `config_fast_mf6.toml`,
  `config_extensive_nwt.toml`, or `config_extensive_mf6.toml`.
- `config_standard.toml` remains intentionally removed. Update external scripts
  to `config_extensive_nwt.toml` instead of keeping a silent alias.
