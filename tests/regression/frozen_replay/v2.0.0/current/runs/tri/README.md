# tri

Run `tri` of project `project`, sim_id `c6429802-16ad-4c1e-9152-79d395f817c3`, attempt 1, status **completed**.

## Site

- `island`
- fingerprint `03e3fd0b3f288d43`

## Period

2003-01-01 to 2003-04-01, 3 month.

## Version

- HydroModPy 2.0.0, solver `modflow6`, mesh engine `triangle`
- code reproducible: unknown
- solution key: `8ffa7c94abf4117ff270d3c216abc0495c7ff51bf448a99379dddb2d3f4f8fd1`

## Checks

- water budget 0 % (no threshold declared)
- converged: unknown

## Label

**exploratory** under rules 3.
- no score window

## Score

No window declared: no score.

## What this run does not give

- The state inside a stress period: fields are stored once per period, at its end.
- The flow between two cells. Set `keep_face_flows = true` under `[simulation.results]` to keep it.
- A residence time: the run has no particle tracking.

## Cost of a replay

A replay of this run computes 11 steps in 4.6 s, 0.1 s of it in the solve, and needs up to 483 MiB of memory.
The times come from `profile.json`, measured on the machine that ran it.

## Where is what

- `config.toml`: what the run was given, replayable; `config.resolved.toml`: the same with every default
- `manifest.json`: the seal; `provenance.json`: the environment; `inputs.json`: the inputs
- `tables.parquet/`: tables (pyarrow); `fields.zarr/`: fields (zarr)
- `figures/`, `exports/`, `report/`: derived, each with its ledger; `logs/`: diagnostics

---
sha256(manifest.json) = ed7827635d147f3f52c7b6d85e1ce0f4b86e861515a610462afad0fe100d02b5
