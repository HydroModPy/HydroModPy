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

No dedicated committed EU-Hydro figure is currently available. A future
non-Nancon gallery case should isolate this provider the same way the current
BD Topage overlay isolates ``bdtopage``.
