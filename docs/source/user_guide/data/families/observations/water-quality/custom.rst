Water Quality Source: custom
============================

Use ``source = "custom"`` when local chemistry station and chronicle files
should be authoritative.

Minimal example
---------------

.. code-block:: toml

   [[data.water_quality.sources]]
   source = "custom"
   path = "data/water_quality"
   site_type = "river"
   col_id = "station"
   col_datetime = "date"
   col_value = "value"
   source_unit = "mg/L"

Operational checks
------------------

- Keep parameter names and units explicit.
- Distinguish river and piezometer sites with ``site_type``.
- Inspect records for censoring, gaps, and inconsistent units before reuse.
