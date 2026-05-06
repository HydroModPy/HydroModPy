Temperature
===========

``temperature`` loads air-temperature forcing and climate context.

Accepted sources
----------------

- ``custom``
- ``sim2``

.. code-block:: toml

   [[data.temperature.sources]]
   source = "sim2"
   extent = "watershed"

Check period coverage, units, and spatial support before using temperature in
preprocessing or reporting.

Visual check
------------

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 temperature monthly summary
   :width: 100%

   Temperature is usually context or preprocessing input. The useful first
   diagnostic is therefore a period and seasonal-cycle check, not a solver
   result.

Temperature Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local temperature fields or station series.

.. code-block:: toml

   [[data.temperature.sources]]
   source = "custom"
   path = "data/temperature/temperature.nc"
   source_unit = "degC"

Check units, time zone assumptions for point data, period coverage, and spatial
alignment.


Temperature Source: sim2
^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 temperature fields.

.. code-block:: toml

   [[data.temperature.sources]]
   source = "sim2"
   extent = "watershed"

Inspect the climatic summary to verify the requested time window and aggregate
temperature behavior.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 replay with monthly temperature summary
   :width: 100%

   The temperature replay is a period and seasonal-cycle check. It documents
   the provider payload before temperature is reused as context or
   preprocessing input.
