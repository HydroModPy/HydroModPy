Piezometry Source: hubeau
=========================

Use ``source = "hubeau"`` to retrieve public French groundwater-level
observations.

Minimal example
---------------

.. code-block:: toml

   [[data.piezometry.sources]]
   source = "hubeau"
   product = "level"
   extent = "watershed"
   nearest = true

Operational checks
------------------

- ``product`` accepts ``level`` or ``depth``; choose the product that matches
  the later comparison.
- ``nearest`` can select nearby usable stations when exact support filtering is
  too strict.
- Verify date coverage and station placement before using the data in
  calibration.

Provider replay
---------------

.. figure:: /_static/user_guide/data/hubeau_provider_replay_examples.png
   :alt: Hub'Eau piezometry replay with station inventory and chronicle coverage
   :width: 100%

   The piezometry part of the Hub'Eau replay keeps groundwater-level semantics
   separate from discharge and chemistry. This matters before comparing
   observations to simulated heads.
