# Capability Gallery Source Artifacts

This directory contains selected, versionable outputs copied from heavier
runtime folders. It is intentionally not a replacement for
`results_simulations/`: only stable documentation assets should live here.

Current sources:

- `launcher_simulation/modflow6_gmsh_mesh_catchment/`: selected figures from
  the end-to-end `MODFLOW 6 + Gmsh + GWT` launcher example.

To refresh one launcher-backed case, rerun its TOML. When its
`[capability_gallery]` section is enabled, the launcher republishes the selected
figures and `manifest.json` here.
