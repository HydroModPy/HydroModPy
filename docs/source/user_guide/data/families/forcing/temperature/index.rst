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

Visual check
------------

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 temperature monthly summary
   :width: 100%

   Temperature is usually context or preprocessing input. The useful first
   diagnostic is therefore a period and seasonal-cycle check, not a solver
   result.

.. toctree::
   :maxdepth: 1

   custom
   sim2
