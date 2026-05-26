Catchment HTML Reports
======================

``hmp report catchment`` builds a block-based HTML report for one watershed
from a single report TOML. The command is intentionally separate from the
simulation TOML: the simulation TOML produces model outputs, while the report
TOML declares where to find the overview, context, simulation, and report
artifacts. The optional ``[pipeline]`` section can also command which steps are
executed, including simulation relaunch and final HTML creation.

Standard command
----------------

Build according to the report TOML pipeline defaults:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml

If ``[pipeline].run_simulation = true`` and
``[pipeline].build_report_html = true``, this single command relaunches the
configured simulation and then produces the HTML report from its outputs.
When ``[pipeline].context_builder_command`` is declared, the context artifacts
are produced by that command instead of the built-in generic context builder.

Only rebuild the final HTML from existing context artifacts:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml --report-only

This mode also skips optional overview/simulation run steps by default, even
when they are enabled in ``[pipeline]``.

Only rebuild the context artifacts:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml --context-only

Run the configured simulation first, then rebuild context and HTML:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml --run-simulation

After the simulation command completes, the report pipeline checks that the
expected ``exports/<simulation_name>/timeseries.csv`` file and
``figures/<simulation_name>`` directory exist under the configured simulation
workspace. If they do not, the report TOML and the simulation TOML are not
pointing at the same run outputs.

By default, logs from these optional ``hmp run`` steps are captured so the
report command only prints the generated report paths. Use
``--stream-run-logs`` to stream the full simulation logs to the console.

Before executing the selected steps, the pipeline runs a preflight check on the
resolved paths. It reports missing required execution inputs such as the
simulation TOML, simulation export when context is rebuilt without rerunning the
simulation, or the context summary in ``--report-only`` mode.

After the final HTML is rendered, the pipeline writes
``block_report_postflight.json`` next to the manifest. This postflight report
lists expected, present, missing and dangling figure artifacts. Use
``--strict-figure-postflight`` to fail the command when any expected figure is
missing.

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

Pipeline fields
---------------

The optional ``[pipeline]`` section controls which steps are executed when no
CLI override is supplied.

.. list-table::
   :header-rows: 1
   :widths: 28 18 54

   * - Field
     - Default
     - Meaning
   * - ``run_overview``
     - ``false``
     - Run the configured overview TOML before context/report production.
   * - ``run_simulation``
     - ``false``
     - Run the configured simulation TOML before context/report production.
   * - ``build_context_artifacts``
     - ``true``
     - Build the context JSON, context HTML and context images.
   * - ``build_report_html``
     - ``true``
     - Build the final catchment HTML report.
   * - ``no_lock``
     - ``true``
     - Pass ``--no-lock`` to the optional ``hmp run`` steps.
   * - ``stream_run_logs``
     - ``false``
     - Stream logs from optional ``hmp run`` steps instead of capturing them.
   * - ``strict_figure_postflight``
     - ``false``
     - Fail after HTML rendering if expected figures are missing from the
       generated figure manifest.
   * - ``context_builder_command``
     - unset
     - Optional string array command used to build context artifacts instead of
       the built-in generic context builder.

CLI flags override these TOML defaults. For example,
``--no-run-simulation`` rebuilds the context and HTML without relaunching a
simulation even when ``run_simulation = true`` in the TOML.

``context_builder_command`` runs from the report TOML directory. It supports
the placeholders ``{python}``, ``{report_config}``, ``{report_config_dir}``,
``{context_outputs_dir}``, ``{watershed_project_dir}``,
``{simulation_workspace_dir}``, ``{simulation_name}``, ``{site_label}``, and
``{station_label}``.

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

   [pipeline]
   run_overview = true
   run_simulation = true
   build_context_artifacts = true
   build_report_html = true
   stream_run_logs = false

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
   overview_config_name = "run_overview_all_apis.toml"

   [pipeline]
   run_overview = true
   run_simulation = true
   build_context_artifacts = true
   build_report_html = true
   context_builder_command = [
     "{python}",
     "../15_nancon_gauged_context/build_nancon_gauged_context.py",
     "--report-config",
     "{report_config}",
   ]

This preset exists only to preserve the validated reference layout and labels.
New basins should normally omit ``preset`` and use the generic default.
