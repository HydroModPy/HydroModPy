Oceanic Source: shom
====================

Use ``source = "shom"`` when SHOM sea-level observations should be discovered
or downloaded for a coastal project.

Minimal example
---------------

.. code-block:: toml

   [[data.oceanic.sources]]
   source = "shom"
   extent = "study_area"
   nearest = true

Operational checks
------------------

- ``nearest`` can help select a usable tide-gauge station near the study area.
- ``fallback_search_radius_km`` should be documented when it changes station
  selection.
- Preserve cache and lockfile metadata for reproducibility.
- Always record the vertical datum assumption before mapping values to a
  boundary stage.

Provider replay
---------------

.. figure:: /_static/user_guide/data/shom_provider_replay_example.png
   :alt: SHOM provider replay for one coastal sea-level station
   :width: 100%

   This replay uses committed sample artifacts rather than a live SHOM request.
   It shows the two checks that a future coastal gallery case should keep on
   the same page: station selection and boundary-stage chronicle.
