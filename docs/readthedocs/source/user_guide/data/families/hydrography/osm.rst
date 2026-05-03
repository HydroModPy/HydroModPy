Hydrography Source: osm
=======================

Use ``source = "osm"`` when OpenStreetMap waterway geometries are acceptable
for screening, teaching, or projects where a public local reference is not
available.

Minimal example
---------------

.. code-block:: toml

   [[data.hydrography.sources]]
   source = "osm"
   waterway_types = ["river", "stream"]

Operational checks
------------------

- ``waterway_types`` controls which OSM waterway classes are retained.
- OSM completeness can vary by region, so visual inspection is mandatory.
- Avoid treating OSM density as a hydrological truth without local validation.

Gallery status
--------------

No dedicated committed OSM figure is currently available. Until one is added,
use the generic hydrography panel as the visual contract and document the
provider choice in the case narrative.
