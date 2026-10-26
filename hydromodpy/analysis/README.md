# `hydromodpy/analysis`

Readings across sealed runs. `analysis` compares N runs of one case that
already finished: it reads their directories, extracts the observables,
computes the differences and the water-budget closure,
and draws the maps and the series. It runs no simulation, reads no comparison
TOML and implements no physics. The HTML page is rendered on top of its output
by `hydromodpy/reporting/comparison`. This file is the map of the package: its
parts, how a command reaches it, the import rules and where to add what.

## Parts

| part | answers |
|---|---|
| `comparison/` | how are N sealed runs of one case compared? |
| `config.py` | the retired `[analysis]` section: the loader refuses it and names what replaces it |

### `comparison/`

| module | answers |
|---|---|
| `runs.py` | which runs a reference names (a run directory, a run name, a recipe), and whether they are one case: same `site_fingerprint` and `mesh_hash` in their manifests (`case_check`) |
| `config.py` | `ComparisonSpec`: the runs, the observables and the shared raster of one comparison, built from the runs, never from a TOML |
| `runtime/` | how one sealed run is read: `run_source.py` (`RunSource` over `fields.zarr`, `tables.parquet/`, `config.toml`), `mesh.py`, `series.py`, `observables.py` |
| `run_comparison.py` | `run_comparison`: one comparison folder, closed by `comparison_manifest.json`, its only writer and reader |
| `output_pipeline.py` | the sequence after the observables are extracted: metrics, exports, closure, figures, markdown report |
| `pairwise.py`, `metric_diff.py` | differences between runs: an index pivot of two runs' metrics, and the observable differences to the reference |
| `numerical_closure.py` | the water-budget closure of each run |
| `exports/` | what a comparison writes: series, budget, network metrics, obstacle diagnostics, execution summary |
| `visuals*.py` | maps and series of a comparison |
| `reporting.py` | the markdown summary of a comparison |

## How a command reaches it

`hmp report compare <ref>... [--by site] [--variables] [--out] [--allow-different-mesh] [--budget-zone]`
calls `reporting.comparison.compare.compare_runs`. It resolves the references
and groups the runs with `comparison/runs.py`, runs `run_comparison` once per
group, then renders the page. A run directory is read alone: a comparison
never opens the project index for the fields, the tables or the seal, and
never writes into a run. The network metrics read a run through `Run`, opened
from its sealed directory (`open_run`, through `hmp.open`); without a
index they are skipped with the reason written beside them.

## Import rules

Outside the package, `analysis` imports only `core`, `schema`, `physics`,
`data`, `results` and `display` (`tests/unit/architecture/layer_matrix.yaml`).
It never imports `reporting`: the page is built by `reporting`, which imports
`analysis`. `calibration` and `solver` are not imported.

`analysis` is imported by `config` (the refusal of `[analysis]`), `reporting`,
`cli` and the root facade (`hmp.compare_pair`). The package has no layout file
of its own.

## Where to add what

1. **A comparison output.** A module in `comparison/exports/`, called from
   `comparison/output_pipeline.py`.
2. **A comparison metric.** `comparison/metric_diff.py` for a difference.
3. **A default observable.** `comparison_observables` in `comparison/runs.py`.
4. **A datum read from a run.** `comparison/runtime/run_source.py`, from the
   run directory only.

## Reading path

1. `reporting/comparison/compare.py`: the command.
2. `comparison/runs.py`, then `comparison/run_comparison.py`.
3. `comparison/runtime/run_source.py`, then `comparison/output_pipeline.py`.
