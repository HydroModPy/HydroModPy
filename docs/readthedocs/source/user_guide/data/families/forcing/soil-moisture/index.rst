Soil Moisture
=============

``soil_moisture`` loads soil-moisture fields or time series.

Accepted sources
----------------

- :doc:`custom`
- :doc:`sim2`

.. code-block:: toml

   [[data.soil_moisture.sources]]
   source = "sim2"
   extent = "watershed"

Check period coverage, unit convention, and whether the data are used as a
diagnostic or preprocessing input.

.. toctree::
   :maxdepth: 1

   custom
   sim2
