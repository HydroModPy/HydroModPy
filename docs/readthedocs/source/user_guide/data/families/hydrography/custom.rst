Hydrography Source: custom
==========================

Use ``source = "custom"`` when a local river-network layer should be trusted
over public providers.

Minimal example
---------------

.. code-block:: toml

   [[data.hydrography.sources]]
   source = "custom"
   path = "data/hydrography/rivers.gpkg"
   rasterize_field = "FID"

Operational checks
------------------

- The network CRS must match or be safely reprojectable to the project CRS.
- The layer should cover the modeled basin and its outlet neighborhood.
- ``rasterize_field`` should identify stable features when raster products are
  generated.
- A correct file path is not enough; inspect the map overlay.
