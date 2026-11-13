# tri

Run `tri` of project `project`, sim_id `c824d709-5928-4b87-9ccb-5e7850a40259`, attempt 1, status **completed**.

## Site

- `island`
- fingerprint `03e3fd0b3f288d43`

## Period

2003-01-01 to 2003-04-01, 3 month.

## Version

- HydroModPy 2.0.0, solver `modflow6`, mesh engine `triangle`
- code reproducible: no
- solution key: `75223fe505f7264ae0106928d9a0425bf635491e5fa97559e0f6c1d94bfa3f87`

## Checks

- water budget 0.00105824 % (no threshold declared)
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

A replay of this run computes 11 steps in 1.4 s, 0.0 s of it in the solve, and needs up to 504 MiB of memory.
The times come from `profile.json`, measured on the machine that ran it.

## Where is what

- `config.toml`: what the run was given, replayable; `config.resolved.toml`: the same with every default
- `manifest.json`: the seal; `provenance.json`: the environment; `inputs.json`: the inputs
- `tables.parquet/`: tables (pyarrow); `fields.zarr/`: fields (zarr)
- `figures/`, `exports/`, `report/`: derived, each with its ledger; `logs/`: diagnostics

---
sha256(manifest.json) = 43487aa30d2b0d63542a1a25c8815a6a6bef4887e51ca005e7f4709d91109354
