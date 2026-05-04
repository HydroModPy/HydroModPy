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
     - :doc:`custom`
   * - ``ign_bdalti``
     - The project should retrieve IGN BD ALTI coverage from the configured
       spatial window.
     - :doc:`ign-bdalti`

Minimal example
---------------

.. code-block:: toml

   [data]
   types = ["dem"]

   [[data.dem.sources]]
   source = "ign_bdalti"
   extent = "watershed"

Loaded shape
------------

The loaded DEM is an elevation raster clipped or resolved on the requested
support. Downstream code expects a consistent CRS, a readable affine transform,
and non-empty elevation values over the basin.

Visual check
------------

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_map_dem.png
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

.. toctree::
   :maxdepth: 1

   custom
   ign-bdalti
