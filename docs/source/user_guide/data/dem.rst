DEM
===

``dem`` loads the elevation support used by watershed delineation, terrain
inspection, raster alignment, and many spatial diagnostics. It is usually the
first data family to check because CRS, extent, outlet position, and mask
alignment problems often become visible on the DEM panel.

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
   * - ``ign_bdalti``
     - The project should retrieve IGN BD ALTI coverage from the configured
       spatial window.
     - ``ign-bdalti``

Minimal example
---------------

.. code-block:: toml

   [data]
   types = ["dem"]

   [[data.dem.sources]]
   source = "ign_bdalti"
   extent = "watershed"
   # Optional for regional workflows:
   # regions = ["Auvergne-Rhone-Alpes"]

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
   vector hydrography layer in the same projected CRS?

Downstream uses
---------------

- watershed and study-area support;
- terrain-derived masks and raster alignment;
- mesh and overview context;
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


DEM Source: ign_bdalti
^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "ign_bdalti"`` when the project should retrieve public IGN BD
ALTI elevation data from the configured spatial support.

Minimal example
"""""""""""""""

.. code-block:: toml

   [[data.dem.sources]]
   source = "ign_bdalti"
   extent = "watershed"

Operational checks
""""""""""""""""""

- ``extent`` should match the support needed by the workflow:
  ``watershed`` for basin runs, ``study_area`` for broader preprocessing.
- ``regions`` can be used for French regional workflows; HydroModPy resolves
  the corresponding departments before downloading IGN archives.
- API-backed files should be visible in the workspace data cache when a
  workspace is active.
- Rebuild or refresh only when the configured extent or data policy changes.
- ``ign_bdalti`` currently resolves BD ALTI 25 m archives by department,
  extracts ASC tiles, and writes a merged GeoTIFF clipped to the requested
  support.

Expected figure
"""""""""""""""

The expected visual result is the same DEM support panel used by custom DEMs:
terrain, watershed boundary, and outlet context must be spatially coherent.


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
     --departements 01 03 07 15 26 38 42 43 63 69 73 74 \
     --dataset bd-alti \
     --resolution 25 \
     --format ASC \
     --dry-run

Cache layout
""""""""""""

The helper stores raw archives by dataset, resolution, and department:

.. code-block:: text

   ~/hydromodpy/data/dem/raw_ign/
     bd-alti/
       25m/
         D029/
           BDALTIV2_...D029....7z

For regional ``site_selection`` review maps, BD ALTI 25 m is the recommended
default. RGE ALTI 5 m or 1 m should be reserved for smaller local extents
unless the storage and processing cost has been accepted explicitly.
