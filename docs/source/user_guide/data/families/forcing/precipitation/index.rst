Precipitation
=============

``precipitation`` loads liquid, solid, or total precipitation forcing. It is a
meteorological input for hydrological preprocessing and a diagnostic context
for recharge and runoff interpretation.

Accepted sources
----------------

- :doc:`custom`
- :doc:`sim2`

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

.. toctree::
   :maxdepth: 1

   custom
   sim2
