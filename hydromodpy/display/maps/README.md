# display/maps

The tools every map figure uses. None of them imports a figure, so a figure, the
run comparison and the calibration report can all draw with them.

| file | what it does |
|---|---|
| `axes.py` | axes in meters or in relative kilometers, the date axis of a time series, the label sizes of a map, and the catchment of a run (`watershed_of`, `overlay_watershed_contour`) |
| `mesh_geometry.py` | the polygon, the centroid and the area of each mesh face |
| `ugrid.py` | `render_face_field`, one value per face drawn as coloured polygons; `last_timestep` |
| `overlays.py` | the named layers drawn on top of a map: watershed, seepage, particles, network, wells, outlet |
| `transect.py` | a field sampled along a line, for the cross sections |
| `geo.py` | a scale bar and a north arrow for a vector map on metric axes |

A map is drawn in the CRS of the mesh, which is projected and in meters. A vector
layer in another CRS is put in meters by
`hydromodpy.core.io.crs.project_gdf_for_metric_operations` before it is drawn or
measured.

A layer that a run cannot feed raises `OverlayUnavailable` in `overlays.py`. The
layer is then skipped and the map is still drawn, so one `[display]` section works
across runs with different processes.
