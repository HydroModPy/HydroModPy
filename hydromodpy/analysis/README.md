# `hydromodpy/analysis`

Readings across sealed runs. `analysis` compares runs of one site that already
finished. It runs no simulation, reads no comparison TOML, never opens the
project index and implements no physics. This file is the map of the package.

## Parts

| part | answers |
|---|---|
| `compare.py` | how sealed runs of one site are compared: `hmp report compare` and `hmp.compare` |

The two runs of `hmp.compare_pair` are read from the index, so that function
lives in `results/catalog/facade.py` beside `Catalog.diff`.

## How a command reaches it

`hmp report compare <ref>... [--by site] [--variables] [--to]` calls
`compare_references` or `compare_by_site`. A run is opened from its sealed
directory and read through the public `Run` API, so a comparison never opens the
project index and never writes into a run. The default output folder is chosen
by the command (`compare_folder` in `cli/commands/report.py`).

## Import rules

Outside the package, `analysis` imports only `core`, `results` and `display`
(`tests/unit/architecture/layer_matrix.yaml`). The package has no layout file
of its own.

`analysis` is imported by `cli` and the root facade (`hmp.compare`).

## Where to add what

A new table is one function in `compare.py`, one line in `compare` and one test
in `tests/unit/analysis/test_compare.py`. Nothing is computed here that `Run`
can answer, and no unit is converted.
