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
