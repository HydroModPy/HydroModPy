Humidity
========

``humidity`` loads relative-humidity forcing and climate context.

Accepted sources
----------------

- :doc:`custom`
- :doc:`sim2`

.. code-block:: toml

   [[data.humidity.sources]]
   source = "sim2"
   extent = "watershed"

Check units, period coverage, and spatial alignment with the other forcing
families.

.. toctree::
   :maxdepth: 1

   custom
   sim2
