DEM Source: custom
==================

Use ``source = "custom"`` for a project-owned elevation raster. This is the
right choice for production studies, offline tests, training material, or any
case where the DEM has already been curated outside HydroModPy.

Minimal example
---------------

.. code-block:: toml

   [[data.dem.sources]]
   source = "custom"
   path = "data/dem/local_dem.tif"
   mask_path = "data/masks/watershed.gpkg"

Operational checks
------------------

- ``path`` is resolved from the TOML file, with workspace data fallbacks for
  bare filenames.
- ``mask_path`` can clip or validate the target support.
- The raster must carry usable CRS and geotransform metadata.
- Source units should be explicit if the file metadata are ambiguous.

Expected figure
---------------

Open the DEM overview panel from the family page and confirm that local terrain
and watershed support agree. A custom DEM should not require solver-side
compensation.
