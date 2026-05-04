Intermittency Source: hubeau
============================

Use ``source = "hubeau"`` to retrieve public flow-state observations.

Minimal example
---------------

.. code-block:: toml

   [[data.intermittency.sources]]
   source = "hubeau"
   extent = "watershed"
   code_departement = ["35", "53"]

Operational checks
------------------

- Department filters can keep discovery predictable.
- Check observation dates against the simulation or comparison window.
- The data are categorical observations, not discharge values.

Provider replay
---------------

.. figure:: /_static/user_guide/data/hubeau_provider_replay_examples.png
   :alt: Hub'Eau intermittency replay with station inventory and categorical states
   :width: 100%

   The intermittency part of the Hub'Eau replay shows categorical state values,
   not a continuous hydrological flux. That distinction should be visible
   before ONDE-style data are compared with a simulated active network.
