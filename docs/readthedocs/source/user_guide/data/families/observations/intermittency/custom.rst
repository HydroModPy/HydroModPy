Intermittency Source: custom
============================

Use ``source = "custom"`` when local flow-state observations should be
ingested from project files.

Minimal example
---------------

.. code-block:: toml

   [[data.intermittency.sources]]
   source = "custom"
   path = "data/intermittency"
   col_id = "station"
   col_datetime = "date"
   col_value = "state"

Operational checks
------------------

- Document the state coding used in the local file.
- Confirm that station coordinates are available or discoverable.
- Do not compare state observations to simulated fluxes until the thresholding
  rule has been stated explicitly.
