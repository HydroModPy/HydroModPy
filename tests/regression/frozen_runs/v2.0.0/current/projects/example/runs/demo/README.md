# demo

Run `demo` of project `example`, sim_id `72bf0eb5-2be2-46ae-8734-b9488dbdc0e2`, attempt 1, status **completed**.

## Site

No site declared.

## Period

2000-01-01 to 2001-01-01, 1 year.

## Version

- HydroModPy 2.0.0, solver `modflow_nwt`, mesh engine `regular`
- code reproducible: no
- solution key: `30c3c077506de4bed08e5d3838b1f0524efe39de6879dd182fec6c3d512b44bc`

## Checks

- water budget 0.0643926 % (no threshold declared)
- converged: unknown

## Label

**exploratory** under rules 3.
- no score window

## Score

No window declared: no score.

## What this run does not give

- A change in time: the run is one steady state.
- The flow between two cells. Set `keep_face_flows = true` under `[simulation.results]` to keep it.
- A residence time: the run has no particle tracking.

## Cost of a replay

A replay of this run computes 11 steps in 2.1 s, 0.0 s of it in the solve, and needs up to 440 MiB of memory.
The times come from `profile.json`, measured on the machine that ran it.

## Where is what

- `config.toml`: what the run was given, replayable; `config.resolved.toml`: the same with every default
- `manifest.json`: the seal; `provenance.json`: the environment; `inputs.json`: the inputs
- `tables.parquet/`: tables (pyarrow); `fields.zarr/`: fields (zarr)
- `figures/`, `exports/`, `report/`: derived, each with its ledger; `logs/`: diagnostics

---
sha256(manifest.json) = e626de8ed00f7f2ea968a9cb93d2914c22ccd9c743c027810ccf1dcbd0147933
