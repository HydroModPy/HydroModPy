# `hydromodpy/analysis`

Readings across sealed runs. `analysis` compares runs of one site that already
finished. It runs no simulation, reads no comparison TOML and implements no
physics. This file is the map of the package.

## Parts

| part | answers |
|---|---|
| `comparison/compare.py` | how sealed runs of one site are compared: `hmp report compare` and `hmp.compare` |
| `comparison/pairwise.py` | `hmp.compare_pair`: two rows of the project index side by side |
| `config.py` | the retired `[analysis]` section: the loader refuses it and names what replaces it |

## How a command reaches it

`hmp report compare <ref>... [--by site] [--variables] [--out]` calls
`compare_references` or `compare_by_site`. A run is opened from its sealed
directory and read through the public `Run` API, so a comparison never opens the
project index and never writes into a run. `pairwise.py` is the one exception:
`compare_pair` reads the index.

## Import rules

Outside the package, `analysis` imports only `core`, `schema`, `physics`,
`data`, `results` and `display` (`tests/unit/architecture/layer_matrix.yaml`).
`calibration`, `solver` and `reporting` are not imported.

`analysis` is imported by `config` (the refusal of `[analysis]`), `cli` and the
root facade (`hmp.compare`, `hmp.compare_pair`). The package has no layout file
of its own.

## Where to add what

A new table is one function in `comparison/compare.py`, one line in `compare`
and one test in `tests/unit/analysis/comparison/test_compare.py`. Nothing is
computed here that `Run` can answer, and no unit is converted.
