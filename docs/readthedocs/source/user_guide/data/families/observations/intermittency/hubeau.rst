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
