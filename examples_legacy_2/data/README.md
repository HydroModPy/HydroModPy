# examples_legacy_2/data

This directory is intentionally empty. It exists only so the HydroModPy
workspace resolver recognises `examples_legacy_2/` as a workspace root
via its scaffold heuristic (`<workspace>/projects/<name>/project.toml`
with a sibling `data/` directory).

The actual input files for the legacy examples live in
[`../../examples/data/`](../../examples/data/). TOML configurations under
`examples_legacy_2/projects/` reference that location via
`../../../examples/data/...`.
