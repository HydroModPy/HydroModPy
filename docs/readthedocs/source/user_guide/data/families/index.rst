Data Families
=============

This section documents HydroModPy data one family at a time. The
:doc:`../provider-matrix` remains the compact inventory; the pages below are
the operational reference for deciding what to load, which source to use, what
shape the loaded payload has, and which figure should be inspected before the
data are trusted by a mesh, solver, calibration, or comparison workflow.

Coverage model
--------------

Each family page follows the same structure:

- purpose of the data family;
- accepted ``source`` values;
- minimal TOML examples;
- expected loaded object shape;
- visual or tabular checks to perform;
- downstream uses in HydroModPy.

When a family has several source values, the family page links to one page per
source. Source pages are intentionally short: they state when to use the
source, the minimal configuration shape, and the first diagnostics to inspect.

Current families
----------------

.. list-table::
   :header-rows: 1
   :widths: 22 28 50

   * - Group
     - Families
     - Main role
   * - Spatial support
     - ``dem``, ``geology``, ``hydrography``
     - Build watershed support, zones, river networks, and mesh constraints.
   * - Observations
     - ``hydrometry``, ``piezometry``, ``intermittency``, ``water_quality``
     - Discover or ingest stations and observed chronicles.
   * - Forcing
     - ``recharge``, ``precipitation``, ``etp``, ``temperature``, ``wind``,
       ``humidity``, ``radiation``, ``soil_moisture``, ``runoff``
     - Load gridded or point forcing fields over the project period.
   * - Coastal boundary
     - ``oceanic``
     - Load or declare sea-level data for coastal boundary conditions.

.. toctree::
   :maxdepth: 3

   dem/index
   geology/index
   hydrography/index
   observations/index
   forcing/index
   oceanic/index
