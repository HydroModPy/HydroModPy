# results/run

This folder answers how one finished simulation, or a set of them, is read back. `Run` is one run directory.
`RunSet` is a view over several runs. The rows of a run (series, budgets, parameters) come from its own Parquet
files and its arrays from its own Zarr store. The index is only used to find the run.

## How the work flows

1. `Catalog` resolves a reference and hands back a `Run`. A run still being computed is opened on its `RunStore`,
   and a sealed directory is opened with `open_run_dir`.
2. `Run` (`view.py`) loads the row that describes the run on first use, from the index or from the facts of the
   directory.
3. Its tabular reads go to `tables.py`, which reads the Parquet tables of the directory (`read_run_table`).
4. Its mixins add the rest. `geographic.py` serves features, rasters, grid, mesh and field reads. `timeseries.py`
   serves parameters, metrics, budgets, series and the time index. `hydrographic.py` serves the network roles.
5. Providers hang on the run. `run.array` is the xarray reader, `run.probe` reads one place, `run.periods` places
   the stress periods on the calendar and `run.descent` gives the routing descent, with the open water, the
   outline cells and the mean recharge the stream criterion read. `read_basin` and `basin_of_group` return the
   stored basin as a `StoredBasin`, for the run views and the catchment aggregation alike.
6. `sealed.py` reads what the seal says about the run, such as its lineage, inputs, label and metrics.
7. `RunSet` (`group.py`) ranks and compares runs, using `ranking.py` and the facts of `sealed_facts.py`.

## The folder map

```text
run/
├── view.py             Run, open_run_dir
├── group.py            RunSet, rank_key
├── tables.py           Parquet tables of one run
├── sealed.py           record, lineage, inputs, metrics read from the seal
├── sealed_facts.py     facts of a seal in the shape a table reads
├── ranking.py          rank_rows, unscored_reason
├── geographic.py       geographic and mesh reads
├── timeseries.py       tabular and time-aligned reads
├── hydrographic.py     hydrographic network roles
├── array.py            RunArrayProvider, xarray reads
├── point.py            one cell, one variable, one series
├── periods.py          stress periods on the calendar
├── descent.py          the routing descent of a run, and the criterion inputs kept beside it
├── particles.py        particle pathlines
├── mesh_families.py    line families of the mesh
├── observation_points.py  declared points sampled and kept on disk
├── sfr.py              links between SFR reaches
├── field_envelope.py   min and max per cell of an earlier run
├── lake_abacus_view.py persisted lake abacus
├── contracts.py        typed returns: Mesh, RasterField, Stack
└── environment.py      host environment snapshot
```

## Where to add what

| To add | Where |
|--------|-------|
| a `Run` accessor | a provider in this folder, bound in `view.py` |
| a tabular read | `timeseries.py`, on top of `tables.py` |
| a geographic or mesh read | `geographic.py` |
| something the seal states | `sealed.py` |
| a column of a table of runs | `sealed_facts.py` |
| a way of ranking runs | `ranking.py` and `rank_key` in `group.py` |
| a typed return for a field or a mesh | `contracts.py` |
