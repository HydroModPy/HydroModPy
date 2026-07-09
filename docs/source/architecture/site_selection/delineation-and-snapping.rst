Delineation and Snapping
========================

The delineation phase turns candidate outlets into catchment artifacts. It is a
thin adapter over the existing geographic DEM utilities; ``site_selection`` does
not reimplement flow direction, flow accumulation, or watershed extraction.

What This Page Explains
-----------------------

The purpose of this phase is simple, even if the geospatial machinery behind it
is not: for each candidate outlet, HydroModPy must decide where the outlet
really sits on the hydrologic grid, then ask the DEM tools which upstream cells
drain to that point.

For a reviewer, this phase answers four practical questions:

- did the candidate point land on a plausible drainage path;
- did snapping move the point too far from the station or proposed outlet;
- did DEM delineation produce a readable watershed polygon;
- if it failed, is the failure visible in the audit trail.

The output of this phase is not yet a final selected site. It is a collection
of ``DelineatedCatchment`` records that the criteria engine can evaluate next.

End-to-End Picture
------------------

The same high-level path is used for station-led, CSV-led, and DEM-derived
candidates:

.. code-block:: text

   Candidate outlet
       |
       |  optional reference-network correction
       v
   Working outlet
       |
       |  local DEM snap inside dem_snap_max_distance_m
       v
   Snapped DEM outlet
       |
       |  flow direction + flow accumulation
       v
   Watershed raster/vector
       |
       |  area read from geometry
       v
   DelineatedCatchment
       |
       +-- status = delineated
       +-- or status = rejected_delineation_failed

The important mental model is that snapping and delineation are not selection
criteria by themselves. They produce the geometry and diagnostics that later
criteria can judge. A candidate can fail here because no basin can be
delineated, but a candidate that delineates successfully can still be rejected
later by area, observations, influence, geology, overlap, or quota rules.

Flow Products
-------------

The build functions call ``build_site_selection_flow_products`` from
``hydromodpy/spatial/site_selection/hydrology/flow_products.py``. That helper
delegates to ``build_regional_flow_products`` unless a test or caller injects a
custom builder.

The resulting ``SiteSelectionFlowProducts`` wraps the normal DEM products and
can serialize itself into the manifest. The manifest entry usually includes:

- the resolved calculation DEM path;
- the DEM source label;
- flow-direction and accumulation artifacts;
- whether intermediate rasters were kept;
- optional reference-network metadata.

DEM extent selection remains a workflow/data concern. The spatial build expects
the DEM path it receives to already represent the intended calculation extent.

In practice, a DEM source becomes useful for selection only after HydroModPy has
derived flow products from it:

.. code-block:: text

   calculation DEM
       |
       +-- flow direction raster
       |
       +-- flow accumulation raster
       |
       +-- optional in-memory arrays/backend handles

The flow-direction raster tells the extractor where each cell drains. The
flow-accumulation raster helps find a nearby hydrologically meaningful cell
when the candidate point is slightly off the drainage line. This is common with
station coordinates: the station point can be located on a bridge, bank,
administrative reference point, or provider geometry that is not exactly on the
DEM-derived stream cell.

Delineation Adapter
-------------------

``delineate_site_selection_candidates`` loops over candidates and calls
``try_delineate_candidate_outlet``. The one-candidate adapter:

#. optionally snaps the candidate to a reference network;
#. calls ``extract_catchment_from_point`` with flow accumulation and flow
   direction rasters;
#. reads the resulting watershed area from the vector output when possible;
#. returns a ``DelineatedCatchment`` record.

``DelineatedCatchment`` is the hand-off record for later phases. It stores the
original or adjusted outlet, the outlet shapefile, snapped outlet shapefile,
watershed raster, watershed vector, computed area, status, and failure reason.

One useful way to read this adapter is as a defensive wrapper around a lower
level geographic operation:

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Step
     - What the adapter passes in
     - What reviewers inspect later
   * - Outlet preparation
     - Candidate coordinates, CRS, optional reference network.
     - Original point, adjusted point, station-to-outlet displacement.
   * - DEM extraction
     - Flow direction, flow accumulation, snap radius, output directory.
     - Outlet snap point, watershed raster, watershed polygon.
   * - Area measurement
     - Watershed vector path.
     - ``area_km2`` used by area criteria and map styling.
   * - Error capture
     - Any exception from the extractor.
     - ``status`` and ``failure_reason`` in the audit outputs.

The adapter keeps the lower-level extractor reusable. Tests can inject a small
``delineation_builder`` or ``area_reader`` without loading a real DEM, while
production runs use the normal geographic implementation.

Failure Is an Audit Record
--------------------------

``try_delineate_candidate_outlet`` catches exceptions and returns a
``DelineatedCatchment`` with ``status = "rejected_delineation_failed"``. The
selection phase then rejects it at the ``delineation`` stage and writes the
failure reason into the decision record.

This is intentional: a failed basin should be visible in the audit trail rather
than disappearing from the run.

That distinction matters when reviewing a regional run. If a site disappears
before the decision table is written, it is hard to know whether the candidate
was never loaded, whether the DEM failed, or whether a criterion rejected it.
Here the failure becomes a normal rejected decision at the ``delineation``
stage. The reviewer sees the candidate id, the failure reason, and a blocking
flag tied to delineation rather than to a scientific criterion.

Snapping Strategies
-------------------

Two strategies exist at the site-selection level:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Strategy
     - Runtime behavior
   * - ``dem_accumulation``
     - Pass the candidate coordinate directly to the DEM catchment extractor,
       using ``dem_snap_max_distance_m`` as the local DEM snap radius.
   * - ``bdtopage_then_dem``
     - Snap the candidate to a reference network first, reject if the reference
       network is too far, then run the DEM catchment extractor from the
       adjusted coordinate.

The reference-network stage constrains candidate locations, but the final
watershed still comes from DEM flow products. BD Topage or a custom reference
network should therefore be treated as an outlet-location support, not as the
selected hydrologic network.

The two strategies are easier to compare as coordinate paths:

.. code-block:: text

   dem_accumulation
   ----------------

   candidate point
        |
        |  DEM snap within dem_snap_max_distance_m
        v
   final DEM outlet used for watershed extraction


   bdtopage_then_dem
   -----------------

   candidate point
        |
        |  reference-network snap within reference_network_snap_max_distance_m
        v
   reference-network outlet
        |
        |  DEM snap within dem_snap_max_distance_m
        v
   final DEM outlet used for watershed extraction

Use ``dem_accumulation`` when the DEM-derived drainage grid is the only
hydrologic support you want to trust. Use ``bdtopage_then_dem`` when the
candidate should first stay close to a known river network before entering the
DEM extractor. The second mode is useful for station-led French runs because
BD Topage can prevent a station from snapping to a nearby but wrong DEM branch.

The reference-network tolerance and the DEM snap radius answer different
questions:

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Parameter
     - Question answered
     - Typical review symptom
   * - ``reference_network_snap_max_distance_m``
     - Is the candidate close enough to the reference river network?
     - A large value can hide stations that are not actually near the intended
       river line.
   * - ``dem_snap_max_distance_m``
     - Once the working outlet is fixed, how far may the DEM extractor move it
       to find an accumulated cell?
     - A large value can shift the final basin downstream or to a neighboring
       branch.

Display Coordinates
-------------------

Later map and spatial-selection code uses ``outlet_display_xy``:

- if the delineation wrote a snapped outlet geometry, display that point;
- otherwise display the original candidate coordinate.

This keeps selected outlet exports aligned with the actual DEM delineation
where snapping occurred, while preserving original candidate coordinates in
properties for review.

For map reading, think of three possible points:

.. code-block:: text

   original candidate point
       |
       |  station/reference displacement, if any
       v
   working outlet
       |
       |  DEM snap displacement, if any
       v
   displayed/final outlet

The report should make the final outlet easy to find, because that is the
point that generated the watershed. The original point still matters for
traceability: if the displacement is unexpectedly large, the reviewer can go
back to station metadata, CRS, reference-network tolerance, or DEM resolution.

Reading the Outputs
-------------------

The delineation phase leaves evidence in several places. These are the first
artifacts to inspect when a basin looks wrong:

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Artifact or field
     - What it tells you
     - Typical use
   * - ``outlet_snap_shp``
     - Where the DEM extractor finally placed the outlet.
     - Check station-to-outlet displacement on the review map.
   * - ``watershed_shp``
     - The vector basin used for area and overlap rules.
     - Inspect basin shape and upstream extent.
   * - ``area_km2``
     - Area measured from the watershed vector.
     - Compare provider area and DEM-recomputed area.
   * - ``status``
     - Whether the basin delineated or failed.
     - Separate DEM failures from scientific rejections.
   * - ``failure_reason``
     - Exception text captured by the safe wrapper.
     - Diagnose missing rasters, bad CRS, or impossible extraction.

Common Review Questions
-----------------------

``The station is visible, but the basin starts downstream.``
   Check the reference-network distance, the DEM snap distance, and the
   snapped outlet geometry. If the DEM snap radius is too permissive, the
   extractor may find a stronger accumulated cell downstream.

``The basin is much smaller than expected.``
   Check whether the calculation DEM extent is too narrow. With
   ``candidate_outlets_bbox``, the buffer must include enough upstream area to
   delineate the full basin.

``The basin is absent but the candidate exists.``
   Look for ``status = "rejected_delineation_failed"`` and the
   ``failure_reason``. The candidate should still appear as rejected at the
   delineation stage.

``BD Topage appears to be changing the hydrology.``
   It should not. BD Topage only adjusts the working outlet before DEM
   extraction. The final watershed is still computed from DEM flow direction
   and accumulation.

Cleanup Contract
----------------

After outputs and manifests are written, the build pipeline calls
``cleanup_site_selection_intermediate_rasters`` unless
``site_selection.output.keep_intermediate_rasters`` is true. Cleanup runs after
manifest/report assembly so declared final artifacts are not removed.

Tests that inject lightweight builders should preserve this order: build,
select, write outputs, write manifest/report, then cleanup.
