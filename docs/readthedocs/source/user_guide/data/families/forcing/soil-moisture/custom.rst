Soil Moisture Source: custom
============================

Use ``source = "custom"`` for local soil-moisture fields or station series.

.. code-block:: toml

   [[data.soil_moisture.sources]]
   source = "custom"
   path = "data/soil_moisture/soil_moisture.nc"

Check whether values are fractions, percentages, or volumetric water content
before using them.
