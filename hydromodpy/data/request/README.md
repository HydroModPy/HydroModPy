# data/request

This folder answers one question: give me these data for this place, without a project. The place
is a box with its CRS, a vector mask or a list of station codes. The answer is a folder of files.
`hmp data get` and the `data-request` process both call it.

## What a request does

1. `model.py` reads the request, a JSON document. It holds the `[data]` sections with the models of
   the TOML, an extent that is exactly one of a box, a mask or station codes, an optional period,
   and plugin sources under `installed`.
2. `engine.py` (`run_request`) loads each section through its manager over the extent, written as a
   polygon mask in the CRS of the manager. `hydrography` and the installed sources go through the
   source registry. A source that fails loses its files and is listed with its error. The others
   keep theirs. An empty answer, a box at sea for example, is a success marked `"empty": true`.
3. `artefacts.py` cuts each answer to the extent and the period, whatever the cache held, and writes
   one file per variable and source: chronicles in one Parquet table, grids in one NetCDF, rasters
   in GeoTIFF, vectors in one GeoPackage layer, tables in Parquet.
4. `job.py` is the `data-request` process. It resolves and refuses before anything is written, uses
   a cache under `$TMPDIR` indexed in memory, writes the seal, and reuses an earlier answer when the
   request is the same.

## The folder map

```text
request/
├── model.py      DataRequest
├── engine.py     run_request and its RequestReport
├── artefacts.py  the files written for an answer
└── job.py        the data-request declaration and its body
```

## Rules

- A `custom` source is refused. A request has no project folder to read it from.
- A failed variable fails the job. The report of `run_request` lists it instead.
- Nothing is written to a project. A request uses its own cache.

## Changing the code

The tests are `tests/unit/data/test_a_request_is_served_without_a_project.py` and
`tests/unit/data/test_data_request_declaration.py`.
