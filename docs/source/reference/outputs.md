# Outputs of a run

A run stores its field arrays in `fields.zarr` and its station series in `tables.parquet/timeseries.parquet`. Both lists below are read from the field registry of the code. A name added to the registry shows up here at the next build.

## Field arrays

Each group is the first folder of the path in the store. The fields under `budget/` follow one sign rule, set in the registry.

```{hmp-outputs} fields
```

## Time series

Each series is one variable of the station table. It holds one value per time step of one station.

```{hmp-outputs} series
```
