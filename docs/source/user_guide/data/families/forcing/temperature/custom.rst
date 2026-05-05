Temperature Source: custom
==========================

Use ``source = "custom"`` for local temperature fields or station series.

.. code-block:: toml

   [[data.temperature.sources]]
   source = "custom"
   path = "data/temperature/temperature.nc"
   source_unit = "degC"

Check units, time zone assumptions for point data, period coverage, and spatial
alignment.
