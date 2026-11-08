# display/figures

One figure per file. Every figure is a `BaseFigure` subclass that carries its
`spec`, in a public module of this folder, and that is the rule of membership:
nothing is registered by hand.

The registry answers a name without importing any module of this folder. It
reads the generated table `hydromodpy/display/figure_table.py`:
`FIGURES` (each name to its module and class), `FORMER_NAMES`, `OPTIONS` (the
keys `[display.overrides.<name>]` takes) and `PYTHON_ONLY_OPTIONS`. Regenerate
it after adding or renaming a figure:

```bash
python -m tools.figure_table
```

Never edit the table by hand. A test regenerates it in memory and fails on a
stale file, and validating a `[display]` section loads no figure module.

A figure reads a finished run (`hydromodpy.results.run.Run`) and draws. It never
computes a hydrological quantity itself: a reading or a derived value lives in
`results` (`results/derive/`, `results/run/`), and the figure imports it. So the
recession cloud of `recession_power_law.py` comes from
`results/derive/recession.py`, and the travel times of
`residence_time_distribution.py` from `results/run/particles.py`.

## Files

| file | what it holds |
|---|---|
| `<name>.py` | one figure: its `spec`, its `render`, sometimes its own `plot` |
| `scalar_face_map.py` | the base class of the maps that draw one value per mesh face |
| `_stream_comparison.py` | the frame, the colours and the legend shared by the stream-network maps |
| `_flow_persistence.py` | the flowing fraction of each cell, read once per run |
| `_trial_diagnostics.py`, `_calibration_session.py` | the trials and the session of a calibration, as the calibration figures read them |
| `_hydrochem.py` | the sample table of the Piper, Schoeller and Stiff diagrams |
| `_cohort.py` | the table of a campaign summary the cohort figures draw |
| `_observed.py`, `_instant.py`, `_window.py`, `_run_score.py`, `_parameter_scale.py` | small readers and labels shared by a few figures |
| `lake_level_fit.py` | a public helper that draws a lake stage against its gauge; it carries no `spec` and is not a figure |

A file whose name starts with `_` is a helper, private to this folder. A tool
that another part of `display` also needs goes to `display/maps/` or to
`display/style.py`, never here, because no tool may import a figure
(`tests/unit/architecture/display_layout.yaml`).

## Adding a figure

Copy `piezometric_map.py` for a map of one value per face, or `hydrograph.py`
for a chart, then run `python -m tools.figure_table`. The parent README
(`display/README.md`) gives the full recipe and the options every figure
takes.
