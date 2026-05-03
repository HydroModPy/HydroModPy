Water Quality Source: hubeau
============================

Use ``source = "hubeau"`` to retrieve public chemistry observations.

Minimal example
---------------

.. code-block:: toml

   [[data.water_quality.sources]]
   source = "hubeau"
   site_type = "river"
   parameters = ["NO3"]
   extent = "watershed"
   require_observations = true

Operational checks
------------------

- ``site_type`` selects river or piezometer observations.
- ``parameters`` should be narrow enough to keep the downloaded chronology
  interpretable.
- Always inspect units and station metadata before comparing values across
  providers or sites.
