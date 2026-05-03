Hydrometry Source: custom
=========================

Use ``source = "custom"`` when project-owned discharge station and chronicle
files should be authoritative.

Minimal example
---------------

.. code-block:: toml

   [[data.hydrometry.sources]]
   source = "custom"
   path = "data/hydrometry"
   col_id = "station"
   col_x = "lon"
   col_y = "lat"
   default_crs = "EPSG:4326"
   col_datetime = "date"
   col_value = "Q"
   station_ids = ["J1234010"]

Operational checks
------------------

- the location file must identify stations and coordinates;
- chronicle files must expose datetime and value columns;
- ``source_unit`` should be set when units are not self-evident;
- rendered hydrographs should be inspected before the data are used in a
  calibration objective.
