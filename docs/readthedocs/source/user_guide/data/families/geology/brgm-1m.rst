Geology Source: brgm_1m
=======================

Use ``source = "brgm_1m"`` for a public regional geology support. It is a good
default when the model needs broad geological differentiation without the
complexity of a finer map.

Minimal example
---------------

.. code-block:: toml

   [[data.geology.sources]]
   source = "brgm_1m"
   extent = "watershed"

Operational checks
------------------

- The selected ``extent`` should cover the future mesh or property support.
- The clipped layer should keep readable categories and a usable legend.
- If properties are transferred from geology, verify the resulting parameter
  map rather than assuming every BRGM code has a property.

Expected figure
---------------

Use the geology overview panel first, then the geology-driven conductivity
transfer figure when the layer feeds hydraulic parameters.
