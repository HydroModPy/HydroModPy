# Calibrate on the stream network

You have a map of the streams of a catchment and you want the model to make the same network.
HydroModPy moves the conductivity $K$ until the cells where the aquifer feeds the surface reach
as far as the mapped streams, then fits the storage $S_y$ to a gauge. The first stage
identifies the ratio $K/R$ of conductivity to recharge, not $K$ alone.

```{hmp-task}
Task
: Calibrate $K$ on one mapped stream network, then $S_y$ on a gauge.

Time
: Example 04 takes 15 steady runs for $K$ (2.5 minutes) and 8 monthly runs for $S_y$ (6.6 minutes).

Needs
: A transient project with drains at the surface, a vector map of the streams, a gauge for the second stage.

Gives
: $K$ with the bracket that proves its root, $K/R$, the verdict of Eq. 4, and $S_y$.
```

The general steps of a calibration, phases and protocols included, are in {doc}`calibrate`.
What the criterion measures, and which way its biases point, is in
{doc}`../theory/downslope-distance`. To score $K$ on a permanent and a complete map, year by
year, see {doc}`score-two-maps`.

## What you need first

- Drains at the ground surface: {toml}`flow.active_bc` lists `"drainage"`, and the
  conductance {toml}`flow.bc.drainage.value` stays at zero, so each drain takes
  $C = K A / b$ from the $K$ the search moves, with $b$ the
  {toml}`solver.drain_bed_thickness_m`. That proportionality is what makes the search
  identify $K/R$.
- A conductivity written as one number, {toml}`flow.param.K.field.value`. The report gives
  $K/R$ only for that case.
- A recharge that does not move during the search: keep it out of
  {toml}`calibration.parameters`.
- No SFR or LAK package in {toml}`flow.active_bc`. Both build their own conductance, and the
  search is refused with them.
- The mapped network as lines in a vector file. It is a target, never an input of the model.

## 1. Write the calibration file

Example 04 names the published method as a protocol. The file keeps what belongs to the site:
the two ranges, the map, and the budget of stage two.

```toml
base_config = "project.toml"

[workflow]
mode = "calibration"

[calibration]
rerun_best_with_outputs = true

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.parameters.Sy]
bounds = [5e-3, 0.35]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"

[calibration.protocol]
name = "matching_hydrographic_network"
transient_max_iter = 30
transient_tolerance = 0.05
```

The protocol writes two stages:

1. `steady_conductivity` moves $K$ alone, in steady state over the whole record, by a root
   search on the signed gap between the two networks.
2. `transient_storage` moves $S_y$ alone, in transient, with $K$ frozen, on the discharge of
   the gauge. It scores from one year after the start of the run, the first year being spin-up.

The gauge needs no output: the protocol reads the station of {toml}`data.hydrometry.sources`.
With several stations, name one in {toml}`calibration.protocol.observed_station_id`.
`hmp calibrate run_calibration.toml --expand` prints the two stages as TOML, and
{ref}`calibrate-phases` says how to write them by hand.

```{hmp-params}
calibration.protocol.name
calibration.protocol.conductivity
calibration.protocol.storage
calibration.protocol.scoring_window
```

## 2. Point at the mapped network

Exactly one of two keys says where the map comes from.

```{hmp-params}
calibration.outputs.<name>.stream_geometry_path
calibration.outputs.<name>.observed_network
```

- {toml}`stream_geometry_path|calibration.outputs.<name>.stream_geometry_path` is a vector
  file. A relative path is looked for from the folder of the calibration file, then from its
  parent and its grandparent; a bare file name also under `data/hydrography/` of each.
- {toml}`observed_network|calibration.outputs.<name>.observed_network` takes
  `"data.hydrography"`, the network the data step loaded (a local file, BD Topage, OSM or
  EU-Hydro), clipped to the catchment. It also takes `"geographic.river_network"`, a network
  derived from the elevation model, which fits a seepage density onto a geomorphological one;
  the run warns and records it.

To read the map from the data section instead of a file:

```toml
base_config = "run_calibration.toml"

[calibration.outputs.seepage_network]
stream_geometry_path__delete = true
observed_network = "data.hydrography"
```

The criterion measures lengths along the flow paths of the model top. Each trial publishes
`alpha_obs_closure_catchment`, the share of the downstream closure of the map that the map
already covers on the model top, and the run warns once below
{toml}`alpha_warning_threshold|calibration.outputs.<name>.alpha_warning_threshold`. A low
value is a fact about the top and the map, not an instruction to edit the top.

## 3. Choose how the map is drawn on the mesh

The criterion needs the map as cells.
{toml}`observed_rasterization|calibration.outputs.<name>.observed_rasterization` decides how.

- `"heads"`, the default, keeps the free ends of the mapped lines, where a stream starts, and
  draws the rest down the descent of the model. A mapped path below a head follows ditches
  and rectified reaches a drain model cannot reproduce, so scoring it cell by cell would count
  false error. Each head lands on the nearest cell within
  {toml}`heads_snap_radius|calibration.outputs.<name>.heads_snap_radius` that drains at least
  {toml}`heads_min_drained_area_km2|calibration.outputs.<name>.heads_min_drained_area_km2`.
  A head with no such cell is lost and counted in `n_heads_lost`.
- `"crossing"` matches the published method: a cell belongs to the map when a line crosses
  the segment joining two edge-sharing cell centres. Use it for a map that is not a tree: a
  canal across a divide, a braided reach, a karst loss.
- `"touch"` keeps every cell the line touches. It replays sessions made before 2026-09.

```{figure} ../_static/figures/guides/observed_network_heads_map.webp
:alt: The Nançon catchment with the mapped network in blue, 29 heads in orange, and the traced network in black running from each head down to the outlet.
:width: 80%

`observed_network_heads_map` in example 04: 29 heads traced, none lost, 94 % of the trace
near the map.
```

## 4. Set how strictly the agreement is judged

Equation 4 of the published method qualifies the result: the calibration is valid when the
mean mismatch $D_{optim}$ stays within a validity length. The bound never changes the cost. It
adds a verdict to the value the search returns.

```toml
base_config = "run_calibration.toml"

[calibration.outputs.seepage_network]
weighting = "area"
validity_length = "300 m"
on_roptim_violation = "error"
```

```{hmp-params}
calibration.outputs.<name>.weighting
calibration.outputs.<name>.validity_length
calibration.outputs.<name>.on_roptim_violation
calibration.outputs.<name>.max_unreachable_fraction
```

Use `weighting = "area"` as soon as the mesh is refined along the streams: an unweighted mean
over-samples the river corridor, where distances are smallest. `validity_length = "auto"` is
two cells of the mesh where the map lies. With `on_roptim_violation = "error"`, a violation
raises after the session is saved, so no phase that depends on this one runs.

## 5. Check, then run

```bash
hmp calibrate run_calibration.toml --check
hmp calibrate run_calibration.toml
```

`--check` names what the protocol does differently from the paper, then what each stage
compares, then its verdict:

```text
protocol: matching_hydrographic_network@1.2 - Matching the hydrographic network
  differs from the paper on tau_specific_ratio: 1e-4 of the cell's own recharge by default; ...
  differs from the paper on observed_rasterization: 'heads' by default and departs from the paper: ...
  option away from the recipe: transient_max_iter = 30 (recipe: 120)
  option away from the recipe: transient_tolerance = 0.05 (recipe: unset)
...
run_calibration.toml: ready to run.
```

State those departures beside the value you publish.

## 6. Read the result

On example 04, the command ends with:

```text
phase steady_conductivity:
  K = 7.96236e-05  [7.49894e-05, 8.25404e-05]
  cost: 0.810634
  k_over_r = 8774 against R_mean_m_s = 9.075e-09 m/s on output 'seepage_network', k_optim = 7.962e-05 m/s,
    d_sat = 17.46 m, t_over_r = 1.532e+05 m, t_optim = 0.00139 m2/s. The aquifer runs 58% full:
    T/R depends on the imposed thickness there.
  roptim (seepage_network) = 1.39, Doptim = 104.1 m <= 150 m (auto), Eq. 4 holds
  bracket on K: [7.91476e-05, 7.96236e-05], width 0.60% (closed)
  search: converged on its rule (rel_tol), 15 evaluation(s) of 23 declared
```

- The bracket is the interval whose two ends change the sign of the residual: the proof
  beyond the value. Here it closed at a width of 0.6 %. An `(open, ...)` bracket means the
  budget ran out first.
- `k_over_r = 8774` is what the network identifies. Publish the ratio with the recharge it
  rests on, $R = 9.075 \times 10^{-9}$ m/s here, not $K$ alone.
- `roptim` and `Eq. 4` are the verdict of step 4: a mean mismatch of 104.1 m against a
  validity length of 150 m, two cells of 75 m. The verdict measures agreement, not
  correctness.
- The interval in brackets after `K` is read off the trials: see
  {doc}`calibration-uncertainty`.

```{figure} ../_static/figures/guides/downslope_distance_crossing.webp
:alt: Two curves against K on a log axis. D_so falls from 1000 m at low K, D_os rises to 1600 m at high K, and they cross at K = 7.958e-5 m/s.
:width: 80%

`downslope_distance_crossing`: the two mean distances against $K$. Their crossing is the root
the search closes on.
```

```{figure} ../_static/figures/guides/bisection_bracket_trace.webp
:alt: The signed residual D_so minus D_os for each of 15 evaluations, positive then negative, with grey brackets narrowing to K between 7.915e-5 and 7.962e-5 m/s.
:width: 80%

`bisection_bracket_trace`: the signed residual of each evaluation and the bracket it closes,
a factor 1.006 at the end.
```

Each trial is written under `sessions/<session>/trials.jsonl`, with the diagnostics of the
network output prefixed by its name, such as `seepage_network.J_signed`:

| Key | What it says |
|---|---|
| `J_signed` | The signed residual $D_{so} - D_{os}$ the search brackets. |
| `D_so`, `D_os` | The mean downslope distance from the simulated network to the map, and back. |
| `roptim`, `roptim_valid`, `validity_length_m` | The mismatch in cells, the Eq. 4 test, and the length it used. |
| `R_mean_m_s` | The recharge the criterion read from the built model, the denominator of $K/R$. |
| `n_valid`, `n_excess`, `n_missing` | Cells where both networks agree, where only the model has a stream, where only the map has one. |
| `n_heads`, `n_heads_lost` | Under `"heads"`: heads landed and heads lost. |

### Look at the networks

List the figures in {toml}`display.figures`; the promoted run draws them. The network maps
need {toml}`simulation.results.derived.release_flux` set to `true`, which example 04 does.

```{figure} ../_static/figures/guides/seepage_network_reference_overlay.webp
:alt: Hillshade of the Nançon catchment with the mapped network in blue (473 cells) and the simulated network in red (363 cells) on top of it.
:width: 70%

`seepage_network_reference_overlay`: the simulated network over the map, October 2002. Open it
before you trust a number: a residual near zero is compatible with a network that ignores the
valleys.
```

```{figure} ../_static/figures/guides/seepage_network_confusion_map.webp
:alt: The catchment with cells where both networks agree in blue (297), cells simulated only in yellow (62) and cells mapped only in red (174), mostly in the upper tributaries.
:width: 70%

`seepage_network_confusion_map`: where the two networks agree, where the model has too much
stream, and where it has too little, October 2002.
```

`downslope_distance_map` draws the distance field behind $D_{so}$ or $D_{os}$, and
`matching_hydrographic_network_card` puts both stages on one page. Their options are on the
cards of {doc}`../reference/figures`.

## Calibrate K without a gauge

{toml}`calibration.protocol.storage` defaults to `Sy`, and a TOML file has no null to turn the
second stage off. Write the single stage by hand:

```toml
base_config = "project.toml"

[workflow]
mode = "calibration"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "nancon_stream_network.gpkg"

[[calibration.objective_blocks]]
name = "network_extension"
metric = "distance_gap"
uses_outputs = ["seepage_network"]

[[calibration.phases]]
name = "steady_conductivity"
parameters = ["K"]
regime = "steady"
objective_blocks = ["network_extension"]
method = "bisection"
```

`bisection` stops on the width of the bracket, never on the size of the residual, which steps
over zero and may never get small. With {toml}`calibration.phases.max_iter` left at `"auto"`,
it counts the evaluations it needs before the first solve.

## What can go wrong

`--check` and the first trial find most of these before the budget is spent.

| Symptom | Cause | Fix |
|---|---|---|
| `calibration output declares neither 'observed_network' nor 'stream_geometry_path': the mapped network has no source.` | The network output has no map. | Declare exactly one of the two keys. |
| `stream_geometry_path 'x.gpkg' is not there, and none of the places the run looks holds it.` | The map file is not found. | Fix the path. |
| A message ending with `Set the value to zero.` | A fixed drain conductance does not follow $K$. | Set {toml}`flow.bc.drainage.value` to zero, or remove it. |
| `Network calibration output(s) 'seepage_network' move a hydraulic conductivity while` ... | SFR or LAK builds its own conductance. | Remove the package from {toml}`flow.active_bc` for this calibration. |
| `a network output reads exactly one state, 'last', 'first' or one date.` | `time` selects several states. | Write one state, or use the `extent` table of {doc}`score-two-maps`. |
| `the residual keeps the same sign over the whole bracket:` | No root inside the bounds, even after `bracket_expand` decades. | Check `n_excess` at the low end of the sweep; widen `bounds` if the root is outside. |
| A warning starting `The root closed on` | The root lies outside your declared bounds. | Several decades out usually means the residual stopped responding to $K$. |
| `Declare transform = "log" for this parameter.` | A bisection on a parameter not in log space. | Remove the transform, or write `"log"`. |
| `frac_unreachable_so = ... of the simulated network never reaches the mapped one` | The routing surface still holds depressions. | Condition the surface, or raise {toml}`max_unreachable_fraction\|calibration.outputs.<name>.max_unreachable_fraction`. |
| `The mean recharge moved between two network criterion builds:` | The recharge changes during the search. | Keep the recharge out of the search; `R_mean_m_s` says by how much it moved. |
| `run has no per-cell release_flux: set [simulation.results.derived] release_flux = true` | A network figure has no flux to read. | Set the key in the project. |

## Where to go next

- Two maps and two bounds, year by year: {doc}`score-two-maps`.
- The width of the value: {doc}`calibration-uncertainty`.
- The criterion and its biases: {doc}`../theory/downslope-distance`.
- Every key of the section: {doc}`../reference/parameters/calibration/index`.
