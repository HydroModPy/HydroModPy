Geology Source: custom
======================

Use ``source = "custom"`` when a local geology vector or raster is the
reference for the project.

Minimal example
---------------

.. code-block:: toml

   [[data.geology.sources]]
   source = "custom"
   path = "data/geology/geology.gpkg"
   code_field = "CODE_LEG"
   values_table_path = "data/geology/hydraulic_properties.csv"

Operational checks
------------------

- ``code_field`` must exist in the local layer and remain non-empty after
  clipping.
- ``values_table_path`` should use the same geology codes when properties are
  joined.
- CRS and geometry validity matter because geology can constrain meshes.
- Empty or unlabeled legend categories usually mean the code field or property
  join is wrong.

Expected figure
---------------

Inspect the geology panel with its legend, then inspect any derived
hydraulic-property transfer figure before trusting the layer in a model.
