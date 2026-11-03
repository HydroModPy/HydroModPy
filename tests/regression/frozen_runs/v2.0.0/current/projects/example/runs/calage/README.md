# calage

Run `calage` of project `example`, sim_id `5e9559c0-d954-4ba2-84a4-3bcc0a2629a2`, attempt 1, status **completed**.

## Site

No site declared.

## Period

2000-01-01 to 2001-01-01, 1 day.

## Version

- HydroModPy 2.0.0rc1, solver `modflow_nwt`, mesh engine `regular`
- code reproducible: unknown
- configuration hash: `638c10dec44fbb06e6f77376e2772d3332b06bcbea02f2c29a45e8a3782e6087`

## Checks

- water budget 0.06 % (no threshold declared)
- converged: yes
- promoted by session `15ed6e9bfc5e44558cf3537f3faa6f33` (phase k_grid, trial 2, session completed)
- its search exhausted its plan (every grid point solved), converged

## Label

**calibrated** under rules 2.
- promoted by session 15ed6e9bfc5e44558cf3537f3faa6f33, completed

## Score

No window declared: no score.

## Lineage

- promoted of `sessions/calage`
- session `15ed6e9bfc5e44558cf3537f3faa6f33`, phase k_grid, trial 2

## Where is what

- `config.toml`: what the run was given, replayable; `config.resolved.toml`: the same with every default
- `manifest.json`: the seal; `provenance.json`: the environment; `inputs.json`: the inputs
- `tables.parquet/`: tables (pyarrow); `fields.zarr/`: fields (zarr)
- `figures/`, `exports/`, `report/`: derived, each with its ledger; `logs/`: diagnostics

---
sha256(manifest.json) = 13cb1b26b836688c67bffb268faad524c121dfd4ae9a0849e1511c0616caf789
