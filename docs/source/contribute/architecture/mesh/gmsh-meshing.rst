Conformal Gmsh meshing
======================

Architecture note: three concepts cooperate to produce a 2D mesh that
conforms to geological zones and the hydrographic network.

1. Hydrographic-network extraction from the DEM (Whitebox backend).
2. In-memory river trace exposed to the mesher.
3. Conformal Gmsh generation against the interfaces.

For the data structures shared by every mesh type, see
:doc:`mesh-pivot`.

Hydrographic network extraction
-------------------------------

Module: ``hydromodpy/spatial/geographic/core/river_network.py``.

Trigger: ``geographic.river_network.enabled = true``. The geographic
pipeline then produces a generated network that feeds the canonical
``HydrographicNetwork(role="generated")`` concept. Files written under
``.hmp/scratch/<run>/_preprocessing/geographic/``:

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

- DEM (corrected via ``fill``, ``breach`` or ``capped_breach``).
- Outlet, snapped on accumulation.
- D8 direction and accumulation rasters.

Backend: ``WhiteboxWorkflowsBackend``
(``hydromodpy/spatial/delineation/whitebox_workflows_backend/``).
Other backends must register explicitly through ``register_backend()``.

The switches are the keys of ``[geographic.river_network]``, among them
:toml:`geographic.river_network.enabled`, :toml:`geographic.river_network.threshold_mode`
and :toml:`geographic.river_network.prune_short_streams`. Their types, defaults and units
are in the generated reference.

Internal conversion:
``threshold_cells = threshold_area_km2 * 1e6 / dem_res_m**2``.

In-memory river trace
---------------------

Class: ``RiverMeshTrace``
(``hydromodpy/spatial/geographic/core/river_mesh_trace.py``).

Exposed through
``GeographicDerivedFeatures.rivers.river_mesh_trace`` or passed as an
explicit ``river_trace`` to the meshing case. The trace is already reprojected
into the domain CRS and clipped to the catchment. No disk re-read happens
during meshing unless ``rivers.source = "file"`` is selected, and that file
then wins over a trace passed in.

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

Conformal Gmsh generation
-------------------------

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

Constraint modes, set by :toml:`mesh_catchment.constraints_mode`:

- ``rivers_only``: conformity to the river traces, no lithology constraint;
- ``geology_only``: conformity to the geology interfaces only;
- ``geology_rivers``: both sets of constraints in one mesh (the default).

The mesh contract
-----------------

The runtime mesh is configured by ``[mesh_catchment]`` (the model is
``MeshCatchmentConfig`` in ``hydromodpy/spatial/mesh/config/main.py``). Its sub-tables
cover the domain (:toml:`mesh_catchment.domain`), the river constraints
(:toml:`mesh_catchment.rivers`), the geology (:toml:`mesh_catchment.geology`), the
watershed boundary (:toml:`mesh_catchment.watershed_boundary`), the Gmsh settings
(:toml:`mesh_catchment.zone_meshing`), lake and zone refinement
(:toml:`mesh_catchment.lake_refinement`, :toml:`mesh_catchment.refinement_zone`) and the
hydraulic properties carried by the mesh. A precomputed mesh is read through
``[mesh_input]`` instead (:toml:`mesh_input.mesh_path`, :toml:`mesh_input.bundle_dir`).
The generated reference lists every key with its type, default and unit.

Reading and projection
----------------------

The produced mesh is read through ``GmshPlanarMesh2D.from_file(...)``.
``Field`` and ``FieldParam`` projection stays in the existing modules
(``Field.on_mesh``, ``FieldParam.to_mesh_field``). On a conformal mesh
the number of mixed cells drops sharply; the projection logic remains
unchanged so it can also handle non-strictly-conformal supports.

Quality criteria
----------------

Output ``*_summary.json`` with:

- River conformity: fraction of river length coincident with mesh
  edges.
- Refinement gradient: median size in a near-river buffer compared to
  the size outside.
- Domain coverage: ``|mesh_area - domain_area|`` under tolerance.
- Numerical stability: total cell count within the expected range.
- Lithology conformity, if enabled: drop in mixed-cell count.
- Reproducibility: stable signature across identical runs.

Validation and tests
--------------------

Non-regression tests:

- ``tests/unit/backends/test_whitebox_workflows_backend.py`` for
  ``extract_streams``, ``raster_streams_to_vector``,
  ``strahler_stream_order``, ``stream_link_identifier``,
  ``remove_short_streams``.
- ``tests/unit/geographic/test_river_network_*.py`` for the core
  layer and the signature golden.
- ``tests/regression/extensive/`` for end-to-end cases.

Deterministic helper:
``tests/_helpers/whitebox.py::configure_whitebox_single_thread`` to
stabilise CI runs.

Structuring decisions
---------------------

- The hydrographic network is produced by ``geographic``, exposed by
  ``DomainGeographicContext``, and consumed by ``zone_meshing``.
- ``Domain`` does not carry meshing logic; it remains the business
  support for parameters (``FieldParam``).
- The two paths (read an existing mesh, generate a conformal mesh)
  converge on ``GmshPlanarMesh2D`` plus a metadata sidecar.

See also
--------

- :doc:`mesh-pivot` for the mesh-pivot architecture and the
  cross-mesh data structures.
- :doc:`index` for the broader mesh architecture and the
  catchment-mesh workflow.
