Precipitation
=============

``precipitation`` loads liquid, solid, or total precipitation forcing. It is a
meteorological input for hydrological preprocessing and a diagnostic context
for recharge and runoff interpretation.

Accepted sources
----------------

- ``custom``
- ``sim2``

Minimal example
---------------

.. code-block:: toml

   [[data.precipitation.sources]]
   source = "sim2"
   components = ["total"]
   extent = "watershed"

Checks
------

- ``components`` accepts ``liquid``, ``solid``, and ``total``.
- Date coverage and units should be checked before comparing with recharge or
  runoff.

Visual check
------------

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 precipitation and temperature monthly summary
   :width: 100%

   The right panel shows the kind of monthly total that should be inspected for
   SIM2 precipitation before it is compared with recharge, runoff, or solver
   budget terms.

Precipitation Source: custom
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "custom"`` for local precipitation rasters, NetCDF files, or
station-derived series.

.. code-block:: toml

   [[data.precipitation.sources]]
   source = "custom"
   path = "data/precipitation/precipitation.nc"
   components = ["total"]
   source_unit = "mm/day"

Check component naming, units, period coverage, and spatial support before the
data are used in hydrological preprocessing.


Precipitation Source: sim2
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``source = "sim2"`` to retrieve SIM2 precipitation fields.

.. code-block:: toml

   [[data.precipitation.sources]]
   source = "sim2"
   components = ["liquid", "solid", "total"]
   extent = "watershed"

Inspect the climatic summary to verify that the requested period and selected
components are available.

Provider replay
"""""""""""""""

.. figure:: /_static/user_guide/data/sim2_grid_forcing_example.png
   :alt: SIM2 replay with monthly precipitation summary
   :width: 100%

   The monthly precipitation panel is the first provider replay to inspect
   before comparing precipitation with recharge, runoff, or solver budgets.
