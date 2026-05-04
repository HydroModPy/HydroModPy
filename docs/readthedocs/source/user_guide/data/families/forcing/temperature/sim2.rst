Temperature Source: sim2
========================

Use ``source = "sim2"`` to retrieve SIM2 temperature fields.

.. code-block:: toml

   [[data.temperature.sources]]
   source = "sim2"
   extent = "watershed"

Inspect the climatic summary to verify the requested time window and aggregate
temperature behavior.

Provider replay
---------------

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 replay with monthly temperature summary
   :width: 100%

   The temperature replay is a period and seasonal-cycle check. It documents
   the provider payload before temperature is reused as context or
   preprocessing input.
