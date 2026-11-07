# display/catchment_report

The catchment report of `hmp report catchment <toml>`. One report file names the
overview, the simulation and the run the report describes. The pipeline may run
the overview and the simulation first, then gathers the figures and writes one
HTML page into the run, `runs/<run>/report/`.

| file | what it does |
|---|---|
| `settings.py` | the report TOML file, its tables and their validation |
| `inputs.py` | `CatchmentReportInputs`: the paths the settings resolve to, the overview and the run directories |
| `simulation_source.py` | the run the report reads, found on disk without the index, and its discharge at the station the report names |
| `context.py` | the context of the run: observed and simulated discharge, network counts, configuration summary |
| `artifacts.py` | which PNG each figure of the report is, where it is looked for, the drawing of the run figures the run lacks, and the copy into `report/figures/` |
| `blocks.py` | the blocks of the page: what each holds (`ReportBlockSpec`) and how it is filled |
| `builder.py` | the presets and `build_catchment_report`, which writes the pages and `block_report_manifest.json` |
| `pipeline.py` | `run_catchment_report_pipeline`: the checks before the steps, the steps, and the figure check after them |

The pipeline starts a simulation as a subprocess (`python -m hydromodpy run`). A
step given on the command line wins over the `[pipeline]` table of the report
file. Before any step, the inputs the selected steps need are checked, and a
missing one stops the pipeline with its path. After the page, the figures the
manifest expects are compared with the figures copied, in
`block_report_postflight.json`.

A run draws only the figures its `[display].figures` lists, and that list is empty by default. So before the context and the page, the pipeline draws the run figures the report reads and the run does not have (`hydrograph`, `piezometric_map`, `water_budget`, `seepage_map` and the active network overlay). The run is opened from its own directory, and the figures are drawn into its `figures/` with the `[display]` the run sealed. That folder is outside the seal. A figure the run cannot feed is skipped with its reason in the log, and its block stays empty.

A run that stored the simulated discharge at several stations is read at the station named by `[context.observed_discharge] station_id`.

A new block is a `ReportBlockSpec` and a function in `_CONTENT_BUILDERS`, both in
`blocks.py`, and its PNG in `DEFAULT_ARTIFACT_SPECS` of `artifacts.py`.
