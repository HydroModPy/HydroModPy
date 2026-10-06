# `hydromodpy/analysis`

Workflows that work across runs. `analysis` compares simulations that share a
case, runs a matrix of controlled variants of a method, and publishes selected
figures of a run to a gallery folder. It runs on finished runs and on child
TOML files it writes itself; it implements no physics. The HTML pages built on
top of a comparison live in `hydromodpy/reporting`. This file is the map of the
package: its parts, how a workflow reaches it, the import rules and where to add
what.

## Parts

| part | answers |
|---|---|
| `comparison/` | how are two or more simulations compared? It writes the child simulations of an experiment, runs them in subprocesses, extracts the observables, computes the differences and the stability checks, and renders the maps and series |
| `testbed/` | how is a method tested on a matrix of controlled cases? It expands cases into self-contained child TOML files, delegates them to the existing runners, and writes the evidence (plan, cases, metrics). `testbed/README.md` is its map |
| `testbed/regional_lab*.py` | the `regional_lab` profile of the testbed: site selection, recipes, coverage and status of a multi-site campaign |
| `catalog.py` | how is a campaign catalog read? Common primitives for CSV and JSONL catalogs (`SUPPORTED_CATALOG_FORMATS`, value normalisers) |
| `capability_gallery.py` | how are figures of a run published to a documentation gallery source folder? It renders each figure through a callback given by a higher layer, or copies the PNG from the run, and lists what is missing in a manifest |
| `config.py` | what does the `[analysis]` section hold? `AnalysisConfig` |
| `config_helpers.py` | shared parsing helpers of the raw TOML of these workflows |

### `comparison/`

| module | answers |
|---|---|
| `dispatch.py` | which launcher serves this comparison TOML? It requires `[comparison]` with `[[comparison.simulation]]` |
| `experiment_config.py` | the user-facing schema of `[comparison]` (`ComparisonSection`) |
| `experiment_launcher.py` | `SimulationComparisonLauncher`: the orchestration of one comparison |
| `child_materialization.py`, `run_backend.py` | how the child simulations are written and run (`hmp run` in a subprocess) |
| `config.py`, `runtime/` | the post-resolution view of a comparison, read by the analysis code |
| `output_pipeline.py` | the neutral sequence after the runs are resolved: observables, metrics, exports, visuals |
| `pairwise.py`, `metric_diff.py` | differences between runs, through a DuckDB SQL pivot and metric by metric |
| `stability.py`, `numerical_closure.py` | the stability checks and the water-budget closure of each run |
| `exports/` | what a comparison writes: time series, budget, figures, network metrics |
| `visuals*.py` | maps and series of a comparison |
| `audit/` | the audit of a comparison |
| `reporting.py` | the human-readable summary of a comparison run |

## How a workflow reaches it

`[workflow].mode` selects the launcher. `project/dispatch/workflow.py` holds the
table (`DISPATCH`), and `hmp run` and `hmp.run` both go through it.

- `comparison`: `run_comparison` calls `analysis.comparison.dispatch.run_comparison_config`.
  The launcher reads `[comparison]` from the raw TOML, with its `base_config`
  chain.
- `testbed`: `run_testbed` reads `[testbed].profile` with
  `testbed.profiles.resolve_testbed_profile`. The value is `generic` (default)
  or `regional_lab`; any other value is refused. `generic` runs
  `TestbedLauncher` (`testbed/runtime.py`); `regional_lab` runs
  `RegionalLabProfileLauncher` (`testbed/regional_lab.py`).
- The capability gallery has no mode of its own: it is the `[analysis.capability_gallery]`
  block, applied by the export step of the workflow.

`[testbed]` is a root section of `HydroModPyConfig`. `[analysis]` is a separate
hub with three optional blocks: `batch` (the regional-lab settings),
`capability_gallery` and `comparison`.

A generated child is an ordinary project file, run with `[workflow].mode` set to
`simulation`, `comparison` or `calibration`. It never contains `[testbed]`.

## Import rules

Outside the package, `analysis` imports only `core`, `schema`, `physics`, `data`,
`results` and `display` (`tests/unit/architecture/layer_matrix.yaml`). One
tolerance: `analysis` imports `reporting` because
`comparison/experiment_launcher.py` writes the final HTML report
(`write_comparison_web_report`). It must not expand. `calibration` and `solver`
are not imported: a child run goes through `hmp run`, not through a Python call
into a solver.

`analysis` is imported by `config`, `reporting`, `workflow`, `project`, `cli` and
the root facade. The package has no layout file of its own.

## Where to add what

1. **A comparison output.** A module in `comparison/exports/`, called from
   `comparison/output_pipeline.py`.
2. **A comparison metric or check.** `comparison/metric_diff.py` for a
   difference, `comparison/stability.py` for a check on one run.
3. **A testbed subject or runner pair.** The workflow adapters are registered
   in `testbed/contracts.py`; the supported pairs are listed in `testbed/README.md`.
4. **A testbed profile.** A name in `testbed/profiles.py` and a launcher that
   `project/dispatch/workflow.py:run_testbed` routes to.
5. **A field of a section.** The model of the section, with a profile and a
   description. The parameter reference is computed from the model at the next
   documentation build (`tools/docs/field_registry.py`).

## Reading path

1. `analysis/__init__.py`: the two lazy sub-modules.
2. `project/dispatch/workflow.py`: the mode to launcher table.
3. `comparison/dispatch.py`, then `comparison/experiment_launcher.py`.
4. `testbed/README.md`, then `testbed/runtime.py`.
5. `testbed/regional_lab.py` for the regional profile.
