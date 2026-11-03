# calage

Run `calage` of project `example`, sim_id `83dee61c-53b9-4f5e-b68d-51e0b2181c75`, attempt 1, status **completed**.

## Site

No site declared.

## Period

2000-01-01 to 2001-01-01, 1 day.

## Version

- HydroModPy 2.0.0a5, solver `modflow_nwt`, mesh engine `regular`
- code reproducible: no
- configuration hash: `a0312e207d72d5a8bf773ff48a28a306d0556e2a23e8c9385f501491a568d56d`

## Checks

- water budget 0.06 % (no threshold declared)
- converged: yes
- promoted by session `1c17c2c39cc54263a6aa64a447d7233e` (phase k_grid, trial 2, session completed)
- its search exhausted its plan (every grid point solved), converged

## Label

**calibrated** under rules 2.
- promoted by session 1c17c2c39cc54263a6aa64a447d7233e, completed

## Score

No window declared: no score.

## Lineage

- promoted of `sessions/calage`
- session `1c17c2c39cc54263a6aa64a447d7233e`, phase k_grid, trial 2

## Where is what

- `config.toml`: what the run was given, replayable; `config.resolved.toml`: the same with every default
- `manifest.json`: the seal; `provenance.json`: the environment; `inputs.json`: the inputs
- `tables.parquet/`: tables (pyarrow); `fields.zarr/`: fields (zarr)
- `figures/`, `exports/`, `report/`: derived, each with its ledger; `logs/`: diagnostics

---
sha256(manifest.json) = 04338142b39fef7d7bc2937c5190f0ddf32f5ea62be693d9f98bd844869ecd53
