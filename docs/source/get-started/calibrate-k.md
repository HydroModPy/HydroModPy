# Calibrate K on a network

```{hmp-task}
Task
: Move K until the stream network the water table sustains matches the mapped one.

Time
: About a minute for the search, 14 steady solves.

Needs
: The files of example 10. The network map is a file of the example, so nothing is downloaded.

Gives
: The best K, a full run at that K with its figures, and a trace of the search.
```

Example 10 models the Urse catchment, an Alpine headwater with no gauge. The only thing to match
is the mapped stream network. The search moves K alone until the cells where the water table
reaches the ground fall on the mapped reaches. The map is a target. It scores the model and
never enters it. {doc}`../understand/how-sure` says what the result can and cannot tell.

## What can be calibrated

`hmp config targets` lists the parameters a calibration can move, with their current value,
unit and the path they write to. It loads the file and solves nothing. On example 10:

```{literalinclude} /_static/figures/calibrate/targets.txt
:language: text
```

A parameter you move gets a `[calibration.parameters.<name>]` table with a pair of bounds. The
search is in log space.

## The file

`run_calibration_k.toml` inherits `project.toml` and writes only the search. K goes from one
to a thousand times the recharge, and a bisection closes on the K where the gap between the two
networks changes sign.

```{hmp-toml}
:file: 10_coupling_with_land_surface_model_pyhelp/run_calibration_k.toml
```

An output is a simulated quantity paired with its observation. The tables of the network output
carry the choices that matter.

- {toml}`map|calibration.outputs.<name>.map` is the mapped network. `complete` is every reach.
  A file that also gives `permanent`, the reaches that never dry, makes a two-bound search.
- {toml}`model|calibration.outputs.<name>.model` says how the model draws its own network, with
  the weight of each cell and the flow a reach must carry to count.
- {toml}`verdict|calibration.outputs.<name>.verdict` says when the result holds. A distance
  above the validity length logs a warning, or stops the run with `on_invalid = "error"`.
  {doc}`../theory/downslope-distance` gives the criterion.

A block scores outputs with one metric, and a phase moves some parameters against some blocks.
A file can chain phases, K on the network then Sy on a gauged discharge, and each phase can
carry a {toml}`window|calibration.phases.window`. {doc}`../how-to/write-calibration-phases`
shows how.

## Check it, then run it

From the folder of example 10:

```bash
hmp check run_calibration_k.toml
hmp calibrate run_calibration_k.toml --list-phases
hmp run run_calibration_k.toml
```

The first command lists every problem of the file at once. The second prints each phase before
any solve. The third runs the search and replays the best trial as a full run,
`runs/urse_example_10_k/`. Its trials are in `sessions/urse_example_10_k/`.

## Read the result

The `root_search` preset, asked with `when = "session"`, draws the search. Each point is a
trial. The two curves are the mean distance from the simulated network to the mapped one, and
from the mapped one to the simulated one. A K too small lets the water table reach the ground
nearly everywhere, so the simulated network is far longer than the map. A K too large leaves
the streams dry. The search closes on K = 3.9e-6 m/s, a bracket 0.9 % wide, where the two
distances cross.

```{image} /_static/figures/calibrate/root_search_urse.webp
:alt: The two mean distances against K on a log axis. They cross near K = 3.9e-6 m/s, where the bisection closes its bracket after 14 trials.
:width: 80%
:align: center
```

The figure comes from `hmp show sessions/urse_example_10_k --figure root_search`, and the table
of targets from `hmp config targets project.toml`, both in the folder of example 10.
{doc}`../understand/network-metrics` explains the network criterion. The options of each method
are on {doc}`../reference/calibration-methods`, and the keys on
{doc}`../reference/parameters/calibration/index`.
