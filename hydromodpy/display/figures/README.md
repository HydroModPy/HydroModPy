# display/figures

One registered figure per file. `figures/__init__.py` imports every module whose
name does not start with `_`, and each module registers its class with
`@register` (`display/figure_registry.py`). `hmp viz list` prints them, and
`[display].figures` names them.

A figure reads a finished run (`hydromodpy.results.run.Run`) and draws. It never
computes a hydrological quantity itself: a reading or a derived value lives in
`results` (`results/derive/`, `results/run/`), and the figure imports it. So the
recession cloud of `recession_power_law.py` comes from
`results/derive/recession.py`, and the travel times of
`residence_time_distribution.py` from `results/run/particles.py`.

## Files

| file | what it holds |
|---|---|
| `<name>.py` | one registered figure: its `spec`, its `render`, sometimes its own `plot` |
| `scalar_face_map.py` | the base class of the maps that draw one value per mesh face |
| `_stream_comparison.py` | the frame, the colours and the legend shared by the stream-network maps |
| `_flow_persistence.py` | the flowing fraction of each cell, read once per run |
| `_trial_diagnostics.py`, `_calibration_session.py` | the trials and the session of a calibration, as the calibration figures read them |
| `_hydrochem.py` | the sample table of the Piper, Schoeller and Stiff diagrams |
| `_cohort.py` | the table of a campaign summary the cohort figures draw |
| `_observed.py`, `_instant.py`, `_window.py`, `_run_score.py`, `_parameter_scale.py` | small readers and labels shared by a few figures |
| `lake_level_fit.py` | a public helper that draws a lake stage against its gauge; not registered |

A file whose name starts with `_` is a helper, private to this folder. A tool
that another part of `display` also needs goes to `display/maps/` or to
`display/style.py`, never here, because no tool may import a figure
(`tests/unit/architecture/display_layout.yaml`).

## Adding a figure

Copy `piezometric_map.py` for a map of one value per face, or `hydrograph.py` for
a chart. Then add its line to `REGISTRY_CONTRACT` in
`tests/unit/display/test_figure_registry_completeness.py`. The parent README
(`display/README.md`) gives the full recipe and the options every figure takes.
