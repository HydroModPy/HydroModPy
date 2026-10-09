# Score K on two maps

One mapped network is one definition of "flowing". A transient run can be scored on two: the
reaches that flow all year, and the reaches that flow at some time of the year. For every
complete calendar year of the run, HydroModPy builds a minimal and a maximal simulated
extent, compares each with its own map, and finds one root of $K$ per bound.

```{hmp-task}
Task
: Calibrate $K$ on a permanent and a complete map of the streams, year by year.

Time
: One bisection sweep for both roots; each trial is a transient run. Example 04's `run_calibration_bdtopage.toml` says about one hour, with $S_y$ after it.

Needs
: The setup of {doc}`calibrate-on-the-stream-network`, a transient run with at least one complete calendar year after its spin-up, and two maps, or a source that tells the permanent reaches apart, such as BD Topage.

Gives
: $K^\ast_{\min}$ and $K^\ast_{\max}$ with their brackets, their spread $\Delta$, and $K$, their weighted geometric mean.
```

This is an option of the network output, in any phase, written by hand or expanded from a
protocol. The single-map setup, the drains and the map sources are in
{doc}`calibrate-on-the-stream-network`; this page adds what changes.

(network-two-bounds)=
## 1. Declare the two maps

The maximal map is every reach of the map of the output. A minimal map, the permanent
reaches, is declared beside it. The maximal map scored is the union of the two files, so
wherever they disagree the wider one is scored; `frac_minimal_outside_maximal` publishes by
how much.

```toml
base_config = "run_calibration.toml"

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "complete_network.gpkg"
minimal_stream_geometry_path = "permanent_network.gpkg"
```

```{hmp-params}
calibration.outputs.<name>.minimal_stream_geometry_path
calibration.outputs.<name>.minimal_observed_network
```

{toml}`minimal_observed_network|calibration.outputs.<name>.minimal_observed_network` takes
`"data.hydrography"` and reads the permanent reaches the data step wrote beside the network
it loaded. It works only when the source says which reaches are permanent, BD Topage among
them. Declare one route for the minimal map, never both. No attribute filter runs in a
calibration: the map is read as it is.

```{figure} ../_static/figures/guides/hydrographic_network_permanence.webp
:alt: The Nançon catchment from BD Topage, with 46 km of permanent reaches in dark blue and 84 km of intermittent reaches in orange.
:width: 80%

`hydrographic_network_permanence` in example 04: BD Topage holds 46 km of permanent reaches,
the minimal map, and 130 km in all, the maximal map.
```

With both maps and no `extent` table, the one scored state is compared with the minimal map.
The maximal map is scored at the same state as a validation, with the suffix
`_maximal_validation`, and never enters the cost.

## 2. Declare the extent table

An `extent` table switches the output from one state to every complete calendar year of a
transient run:

```toml
base_config = "run_calibration_bdtopage.toml"

[calibration.outputs.seepage_network.extent]
maximal_flowing_steps = 1
minimal_dry_steps     = 1
year_quorum           = 0.5
visible_flow          = "1 L/s"

[calibration.outputs.seepage_network.extent.weights]
minimal = 0.5
maximal = 0.5
```

```{hmp-params}
calibration.outputs.<name>.extent.maximal_flowing_steps
calibration.outputs.<name>.extent.minimal_dry_steps
calibration.outputs.<name>.extent.year_quorum
calibration.outputs.<name>.extent.visible_flow
calibration.outputs.<name>.extent.weights.minimal
calibration.outputs.<name>.extent.weights.maximal
```

For each complete year, two masks are built from the number of timesteps each cell flowed. A
timestep belongs to the year its midpoint falls in, and a year the run does not cover whole is
dropped.

- The maximal mask holds the cells that flow at least `maximal_flowing_steps` timesteps of the
  year.
- The minimal mask holds the cells that flow at every timestep but at most
  `minimal_dry_steps`.

Both count timesteps, never days. With 12 monthly steps and `maximal_flowing_steps = 1`, a
cell flows one month out of twelve; the same value on a daily run asks one day out of 365. A
cell enters the mask compared with the map when it meets the rule in
`ceil(year_quorum * n_years)` scored years. Under three scored years the run warns, because
with two years a quorum of one half is their union.

A cell flows at a timestep when it lies downstream of the seepage cells and, unless
`visible_flow` is `"0 L/s"`, when the discharge routed to it reaches that threshold. Write it
as a discharge with its unit (`"1 L/s"`, `"0.002 m3/s"`) or as a share of the outlet discharge
(`"1%"`). A bare number is refused. No value is agreed in the literature.

## 3. Write the phase

The two-bound mode reads the timesteps of a transient run, so the phase that moves $K$ is
transient. A scoring window keeps only the complete years it holds, which is how the spin-up
year leaves the score. This is the $K$ stage of example 04's `run_calibration_bdtopage.toml`,
with the two maps written as files:

```toml
base_config = "project.toml"

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "complete_network.gpkg"
minimal_stream_geometry_path = "permanent_network.gpkg"

# 2000 is spin-up, so two years are scored: a cell meets the rule in both.
[calibration.outputs.seepage_network.extent]
year_quorum = 1.0

[[calibration.objective_blocks]]
name = "network_extent"
metric = "distance_gap"
uses_outputs = ["seepage_network"]

[[calibration.phases]]
name = "transient_conductivity"
parameters = ["K"]
regime = "transient"
objective_blocks = ["network_extent"]
method = "bisection"

[calibration.phases.scoring_window]
start = "2001-01-01"
```

```{hmp-resolved} calibration.outputs.seepage_network.extent.year_quorum
:config: run_calibration_bdtopage.toml
```

## 4. Read two roots

Each bound has its own root. One bisection sweep brackets both residuals on the same trials,
and the value returned is the weighted geometric mean of the two roots, with weights that sum
to one:

$$
\log_{10} K = w_{\min} \log_{10} K^\ast_{\min} + w_{\max} \log_{10} K^\ast_{\max}.
$$

That value is solved once more as an ordinary trial, so every number published beside it
comes from a real solve. The command prints one line per bound, then the spread and the
value:

```text
  K*_minimal = ..., bracket [..., ...], width ...% (closed)
  K*_maximal = ..., bracket [..., ...], width ...% (closed)
  Delta = log10(K*_maximal / K*_minimal) = ... decade(s)
  K = ..., weighted geometric mean of the two roots (0.5 / 0.5)
```

Read `Delta` as the spread: a large one means no homogeneous $K$ holds both maps. The report
has no single bracket in this mode, because an interval around one value means nothing
between two roots.

- A weight of zero removes that bound: `minimal = 1` and `maximal = 0` give one root on the
  permanent map.
- A minimiser has no root to combine. It minimises the weighted sum of the two absolute
  residuals, which tends to settle at one root or the other. Keep the bisection.
- With two bounds, only suffixed keys exist: `J_signed_minimal`, `J_signed_maximal`,
  `roptim_minimal`, `roptim_maximal`. Each year is also scored as a diagnostic,
  `J_signed_<bound>_y<year>`, beside `n_years_scored`, `first_year_scored` and
  `last_year_scored`.

The figure `network_extent_bounds_map` draws the two simulated extents against the two stored
maps, on any run that stored both.

State the departures beside the value: a run with an `extent` table departs from the published
method on five points. It scores transient masks over calendar years, counts duration in
timesteps, uses a quorum across years, adds a visible-flow threshold to the geometric closure,
and combines two bounds with declared weights. The equations are in
{doc}`../theory/downslope-distance`.

## What can go wrong

| Symptom | Cause | Fix |
|---|---|---|
| `declares an extent table and is scored by a steady search` | The extent mode reads timesteps; a steady phase has one. | Score the output in one state without the table, or run the phase transient. |
| `the extent table weighs the bounds (minimal = 0.7, maximal = 0.3) and no minimal map is declared` | Weights other than the default without a minimal map. | Declare `minimal_stream_geometry_path` or `minimal_observed_network`, or drop the weights. |
| `a network output reads exactly one state, 'last', 'first' or one date.` | `time` asks for several states. | Drop `time`: the extent table is the transient comparison. |
| `the extent table cannot be read on this run:` followed by causes | `maximal_flowing_steps` above the timesteps of the shortest year, `minimal_dry_steps` too large, or no complete calendar year. Refused at the first trial, not by `--check`. | Lower the counts, or lengthen the run. |
| `the residual of the minimal bound keeps the same sign over the whole bracket:` | One bound has no root inside the bounds. | Widen `bounds`, or set the weight of that bound to zero. |

The single-map messages are in {doc}`calibrate-on-the-stream-network`.

## Where to go next

- The single-map calibration: {doc}`calibrate-on-the-stream-network`.
- The equations of the two bounds: {doc}`../theory/downslope-distance`.
- The width of a value: {doc}`calibration-uncertainty`.
