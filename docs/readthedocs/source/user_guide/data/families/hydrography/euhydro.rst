Hydrography Source: euhydro
===========================

Use ``source = "euhydro"`` when EU-Hydro coverage is the intended
continental-scale river-network reference.

Minimal example
---------------

.. code-block:: toml

   [[data.hydrography.sources]]
   source = "euhydro"

Operational checks
------------------

- Check that the selected extent is large enough to retrieve the expected
  network around the basin.
- Compare network density with the modeling scale; continental products may be
  too coarse for small headwater studies.
- Inspect the river overlay before using the network as a mesh or drainage
  target.

Gallery status
--------------

No dedicated committed EU-Hydro replay artifact is currently available. A
future non-Nancon gallery case should isolate this provider the same way the
current BD Topage overlay isolates ``bdtopage``.

.. figure:: /_static/user_guide/data/hydrography_provider_replay_examples.png
   :alt: Hydrography provider replay showing the current EU-Hydro gallery gap
   :width: 100%

   The replay figure marks the current EU-Hydro gap explicitly. The stable
   version should use a bbox where a continental-scale river product is
   meaningful, then publish the cached provider payload and density comparison.
