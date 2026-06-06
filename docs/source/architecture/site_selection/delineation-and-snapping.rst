Delineation and Snapping
========================

The delineation phase turns candidate outlets into catchment artifacts. It is a
thin adapter over the existing geographic DEM utilities; ``site_selection`` does
not reimplement flow direction, flow accumulation, or watershed extraction.

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

Failure Is an Audit Record
--------------------------

``try_delineate_candidate_outlet`` catches exceptions and returns a
``DelineatedCatchment`` with ``status = "rejected_delineation_failed"``. The
selection phase then rejects it at the ``delineation`` stage and writes the
failure reason into the decision record.

This is intentional: a failed basin should be visible in the audit trail rather
than disappearing from the run.

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

Display Coordinates
-------------------

Later map and spatial-selection code uses ``outlet_display_xy``:

- if the delineation wrote a snapped outlet geometry, display that point;
- otherwise display the original candidate coordinate.

This keeps selected outlet exports aligned with the actual DEM delineation
where snapping occurred, while preserving original candidate coordinates in
properties for review.

Cleanup Contract
----------------

After outputs and manifests are written, the build pipeline calls
``cleanup_site_selection_intermediate_rasters`` unless
``site_selection.output.keep_intermediate_rasters`` is true. Cleanup runs after
manifest/report assembly so declared final artifacts are not removed.

Tests that inject lightweight builders should preserve this order: build,
select, write outputs, write manifest/report, then cleanup.
