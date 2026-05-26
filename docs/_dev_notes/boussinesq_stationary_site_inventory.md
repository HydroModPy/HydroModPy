# Boussinesq stationary site inventory

Date: 2026-05-15

This note records the first dry inventory for wider strict stationary
Boussinesq Picard/VI campaigns.

Problem definition kept for the inventory:

- heterogeneous hydraulic conductivity from mesh bundles;
- drainage `0.0 m2/s`;
- no `b_min`;
- no added surface conductance.

## Inventory builder

Script:

```bash
python examples/projects/10_testbed_workflow/boussinesq/natural_geology_k/build_bouss_stationary_site_inventories.py
```

The historical map/HTML review script for the Boussinesq inventory has been
removed. Current site-selection reviews are generated from a
`site_selection_manifest.json` with the standard report command:

```bash
hmp site-selection report SITE_SELECTION_MANIFEST
```

The inventory builder uses:

- `hydromodpy.analysis.testbed.regional_lab_catalog.load_site_catalog`;
- `hydromodpy.analysis.testbed.regional_lab_site_selection.filter_sites`;
- `hydromodpy.analysis.testbed.regional_lab_bootstrap.inspect_mesh_bundle_boussinesq_readiness`.

Generated local artifacts:

- `docs/_dev_notes/diagnostics/boussinesq_stationary_site_inventory/bouss_stationary_site_inventory.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_site_inventory/bouss_stationary_mesh_inventory.csv`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_site_inventory/bouss_stationary_site_inventory_summary.json`;
- `docs/_dev_notes/diagnostics/boussinesq_stationary_site_inventory/bouss_stationary_site_inventory_summary.md`.
- historical map/HTML artifacts under
  `docs/_dev_notes/diagnostics/boussinesq_stationary_site_inventory/selections/`,
  when regenerated from older revisions.

The diagnostics directory is intentionally git-ignored; regenerate the CSV/JSON
artifacts with the script when needed.

The map artifacts use the standard HydroModPy matplotlib map styling from
`hydromodpy.display._map_axes.style_map_axes`. The selected-site HTML is not a
global index: it is written under `selections/<selection_id>/index.html`.
Images in the page are clickable and open the full-resolution PNG. The map uses
relative coordinates in kilometres. Site geometry is reconstructed from bundle
`edges.csv` rows with `edge_kind=boundary`, with a `nodes.csv` bounding-box
fallback when boundary edges are unavailable. The regional background uses the
topography and valid-data contour of
`examples/data/dem/DEM_armorican_massif.tif`; the GeoJSON remains in Lambert-93
coordinates (`EPSG:2154`).

## Current coverage

| scale | inventory sites | regional-lab sites | preflight mesh sites | existing child sites | mesh-gallery sites | hetero-ready sites | hetero-ready variants | gap to 10 hetero-ready sites |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 10km2 | 13 | 8 | 13 | 8 | 5 | 8 | 8 | 2 |
| 100km2 | 10 | 9 | 10 | 0 | 10 | 6 | 6 | 4 |
| 1000km2 | 5 | 0 | 5 | 0 | 5 | 2 | 2 | 8 |

## Interpretation

The current regional-lab catalog is sufficient to start broader N1 tests, but
not enough to claim ten heterogeneous ready sites at each scale:

- N1 10 km2: eight regional-lab Boussinesq child bundles are ready; seven have
  heterogeneous K and one is effectively homogeneous, plus one hetero-ready
  Strahler-3 mesh-gallery site.
- N2 100 km2: ten candidate sites exist after adding the mesh-gallery-only
  `s3_100km2_outlet_2`, but only six mesh-gallery bundles are Boussinesq
  steady-ready and heterogeneous.
- 1000 km2: five mesh-gallery candidate sites exist; only two are currently
  steady-ready and heterogeneous.

## Next step

Before launching a ten-site-per-scale strict `drain_00` campaign, promote the
selected `mesh_gallery_only` rows into `natural_regional_lab_sites.csv`, or
regenerate that catalog from the upstream site-selection table using the
regional-lab bootstrap path. The next preflight should reject non-ready bundles
before computation and should keep the heterogeneous-K criterion explicit.
