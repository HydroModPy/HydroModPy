# `launcher_simulation` configs

- `config_common.toml` contains the cross-solver and cross-tier settings shared
  by all launcher regression variants.
- `config_fast_common.toml` and `config_extensive_common.toml` specialize the
  common base for the fast and extensive tiers.
- `config_fast_nwt.toml` is the reduced NWT / MODPATH / MT3DMS regression
  variant.
- `config_fast_mf6.toml` is the reduced MODFLOW 6 / GWT regression variant.
- `run_fast_boussinesq_mesh_input.toml` is the reduced pure-flow Boussinesq
  example that reuses one precomputed catchment mesh through `[mesh_input]`.
- To generate a fresh commented mesh section from the schema instead of copying
  an example, use: `python -m launchers mesh-catchment template`
- `config_extensive_nwt.toml` is the canonical default launcher config for
  example12. It keeps the historical long-run NWT / MT3DMS baseline behavior.
- `config_extensive_mf6.toml` is the long-run MODFLOW 6 / GWT counterpart of
  the canonical baseline.
- Historical aliases have been removed. Update external scripts to the
  canonical names directly: `config_fast_nwt.toml`, `config_fast_mf6.toml`,
  `config_extensive_nwt.toml`, or `config_extensive_mf6.toml`.
- `config_standard.toml` remains intentionally removed. Update external scripts
  to `config_extensive_nwt.toml` instead of keeping a silent alias.
