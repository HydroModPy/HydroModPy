Wind
====

``wind`` loads wind forcing and climate context.

Accepted sources
----------------

- ``custom``
- ``sim2``

.. code-block:: toml

   [[data.wind.sources]]
   source = "sim2"
   extent = "watershed"

Check unit convention, period coverage, and whether the variable is being used
only for reporting or for a preprocessing chain.

Wind Source: custom
^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local wind fields or station series.

.. code-block:: toml

   [[data.wind.sources]]
   source = "custom"
   path = "data/wind/wind.nc"
   source_unit = "m/s"

Check units, date coverage, and spatial support before mixing wind with other
climate variables.


Wind Source: sim2
^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 wind fields.

.. code-block:: toml

   [[data.wind.sources]]
   source = "sim2"
   extent = "watershed"

Use the climatic summary as the first visible check.
