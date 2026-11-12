# calage

Run `calage` of project `island`, sim_id `20cf5504-afc9-4ae5-aeec-2b69febecc3b`, attempt 1, status **completed**.

## Site

- `island`
- fingerprint `03e3fd0b3f288d43`

## Period

2003-01-01 to 2003-01-03, 1 day.

## Version

- HydroModPy 2.0.0, solver `modflow6`, mesh engine `regular`
- code reproducible: no
- configuration hash: `b109da8fa846fa0468a2b9581ff11cc08f32ef209a85230bbfb95edec4856096`

## Checks

- water budget 0 % (no threshold declared)
- converged: yes
- promoted by session `c7972ee85eed416384eb70ff79c0c9ff` (phase k_grid, trial 3, session completed)
- its search exhausted its plan (every grid point solved), converged
- parameters on a bound: K

## Label

**calibrated** under rules 2.
- promoted by session c7972ee85eed416384eb70ff79c0c9ff, completed

## Score

No window declared: no score.

## Lineage

- promoted of `sessions/calage`
- session `c7972ee85eed416384eb70ff79c0c9ff`, phase k_grid, trial 3

## Where is what

- `config.toml`: what the run was given, replayable; `config.resolved.toml`: the same with every default
- `manifest.json`: the seal; `provenance.json`: the environment; `inputs.json`: the inputs
- `tables.parquet/`: tables (pyarrow); `fields.zarr/`: fields (zarr)
- `figures/`, `exports/`, `report/`: derived, each with its ledger; `logs/`: diagnostics

---
sha256(manifest.json) = ba0f15faa6e2c50e86f1d0c0dc5d71131c606b898fdf9cd5132ed7cd3b4f24a1
