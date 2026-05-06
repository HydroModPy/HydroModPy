Soil Moisture
=============

``soil_moisture`` loads soil-moisture fields or time series.

Accepted sources
----------------

- ``custom``
- ``sim2``

.. code-block:: toml

   [[data.soil_moisture.sources]]
   source = "sim2"
   extent = "watershed"

Check period coverage, unit convention, and whether the data are used as a
diagnostic or preprocessing input.

Soil Moisture Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local soil-moisture fields or station series.

.. code-block:: toml

   [[data.soil_moisture.sources]]
   source = "custom"
   path = "data/soil_moisture/soil_moisture.nc"

Check whether values are fractions, percentages, or volumetric water content
before using them.


Soil Moisture Source: sim2
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 soil-moisture fields.

.. code-block:: toml

   [[data.soil_moisture.sources]]
   source = "sim2"
   extent = "watershed"

Use the climatic summary as the first visible check.
