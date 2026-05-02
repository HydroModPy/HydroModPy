# Geographic Package

## Scope

`hydromodpy.spatial.geographic` prepares all geospatial inputs required before domain
and simulation steps:

- watershed delineation or direct DEM domain setup,
- domain support polygons (catchment, box, buffered box),
- clipped DEM products used by domain gridding,
- optional DEM-derived river network products,
- compatibility payload consumed by legacy and modern runtimes,
- canonical hydrographic-network objects shared with comparison and display layers.

## Package Layout

- `geographic.py`: compatibility facade (`Geographic` class) used by existing runtime code.
- `geographic_config.py`: validated configuration model (`GeographicConfig`, `RiverNetworkConfig`).
- `dem_metadata.py`: DEM-derived metadata contract used by `Geographic`.
- `domain_rasters.py`: historical raster bundle builder kept near the canonical pipeline.
- `pipeline.py`: compatibility orchestration that hydrates the `Geographic` runtime payload.
- `geographic_paths.py`: canonical output-path contract.
- `geographic_io.py`: CRS and shapefile I/O helpers.
- `core/`: decomposed geographic pipeline modules (single-responsibility steps).
- `cases/`: runnable examples and review scripts.
- `synthetic/`: synthetic geographic support builder and config.

## Core Modules (`geographic/core`)

- `flow_products.py`: DEM correction + D8 direction + D8 accumulation rasters.
- `catchment_from_point.py`: outlet-based watershed delineation.
- `catchment_from_polygon.py`: normalize externally provided watershed polygon.
- `catchment_domain.py`: derive buffered and box domain polygons.
- `domain_dem.py`: clip DEM to buffered rectangular support.
- `surface_from_dem.py`: convert DEM raster to `RasterSupport` + `Surface`.
- `catchment_zones.py`: build categorical zone rasters.
- `catchment_metrics.py`: scalar metrics (currently catchment area).
- `direct_dem_domain.py`: direct-domain mode from DEM (`catch_def="dem"`).
- `river_network.py`: optional stream extraction and network diagnostics.
- `hydrographic_network.py`: canonical hydrographic-network concept and naming contract.
- `pipeline_steps.py`: shared setup helpers reused by orchestration.
- `domain_geographic_pipeline.py`: top-level context builder for domain runtime.

## Processing Modes

`GeographicConfig.source_mode` controls the mode:

- `standard` (default): use DEM/outlet/polygon based preprocessing.
- `synthetic`: build analytical support from `[geographic.synthetic]`.

For `standard`, `catch_def` selects the domain definition:

- `from_outlet_coord`: delineate watershed from one outlet coordinate.
- `from_polyg_shp`: import a provided watershed polygon.
- `dem`: use DEM extent directly as model domain (no watershed delineation).
- `txt`: build domain from XYZ text file + `cell_size`.

## Standard Pipeline (Conceptual Sequence)

1. Resolve output paths and DEM metadata.
2. Build flow rasters (`flow_products`).
3. Build catchment geometry (`catchment_from_point` or `catchment_from_polygon`).
4. Build domain supports (`catchment_domain`) or direct DEM supports (`direct_dem_domain`).
5. Clip DEM to buffered box (`domain_dem`).
6. Build topographic surface (`surface_from_dem`).
7. Compute metrics (`catchment_metrics`).
8. Optionally build the generated hydrographic network (`geographic.river_network`).

The `domain_geographic_pipeline` module orchestrates this sequence for modern
domain entrypoints. The `Geographic` class preserves historical behavior using
compatibility payloads that now live directly in this package, with old import
paths served only through centralized aliases.

## Generated Hydrographic Network

`[geographic.river_network]` controls stream extraction:

- `enabled`: activate/deactivate network products.
- `threshold_mode`: `"area_km2"` or `"cells"`.
- `threshold_area_km2` or `threshold_cells`: stream initiation threshold.
- `prune_short_streams`, `min_stream_length_m`: optional cleaning.
- `compute_strahler_order`, `compute_stream_links`: optional diagnostics.

Outputs can include:

- extracted streams raster,
- optional pruned streams raster,
- optional Strahler order raster,
- optional stream-link raster,
- vector generated network (`river_network.shp`, legacy filename),
- summary JSON (`river_network_summary.json`, legacy filename).

Canonical concept:

- `HydrographicNetwork(role="generated")` is the shared conceptual object used by
  display, comparison and result APIs.
- `RiverNetworkProducts` remains the technical low-level bundle produced by the
  geographic preprocessing step.
- `RiverMeshTrace` remains the narrow downstream projection used by meshing.

Canonical persisted names:

- `hydrographic_network_generated` for the generated network,
- `hydrographic_network_reference` for the loaded reference network.

Legacy aliases still kept for compatibility:

- `river_network` as the generated feature alias,
- `streams.shp` / `streams.tif` for the loaded reference files,
- `river_network.shp` / `river_network_summary.json` for generated on-disk products.

## Typical Inputs

- DEM in projected CRS (meters recommended).
- Outlet coordinates (`x_outlet`, `y_outlet`) for outlet mode.
- Or polygon shapefile for polygon mode.
- Optional explicit `crs_project` if CRS normalization is required.

## Typical Outputs

Common geographic outputs include:

- `watershed.shp`
- `watershed_buff.shp`
- `watershed_box.shp`
- `watershed_box_buff.shp`
- `watershed_dem.tif`
- `watershed_buff_dem.tif`
- `watershed_box_buff_dem.tif`

Exact outputs depend on selected mode and enabled options.

## Runnable Cases

Catchment delineation reference set:

```bash
python hydromodpy/spatial/geographic/cases/reference_catchment_delineation_case/run_case.py --cases all --no-show-plot
```

River-network reference case:

```bash
python hydromodpy/spatial/geographic/cases/reference_river_network_nancon/run_case_river_network_nancon.py --no-show-plot
```

Sequential visual review:

```bash
python hydromodpy/spatial/geographic/cases/review_cases.py --list
python hydromodpy/spatial/geographic/cases/review_cases.py
```

## Design Notes

- The package keeps backward compatibility via `Geographic` facade while
  progressively moving logic into `core/`.
- Core modules are intentionally small and explicit to simplify testing and
  maintenance.
- File/path contracts are centralized to keep downstream code deterministic.
- `HydrographicNetwork` is the preferred cross-layer concept; `RiverNetworkProducts`
  should be treated as an internal preprocessing contract.

## Development Tips

- Add new geographic behavior in `core/` first, then wire through orchestration.
- Keep module-level docstrings explicit about pipeline role, inputs, outputs.
- Prefer deterministic output naming to keep non-regression tests stable.
