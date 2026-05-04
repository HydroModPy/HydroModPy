Hydrometry Source: hubeau
=========================

Use ``source = "hubeau"`` when public French discharge observations should be
discovered and downloaded through Hub'Eau.

Minimal example
---------------

.. code-block:: toml

   [[data.hydrometry.sources]]
   source = "hubeau"
   product = "QmnJ"
   extent = "watershed"
   require_observations = true

Operational checks
------------------

- ``product`` selects the discharge product; daily discharge commonly uses
  ``QmnJ``.
- ``require_observations`` filters out stations without usable records over
  the requested period.
- ``fallback_search_radius_km`` can be useful when the watershed has no station
  inside its exact support.
- Cache and lockfile metadata should be preserved for reproducible studies.

Provider replay
---------------

.. figure:: /_static/user_guide/data/hubeau_provider_replay_examples.png
   :alt: Hub'Eau hydrometry replay with station inventory and chronicle coverage
   :width: 100%

   The hydrometry part of the Hub'Eau replay shows why station metadata and
   chronicle coverage must be checked together. The discharge product should be
   readable before it becomes an objective or comparison target.
