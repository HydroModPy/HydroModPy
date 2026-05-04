Data Families
=============

This section documents HydroModPy data one family at a time. The
:doc:`../provider-matrix` remains the compact inventory; the pages below are
the operational reference for deciding what to load, which source to use, what
shape the loaded payload has, and which figure should be inspected before the
data are trusted by a mesh, solver, calibration, or comparison workflow.

Visual orientation
------------------

The expanded data documentation is organized around one contract: a data source
is not documented just because a TOML field exists. A useful page should show
the declaration, the loading path, the normalized shape, the first diagnostic
figure, and the workflow that will consume the result.

.. figure:: /_static/user_guide/data/data_contract_ladder.png
   :alt: Data contract ladder from declaration to model use
   :width: 100%

   The file path or API name is only the beginning of the story. The important
   documentation question is whether a reader can see what was loaded and how
   it becomes useful.

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

Run and figure roadmap
----------------------

Not every page needs a full simulation. For data documentation, the cheapest
credible figure is often enough: a source matrix for inventory, a local
data-only case for file formats, a Nancon data overview for real-basin context,
then solver outputs only when the page explains how input data affect model
behavior.

.. figure:: /_static/user_guide/data/data_run_figure_roadmap.png
   :alt: Roadmap of runs and figures for documenting HydroModPy data
   :width: 100%

   This roadmap separates documentation assets that require no model run from
   data-only runs, basin overview runs, solver illustrations, and future
   provider-specific gallery cases.

The current communication assets can be regenerated with:

.. code-block:: powershell

   python docs/readthedocs/source/user_guide/data/render_data_communication_assets.py

For the complete list of generated figures, local cases, and remaining gallery
gaps, read :doc:`../runs-and-figures`.

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
