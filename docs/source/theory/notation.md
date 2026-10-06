# Notation

One table of the symbols the theory pages share. When a quantity is set by a key of
the configuration file, the last column names the key, and the key links to its
generated card. The units are the ones the code stores: lengths in metres, hydraulic
conductivity in m/s, rates in m/s. The soil reservoir is the exception, because it
works in mm and days: its symbols are in their own section.

Each theory page also opens with a Notation table of its own, and that table is the
one that holds on the page. Most symbols below are used the same way everywhere. Two
letters are not:

- The recharge rate is $N$ here and on {doc}`groundwater-flow`, because $R_t$ is the
  transit store of the soil reservoir. {doc}`forcing`, {doc}`exits` and
  {doc}`downslope-distance` write it $R$, as the $K/R$ ratio of the stream-network
  method does.
- A volumetric discharge is $\Phi$ here, because $Q_t$ is the runoff of the soil
  reservoir. Pages that write $Q$ define it in their own table.

A name that exists in the code or in an output file is given in `code font` in the
meaning column, so a symbol on a theory page can be matched with a column of a
result file.

## Space, time and heads

| Symbol | Meaning | Unit | Read from |
|---|---|---|---|
| $x$, $y$ | horizontal coordinates | m | the grid ({doc}`mesh`) |
| $z$ | elevation, positive up | m | |
| $d$ | depth below the top of a cell, the variable of the depth factor of a property | m | |
| $t$ | time; on the soil page, the day | s | {toml}`start_datetime\|simulation.time.start_datetime` and {toml}`end_datetime\|simulation.time.end_datetime` bound the run |
| $\Delta t$ | length of a stress period, the step on which the forcing is aggregated | s | {toml}`simulation.time.step_value` |
| $h$ | hydraulic head, measured from a fixed datum | m | solved by the flow solver, not set |
| $z_\mathrm{top}$ | land surface elevation, the model top | m | the DEM, {toml}`data.dem` |
| $z_\mathrm{bot}$ | bottom of the aquifer | m | {toml}`domain.depth_model` |
| $B$ | saturated thickness, $B = h - z_\mathrm{bot}$ | m | derived |
| $\bar B$ | saturated thickness averaged by area over the catchment (`d_sat_m`) | m | derived |
| $A$ | catchment area | m² | derived from {toml}`geographic.catchment` |

## Fluxes

| Symbol | Meaning | Unit | Read from |
|---|---|---|---|
| $\mathbf{q}$ | specific discharge (Darcy flux) | m/s | derived |
| $\Phi$ | volumetric discharge, for example at the outlet | m³/s | derived |
| $N$ | recharge rate, positive into the aquifer | m/s | {toml}`flow.sinks_sources.recharge` |
| $\bar N$ | recharge averaged over the catchment and the scored period (`R_mean_m_s`) | m/s | derived |

A recharge series is read in the unit of {toml}`flow.sinks_sources.recharge.units`
and converted to m/s. When the soil reservoir computes it, $N = (1 - f)\,O_t$
(see {doc}`soil-reservoir`).

## Properties of the ground

| Symbol | Meaning | Unit | Read from |
|---|---|---|---|
| $K$ | horizontal hydraulic conductivity, the same along $x$ and $y$ | m/s | {toml}`flow.param.K.field.value` |
| $K_z$ | vertical hydraulic conductivity | m/s | $K$ divided by {toml}`modflow6.process_specific.vka`, or a parameter with the id `Kv` ({toml}`flow.param.Kv.field.value`) |
| $H$ | aquifer thickness, $H = z_\mathrm{top} - z_\mathrm{bot}$ | m | {toml}`domain.depth_model` |
| $T$ | transmissivity, $T = K\,B$ | m²/s | derived |
| $S_s$ | specific storage | 1/m | {toml}`flow.param.Ss.field.value` |
| $S_y$ | specific yield | - | {toml}`flow.param.Sy.field.value` |
| $\theta$ | porosity | - | {toml}`flow.param.n.field.value` |
| $d_c$ | characteristic depth of the exponential depth factor of a property | m | {toml}`flow.param.K.field_vertical_profile.characteristic_depth` |

$S_s$ and $S_y$ carry a subscript of their own. The soil store $S_t$ carries the
index of the day. They are never written without it.

## The soil reservoir

These are the symbols of {doc}`soil-reservoir`. Stores are in mm of water per
unit of unsealed area, fluxes in mm/day. The page defines each one with its
equation.

| Symbol | Meaning | Unit | Read from |
|---|---|---|---|
| $P_t$ | rain of day $t$ | mm/day | {toml}`data.precipitation` |
| $E_t$ | ETP of day $t$, as loaded | mm/day | {toml}`data.etp` |
| $\mathrm{RU}$ | capacity of the soil store | mm | {toml}`ru\|flow.sinks_sources.recharge.soil.ru` |
| $\alpha$ | share of RU above which evaporation is not limited | - | {toml}`alpha\|flow.sinks_sources.recharge.soil.alpha` |
| $k_c$ | factor applied to the loaded ETP | - | {toml}`kc\|flow.sinks_sources.recharge.soil.kc` |
| $f$ | sealed share of the area | - | {toml}`impervious_fraction\|flow.sinks_sources.recharge.soil.impervious_fraction` |
| $b$ | share of the rain that skips the soil | - | {toml}`bypass_fraction\|flow.sinks_sources.recharge.soil.bypass_fraction` |
| $\tau$ | time constant of the transit store | day | {toml}`transit_time\|flow.sinks_sources.recharge.soil.transit_time` |
| $\mathrm{CN}$ | SCS curve number | - | {toml}`curve_number\|flow.sinks_sources.recharge.soil.curve_number` |
| $\tau_q$ | time constant of the curve-number runoff store | day | {toml}`runoff_time\|flow.sinks_sources.recharge.soil.runoff_time` |
| $L$ | pure delay of the curve-number runoff | day | {toml}`runoff_lag\|flow.sinks_sources.recharge.soil.runoff_lag` |
| $S_t$, $R_t$, $C_t$ | soil, transit and curve-number stores at the end of day $t$ | mm | state, not a key |
| $Q_t$ | curve-number runoff of day $t$ | mm/day | derived |
| $O_t$ | water that reaches the water table, per unit of unsealed area | mm/day | derived |

$\alpha$, $b$, $L$, $Q_t$, $R_t$ and $S_t$ belong to the soil reservoir. The
aquifer uses $N$, $\Phi$, $B$, $S_s$ and $S_y$ for the same family of ideas, so
that no page needs to say which one it means.

## The descent and the distance between networks

The descent $D$ is where water goes on the model top: from each cell, the path to
a lower neighbour, down to the outlet or to a cell where water leaves the model.
It is a computation on a copy of the top. It is never given back to the solver.
The distances below are not measured on $D$: the stream-network criterion floods
its own copy of the model top and descends that one ({doc}`downslope-distance`).

| Symbol | Meaning | Unit | Read from |
|---|---|---|---|
| $D$ | the descent of the model top | - | built with every MODFLOW grid |
| $D_{so}$ | mean downslope distance from the simulated network to the mapped one (`D_so`). Large: the model has too much stream. | m | derived |
| $D_{os}$ | mean downslope distance from the mapped network to the simulated one (`D_os`). Large: the model has too little stream. | m | derived |
| $J_{signed}$ | $D_{so} - D_{os}$, the residual a root search drives to zero (`J_signed`) | m | derived |
| $J$ | $\lvert D_{so} - D_{os}\rvert$, the cost of the `distance_gap` metric (`J`) | m | {toml}`calibration.objective_blocks.metric` |
| $D_{optim}$ | $(D_{so} + D_{os}) / 2$, a diagnostic (`Doptim`) | m | derived |
| $h_{obs}$ | cell size where the mapped network lies, the median distance between neighbouring cell centres over the mapped cells (`L_ref`) | m | derived |
| $r_{optim}$ | $D_{optim} / h_{obs}$, the validity indicator (`roptim`) | - | derived |
| $V$ | the length $D_{optim}$ must stay under for the result to be valid (`validity_length_m`) | m | {toml}`validity_length\|calibration.outputs.<name>.validity_length`, {toml}`observed_position_accuracy\|calibration.outputs.<name>.observed_position_accuracy` |
| $L_{cap}$ | longest descent to the outlet inside the catchment; the value a cell whose descent never meets its target takes (`L_cap`) | m | derived |
| $\alpha_\Omega$ | share of the mapped network in its own downslope closure, inside the catchment (`alpha_obs_closure_catchment`). A low value means the map and the model top disagree. | - | warning level: {toml}`alpha_warning_threshold\|calibration.outputs.<name>.alpha_warning_threshold` |
| $K/\bar N$ | conductivity over mean recharge (`k_over_r`) | - | derived |
| $T/\bar N$ | $K\,\bar B / \bar N$, transmissivity over recharge (`t_over_r_m`) | m | derived |

$\alpha_\Omega$ always carries its subscript: $\alpha$ alone is the evaporation
threshold of the soil reservoir. The descent $D$ carries none, and the distances
$D_{so}$ and $D_{os}$ always carry theirs.

## Scores

The names below are written in roman type. Each is a value of
{toml}`calibration.objective_blocks.metric`.

| Symbol | Meaning | Unit | Read from |
|---|---|---|---|
| $\mathrm{RMSE}$ | root-mean-square error | that of the series | `rmse` |
| $\mathrm{MAE}$ | mean absolute error | that of the series | `mae` |
| $\mathrm{NSE}$ | Nash-Sutcliffe efficiency | - | `nse` |
| $\mathrm{KGE}$ | Kling-Gupta efficiency | - | `kge` |
| $\mathrm{NSE}_{\log}$ | Nash-Sutcliffe efficiency of the log-transformed series; weights the recessions rather than the peaks | - | `nse_log` |

$\mathrm{NSE}_{\log}$ is not {toml}`transform\|calibration.objective_blocks.transform`
set to `log`. The metric takes the logarithm of the series. The transform takes
the logarithm of a cost that is already computed.

## Conventions

- Lengths are in metres, and elevation is positive up.
- $N$ is positive when water enters the aquifer.
- A TOML value can carry its unit, such as `"500 m"` or `"1 month"`. The unit of
  a key is on its card, not on this page.
- A symbol with an overbar, such as $\bar B$, is an average over the catchment.
  It is by area, unless the page says otherwise.
