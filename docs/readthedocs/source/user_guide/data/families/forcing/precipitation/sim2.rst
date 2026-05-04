Precipitation Source: sim2
==========================

Use ``source = "sim2"`` to retrieve SIM2 precipitation fields.

.. code-block:: toml

   [[data.precipitation.sources]]
   source = "sim2"
   components = ["liquid", "solid", "total"]
   extent = "watershed"

Inspect the climatic summary to verify that the requested period and selected
components are available.

Provider replay
---------------

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 replay with monthly precipitation summary
   :width: 100%

   The monthly precipitation panel is the first provider replay to inspect
   before comparing precipitation with recharge, runoff, or solver budgets.
