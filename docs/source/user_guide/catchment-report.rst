Catchment HTML Reports
======================

``hmp report catchment`` builds a block-based HTML report for one watershed
from a single report TOML. The command is intentionally separate from the
simulation TOML: the simulation TOML produces model outputs, while the report
TOML declares where to find the overview, context, simulation, and report
artifacts.

Standard command
----------------

Build context artifacts and the final HTML from existing simulation outputs:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml

Only rebuild the final HTML from existing context artifacts:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml --report-only

Only rebuild the context artifacts:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml --context-only

Run the configured simulation first, then rebuild context and HTML:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml --run-simulation

Run the configured overview first:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml --run-overview

The command prints the generated paths, for example:

.. code-block:: text

   context_summary=.../outputs/selune_context/context/selune_catchment_context_summary.json
   html_report=.../outputs/selune_catchment_report/web/index.html

TOML contract
-------------

The report TOML has two required sections, ``[report]`` and ``[layout]``.
Relative paths are resolved from the directory containing the report TOML.

Required ``[report]`` fields:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Field
     - Meaning
   * - ``site_label``
     - Watershed label displayed in report titles and subtitles.
   * - ``station_label``
     - Gauge or outlet label displayed in site/context blocks.
   * - ``output_dir``
     - Report output directory. The HTML is written to
       ``<output_dir>/web/index.html``.

Optional ``[report]`` fields:

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Field
     - Meaning
   * - ``title``
     - Override the generated HTML page title.
   * - ``allow_gallery_fallbacks``
     - Whether missing figures may be copied from documentation gallery
       fallbacks. The generic preset defaults to ``false``.
   * - ``preset``
     - Report preset. Use ``generic_catchment_report`` for normal basins.
       ``nancon_reference`` is a compatibility preset that preserves the
       validated Nancon reference HTML exactly.

Required ``[layout]`` fields:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Field
     - Meaning
   * - ``watershed_project_dir``
     - Project directory containing overview figures and the default run TOML.
   * - ``context_outputs_dir``
     - Directory containing, or receiving, context artifacts. The context JSON
       lives below ``<context_outputs_dir>/context`` and context images below
       ``<context_outputs_dir>/web/assets``.

Optional ``[layout]`` fields:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Field
     - Meaning
   * - ``data_overview_project_dir``
     - Project directory used for overview/data figures when it differs from
       ``watershed_project_dir``.
   * - ``simulation_workspace_dir``
     - Workspace holding simulation figures, exports, and parquet outputs when
       it differs from ``watershed_project_dir``.
   * - ``simulation_name``
     - Simulation run name. Defaults to ``transient_nwt``.
   * - ``context_summary_name``
     - File name under ``<context_outputs_dir>/context``. If omitted, the
       builder derives a name from the site label or the only existing
       ``*_gauged_context_summary.json`` file.
   * - ``transient_config_name``
     - Simulation TOML file name under ``watershed_project_dir``. Defaults to
       ``run_<simulation_name>.toml``.
   * - ``overview_config_name``
     - Overview TOML file name under ``data_overview_project_dir``. Defaults to
       ``config_overview.toml``.

Observed discharge
------------------

If observed discharge is available outside the simulation export, declare it in
``[context.observed_discharge]``:

.. code-block:: toml

   [context.observed_discharge]
   path = "../../data/hydrometry/hydrometry_hubeau_I922102001_20200101_20201231_D.csv"
   station_id = "I922102001"

The CSV must expose ``datetime`` and ``value`` columns. The context builder
uses this series for the observed-discharge and observed-vs-simulated figures.

Minimal generic example
-----------------------

.. code-block:: toml

   [report]
   site_label = "Selune"
   station_label = "Selune at outlet"
   output_dir = "outputs/selune_catchment_report"

   [layout]
   watershed_project_dir = "."
   context_outputs_dir = "outputs/selune_context"
   simulation_workspace_dir = "outputs/selune_nwt"
   simulation_name = "selune_nwt_report"
   transient_config_name = "run_selune_nwt_report.toml"

   [context.observed_discharge]
   path = "../../data/hydrometry/hydrometry_hubeau_I922102001_20200101_20201231_D.csv"
   station_id = "I922102001"

Nancon compatibility example
----------------------------

The Nancon reference report is intentionally pinned to its compatibility
preset:

.. code-block:: toml

   [report]
   site_label = "Nancon"
   station_label = "Nancon a Lecousse"
   output_dir = "outputs/nancon_real_figures"
   allow_gallery_fallbacks = false
   preset = "nancon_reference"

   [layout]
   watershed_project_dir = "../02_nancon_watershed"
   context_outputs_dir = "../15_nancon_gauged_context/outputs"
   data_overview_project_dir = "../02_nancon_watershed"
   simulation_workspace_dir = "../02_nancon_watershed"
   simulation_name = "transient_nwt"
   context_summary_name = "nancon_gauged_context_summary.json"
   transient_config_name = "run_transient_nwt.toml"
   overview_config_name = "config_overview.toml"

This preset exists only to preserve the validated reference layout and labels.
New basins should normally omit ``preset`` and use the generic default.
