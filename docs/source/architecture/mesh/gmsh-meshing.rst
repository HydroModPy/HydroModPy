Conformal Gmsh Meshing
======================

Architecture note: three concepts cooperate to produce a 2D mesh that
conforms to geological zones and the hydrographic network.

1. Hydrographic-network extraction from the DEM (Whitebox backend).
2. In-memory river trace exposed to the mesher.
3. Conformal Gmsh generation against the interfaces.

For the data structures shared by every mesh type, see
:doc:`mesh-pivot`.

1. Hydrographic-network extraction
----------------------------------

Module: ``hydromodpy/spatial/geographic/core/river_network.py``.

Trigger: ``geographic.river_network.enabled = true``. The geographic
pipeline then produces a generated network that feeds the canonical
``HydrographicNetwork(role="generated")`` concept. Files written under
``results_stable/geographic/``:

- ``river_streams.tif``: raster of stream cells.
- ``river_streams_pruned.tif``: same, after optional pruning.
- ``river_stream_order_strahler.tif``: Strahler order.
- ``river_stream_link_id.tif``: stream-link identifier.
- ``river_network.shp``: vector version clipped to the catchment
  (legacy filename kept).
- ``river_network_summary.json``: reproducibility metrics (legacy
  filename kept).

Contracts to keep distinct:

- ``HydrographicNetwork``: shared concept across storage, display, and
  comparison.
- ``RiverNetworkProducts``: technical bundle produced by the geographic
  preprocessing.
- ``RiverMeshTrace``: reduced projection consumed by the mesher.

Required inputs:

- DEM (corrected via ``fill`` or ``breach``).
- Outlet, snapped on accumulation.
- D8 direction and accumulation rasters.

Backend: ``WhiteboxWorkflowsBackend``
(``hydromodpy/spatial/delineation/whitebox_workflows_backend.py``).
Other backends must register explicitly through ``register_backend()``.

TOML parameters:

.. code-block:: toml

   [geographic.river_network]
   enabled = true
   threshold_mode = "area_km2"      # or "cells"
   threshold_area_km2 = 0.5
   prune_short_streams = false
   min_stream_length_m = 0.0
   compute_strahler_order = true
   compute_stream_links = true

Internal conversion:
``threshold_cells = threshold_area_km2 * 1e6 / dem_res_m**2``.

2. In-memory river trace
------------------------

Class: ``RiverMeshTrace``
(``hydromodpy/spatial/geographic/core/river_mesh_trace.py``).

Exposed through
``GeographicDerivedFeatures.rivers.river_mesh_trace`` or passed as an
explicit ``river_trace`` to the meshing case. The trace is already reprojected
into the domain CRS and clipped to the catchment. No disk re-read happens
during meshing unless ``rivers.source = "file"`` is selected.

Fields:

- ``source_kind``: ``geographic_generated``, ``hydrography_loaded``,
  ``file``.
- ``crs_wkt``: target CRS.
- ``lines``: tuple of Shapely ``LineString``.
- ``segment_count`` and ``total_length_m``: control metrics.

Structuring rule: the hydrographic network is not a domain zone. Mesh
generation stays in ``zone_meshing``, the domain business logic stays
in ``spatial/domain/``, and the central concept shared across layers
remains ``HydrographicNetwork``.

3. Conformal Gmsh generation
----------------------------

Module: ``hydromodpy/spatial/mesh/gmsh_grid/zone_meshing/``.

Main entry point: ``conformal.py``. Pipeline:

1. Load the zone polygons and the domain.
2. Geometric cleaning (``_geometry_cleaning.py``,
   ``_polygon_cleaning.py``): ``make_valid``, simplification, snapping,
   sliver removal.
3. Non-overlapping planar partition (``_partition_builder.py``,
   ``_partition_split.py``), with overlap resolution through a
   priority field.
4. Translation to Gmsh OCC geometry (``_gmsh_occ.py``): points, curves,
   loops, surfaces.
5. Size fields (``_gmsh_fields.py``): global, refinement around
   interfaces, around small zones, around rivers.
6. ``.msh`` export (``_gmsh_export.py``) and metadata sidecar
   (``_summary_sidecar.py``).

Physical groups created:

- ``zone::<zone_key>`` on surfaces.
- ``interface::<zone_a>::<zone_b>`` on internal lines.
- ``boundary::<name>`` on external contours.

Available modes:

- ``river_only``: hydrographic-network conformity, no lithology
  constraint.
- ``river_plus_lithology``: simultaneous conformity to lithology
  interfaces and rivers.

4. TOML mesh contract
---------------------

.. code-block:: toml

   [mesh]
   enabled = true
   backend = "gmsh"
   mode = "river_conformal"          # or "river_lithology_conformal"

   [mesh.domain]
   kind = "vector"                    # "bbox" | "polygon" | "vector"
   path = "..."
   id_field = "domain_id"
   selected_id = "main"

   [mesh.river.source]
   origin = "geographic_generated"    # "hydrography_loaded" | "file"
   path = null                        # required if origin="file"

   [mesh.gmsh]
   algorithm = "delaunay"
   global_size = 250.0
   min_size = 80.0
   max_size = 500.0

   [mesh.gmsh.river_refinement]
   enabled = true
   river_size = 60.0
   river_distance = 400.0
   river_sampling = 96

   [mesh.runtime]
   use_in_memory_river_trace = true
   persist_mesh_inputs = false

   [mesh.lithology]
   enabled = false
   source_mode = "geology_data_manager"

5. Reading and projection
-------------------------

The produced mesh is read through ``GmshPlanarMesh2D.from_file(...)``.
``Field`` and ``FieldParam`` projection stays in the existing modules
(``Field.on_mesh``, ``FieldParam.to_mesh_field``). On a conformal mesh
the number of mixed cells drops sharply; the projection logic remains
unchanged so it can also handle non-strictly-conformal supports.

6. Quality criteria
-------------------

Output ``*_summary.json`` with:

- River conformity: fraction of river length coincident with mesh
  edges.
- Refinement gradient: median size in a near-river buffer compared to
  the size outside.
- Domain coverage: ``|mesh_area - domain_area|`` under tolerance.
- Numerical stability: total cell count within the expected range.
- Lithology conformity, if enabled: drop in mixed-cell count.
- Reproducibility: stable signature across identical runs.

7. Validation and tests
-----------------------

Non-regression tests:

- ``tests/unit/backends/test_whitebox_workflows_backend.py`` for
  ``extract_streams``, ``raster_streams_to_vector``,
  ``strahler_stream_order``, ``stream_link_identifier``,
  ``remove_short_streams``.
- ``tests/unit/geographic/test_river_network_*.py`` for the core
  layer and the signature golden.
- ``tests/regression/extensive/`` for end-to-end cases.

Deterministic helper:
``tests/support/whitebox.py::configure_whitebox_single_thread`` to
stabilise CI runs.

8. Structuring decisions
------------------------

- The hydrographic network is produced by ``geographic``, exposed by
  ``DomainGeographicContext``, and consumed by ``zone_meshing``.
- ``Domain`` does not carry meshing logic; it remains the business
  support for parameters (``FieldParam``).
- The two paths (read an existing mesh, generate a conformal mesh)
  converge on ``GmshPlanarMesh2D`` plus a metadata sidecar.
- Triangles are the target of the first iteration; quadrilateral
  recombination will follow if needed.

See also
--------

- :doc:`mesh-pivot` for the mesh-pivot architecture and the
  cross-mesh data structures.
- :doc:`index` for the broader mesh architecture and the
  catchment-mesh workflow.
