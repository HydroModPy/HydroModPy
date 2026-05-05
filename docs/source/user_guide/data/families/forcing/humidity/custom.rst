Humidity Source: custom
=======================

Use ``source = "custom"`` for local humidity fields or station series.

.. code-block:: toml

   [[data.humidity.sources]]
   source = "custom"
   path = "data/humidity/humidity.nc"
   source_unit = "%"

Check whether values are fractions or percentages before any preprocessing
uses them.
