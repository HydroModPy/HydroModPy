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
- `run_fast_boussinesq_petsc_partition_precomputed_mesh_input.toml` is the
  Linux/PETSc regularized-partition counterpart of that exact precomputed-mesh
  replay.
- `run_headwater_100km2_outlet_2_boussinesq_mesh_input.toml` revives the
  historical real-case headwater 100 km2 outlet-2 trial on the committed mesh
  gallery bundle.
- `run_headwater_100km2_outlet_2_boussinesq_petsc_partition_mesh_input.toml`
  is the PETSc regularized-partition replay of that headwater real case.
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
