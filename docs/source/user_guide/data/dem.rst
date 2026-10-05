DEM
===

``dem`` loads the elevation support used by watershed delineation, terrain
inspection, raster alignment, and many spatial diagnostics. It is usually the
first data family to check because CRS, extent, outlet position, and mask
alignment problems often become visible on the DEM panel.

Watershed delineation itself, including DEM depression correction
(``dem_correc_type``), is configured in the :doc:`[geographic] section
</user_guide/config_reference/geographic>`.

``dem_correc_type`` offers three ways to make the routing DEM drain. ``fill``
(the default) only raises cells: each closed depression is brought to its spill
level. ``breach`` mostly lowers cells: it carves a path through the barrier that
closes a depression, after raising single-cell pits to their lowest neighbour,
with no limit on its length or depth and no fill afterwards. ``capped_breach``
lowers and raises: it breaches only within a maximum depth and a maximum length,
both in metres (``[geographic.capped_breach]``, defaults 0.5 m and 200 m), then
fills the depressions those limits refused.

``max_depth`` bounds the cumulative lowering of one breach path (Whitebox's
``max_cost``), not the depth of one cell. Measured on the Flume at 25 m with
8-cell paths, the realised maximum lowering of a cell follows it within 0.01 m.
On a finer grid a thick embankment spreads the cost over more cells, so it is
filled instead of dug: the same values do not give the same landscape at every
resolution. Overlapping paths can also cut a cell deeper than ``max_depth``.
The engine measures what it dug, logs it, records it with the geographic
products, and warns when the maximum lowering exceeds ``max_depth``.
``max_distance`` is counted in cells along the path, a diagonal step counting
one cell, so a diagonal breach can be up to 1.41 times longer than
``max_distance``.

.. _the-ground:

The ground
----------

The DEM is not read as it comes once corrections are declared. The **ground** is
the DEM plus those corrections, each bounded and logged, and every surface reads
it: the routing chain (lake carve, depression correction, D8)
starts from the ground, and so does the model top. Both geographic entry points
build it the same way, so the flow routing and the aquifer never disagree about
a structure. With no correction declared the ground is the DEM file itself: no
copy is written and nothing changes.

Two corrections exist, applied in this order:

1. ``[geographic.dam_carve]`` lowers the dam footprint to the valley floor, so a
   cutoff wall sits at the true dam on a raw DEM.
2. ``[geographic.crossings]`` cuts the embankments of roads, railways and bridges
   along the generated channel. The channel tree is delineated a first time on
   the ground with the dam carved, the embankment is lowered where a structure
   crosses it, and the catchment is delineated again on the notched ground, then
   the lake capture pass runs if enabled.

The notch reads the bed level on the channel ``bed_reach`` metres upstream and
downstream of the crossing, and draws the straight line between the two levels.
Only the embankment span is lowered to that line: the run of channel pixels
around the crossing that stand above it. ``notch_width`` widens the cut across
that span, within ``notch_width / 2`` of its pixels, and never along the channel
past it; the two pixels where the bed is read are never touched. When a bed end
falls on the embankment of another crossing, it is read further along the
channel, beyond that embankment, so two structures close to each other do not
take each other's crest for the bed. A crossing whose ends cannot be found that
way is skipped and reported (``no_bed_end``).

The ground is never raised, no pixel is lowered by more than ``max_depth``, and
a point structure farther than ``snap_radius`` from the channel is ignored.
Weirs and dams are not notched: a weir is a drop of the bed, not a wall. A
crossing at a declared dam or weir is not notched either, since a road on a dam
crest is the dam: a ``dam`` or ``weir`` of the file within ``snap_radius`` of the
crossing, a ``[geographic.dam_carve]`` line within ``snap_radius``, or a
``[geographic.enforce_lakes]`` polygon touching the channel reach is skipped and
counted as ``dam_or_weir``. The structures come from the
:doc:`crossings <crossings>` data variable, which fills
``[geographic.crossings] path`` when it is left empty, or from a file named
there; a named file is checked like the variable (a ``kind`` column with one of
the six values, and a CRS). The notch needs ``[geographic.river_network]``
enabled, because it follows that tree.

One INFO line and ``dem_ground_crossings.json`` next to the corrected DEM
(``dem_ground.tif``, in the ``demcorrecflow`` folder of the geographic
products) record what was found per kind, what was notched, what was skipped
and why, the pixels lowered with their maximum and median lowering, the pixels
the cap held back, and the catchment area before and after the second
delineation. A run with no pixel lowered does not delineate twice.

A shared regional flow job (``reg_fold``) was routed on the raw DEM and cannot be
combined with either correction.

.. _the-channel-bed:

The channel bed of the model top
--------------------------------

Read along its own channel network, a DEM rises downstream at many pixels: a
deck, a hedge, a resampling artefact. A drain or a stream cell on such a rise
cannot drain into the next one. ``[geographic.bed_regularization]`` (off by
default) fits, on the pixels of the generated channel tree only, the bed closest
to the ground in least squares that never rises downstream: the isotonic
regression on a tree (Pardalos and Xue, 1999). It raises and lowers alike, so the
mean of the bed is kept. Every flat run of the fit then gets a minimum drop of
``min_slope`` per metre (``1e-4`` by default, the SFR default slope), centred on
the run's mean: a long flat is tilted about its level, not lifted by its length.
A closing pass raises the few nodes this leaves short of the minimum drop.

The tree is the channel network of ``[geographic.river_network]``, as pixels of
the whole DEM grid: its link raster (``dem_stream_link_id_full.tif``), else its
stream raster (pruned when ``prune_short_streams`` is on), each pixel draining to
the next one along the D8 pointer of the routing DEM. Every outlet is a root, so
each tree of the forest is fitted. Three things change the fit:

- the pixels inside a ``[geographic.enforce_lakes]`` polygon are **left out**:
  the lake keeps its surface, the reach entering it ends there, and the reach
  below its outlet is a tree of its own;
- the pixels a crossing notch lowered (the footprint the notch writes,
  ``dem_ground_notch_footprint.tif``) are **gaps**: their value is the line
  between the nearest measured bed upstream (on the larger branch) and
  downstream, and they carry a negligible weight in the fit;
- a ``weir`` or a ``dam`` of the crossings file **cuts** the tree at the channel
  pixel nearest to it within ``snap_radius``, unless it lies inside a lake
  polygon: both edges of that pixel are left free, so its drop is never smoothed
  away. The crossings file is ``[geographic.crossings] path``, else the file
  ``[[data.crossings.sources]]`` resolves, read whenever the regularisation is
  on, even with the notch off. With neither, the fit has no cut and says so in
  one INFO line. The notch itself stays governed by ``[geographic.crossings]
  enabled``.

The fit runs on the whole ground and writes its regularised copy,
``dem_ground_bed.tif``, next to it in the ``demcorrecflow`` folder. The three
clips the model top reads (``watershed_box_buff_dem_bed.tif`` and the same for
the ``watershed_buff`` and ``watershed`` clips) are cut from that copy by the
routine and the polygons that cut the clips of the ground, and the model top of
every grid is sampled from them: centroid, zonal (the channel minimum then falls
on the regularised bed) and structured alike. The stream reaches read their bed
on the same copy, so drains and stream reaches see one bed. The routing DEM, the
channel tree and the catchment are built before it and the mesh never reads it:
the mesh cache ignores the option, so a run that toggles it reuses the cached
mesh, and MODFLOW samples its top again on it, as on a ``[mesh_input]`` mesh.
The Boussinesq solver reads the top stored in the mesh bundle instead, so it
keeps the top the mesh was built with.

One INFO line and ``dem_ground_bed.json`` next to the copy record the channel
pixels, the lake pixels left out, the gaps and the cuts (with the climb left at
each cut), the pixels raised and lowered, the median and maximum change, the
mean bias, the rising edges before and after the fit (none after, off the cuts),
the largest lift of the minimum drop, the edges it leaves short and what the
closing pass raised, and every pooled block at a confluence (a junction pooled
with one of its upstream pixels) with its size, largest raise, largest lowering
and position, largest first. A real pool or a real step that no structure
declares is smoothed like noise. The option needs ``[geographic.river_network]``
enabled and a delineated catchment.

Accepted sources
----------------

.. list-table::
   :header-rows: 1
   :widths: 24 38 38

   * - Source
     - Use when
     - Source page
   * - ``custom``
     - A local raster is authoritative.
     - ``custom``
   * - ``ign_geoplateforme_dem``
     - A regional French workflow should discover, download, assemble, and
       cache public IGN DEM archives through Geoplateforme.
     - ``ign-geoplateforme-dem``

The complete ``[[data.dem.sources]]`` schema for both sources, field by field, is
defined in :ref:`the data reference <data-dem-sources>`.

Minimal example
---------------

.. code-block:: toml

   [data]
   types = ["dem"]

   [[data.dem.sources]]
   source = "ign_geoplateforme_dem"
   dataset = "bd-alti"
   resolution_m = 25.0
   file_format = "ASC"
   extent = "watershed"
   # Optional for regional workflows:
   # regions = ["Bretagne"]

Loaded shape
------------

The loaded DEM is an elevation raster clipped or resolved on the requested
support. Downstream code expects a consistent CRS, a readable affine transform,
and non-empty elevation values over the basin.

Visual check
------------

.. gallery-figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_dem.png
   :alt: Nancon DEM and watershed support
   :width: 100%

   The DEM check should make terrain, watershed boundary, and outlet context
   readable at the same time. If the basin is shifted, cropped, empty, or
   inverted, fix the DEM source before looking at solver settings.

Local spatial smoke test
------------------------

.. figure:: /_static/user_guide/data/spatial_local_dem_hydrography_example.png
   :alt: Local DEM and hydrography stack
   :width: 100%

   This generated data-doc figure is smaller than the Nancon overview and
   focuses on one practical question: does the raster support align with a
   vector :doc:`hydrography <hydrography>` layer in the same projected CRS?

Downstream uses
---------------

- watershed and study-area support;
- terrain-derived masks and raster alignment;
- mesh and overview context, since the :doc:`[mesh_catchment] launcher
  </user_guide/config_reference/mesh_catchment>` conforms its mesh to the same
  watershed support;
- solver figures that display head or water-table depth against terrain.

DEM Source: custom
^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for a project-owned elevation raster. This is the
right choice for production studies, offline tests, training material, or any
case where the DEM has already been curated outside HydroModPy.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.dem.sources]]
   source = "custom"
   path = "data/dem/local_dem.tif"
   mask_path = "data/masks/watershed.gpkg"

Operational checks
""""""""""""""""""

- ``path`` is resolved from the TOML file, with workspace data fallbacks for
  bare filenames.
- ``mask_path`` can clip or validate the target support.
- The raster must carry usable CRS and geotransform metadata.
- Source units should be explicit if the file metadata are ambiguous.

Expected figure
"""""""""""""""

Open the DEM overview panel from the family page and confirm that local terrain
and watershed support agree. A custom DEM should not require solver-side
compensation.

DEM Source: ign_geoplateforme_dem
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "ign_geoplateforme_dem"`` when a workflow should resolve French
administrative regions or departments, discover matching IGN archives through
Geoplateforme, assemble the DEM, and cache the processed GeoTIFF.

This source lives in the data layer. Workflows such as ``site_selection`` only
declare their DEM need through ``[data.dem]``; they do not call IGN services
directly.

Minimal example
"""""""""""""""

.. code-block:: toml

   [data]
   types = ["dem"]

   [[data.dem.sources]]
   source = "ign_geoplateforme_dem"
   dataset = "bd-alti"
   resolution_m = 25.0
   file_format = "ASC"
   regions = ["Auvergne-Rhone-Alpes"]

Operational checks
""""""""""""""""""

- ``regions`` are canonical French region names such as ``Bretagne``,
  ``Corse`` or ``Auvergne-Rhone-Alpes``. HydroModPy resolves the corresponding
  departments before download.
- ``departments`` can be used instead when the required support is known
  explicitly.
- ``dataset = "bd-alti"`` assembles the BD ALTI 25 m ASC archives of the
  departments, written as a clipped GeoTIFF in ``data/dem/processed``.
- The processed cache is keyed by bbox and departments and accompanied by a
  JSON metadata sidecar. Compatible processed rasters are reused without
  re-downloading raw archives.
- ``dataset = "rge-alti"`` assembles the RGE ALTI from the Geoplateforme
  WMS-Raster service, by extent, at 5 m (default) or 1 m (``resolution_m = 1``).
  No other size is accepted: the server resamples them with an undocumented
  kernel, whereas inland a 5 m request returns the centre pixels of the native
  1 m grid unchanged. Water (tidal areas, harbour basins), the cells the product
  does not cover and the pixels the server blends next to them are nodata; real
  land below -5 m, such as a quarry floor, is kept. A request above 150 million
  pixels is refused with its expected size (a 1 m box is limited to about 12 km
  a side), so 1 m cannot bootstrap a project from its outlet (the box around it
  is 60 km wide): use 5 m, or give ``[geographic].dem_init_path`` a file. The
  layer answers outside France with another, coarser source; the JSON sidecar
  counts the valid pixels outside the department outlines buffered by 1 km and a
  warning is logged above 1 %. ``departments``, ``regions``, ``file_format`` and
  ``crs`` do not apply to this dataset.

Cache layout
""""""""""""

The Geoplateforme source separates raw archives, extracted archive contents, and
processed GeoTIFFs:

.. code-block:: text

   <workspace>/data/dem/
     raw_ign/
       bd-alti/25m/D029/*.7z
     extracted_ign/
       D029_<hash>/
     processed/
       dem_ign_geoplateforme_bdalti_25m_<hash>.tif
       dem_ign_geoplateforme_bdalti_25m_<hash>.json
       dem_ign_geoplateforme_rgealti_5m_<hash>.tif
       dem_ign_geoplateforme_rgealti_5m_<hash>.json

For ``site_selection`` review maps, use BD ALTI 25 m as the default regional
background. Reference hydrography such as BD Topage may be used to constrain
outlet snapping, but it should not be displayed as a cartographic proof of the
selected basin network unless that is the explicit review objective.


French IGN archive helper
^^^^^^^^^^^^^^^^^^^^^^^^^

``tools/download_dem_fr`` is a standalone helper for preparing or diagnosing
French IGN DEM archives outside a full HydroModPy run. It is useful when a
regional workflow needs many departments, for example before producing a
regional review map.

The helper is intentionally separate from ``site_selection``. Workflows should
still request DEM data through ``[data.dem]``; the helper only manages raw
archive discovery/download.

By default, the helper writes raw IGN archives outside the source repository:
``HYDROMODPY_WORKSPACE/data/dem/raw_ign`` when ``HYDROMODPY_WORKSPACE`` is
defined, otherwise ``~/hydromodpy/data/dem/raw_ign``. Use ``--output-dir`` only
when an explicit data cache location is needed.

Examples
""""""""

Dry-run BD ALTI 25 m for one department:

.. code-block:: bash

   python tools/download_dem_fr/download_dem_fr.py \
     --departements 29 \
     --dataset bd-alti \
     --resolution 25 \
     --format ASC \
     --dry-run

Dry-run the Auvergne-Rhone-Alpes departments:

.. code-block:: bash

   python tools/download_dem_fr/download_dem_fr.py \
     --regions Auvergne-Rhone-Alpes \
     --dataset bd-alti \
     --resolution 25 \
     --format ASC \
     --dry-run

Show provider checksums in a dry-run when Geoplateforme exposes them:

.. code-block:: bash

   python tools/download_dem_fr/download_dem_fr.py \
     --departements 29 \
     --dataset bd-alti \
     --resolution 25 \
     --format ASC \
     --dry-run \
     --include-md5

Cache layout
""""""""""""

The helper stores raw archives by dataset, resolution, and department:

.. code-block:: text

   ~/hydromodpy/data/dem/raw_ign/
     bd-alti/
       25m/
         D029/
           BDALTIV2_...D029....7z

For regional ``site_selection`` review maps, BD ALTI 25 m is the default
assembled DEM. RGE ALTI 5 m or 1 m is also assembled by the data manager, from
WMS-Raster by extent (see the operational checks above); the helper only
inspects and downloads the raw RGE ALTI department archives, which are not
needed for that.
