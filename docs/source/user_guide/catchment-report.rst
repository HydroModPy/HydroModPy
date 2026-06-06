Catchment HTML Reports
======================

``hmp report catchment`` builds a block-based HTML report for one watershed
from a single report TOML. The command is intentionally separate from the
simulation TOML: the simulation TOML produces model outputs, while the report
TOML declares where to find the overview, context, simulation, and report
artifacts.

Standard command
----------------

Build context artifacts and the final HTML report from the artifacts declared
in the report TOML:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml

This command does not relaunch the overview or the simulation unless the
corresponding CLI flags are passed.

Only rebuild the final HTML from existing context artifacts:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml --report-only

This mode also skips optional overview/simulation run steps by default, even
when pipeline defaults exist in the TOML.

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

The same build also writes ``report_artifact_manifest.json``. This second
manifest is the generic report-artifact contract: it records semantic artifact
identifiers, their producers, whether they are required by the report profile,
and whether the concrete files were present for this run.

Run the configured overview first:

.. code-block:: bash

   hmp report catchment path/to/catchment_report.toml --run-overview

The command prints the generated paths, for example:

.. code-block:: text

   context_summary=.../outputs/selune_context/context/selune_catchment_context_summary.json
   html_report=.../outputs/selune_catchment_report/web/index.html
   postflight_report=.../outputs/selune_catchment_report/block_report_postflight.json

Generated outputs
-----------------

The printed ``html_report`` path points to the standard report page:
``<output_dir>/web/index.html``. The same run also writes review variants under
``<output_dir>/web_review``:

- ``compact/index.html`` for a fast plausibility read;
- ``standard/index.html`` for the default scientific review;
- ``audit/index.html`` for provenance, detailed tables, and artifact links;
- ``by_block/index.html`` to choose the detail level block by block.

Report outputs are build products, not the source of truth. Example TOMLs are
kept under version control; generated context summaries, HTML pages, copied
figures, API caches, local NetCDF provider files, and ``hydromodpy.lock`` files
are expected to be regenerated locally by rerunning ``hmp report catchment``.

When regression confidence is needed, prefer a small contract test around the
TOML, manifest, or regenerated file fingerprints rather than committing the full
HTML and figure tree. The full report can still be inspected locally after a
run through the printed ``html_report`` path.

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
   * - ``preset``
     - Report preset. The current public preset is
       ``generic_catchment_report``.

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

Optional pipeline fields
------------------------

The optional ``[pipeline]`` section is still read for older report TOMLs, but it
is no longer the preferred contract. New report TOMLs should describe the report
only. Run orchestration should live in CLI flags, in the simulation workflow, or
in ``[report.html]`` on the simulation TOML.

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
CLI flags override these TOML defaults. For example,
``--no-run-simulation`` rebuilds the context and HTML without relaunching a
simulation even when a config still declares ``run_simulation = true``.

Optional HTML intent
--------------------

Simulation TOMLs can use ``[report.html]`` to express report intent without
duplicating the lower-level pipeline switches. ``build_at_end = true`` implies
``enabled = true`` and ``strict`` defaults to ``false``:

.. code-block:: toml

   [report.html]
   build_at_end = true
   profile = "catchment_gauged"
   config_path = "../16_nancon_natural_calibration/catchment_report_transient_nwt_html.toml"

Using ``enabled = true`` without ``build_at_end`` means that the run should
prepare the report artifacts but the final HTML can be built later from the
manifest.

For ``profile = "catchment_gauged"``, ``config_path`` points to the catchment
report TOML that declares the report layout and context inputs. The end-of-run
step consumes this TOML in report-only mode: it forces ``run_overview = false``
and ``run_simulation = false``. The report TOML adapts to the artifacts
produced by the simulation; it does not decide which simulation steps run.

When the simulation display step produced
``figures/<run_name>/report_artifact_manifest.json``, the HTML step uses that
manifest first. It validates that required display artifacts are present, uses
the manifest location as the source figure directory, and records that upstream
manifest in the final report ``report_artifact_manifest.json``. The report TOML
then remains a layout/context descriptor rather than the source of truth for
which run was executed.

The bundled Nancon example is:

.. code-block:: bash

   hmp run examples/projects/02_nancon_watershed/run_transient_nwt_html_report.toml

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
   data_overview_project_dir = "outputs/selune_overview"
   simulation_workspace_dir = "outputs/selune_nwt"
   simulation_name = "selune_nwt_report"
   context_summary_name = "selune_catchment_context_summary.json"
   transient_config_name = "run_selune_nwt_report.toml"
   overview_config_name = "../../overview_selune.toml"

   [context.observed_discharge]
   path = "../../data/hydrometry/hydrometry_hubeau_I922102001_20200101_20201231_D.csv"
   station_id = "I922102001"

Second basin example
--------------------

The Nancon example uses the same generic report contract as any other basin:

.. code-block:: toml

   [report]
   site_label = "Nancon"
   station_label = "Nancon a Lecousse"
   output_dir = "outputs/nancon_real_figures"

   [layout]
   watershed_project_dir = "../02_nancon_watershed"
   context_outputs_dir = "outputs/nancon_context"
   data_overview_project_dir = "../02_nancon_watershed"
   simulation_workspace_dir = "../02_nancon_watershed"
   simulation_name = "transient_nwt"
   context_summary_name = "nancon_catchment_context_summary.json"
   transient_config_name = "run_transient_nwt.toml"
   overview_config_name = "run_overview_all_apis.toml"

   [context.observed_discharge]
   path = "../../data/hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv"
   station_id = "NANCON"

Adding a New Basin
------------------

Adding a basin to the catchment report pipeline should not require Python code.
The reproducible unit is the report TOML, plus any simulation or overview TOML
overlay needed to point the existing generic producers at the new basin.

The expected pattern is:

1. create or reuse an overview TOML for the basin outlet;
2. create or reuse a simulation TOML whose ``[display].figures`` list includes
   the report figures consumed by the generic preset;
3. create a ``catchment_report_*.toml`` that points to those TOMLs and declares
   the report output directory;
4. generate or reuse the simulation artifacts, then run one report command:

.. code-block:: bash

   hmp report catchment path/to/catchment_report_<basin>.toml

If the artifacts do not exist yet and the report CLI should produce them for a
one-off rebuild, pass explicit orchestration flags such as
``--run-overview --run-simulation``.

The command must print the generated ``context_summary``, ``html_report`` and
``postflight_report`` paths. A valid new-basin run has
``missing_count = 0`` and ``dangling_count = 0`` in
``block_report_postflight.json``.

The Vire example is a third basin using this contract:

.. code-block:: bash

   hmp report catchment examples/projects/06_vire_selune/catchment_report_vire.toml

It reuses ``overview_vire.toml`` and adds only a simulation overlay,
``run_vire_nwt_report.toml``, to request the generic report figures from the
existing Vire MODFLOW-NWT run configuration. Its overview TOML writes to
``outputs/vire_overview`` and the report TOML declares this directory as
``data_overview_project_dir`` so the shared project-level ``web/`` folder is not
rewritten during report generation.
