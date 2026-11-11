# tri

Run `tri` of project `project`, sim_id `1200e1f7-1120-4482-87be-22ac4692943f`, attempt 1, status **completed**.

## Site

- `island`
- fingerprint `03e3fd0b3f288d43`

## Period

2003-01-01 to 2003-04-01, 3 month.

## Version

- HydroModPy 2.1.0.dev0, solver `modflow6`, mesh engine `triangle`
- code reproducible: unknown
- solution key: `6d40155254bc46f517df93513518117c9bdb9e7d9db4e1522252003f06e6c9c2`

## Checks

- water budget 0 % (no threshold declared)
- converged: unknown

## Label

**exploratory** under rules 3.
- no score window

## Score

No window declared: no score.

## Cost of a replay

A replay of this run computes 11 steps in 1.3 s, 0.0 s of it in the solve, and needs up to 494 MiB of memory.
The times come from `profile.json`, measured on the machine that ran it.

## Where is what

- `config.toml`: what the run was given, replayable; `config.resolved.toml`: the same with every default
- `manifest.json`: the seal; `provenance.json`: the environment; `inputs.json`: the inputs
- `tables.parquet/`: tables (pyarrow); `fields.zarr/`: fields (zarr)
- `figures/`, `exports/`, `report/`: derived, each with its ledger; `logs/`: diagnostics

---
sha256(manifest.json) = 2e297c1dbe3d24ce2520d56772a39fd994a5bbbc3278e9b8a6eec67ffdd18ddf
