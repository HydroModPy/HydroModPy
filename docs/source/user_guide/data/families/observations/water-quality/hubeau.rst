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

Provider replay
---------------

.. figure:: /_static/user_guide/data/hubeau_provider_replay_examples.png
   :alt: Hub'Eau water-quality replay with station inventory and chronicle coverage
   :width: 100%

   The water-quality part of the Hub'Eau replay is intentionally plotted with
   the other observation families: chemistry shares the station/time-series
   contract, but parameter identity and units decide whether the values are
   usable.
