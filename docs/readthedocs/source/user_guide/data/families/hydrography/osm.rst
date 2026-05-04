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

No dedicated committed OSM replay artifact is currently available. Until one
is added, use the generic hydrography panel as the visual contract and document
the provider choice in the case narrative.

.. figure:: /_static/user_guide/data/hydrography_provider_replay_examples.png
   :alt: Hydrography provider replay showing the current OSM gallery gap
   :width: 100%

   The replay figure marks the current OSM gap explicitly. The next stable OSM
   page should fetch one small bbox, persist the raw GPKG in the cache, record
   the lockfile identity, and compare network density against a local or BD
   Topage reference.
