Observation Families
====================

Observation families load station metadata and time-series records. They are
used to inspect basin context before simulation, build calibration objectives,
compare modeled and observed responses, and document whether a project has
enough measurements to support its modeling goal.

Supported families
------------------

.. list-table::
   :header-rows: 1
   :widths: 24 30 46

   * - Family
     - Accepted sources
     - Main diagnostic
   * - ``hydrometry``
     - ``custom``, ``hubeau``
     - Discharge station inventory and discharge chronicles.
   * - ``piezometry``
     - ``custom``, ``hubeau``
     - Groundwater-level station inventory and piezometric chronicles.
   * - ``intermittency``
     - ``custom``, ``hubeau``
     - ONDE-style flow-state observations through time.
   * - ``water_quality``
     - ``custom``, ``hubeau``
     - River or piezometer chemistry observations.

Common configuration pattern
----------------------------

.. code-block:: toml

   [data.hydrometry]
   date_start = "2000-01-01"
   date_end = "2020-12-31"

   [[data.hydrometry.sources]]
   source = "hubeau"
   extent = "watershed"
   require_observations = true

Common checks
-------------

- station coordinates must sit on or near the modeled support;
- station identifiers should be stable enough to reuse in calibration or
  comparison workflows;
- the requested period must overlap available observations;
- units and product choices must be visible before a solver run depends on the
  data.

Station inventory
-----------------

.. figure:: /_static/capability_gallery/geographic/geographic_nancon_identity_card_station_inventory.png
   :alt: Nancon observation station inventory
   :width: 100%

   The inventory figure answers the first question: which observations exist
   around the basin before any model result is inspected?

.. toctree::
   :maxdepth: 3

   hydrometry/index
   piezometry/index
   intermittency/index
   water-quality/index
