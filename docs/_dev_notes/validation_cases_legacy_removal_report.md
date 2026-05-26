# Validation Cases Legacy Removal Report

Date: 2026-05-27

## Scope

This report covers legacy compatibility inside `validation_cases/` and the
matching unit tests under `tests/unit/validation/`. It intentionally excludes
broader project/runtime compatibility unless validation cases call into it
directly.

## Executive Summary

The active validation-code legacy targeted by this chantier has been removed
from the scoped source tree:

- public `load_npy*` validation helpers and the
  `HMP_ALLOW_LEGACY_NPY_VALIDATION` flag are gone;
- validation field readers now require `store` + `sim_id`;
- Boussinesq validation producers either write in-memory fields directly to
  `SimulationCatalog` or consume the production catalog emitted by
  `hydromodpy run`; they no longer rewrite structured `_postprocess/*.npy`
  files;
- `launcher = "launcher_simulation"` metadata has been removed from
  validation cases and unit fixtures;
- calibration cell resolution no longer exposes a `_legacy` fallback name;
- analytical Boussinesq defaults now fill missing PETSc settings instead of
  upgrading legacy backend/surface values.

Remaining non-code or intentionally current items:

- the known generated comparison snapshot under
  `validation_cases/analytical/transient/linearized_unconfined_boundary_step_1d/comparison/lu_boundary_step_same_support/`
  was removed from Git tracking and ignored; rerun `run_comparison.py` to
  regenerate it locally when needed;
- `_postprocess` remains as a run-artifact/sidecar directory for current
  workflows, not as the validation field-reader contract;
- broader project compatibility outside validation is intentionally out of
  this report's scope.

## Inventory

| Area | Current code | Legacy behavior | Removal direction |
| --- | --- | --- | --- |
| NPY output bridge | `validation_cases/shared/loaders.py`, `validation_cases/shared/runtime.py`, Boussinesq runtime helpers | Field readers and producers are now catalog-first. The public `.npy` helper surface and compatibility env flag were removed. | Done for active validation code. Keep `_postprocess` only for current sidecar artifacts. |
| Postprocess directory contract | `ValidationRunResult.postprocess_dir`, diagnostics | Diagnostics migrated to catalog-backed field access where they read validation fields. | Keep `postprocess_dir` for solver artifacts and non-field metadata only. |
| Analytical Boussinesq runtime defaults | `validation_cases/shared/boussinesq_analytical_runtime.py` | Defaults now fill missing PETSc settings. They no longer remap legacy backend/surface values. | Done for validation defaults. Preserve non-PETSc backends only where a case intentionally tests them. |
| Launcher metadata | `validation_cases/**/metadata.toml`, `tests/unit/validation/test_validation_runtime.py` | Obsolete `launcher = "launcher_simulation"` entries were removed. Runtime still materializes temporary configs with a workflow block for CLI execution. | Remaining optional cleanup: make all source config overlays workflow-complete, then tighten the temp-config builder. |
| Historical output cleanup | `validation_cases/shared/runtime.py`, `tests/unit/validation/test_validation_runtime.py` | `resolve_validation_results_dir()` removes stale hash-suffixed directories such as `<run>_deadbeef`. | Keep as stale-output cleanup unless old generated outputs are no longer a concern. |
| Calibration extraction fallback | `validation_cases/calibration/shared/runtime.py`, `tests/unit/validation/test_calibration_runtime_extraction.py` | The fallback is now named `_resolve_cell_index_from_mesh_planar(...)`; JSONL iteration history is current reporting output. | Done for legacy naming. `_DeclShim` can be audited separately if the calibration schema is frozen. |
| Generated comparison artifacts | `validation_cases/**/comparison/**` | The tracked historical `lu_boundary_step_same_support` snapshot was removed and ignored. | Done for the known validation comparison snapshot. Regenerate locally through `run_comparison.py` when needed. |
| Docs and tests | `tests/validation/README.md`, `tests/unit/validation/*`, shared `__init__.py` exports | Docs and tests describe the current catalog-first behavior; no scoped source/test legacy grep matches remain outside generated comparison artifacts. | Done for scoped source/docs/tests. |

## Removal Sequence Applied

1. Established `write_validation_fields_to_store(...)` as the direct catalog
   writer for validation field series.
2. Migrated analytical and numerical Boussinesq producers to return in-memory
   fields and write them directly to the catalog.
3. Migrated diagnostics and comparisons from `load_npy*` helpers to
   catalog-backed `load_field(...)`, `load_field_on_expected_grid(...)`, and
   `load_time_series_fields(...)`.
4. Removed the public `.npy` compatibility layer and the
   `HMP_ALLOW_LEGACY_NPY_VALIDATION` gate.
5. Removed launcher-era metadata from validation `metadata.toml` files.
6. Removed legacy-named structured `.npy` writer wrappers and calibration
   fallback names.
7. Updated docs/tests and ran the scoped legacy grep.

## Acceptance Checks

Targeted tests:

```powershell
pytest tests/unit/validation
```

Legacy search:

```powershell
rg -n "legacy|Legacy|deprecated|compatibilit|compatibility|HMP_ALLOW_LEGACY_NPY_VALIDATION|load_npy|load_last_npy|launcher_simulation" validation_cases tests/unit/validation tests/validation/README.md -S --glob '!**/comparison/**'
```

The scoped source/test/docs grep now returns no matches.

## Progress

2026-05-27:

- Added `write_validation_fields_to_store(...)` in
  `validation_cases/shared/runtime.py`.
- Refactored `materialize_postprocess_fields_to_store(...)` so the legacy
  `.npy` bridge calls the catalog-first writer.
- Added `aggregate_triangle_history_to_structured_fields(...)` in
  `validation_cases/shared/boussinesq_uniform_strip.py`.
- Migrated `run_boussinesq_uniform_strip_case(...)` to write the aggregated
  fields directly to `SimulationCatalog`.
- Kept `aggregate_triangle_history_to_structured_grids(...)` as the
  compatibility writer for cases that still expect `_postprocess/*.npy`.
- Added unit coverage for the catalog writer and the uniform-strip aggregation
  split.

Tested with:

```powershell
python -m pytest tests\unit\validation
```

Result: `67 passed`.

2026-05-27 follow-up:

- Added `aggregate_piecewise_strip_postprocess_fields(...)` in
  `validation_cases/shared/boussinesq_piecewise_strip.py`.
- Routed `run_piecewise_strip_boussinesq_launcher_case(...)` through
  `write_validation_fields_to_store(...)` after structured aggregation.
- Kept `aggregate_piecewise_strip_postprocess(...)` as the compatibility
  writer for structured `_postprocess/*.npy` files.
- Migrated the hillslope recharge-pulse overflow Boussinesq runtime to return
  `store` and `sim_id`.
- Switched overflow diagnostics from `load_npy_time_series_arrays(...)` to
  catalog-backed `load_time_series_fields(...)`.
- Added unit coverage for piecewise aggregation and overflow catalog fallback.

Tested with:

```powershell
python -m pytest tests\unit\validation
python -m ruff check validation_cases\shared\boussinesq_piecewise_strip.py validation_cases\numerical\transient\boussinesq_hillslope_recharge_pulse_overflow_1d\runtime_boussinesq.py validation_cases\numerical\transient\boussinesq_hillslope_recharge_pulse_overflow_1d\diagnostics.py tests\unit\validation\test_boussinesq_piecewise_strip.py tests\unit\validation\test_hillslope_pulse_overflow_case.py
```

Result: `70 passed`; Ruff passed.

2026-05-27 analytical producer migration:

- Migrated all in-repo analytical Boussinesq producers that called
  `materialize_postprocess_fields_to_store(...)` to
  `write_validation_fields_to_store(...)`.
- Removed `materialize_postprocess_fields_to_store(...)` from
  `validation_cases/shared/runtime.py`.
- Split 2D projection helpers so direct runtimes can return in-memory field
  payloads while compatibility wrappers can still write `_postprocess/*.npy`.
- Migrated Brutsaert recession scalar discharge series into the catalog-backed
  field payload. The comparison still reads `brutsaert_context.json` from the
  run's `_postprocess` directory for initial-discharge metadata.

Tested with:

```powershell
python -m pytest tests\unit\validation
python -m ruff check validation_cases\analytical\transient\runtime_boussinesq_1d.py validation_cases\analytical\steady\boussinesq_fixed_head_piecewise_k_1d\runtime_boussinesq.py validation_cases\analytical\steady\boussinesq_hillslope_interception_1d\runtime_boussinesq.py validation_cases\analytical\transient\boussinesq_hillslope_recharge_step_interception_1d\runtime_boussinesq.py validation_cases\analytical\steady\boussinesq_circular_island_piecewise_k_2d\runtime_boussinesq.py validation_cases\analytical\steady\dupuit_circular_island_ocean_2d\runtime_boussinesq.py validation_cases\analytical\transient\late_time_unconfined_pumping_2d\runtime_boussinesq.py validation_cases\analytical\transient\runtime_boussinesq_brutsaert_1d.py validation_cases\shared\runtime.py
```

Result: `70 passed`; Ruff passed.

2026-05-27 loader legacy deletion:

- Renamed the expected-grid reader to `load_field_on_expected_grid(...)`.
- Removed the validation `.npy` reader surface from `validation_cases.shared`:
  `load_npy_dict`, `load_last_npy_array`, `load_npy_time_series_arrays*`, and
  the `HMP_ALLOW_LEGACY_NPY_VALIDATION` opt-in flag are gone.
- Made `load_field(...)`, `load_time_series_fields(...)`, and
  `load_field_on_expected_grid(...)` require `store` + `sim_id`.
- Removed the remaining comparison call sites that passed
  `result.postprocess_dir` into validation loaders.
- Kept `ValidationRunResult.postprocess_dir` for run artifacts and sidecar
  metadata still produced by current runtimes; it is no longer a field-reader
  fallback.

Tested with:

```powershell
python -m ruff check validation_cases tests\unit\validation\test_validation_loaders.py
python -m pytest tests\unit\validation
rg -n "HMP_ALLOW_LEGACY_NPY_VALIDATION|load_npy|load_last_npy_array|load_last_npy_array_on_expected_grid|_read_postprocess|Legacy validation \.npy" validation_cases tests\unit\validation tests\validation\README.md -g "*.py" -g "*.md"
```

Result: Ruff passed; `71 passed`; legacy-loader grep returned no matches.

2026-05-27 metadata/wrapper/calibration cleanup:

- Removed `launcher = "launcher_simulation"` from 23 validation
  `metadata.toml` files and from validation runtime test fixtures.
- Updated `tests/validation/README.md` to describe production
  `hydromodpy run` execution instead of launcher-era fixtures.
- Removed structured `.npy` writer wrappers:
  `aggregate_triangle_history_to_structured_grids(...)` and
  `aggregate_piecewise_strip_postprocess(...)`.
- Switched the piecewise Boussinesq launcher path to
  `aggregate_piecewise_strip_postprocess_fields(...)` plus
  `write_validation_fields_to_store(...)`.
- Renamed calibration `_nearest_cell_index_legacy(...)` to
  `_resolve_cell_index_from_mesh_planar(...)` and removed legacy wording from
  stale-output cleanup and JSONL reporting.
- Simplified analytical Boussinesq runtime defaults so they fill missing PETSc
  settings without legacy backend/surface remapping.

Tested with:

```powershell
python -m pytest -q tests/unit/validation -o addopts=""
python -m ruff check validation_cases/shared/loaders.py validation_cases/shared/__init__.py validation_cases/shared/runtime.py validation_cases/shared/boussinesq_uniform_strip.py validation_cases/shared/boussinesq_piecewise_strip.py validation_cases/shared/boussinesq_analytical_runtime.py validation_cases/analytical/transient/runtime_boussinesq_1d.py validation_cases/analytical/steady/boussinesq_fixed_head_piecewise_k_1d/runtime_boussinesq.py validation_cases/analytical/steady/boussinesq_hillslope_interception_1d/runtime_boussinesq.py validation_cases/analytical/steady/boussinesq_circular_island_piecewise_k_2d/runtime_boussinesq.py validation_cases/analytical/steady/dupuit_circular_island_ocean_2d/runtime_boussinesq.py validation_cases/analytical/transient/late_time_unconfined_pumping_2d/runtime_boussinesq.py validation_cases/calibration/shared/runtime.py tests/unit/validation/test_validation_loaders.py tests/unit/validation/test_validation_runtime.py tests/unit/validation/test_boussinesq_uniform_strip.py tests/unit/validation/test_boussinesq_piecewise_strip.py tests/unit/validation/test_boussinesq_analytical_runtime.py tests/unit/validation/test_calibration_runtime_extraction.py
rg -n "legacy|Legacy|deprecated|compatibilit|compatibility|HMP_ALLOW_LEGACY_NPY_VALIDATION|load_npy|load_last_npy|launcher_simulation" validation_cases tests/unit/validation tests/validation/README.md -S --glob '!**/comparison/**'
```

Result: `69 passed`; Ruff passed; scoped legacy grep returned no matches.

2026-05-27 workflow contract tightening:

- Removed the remaining `_build_validation_launcher_config(...)` workflow
  default injection. Validation launcher configs must now define `[workflow]`
  directly or inherit it from `base_config`.
- Added an explicit failure test for configs that lack workflow metadata after
  merge.
- Added `[workflow] mode = "simulation"` to the two Boussinesq direct config
  placeholders that did not inherit a base config.
- Verified that every config referenced from validation metadata resolves a
  workflow after base-config merge.
- Replaced the calibration extraction dynamic `_DeclShim` class with an
  explicit `SimpleNamespace` declaration adapter.

Tested with:

```powershell
python -m ruff check validation_cases\calibration\shared\runtime.py validation_cases\shared\runtime.py tests\unit\validation\test_validation_runtime.py validation_cases\analytical\steady\boussinesq_hillslope_interception_1d\config_boussinesq.toml validation_cases\analytical\transient\boussinesq_hillslope_recharge_step_interception_1d\config_boussinesq.toml
python -m pytest tests\unit\validation
rg -n "_DeclShim|_nearest_cell_index_legacy|legacy-shaped|launcher_simulation|^launcher\s*=|setdefault\(\s*\"workflow\"|HMP_ALLOW_LEGACY_NPY_VALIDATION|load_npy|load_last_npy" validation_cases tests\unit\validation tests\validation\README.md -S --glob "!**/comparison/**" --glob "!**/.__validation_runtime_*.toml"
```

Result: Ruff passed; `70 passed`; scoped grep returned no matches.

2026-05-27 generated comparison artifact cleanup:

- Removed the tracked generated comparison directory
  `validation_cases/analytical/transient/linearized_unconfined_boundary_step_1d/comparison/lu_boundary_step_same_support/`.
- Added a targeted `.gitignore` rule so rerunning
  `validation_cases/analytical/transient/linearized_unconfined_boundary_step_1d/run_comparison.py`
  does not reintroduce generated CSV/JSON/PNG/HTML artifacts.

Validation:

```powershell
rg -n "launcher_simulation" validation_cases tests/unit/validation tests/validation/README.md -S
```

Result: no matches after the generated directory removal.

2026-05-27 Brutsaert diagnostic cleanup:

- Updated the two direct Brutsaert diagnostic scripts so outlet discharge is
  read from the post-processing dictionary already attached to the solver
  model instead of reloading `_postprocess/*.npy`.
- Kept solver state sidecars (`_boussinesq_state_history.npz`,
  `_boussinesq_summary.json`) because they are current diagnostic artifacts,
  not validation field-reader fallbacks.

Tested with:

```powershell
python -m ruff check validation_cases/analytical/transient/brutsaert_recession_linearized_deep_1d/diagnose_modflownwt_single_boundary.py validation_cases/analytical/transient/brutsaert_recession_linearized_deep_1d/diagnose_single_boundary_solver_comparison.py
python -m pytest -q tests/unit/validation -o addopts=""
rg -n "np\.load|np\.save|\.npy" validation_cases -S --glob '!**/comparison/**'
```

Result: Ruff passed; `70 passed`. Remaining `.npy` matches were limited to
`aggregate_piecewise_strip_postprocess_fields(...)`, which was removed in the
next tranche, and a current `.npz` state-history diagnostic.

2026-05-27 final Boussinesq `.npy` bridge removal:

- Removed `aggregate_piecewise_strip_postprocess_fields(...)` and the related
  bundle-geometry reader from `validation_cases/shared/boussinesq_piecewise_strip.py`.
- Switched `run_piecewise_strip_boussinesq_launcher_case(...)` to require the
  `SimulationCatalog` produced by `hydromodpy run` instead of re-reading
  launcher `_postprocess/watertable_elevation.npy`.
- Removed the unused Boussinesq `write_standard_postprocess_outputs(...)`
  exporter and the orphaned `write_time_series_npy(...)` / `__time_axis.npy`
  helper API.
- Updated Boussinesq docs and the generated API stub so the documented
  transient export contract is `_boussinesq_state_history.npz` plus catalog
  fields, not `_postprocess/*.npy` sidecars.

Tested with:

```powershell
python -m ruff check hydromodpy\physics\flow\history_contract.py hydromodpy\solver\boussinesq\export_payload.py validation_cases\shared\boussinesq_piecewise_strip.py tests\unit\validation\test_boussinesq_piecewise_strip.py tests\unit\physics\test_flow_contract_helpers.py
python -m pytest tests\unit\validation\test_boussinesq_piecewise_strip.py tests\unit\physics\test_flow_contract_helpers.py
python -m pytest tests\unit\validation
python -m pytest tests\unit\solver\test_boussinesq_export_payload.py tests\unit\solver\test_boussinesq_extract_series.py tests\unit\solver\test_boussinesq_numerical_contracts.py tests\unit\simulation\test_boussinesq_flow_adapter.py
rg -n "time_axis_sidecar_path|write_time_series_npy|__time_axis|_postprocess/\*\.npy|watertable_elevation\.npy|watertable_depth\.npy|aggregate_piecewise_strip_postprocess_fields|write_standard_postprocess_outputs" hydromodpy validation_cases tests docs -S --glob "!docs/source/_static/capability_gallery/**" --glob "!docs/_internal/legacy_notebooks/**"
```

Result: Ruff passed; targeted tests `12 passed`; validation unit suite
`70 passed`; Boussinesq solver/adapter tests `28 passed`. Remaining grep
matches are MODFLOW regression/golden `.npy` helpers, generated gallery
CSV/build artifacts, or this report.

## Proposed Next Change

Close the remaining repository-wide non-code debt in this order:

1. Treat the broader `launcher_simulation` fixture/gallery naming as a
   separate repository-wide migration, because it touches regression fixtures,
   docs, generated gallery manifests, and e2e tests.
2. Decide separately whether MODFLOW `_postprocess/*.npy` golden helpers are
   still part of the supported regression surface or should move to catalog
   snapshots.
