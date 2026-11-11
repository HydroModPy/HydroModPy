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

A figure draws one subject, the one `FigureSpec.subject` names. Most draw a
finished run (`hydromodpy.results.run.view.Run`). The calibration figures draw a
`Session` (`results/session/view.py`), and `ensemble_band` draws a `RunSet`.
`render`, `plot` and `unavailable_reason` receive that object. A session figure
asked for on a promoted run receives `Session.of_run(run)` and the run as the
option `promoted`, which only the display layer fills. The three figures that
compare a run with its reference (`difference_map`, `side_by_side`,
`conditioning_impact_map`) stay run figures and take `reference=<run>`, since a
`RunSet` has no order. A figure never touches a solver, a raw output file or a
`ProjectState`. It never computes a hydrological quantity itself: a reading or
a derived value lives in `results` (`results/derive/`, `results/run/`), and the
figure imports it. So the
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
| `_trial_diagnostics.py`, `_calibration_session.py` | the trials and the descriptor of a `Session`, as the calibration figures read them |
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

## Calibration figures

`_trial_diagnostics.trial_table(session, *, phase=None)` flattens the journal
of a session, one row per trial and case. The sampled parameters and the
numbers of the criterion become columns, and a network output prefixes its
diagnostics with its own name (`<output>.D_so`), so a diagnostic is read by
its bare name or under `output=`. A trial that failed keeps its row with an
empty diagnostic: a distance never measured is a gap in a curve, never a zero.
`_calibration_session.py` reads the rest of the session once for every figure:
the unit of each parameter (the journal bounds first, then the frozen
configuration), the metric of each objective block, the trial the search
returned, the roots record, and the width the calibration reads its interval
with. `display` may not import `calibration`, so that width is restated there.

### matching_hydrographic_network_card

One page for a staged downslope-distance calibration, four panels. The first
shows the value the root search closed on and the bracket it closed it in,
because the stopping rule of the search is the width of that bracket, never
the size of the residual. The second shows the storage value and its metric.
The third puts `D_optim` against the validity length the trial itself bounded
it by (Eq. 4). It qualifies the result and never withholds it, so the value
and the breach are drawn together. The fourth splits the cells into valid,
excess and missing, because a residual near zero is either a good fit or a
large excess cancelling a large gap.

Nothing is fabricated. A session with one phase draws the second panel as not
run, or names the phase that comes next when the frozen configuration declares
it. A diagnostic no trial published is drawn as absent, never as zero. A
search that never changed sign says so and points at no point. The reported
value is an evaluated trial, the end of the tightest sign-changing bracket with
the smaller residual, and every diagnostic is read at that trial.

The keys depend on the maps the output was scored on. One bound in the cost
publishes its components unsuffixed. A one-state output scored on the minimal
map may publish the maximal one as a validation (`<key>_maximal_validation`),
drawn beside it and kept out of its verdict. Two bounds publish only
`<key>_minimal` and `<key>_maximal`. The first panel then draws one bracket per
bound, and the lower panels show both bounds read at the trial the search
returned, the combined trial of the roots record or else the best trial of the
session. A bound weighted zero is drawn and gets no verdict. The roots, their
spread `Delta` and the combined value come from the `roots` option, else from
`root_search` of `session.json`. The mean recharge is the `mean_recharge`
option, else the median `R_mean_m_s` the trials published. Without it the card
says the ratio is not a conductivity. The unit of the parameter axis is
`parameter_units`, else `bounds.<name>.units` of the journal, else
`calibration.parameters.<name>.units` of the frozen configuration.
