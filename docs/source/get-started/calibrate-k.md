# Calibrate on a network and a discharge

```{hmp-task}
Task
: Move K until the simulated stream network matches a mapped one, then move Sy until the simulated discharge matches the gauge.

Time
: A few minutes for the check, the calibration is a series of monthly runs.

Needs
: The example files ({doc}`staircase/index`). The network map is a file of the example, so nothing is downloaded.

Gives
: The best K and Sy, a full run of each stage with its figures, and a trace of the search.
```

Example 04 calibrates in two stages. K alone is moved until the cells where the water table reaches the surface fall on the mapped network. Then Sy alone is moved, with K frozen, until the simulated discharge follows the gauge. The mapped network and the gauge are targets. They score the model and never enter it. {doc}`../understand/how-sure` says what the result can and cannot tell.

## What can be calibrated

`hmp config targets` lists the parameters a calibration can move, with their current value, unit and the path they write to. It loads the file and solves nothing.

```{literalinclude} /_static/figures/calibrate/targets.txt
:language: text
```

A parameter you move gets a `[calibration.parameters.<name>]` table with a pair of bounds. The search is in log space.

## The file

`run_calibration_by_hand.toml` writes the two stages as two phases. `run_calibration.toml` runs the same trials under the name of the published protocol.

```{hmp-step} run_calibration_by_hand.toml
```

An output is a simulated quantity paired with its observation. The tables of the network output carry the choices that matter.

- {toml}`map|calibration.outputs.<name>.map` is the mapped network. `complete` is every reach and `permanent` the reaches that never dry. Both together make a two-bound search, shared by `calibrate_on`.
- {toml}`model|calibration.outputs.<name>.model` says how the model draws its own network, with the weight of each cell and the flow a reach must carry to count.
- {toml}`verdict|calibration.outputs.<name>.verdict` says when the result holds. A distance above the validity length logs a warning, or stops the run with `on_invalid = "error"`. {doc}`../theory/downslope-distance` gives the criterion.

A block scores outputs with one metric, and a phase moves some parameters against some blocks. Each phase can carry a {toml}`window|calibration.phases.window`. The first year here is spin-up, so it is simulated and not scored. A {toml}`validation_window|calibration.validation_window` is scored beside the cost and never enters it, to check the result on dates the search did not see.

## Check it, then run it

```bash
hmp config check run_calibration_by_hand.toml
hmp calibrate run_calibration_by_hand.toml --list-phases
hmp run run_calibration_by_hand.toml
```

The first command lists every problem of the file at once. The second prints each phase before any solve. The third runs both phases and replays the best trial of each as a full run.

## Read the result

The calibration card shows both stages. Stage one shows the evaluations of K and the bracket the bisection closed on. Stage two shows the cost of each Sy. The lower panels give the validity of the network agreement, $D_{optim}$ against its bound, and the cells that are valid, in excess or missing at the calibrated point.

```{image} /_static/figures/calibrate/matching_hydrographic_network_card.webp
:alt: Four panels. The K trials close on a bracket around 8e-5 m/s, the Sy trials have a minimum cost near 0.043, the mean distance is under its bound, and the cells are split into valid, excess and missing.
:class: only-light
:width: 90%
:align: center
```

```{image} /_static/figures/calibrate/matching_hydrographic_network_card-dark.webp
:alt: Four panels. The K trials close on a bracket around 8e-5 m/s, the Sy trials have a minimum cost near 0.043, the mean distance is under its bound, and the cells are split into valid, excess and missing.
:class: only-dark
:width: 90%
:align: center
```

The figure and the output of `hmp config targets` above are written by `tools/docs/figures/render_ex04_figures.py` from the runs of `run_calibration.toml`, which are the same trials. {doc}`../understand/network-metrics` explains the network criterion. The options of each method are on {doc}`../reference/calibration-methods`, and the keys on {doc}`../reference/parameters/calibration/index`.
