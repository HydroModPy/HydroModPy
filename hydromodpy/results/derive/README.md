# results/derive

This folder answers what can be computed from a stored run at read time, so that it needs no storage. A derived
field is rebuilt from the stored ones each time it is asked for. Nothing here writes to the index or to the run
directory.

## How the work flows

1. A caller asks for a variable through `Run.read` or `Catalog.read`. `reading.py` is the one dispatch behind both.
   A field gives an `xarray.DataArray`, a series a `pandas.Series`, a geographic feature a `GeoDataFrame`.
2. If the name is a virtual field, `virtual_fields.py` computes it from the stored fields. Water table elevation
   and depth, seepage and release flux are of that kind.
3. `accumulation.py` routes drain and release fluxes down the descent of the run, range by range.
4. `views.py` reduces a field over the catchment or the active domain to a series (`saturated_fraction`,
   `drainage_density`, `persistence`, `catchment_mean`), and `budget_over` totals a per-cell budget term over the
   catchment or a polygon.
5. `time_alignment.py` puts observed and simulated series on the same time axis. `run_period_edges` gives the
   edges of the periods of a run and `naive_utc` gives a timestamp in UTC without a time zone.
6. `config_flags.py` tells a reader which option to switch on when a field is missing.
7. `catchment_aggregation.py` writes the discharge and well_pumping series of one run, each term from the catchment row,
   its per-cell field or the domain row. The `derive` step of the workflow calls it.
   It reads the stored basin through `basin_of_group` of `results/run/descent.py`, the one reader the run views use too.
8. `stream/` reads the stream criterion on a finished run. The kernels on arrays live in `catchment/stream_network`,
   and `stream/criterion_inputs.py` holds the inputs a trial and a redrawn figure both read. It has its own `README.md`.

## The folder map

```text
derive/
├── reading.py          read_variable, the dispatch of Run.read and Catalog.read
├── virtual_fields.py   fields computed from stored fields
├── derived.py          pure formulas for water table and flux per area
├── views.py            reductions over the catchment or the active domain
├── accumulation.py     drain and release accumulation on the descent
├── catchment_aggregation.py   catchment series from the budget of one run
├── time_alignment.py   observed and simulated series on one axis
├── downsample.py       LTTB downsampling of dense series
├── recession.py        recession cloud on the Brutsaert-Nieber plane
├── mesh_quality.py     quality of the stored mesh, one value per cell
├── config_flags.py     what a run kept of the budget, and the hint for a missing field
├── run_memo.py         per-run memo for heavy rebuilds shared by figures
└── stream/             the stream criterion read on a finished run, and its inputs
```

## Where to add what

| To add | Where |
|--------|-------|
| a computed field | a function in `virtual_fields.py` |
| a reduction over the catchment | `views.py`, or `catchment_aggregation.py` for a series of the derive step |
| a formula on stored arrays | `derived.py` |
| a rule to align two series in time | `time_alignment.py` |
| a message about a missing option | `config_flags.py` |
| a reader of the stream criterion on a run | `stream/` |
| a kernel of the stream criterion on arrays | `catchment/stream_network` |
