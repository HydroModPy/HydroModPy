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

Provider replay
---------------

.. figure:: /_static/user_guide/data/hydrography_provider_replay_examples.png
   :alt: Hydrography provider replay including OSM
   :width: 100%

   The replay figure includes a committed OSM GPKG on the Couesnon bbox. It
   should be read as a provider payload check, not as proof that OSM is always
   complete enough for modeling.

Provider comparison
-------------------

.. figure:: /_static/user_guide/data/hydrography_provider_couesnon_comparison.png
   :alt: Couesnon hydrography comparison including OSM
   :width: 100%

   On this bbox, OSM contributes the densest small-stream network. That can be
   valuable for screening, but it also reinforces why OSM needs visual
   validation against local knowledge or an institutional reference before it
   becomes a modeling constraint.
