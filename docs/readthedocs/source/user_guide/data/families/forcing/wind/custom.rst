Wind Source: custom
===================

Use ``source = "custom"`` for local wind fields or station series.

.. code-block:: toml

   [[data.wind.sources]]
   source = "custom"
   path = "data/wind/wind.nc"
   source_unit = "m/s"

Check units, date coverage, and spatial support before mixing wind with other
climate variables.
