Temperature
===========

``temperature`` loads air-temperature forcing and climate context.

Accepted sources
----------------

- :doc:`custom`
- :doc:`sim2`

.. code-block:: toml

   [[data.temperature.sources]]
   source = "sim2"
   extent = "watershed"

Check period coverage, units, and spatial support before using temperature in
preprocessing or reporting.

.. toctree::
   :maxdepth: 1

   custom
   sim2
