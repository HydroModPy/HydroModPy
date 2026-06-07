Humidity
========

``humidity`` loads relative-humidity forcing and climate context.

Accepted sources
----------------

- ``custom``
- ``sim2``

.. code-block:: toml

   [[data.humidity.sources]]
   source = "sim2"
   extent = "watershed"

Check units, period coverage, and spatial alignment with the other forcing
families.

Humidity Source: custom
^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local humidity fields or station series.

.. code-block:: toml

   [[data.humidity.sources]]
   source = "custom"
   path = "data/humidity/humidity.nc"
   source_unit = "%"

Check whether values are fractions or percentages before any preprocessing
uses them.


Humidity Source: sim2
^^^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 humidity fields.

.. code-block:: toml

   [[data.humidity.sources]]
   source = "sim2"
   extent = "watershed"

Use the climatic summary as the first visible check.
