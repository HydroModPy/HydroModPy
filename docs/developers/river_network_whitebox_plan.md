# River Network From Topography (Whitebox) - Implementation Proposal

Status: design note, no implementation in this document.

Compatibility note (2026-03-15):
- `hydromodpy.geographic.cases.run_geographic_case` has been removed.
- Use `hydromodpy.geographic.cases` (public API) or
  `hydromodpy.geographic.cases.reference_catchment_delineation_case.run_case`
  (implementation module).

## Objective

Define a clear, incremental plan to generate a river network from:

- one DEM (topography),
- one outlet point,
- Whitebox workflows backend,
- current HydroModPy geographic pipeline.

The target is to add a production-ready path with deterministic tests aligned with existing project standards (unit + golden + regression).

## Current baseline in HydroModPy

Already available and stable:

- DEM correction (`fill` / `breach`) via `build_regional_flow_products`.
- D8 flow direction and flow accumulation.
- Outlet snapping (`snap_pour_points`).
- Catchment delineation from outlet (`watershed` + polygonization).
- Whitebox backend abstraction (`WhiteboxBackend` + `WhiteboxWorkflowsBackend`).
- Geographic tests and golden references for DEM/catchment products.

Missing for river-network extraction:

- backend contract methods for stream extraction and stream vectorization.
- dedicated geographic core module for "river network products".
- explicit configuration for stream-threshold strategy and options.
- dedicated non-regression tests for stream outputs.

## Scope

In scope:

- Extract raster stream network from accumulation threshold.
- Convert stream raster to vector network.
- Optional Strahler stream order and stream-link ids.
- Optional minimum length pruning.
- Output canonical files under `results_stable/geographic`.
- Add deterministic tests and golden references.

Out of scope (first iteration):

- auto-calibration against observed hydrography,
- multi-outlet partitioning,
- advanced uncertainty quantification,
- solver coupling changes (MODFLOW package generation).

## Proposed outputs

Canonical output files (suggested):

- `results_stable/geographic/river_streams.tif`
- `results_stable/geographic/river_streams_pruned.tif` (optional)
- `results_stable/geographic/river_stream_order_strahler.tif` (optional)
- `results_stable/geographic/river_stream_link_id.tif` (optional)
- `results_stable/geographic/river_network.shp`
- `results_stable/geographic/river_network_summary.json`

Suggested summary metrics:

- `threshold_mode`, `threshold_value`, `threshold_cells`
- `stream_pixel_count`
- `network_total_length_m`
- `segment_count`
- `max_strahler_order` (if enabled)
- `catchment_area_km2`
- `drainage_density_km_per_km2`

## Proposed algorithm

Step 1. Build hydrologic rasters:

- Correct DEM (`breach` by default).
- Build D8 pointer.
- Build D8 accumulation for thresholding.

Important design choice:

- keep one accumulation product for snapping compatibility,
- add one non-log accumulation raster for stream-threshold logic if needed.

Step 2. Delineate catchment from outlet:

- write outlet point,
- snap outlet on accumulation raster,
- delineate watershed raster and polygon.

Step 3. Extract streams:

- run `extract_streams(flow_accumulation, threshold=...)`,
- set explicit `zero_background` behavior for deterministic values.

Step 4. Optional post-processing:

- `remove_short_streams(..., min_length=...)` when enabled,
- `strahler_stream_order(...)`,
- `stream_link_identifier(...)`.

Step 5. Vectorize:

- run `raster_streams_to_vector(streams, d8_pointer, ...)`,
- clip to watershed polygon as safety guard.

Step 6. Build summary:

- compute deterministic signatures/metrics for golden tests and case review.

## Configuration proposal

Add a dedicated optional block in geographic config:

```toml
[geographic.river_network]
enabled = true
threshold_mode = "area_km2"      # one of: "area_km2", "cells"
threshold_area_km2 = 0.5         # used when threshold_mode="area_km2"
threshold_cells = 2000           # used when threshold_mode="cells"
prune_short_streams = false
min_stream_length_m = 0.0
compute_strahler_order = true
compute_stream_links = true
all_vertices = false
```

Threshold conversion:

- `threshold_cells = threshold_area_km2 * 1_000_000 / (dem_res_m * dem_res_m)`

Validation rules:

- exactly one threshold source active based on `threshold_mode`,
- strictly positive threshold,
- non-negative `min_stream_length_m`.

## Backend contract extension proposal

Extend `WhiteboxBackend` with:

- `extract_streams(...)`
- `raster_streams_to_vector(...)`
- `strahler_stream_order(...)`
- `stream_link_identifier(...)`
- `remove_short_streams(...)`

Add matching in-memory and file-oriented wrappers in `WhiteboxWorkflowsBackend`.

Expected Whitebox workflows methods already available in runtime:

- `extract_streams`
- `raster_streams_to_vector`
- `strahler_stream_order`
- `stream_link_identifier`
- `remove_short_streams`

## Geographic architecture proposal

New core module:

- `hydromodpy/geographic/core/river_network.py`

Suggested API:

- `RiverNetworkConfig` (if not embedded in `GeographicConfig`)
- `RiverNetworkProducts` dataclass
- `build_river_network_products(...)`
- helper `resolve_stream_threshold_cells(...)`
- helper `compute_river_network_summary(...)`

Pipeline integration:

- call river-network builder from `domain_geographic_pipeline.py` and/or legacy compatibility pipeline,
- keep feature behind `geographic.river_network.enabled`.

Paths integration:

- extend `GeographicPaths` with canonical river-network outputs.

## Implementation phases

Phase 1 - Backend and contract:

- extend `whitebox_backend.py` protocol,
- implement methods in `whitebox_workflows_backend.py`,
- extend backend smoke tests.

Phase 2 - Config and paths:

- add `geographic.river_network` schema,
- add validation rules,
- extend `GeographicPaths`.

Phase 3 - Core river-network builder:

- implement `geographic/core/river_network.py`,
- compute outputs + summary metrics,
- wire into geographic pipeline when enabled.

Phase 4 - Cases and docs:

- extend geographic case runner with optional river-network summary export,
- add developer/user docs and examples.

## Test strategy (aligned with existing modules)

### 1) Unit tests - backend

Update:

- `tests/unit/backends/test_whitebox_workflows_backend.py`

Add checks for:

- `extract_streams` output exists and contains active cells,
- `raster_streams_to_vector` output exists and non-empty,
- `strahler_stream_order` raster exists and has expected positive classes,
- `stream_link_identifier` raster exists,
- `remove_short_streams` does not increase active stream cells.

### 2) Unit tests - config

Add:

- `tests/unit/geographic/test_river_network_config.py`

Cases:

- valid `threshold_mode="area_km2"`,
- valid `threshold_mode="cells"`,
- reject missing threshold value,
- reject non-positive threshold,
- reject negative `min_stream_length_m`.

### 3) Unit tests - core logic

Add:

- `tests/unit/geographic/test_river_network_products.py`

Cases:

- threshold conversion to cells,
- deterministic summary metrics on synthetic mini-DEM,
- optional flags (`compute_strahler_order`, `prune_short_streams`) control output files,
- graceful behavior when river network is disabled.

### 4) Golden non-regression tests

Add:

- `tests/unit/geographic/test_run_geographic_river_network_golden.py`
- `tests/unit/geographic/golden/run_geographic_river_network_golden.json`

Pattern:

- same style as `test_run_geographic_dem_processing_golden.py`,
- use `configure_whitebox_single_thread(monkeypatch)`,
- produce stable signatures from:
  - stream raster,
  - optional Strahler raster,
  - vector summary metrics.

Suggested signature fields:

- raster shape/dtype/nodata,
- valid stream-pixel count,
- min/max/mean/std (for order raster when present),
- vector segment count,
- total network length.

### 5) Regression test (optional but recommended)

Add:

- `tests/regression/extensive/test_run_geographic_case_river_network_regression.py`
- `tests/regression/reference/golden_references/extensive/run_geographic_case_river_network_signatures.json`

Goal:

- stability across selected case presets (for example: base, nancon, aber).

## Determinism and CI stability

Use existing deterministic helper:

- `tests/support/whitebox.py::configure_whitebox_single_thread`

Additional recommendations:

- avoid brittle per-feature exact geometry assertions,
- prefer aggregate metrics and raster signatures with explicit tolerances,
- keep thresholds fixed in tests and avoid auto-calibration in CI.

## QA criteria (river-network outputs)

Definition:

- a QA criterion is one objective, measurable check proving that generated
  river-network outputs are valid and stable for a given input/configuration.

Recommended minimum QA criteria:

1. Threshold traceability
   - `threshold_mode`, `threshold_value`, and `threshold_cells` are present in
     summary outputs.
   - For `threshold_mode="area_km2"`, `threshold_cells` matches
     `area_km2 * 1_000_000 / (dem_res_m^2)` within a small tolerance.

2. Catchment consistency
   - Vector network is clipped to the catchment polygon.
   - No river segment should remain fully outside the watershed support.

3. Raster activity sanity
   - `stream_pixel_count > 0` for reference test cases.
   - When `prune_short_streams=true`, active stream pixels after pruning must
     be less than or equal to pre-pruning active pixels.

4. Raster/vector coherence
   - If `segment_count > 0`, then `stream_pixel_count > 0`.
   - `network_total_length_m > 0` when non-empty vector output exists.

5. Optional diagnostics coherence
   - If `compute_strahler_order=true`, Strahler raster exists and contains
     positive classes (`max_strahler_order >= 1`).
   - If `compute_stream_links=true`, stream-link raster exists with active
     non-zero labels.

6. Deterministic signatures
   - Summary and raster/vector signatures remain stable across runs in
     single-thread mode, with explicit tolerances in golden tests.

Suggested tolerances for non-regression checks:

- small absolute tolerance for scalar floats (for example `1e-3`),
- dedicated absolute tolerance for lengths (for example `1.0 m`),
- exact match for integer counters and categorical fields.

## Risks and mitigations

Risk: threshold sensitivity creates unstable outputs between DEMs.

Mitigation:

- support both area-based and cell-based thresholds,
- document recommended default ranges by DEM resolution.

Risk: stream vector topology can vary across Whitebox versions.

Mitigation:

- validate deterministic aggregate metrics first,
- keep exact topology checks limited to local smoke tests.

Risk: adding non-log accumulation changes existing behavior if reused by mistake.

Mitigation:

- keep current accumulation path unchanged for legacy outputs,
- introduce explicit naming for stream-threshold accumulation products.

## Acceptance criteria

- River network generation works end-to-end from DEM + outlet in standard geographic mode.
- Existing geographic tests remain green unchanged when feature disabled.
- New backend/core/config tests pass.
- New golden test passes without flaky behavior in single-thread mode.
- Outputs are documented and reproducible from one case TOML.

## Proposed file-level change map (for future implementation)

- `hydromodpy/backends/whitebox_backend.py`
- `hydromodpy/backends/whitebox_workflows_backend.py`
- `hydromodpy/geographic/geographic_config.py`
- `hydromodpy/geographic/geographic_paths.py`
- `hydromodpy/geographic/core/river_network.py` (new)
- `hydromodpy/geographic/core/domain_geographic_pipeline.py`
- `hydromodpy/legacy/geographic/pipeline.py`
- `tests/unit/backends/test_whitebox_workflows_backend.py`
- `tests/unit/geographic/test_river_network_config.py` (new)
- `tests/unit/geographic/test_river_network_products.py` (new)
- `tests/unit/geographic/test_run_geographic_river_network_golden.py` (new)
- `tests/unit/geographic/golden/run_geographic_river_network_golden.json` (new)
- `tests/regression/extensive/test_run_geographic_case_river_network_regression.py` (optional, new)

## Suggested first implementation PR split

PR 1:

- backend contract + workflows backend + backend unit tests.

PR 2:

- geographic config/path additions + core river-network module + unit tests.

PR 3:

- pipeline integration + golden test + docs/case runner updates.
