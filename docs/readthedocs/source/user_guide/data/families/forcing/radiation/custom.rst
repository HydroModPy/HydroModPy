Radiation Source: custom
========================

Use ``source = "custom"`` for local radiation fields or station series.

.. code-block:: toml

   [[data.radiation.sources]]
   source = "custom"
   path = "data/radiation/radiation.nc"
   components = ["atmospheric"]

Check component names, units, date coverage, and spatial support.
