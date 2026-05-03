Oceanic Source: custom
======================

Use ``source = "custom"`` when project-owned sea-level or coastal-stage files
should be authoritative.

Minimal example
---------------

.. code-block:: toml

   [[data.oceanic.sources]]
   source = "custom"
   path = "data/oceanic/sea_level.csv"
   col_datetime = "date"
   col_value = "stage"
   source_unit = "m"

Operational checks
------------------

- Document vertical datum and sign convention.
- Check station or boundary location.
- Confirm date coverage before a transient coastal boundary consumes the data.
