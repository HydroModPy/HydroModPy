# calage

Run `calage` of project `example`, sim_id `eab9575d-5f50-476e-953a-26a85ad30cfe`, attempt 1, status **completed**.

## Site

No site declared.

## Period

2000-01-01 to 2001-01-01, 1 day.

## Version

- HydroModPy 2.0.0, solver `modflow_nwt`, mesh engine `regular`
- code reproducible: no
- solution key: `none`

## Checks

- water budget 0.0643926 % (no threshold declared)
- converged: yes
- promoted by session `2473cfc06b9943a1b59b0c180ac9db26` (phase k_grid, trial 2, session completed)
- its search exhausted its plan (every grid point solved), converged

## Label

**calibrated** under rules 3.
- promoted by session 2473cfc06b9943a1b59b0c180ac9db26, completed

## Score

No window declared: no score.

## Lineage

- promoted of `sessions/calage`
- session `2473cfc06b9943a1b59b0c180ac9db26`, phase k_grid, trial 2

## What this run does not give

- A change in time: the run is one steady state.
- The flow between two cells. Set `keep_face_flows = true` under `[simulation.results]` to keep it.
- A residence time: the run has no particle tracking.

## Cost of a replay

A replay of this run computes 5 steps in 1.8 s, 0.0 s of it in the solve, and needs up to 443 MiB of memory.
The times come from `profile.json`, measured on the machine that ran it.

## Where is what

- `config.toml`: what the run was given, replayable; `config.resolved.toml`: the same with every default
- `manifest.json`: the seal; `provenance.json`: the environment; `inputs.json`: the inputs
- `tables.parquet/`: tables (pyarrow); `fields.zarr/`: fields (zarr)
- `figures/`, `exports/`, `report/`: derived, each with its ledger; `logs/`: diagnostics

---
sha256(manifest.json) = 71f98652a1bcd93fc5ed028054ff4eed476c1a7c219e380c25a04cafe46f1c54
