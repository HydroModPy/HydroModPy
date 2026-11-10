# `hydromodpy/core`

The kernel leaf. Every layer may read `core`, and `core` reads no sibling layer, not even under
`TYPE_CHECKING`. It holds what several layers need and none should own: the base of every config
model, units, workspace and path rules, runtime state, I/O primitives, the typed exceptions and a
few numerical kernels that two layers must compute the same way. The root keeps the words every
layer shares, and a sub-package answers one question and has its own README. `io/value_digest.py`
holds the rule `values/1` of the seal, one digest for a block of values whatever their dtype, with
`-0.0` read as `0.0` and one canonical NaN. Keep the package light: importing
`hydromodpy.core` loads neither the configuration nor the data stack. A helper used by one layer
stays in that layer, and moves here when a second layer needs it and the matrix forbids the edge.
The answers column below is the first line of each module or sub-package docstring.

| module | answers |
|---|---|
| `budget/` | Per-cell water budgets: the sign of each flux, the terms a field reads and the terms a store keeps. |
| `code_fingerprint.py` | The fingerprint of the code that computes: one digest per layer of the package. |
| `config_kit/` | Pydantic helpers shared by every HydroModPy configuration model. |
| `console/` | What a run shows while it works: the live progress display and its NDJSON sink. |
| `contracts/` | Neutral contracts shared across pipeline layers. |
| `diagnostic.py` | One finding of a check on a configuration document, in the shape every producer gives. |
| `exceptions.py` | Typed exception hierarchy for HydroModPy. |
| `fields/` | Plain descriptions of grids and field arrays: nodata, grid geometry, columns, storage precision. |
| `io/` | Low-level I/O helpers: raster, vector, CRS, JSON, HTTP. |
| `io/value_digest.py` | The `values/1` rule: one digest for a block of values, whatever their dtype. |
| `licensing.py` | The SPDX token this repository writes when nobody declared a licence. |
| `logging.py` | Console and file logging policy for HydroModPy. |
| `old_members.py` | Members of the public objects that left before the first stable version. |
| `payload/` | What a package installs into a workspace, and the one installer that places it. |
| `pipeline_steps.py` | The names of the steps of a simulation, the words every layer shares. |
| `plugin_registry.py` | One registry engine, shared by every `id -> class` plugin surface. |
| `runtime/` | The running process: environment variables and signal handling. |
| `scope.py` | The words the stored tables share. |
| `scoring/` | Goodness-of-fit scores between simulated and observed series, and the margin that ties two costs. |
| `site/` | The site: one catchment, declared once and recognized everywhere. |
| `state/` | Runtime state models shared by launchers and simulation execution. |
| `time/` | Shared simulation time-window resolution helpers. |
| `toml_io/` | TOML I/O and path-resolution helpers shared by every config layer. |
| `tracking/` | Input-file tracking primitives used across HydroModPy configs. |
| `units/` | Unit parsing and formatting helpers. |
| `version.py` | Canonical source of the HydroModPy version string. |
| `workspace/` | WorkspaceLayout structures used by simulation and launchers. |
