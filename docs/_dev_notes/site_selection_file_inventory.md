# Site selection file inventory

Date: 2026-05-15

This note locates the current files involved in choosing basin sites in a
region, rendering a map/HTML review, and passing selected sites downstream to
regional-lab/testbed campaigns.

## Current tree

```text
hydromodpy/
  spatial/
    site_selection/
      __init__.py
      reports/
        legacy_review.py
  analysis/
    testbed/
      regional_lab_bootstrap.py
      regional_lab_catalog.py
      regional_lab_config.py
      regional_lab_planning.py
      regional_lab_reporting.py
      regional_lab_site_selection.py
      regional_lab_types.py

examples/
  data/
    dem/
      DEM_armorican_massif.tif
    hydrography/
      regional_stream_network.shp
    geology/
      geology_brgm_1m_france.gpkg
  projects/
    07_mesh_gallery/
      10km2/
      100km2/
      1000km2/
    10_testbed_workflow/
      site_tables/
        armorican_demo_sites.csv
      boussinesq/
        natural_geology_k/
          natural_regional_lab.toml
          natural_regional_lab_sites.csv
          natural_10km2_sites.csv
          build_bouss_stationary_site_inventories.py
          build_bouss_stationary_site_maps.py

docs/
  _dev_notes/
    site_selection_tool_implementation_plan.md
    site_selection_file_inventory.md
    boussinesq_stationary_site_inventory.md
```

## Reusable site-selection reporting

| file | role |
|---|---|
| `hydromodpy/spatial/site_selection/reports/legacy_review.py` | Reusable legacy map/HTML renderer for a site selection in a region. Reads site and mesh inventories, filters rows, optionally applies spatial balancing, writes `index.html`, `map_selection.png`, and GeoJSON. |
| `hydromodpy/spatial/site_selection/__init__.py` | Public package entrypoint for site-selection helpers. |

This is the right home for the basin-choice map/report layer. It is not
Boussinesq-specific.

## Regional-lab bridge

| file | role |
|---|---|
| `hydromodpy/analysis/testbed/regional_lab_catalog.py` | Loads site catalogs into typed regional-lab records. |
| `hydromodpy/analysis/testbed/regional_lab_site_selection.py` | Applies regional-lab site filters: site ids, regions, families, scales, statuses, maturity, tags. |
| `hydromodpy/analysis/testbed/regional_lab_config.py` | Configuration contract for catalog, selection filters, cluster rules, and recipes. |
| `hydromodpy/analysis/testbed/regional_lab_types.py` | Data classes for site records, planned cases, skipped cases, and outcomes. |
| `hydromodpy/analysis/testbed/regional_lab_planning.py` | Expands selected sites and recipes into planned regional-lab cases. |
| `hydromodpy/analysis/testbed/regional_lab_reporting.py` | Writes regional-lab CSV/JSON/Markdown summaries. |
| `hydromodpy/analysis/testbed/regional_lab_bootstrap.py` | Bootstrap helpers to build regional-lab catalogs from outlet/manifest tables and inspect mesh readiness. |

Regional-lab is currently the downstream orchestration bridge. It consumes a
site catalog; it does not itself discover new basins.

## Project-level adapters and inventories

| file | role |
|---|---|
| `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/build_bouss_stationary_site_inventories.py` | Boussinesq-specific inventory builder. It joins regional-lab sites, existing child bundles, mesh-gallery bundles, and Boussinesq readiness/K metrics. |
| `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/build_bouss_stationary_site_maps.py` | Thin compatibility wrapper around `hydromodpy.spatial.site_selection.reports.legacy_review`. Kept so existing project commands still work. |
| `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_regional_lab.toml` | Current regional-lab config for natural Boussinesq campaigns. |
| `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_regional_lab_sites.csv` | Current hand-maintained/bootstrapped site catalog for regional-lab runs. |
| `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_10km2_sites.csv` | Earlier 10 km2 site table used by natural workflows. |
| `examples/projects/10_testbed_workflow/site_tables/armorican_demo_sites.csv` | Small Armorican demo site table used by older testbed/prototype workflows. |

## Spatial data inputs

| path | role |
|---|---|
| `examples/data/dem/DEM_armorican_massif.tif` | Regional topography background and valid-data contour for selection maps. |
| `examples/data/hydrography/regional_stream_network.shp` | Regional stream-network context used by natural workflows and candidate delineation. |
| `examples/data/geology/geology_brgm_1m_france.gpkg` | Coarse geology context. |
| `examples/data/geology/departments_50k/` | Department-level 50k geology sources, when higher-resolution geology is needed. |

## Mesh-gallery candidates

| path | role |
|---|---|
| `examples/projects/07_mesh_gallery/10km2/` | Existing 10 km2 mesh-gallery candidates and bundles. |
| `examples/projects/07_mesh_gallery/100km2/` | Existing 100 km2 mesh-gallery candidates and bundles. |
| `examples/projects/07_mesh_gallery/1000km2/` | Existing 1000 km2 mesh-gallery candidates and bundles. |

Bundle files used by the current reporting path:

```text
bundle/
  nodes.csv   # node coordinates, top/bottom elevations
  edges.csv   # edge_kind=boundary is used to reconstruct basin/model support outline
  cells.csv   # cell counts, areas, K statistics
```

## Generated review artifacts

The diagnostics directory is git-ignored and should be regenerated.

```text
docs/_dev_notes/diagnostics/boussinesq_stationary_site_inventory/
  bouss_stationary_site_inventory.csv
  bouss_stationary_mesh_inventory.csv
  bouss_stationary_site_inventory_summary.json
  bouss_stationary_site_inventory_summary.md
  selections/
    headwater_10km2_catalog/
      index.html
      map_selection.png
      bouss_stationary_site_emprises.geojson
    headwater_10km2_spatial_screening/
      index.html
      map_selection.png
      bouss_stationary_site_emprises.geojson
```

## Workflow status

The basin-choice map is currently a reusable reporting component, not a complete
workflow by itself.

The intended workflow boundary is:

1. site-selection workflow discovers or imports basin candidates;
2. `hydromodpy.spatial.site_selection.reports.legacy_review` renders a map/HTML review;
3. selected rows are exported as a regional-lab-compatible site catalog;
4. regional-lab/testbed expands sites into simulation/comparison cases.

The current gap is the upstream candidate discovery workflow. Existing files
already document the target design in
`docs/_dev_notes/site_selection_tool_implementation_plan.md`.

## Other realized selection/list mechanisms

There are several adjacent mechanisms in the completed projects. They should
not all be folded into one "site selection" concept.

| location | what it selects | status | relation to basin selection |
|---|---|---|---|
| `hydromodpy/analysis/catalog.py` | Generic CSV/JSONL rows by field equality, tags, enabled flag, and limit. | Implemented reusable primitive. | Useful low-level loader/filter for catalogs, but it has no basin/spatial semantics. |
| `hydromodpy/analysis/testbed/regional_lab_site_selection.py` | Existing regional-lab site records by `site_id`, `region_id`, `cluster_id`, family, scale, status, maturity, tags, enabled. | Implemented and used by `regional_lab`. | This is operational filtering of an existing catalog; it should remain downstream of geographic site discovery. |
| `examples/projects/10_testbed_workflow/site_tables/armorican_demo_sites.csv` | Eight manually numbered Armorican outlet sites. | Implemented older demo catalog. | Source/prototype catalog, not a reproducible site-selection workflow. |
| `examples/projects/10_testbed_workflow/nwt_small_catchment_flux_testbed.toml` | Testbed variants hard-code the eight demo sites as `[[testbed.variant]]` overlays. | Implemented testbed. | This is a simulation matrix using site coordinates, not a selector. |
| `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_regional_lab_sites.csv` | Unified natural regional-lab catalog with N1/N2/N3 rows, provenance, scale, group, paths and tags. | Implemented current catalog. | Best current bridge from selected basins to regional-lab/testbed. |
| `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_network_site_candidates_sites.csv` | Small candidate catalog for network-comparison pages. | Implemented focused catalog. | Useful historical subset, but still hand/mesh-gallery driven. |
| `examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/natural_drainage_k_mesh_matrix_sites.csv` | Site/K scenarios for stationary Boussinesq diagnostics. | Implemented diagnostic matrix. | Selects numerical scenarios derived from sites, not new basins. |
| `examples/projects/07_mesh_gallery/**/case.json` and `bundle/` | Mesh-candidate families by scale, outlet id, constraint mode, and variant. | Implemented gallery corpus. | Acts as a realized candidate reservoir; it stores imported candidates, but does not itself perform selection. |
| `examples/projects/12_calibration_network_transient_b0/*candidate*` | Calibration parameter/run candidates. | Implemented calibration scoring. | "Candidate" means model parameter/run candidate, not basin site candidate. |
| `examples/projects/15_nancon_gauged_context/` and `hydromodpy/data/variables/*` station managers | Observation stations by configured station ids, bbox, period, and data availability. | Implemented data-loading/observation logic. | Relevant future attribute source for site scoring, but not basin-site selection. |
| `examples/projects/06_vire_selune/` and `examples/projects/09_comparison_workflow/` | Manually named watersheds or solver comparison variants. | Implemented project examples. | Manual case definitions, not reusable multi-site selection. |

## Structural recommendation

The codebase already has the pieces for the downstream half. The missing piece
is the upstream, reproducible basin-selection engine.

Recommended ownership:

```text
hydromodpy.spatial.site_selection
  discovers/imports basin candidates
  scores and filters them
  spatially balances selections
  renders map/HTML review
  exports regional-lab-compatible catalogs

hydromodpy.analysis.catalog
  stays generic row loading/filtering

hydromodpy.analysis.testbed.regional_lab
  consumes site catalogs
  filters selected records operationally
  expands site x recipe plans
  writes regional-lab inventories/reports

examples/projects/*/
  keep project-specific adapters, compatibility wrappers and campaign scripts
```

The practical boundary should stay:

```text
site_selection chooses basins.
regional_lab chooses which selected basins enter which recipes.
testbed/comparison choose numerical variants and execute simulations.
```

This avoids mixing three different decisions:

1. geographic/scientific selection of catchments;
2. operational filtering of a site catalog;
3. construction of simulation or calibration candidate matrices.
