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

Provider replay
---------------

.. figure:: /_static/user_guide/data/hydrography_provider_replay_examples.png
   :alt: Hydrography provider replay including EU-Hydro
   :width: 100%

   The replay figure includes a committed EU-Hydro GPKG on the Couesnon bbox.
   This keeps the provider visible in the documentation while making clear that
   it is coarser than local or national hydrography on small headwater windows.

Provider comparison
-------------------

.. figure:: /_static/user_guide/data/hydrography_provider_couesnon_comparison.png
   :alt: Couesnon hydrography comparison including EU-Hydro
   :width: 100%

   EU-Hydro retrieves fewer line features on this bbox. That is useful
   evidence: continental coverage is not automatically the right support for a
   small basin, and the comparison should be inspected before selecting it as a
   network reference.
