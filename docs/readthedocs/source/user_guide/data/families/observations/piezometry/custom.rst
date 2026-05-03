Piezometry Source: custom
=========================

Use ``source = "custom"`` when local piezometer files should be trusted over
public discovery.

Minimal example
---------------

.. code-block:: toml

   [[data.piezometry.sources]]
   source = "custom"
   path = "data/piezometry"
   col_id = "station"
   col_x = "x"
   col_y = "y"
   default_crs = "EPSG:2154"
   col_datetime = "date"
   col_value = "level"

Operational checks
------------------

- State whether the value is a level or a depth before using it as a head
  target.
- Keep station CRS and vertical datum assumptions explicit.
- Inspect the rendered chronicle for gaps and physically impossible jumps.
