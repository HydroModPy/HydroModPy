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

.. toctree::
   :maxdepth: 1

   custom
   sim2
