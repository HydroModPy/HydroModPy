# The daily soil reservoir

Each day, a soil store takes the rain, loses water to evapotranspiration, and
sends the water it cannot hold down to the water table. This page gives the
equations the code solves, what they assume, and where they stop being true.
It does not say how to set up a run: for that, see {doc}`../guides/recharge`.

:::{note}
**Scope.** The reservoir runs under MODFLOW 6 only. A file that declares
{toml}`flow.sinks_sources.recharge.soil` with another flow solver is refused
when it is read. The equations below are the ones of
`hydromodpy/physics/hydrology/soil_reservoir/kernel.py`.
:::

## The model in one picture

```{raw} html
<figure class="hmp-theory-figure" style="margin:1.2rem 0">
<svg viewBox="0 40 800 315" role="img" aria-labelledby="soil-fig-title soil-fig-desc" style="width:100%;height:auto;max-width:800px;font-family:inherit;font-size:13px;color:var(--pst-color-text-base)">
<title id="soil-fig-title">Water path through the daily soil reservoir</title>
<desc id="soil-fig-desc">Rain splits into a sealed share that runs off, a curve-number runoff that is routed and delayed, a bypass that goes to the transit store, and the rest that enters the soil store. The soil store loses evapotranspiration and overflows to the transit store, which releases the recharge.</desc>
<defs>
<marker id="soil-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="currentColor"/></marker>
</defs>
<g fill="none" stroke="currentColor" stroke-width="1.5" marker-end="url(#soil-arrow)">
<path d="M80 150 H110"/>
<path d="M240 150 H290"/>
<path d="M430 150 H500"/>
<path d="M620 150 H680"/>
<path d="M360 130 V70" />
<path d="M265 150 V205 H560 V172"/>
<path d="M210 170 V270 H290"/>
<path d="M400 270 H440"/>
<path d="M540 270 H680"/>
<path d="M45 170 V325 H735 V290"/>
</g>
<g fill="var(--pst-color-surface)" stroke="var(--pst-color-border)" stroke-width="1.5">
<rect x="10" y="130" width="70" height="40" rx="6"/>
<rect x="110" y="130" width="130" height="40" rx="6"/>
<rect x="290" y="130" width="140" height="40" rx="6" stroke="var(--pst-color-primary)" stroke-width="2.5"/>
<rect x="500" y="130" width="120" height="40" rx="6"/>
<rect x="680" y="130" width="110" height="40" rx="6" stroke="var(--pst-color-primary)" stroke-width="2.5"/>
<rect x="290" y="250" width="110" height="40" rx="6"/>
<rect x="440" y="250" width="100" height="40" rx="6"/>
<rect x="680" y="250" width="110" height="40" rx="6"/>
</g>
<g fill="currentColor" text-anchor="middle">
<text x="45" y="155">Rain P</text>
<text x="175" y="155">1 Curve number</text>
<text x="360" y="155">Soil store S</text>
<text x="560" y="155">5 Transit store R</text>
<text x="735" y="155">Recharge</text>
<text x="345" y="275">6 Routing</text>
<text x="490" y="275">7 Lag</text>
<text x="735" y="275">Runoff</text>
</g>
<g fill="var(--pst-color-text-muted)" text-anchor="middle" font-size="12">
<text x="360" y="60">3 ETR, at most kc E</text>
<text x="410" y="198">2 bypass, share b</text>
<text x="265" y="143">P - Q</text>
<text x="465" y="143">4 X</text>
<text x="650" y="143">O</text>
<text x="200" y="215" text-anchor="end">Q</text>
<text x="390" y="340">8 sealed share f: runs off at once, no evaporation</text>
</g>
</svg>
<figcaption class="hmp-muted" style="font-size:.9em">The numbers 1 to 8 are the steps of the next sections. The two thick boxes are the stores that the soil and transit equations update; the recharge is what MODFLOW 6 receives.</figcaption>
</figure>
```

## Notation

Every column of the reservoir is independent, so the column index is left out.
$t$ is the day. Stores are in mm of water per unit of unsealed area. Fluxes
are in mm/day.

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
| $\mathrm{CN}$ | SCS curve number, antecedent moisture class II | - | {toml}`curve_number\|flow.sinks_sources.recharge.soil.curve_number` |
| $\tau_q$ | time constant of the curve-number runoff store | day | {toml}`runoff_time\|flow.sinks_sources.recharge.soil.runoff_time` |
| $L$ | pure delay of the curve-number runoff | day | {toml}`runoff_lag\|flow.sinks_sources.recharge.soil.runoff_lag` |
| $S_t$, $R_t$, $C_t$ | soil, transit and curve-number stores at the end of day $t$ | mm | state, not a field |

The state before the first day, $S_0$, $R_0$ and $C_0$, comes from
{toml}`spinup|flow.sinks_sources.recharge.soil.spinup` (see
[the starting state](#the-starting-state)).

## The daily balance

The code applies the steps below in this order, for every column and every
day.

### 1. Curve-number runoff (optional)

Read only when {toml}`curve_number|flow.sinks_sources.recharge.soil.curve_number`
is set. Without it, $Q_t = 0$ and the step costs nothing.

The wetness of the soil is the store at the end of the day before, as a share
of its capacity:

$$
w_t = \min\!\left(1,\ \max\!\left(0,\ \frac{S_{t-1}}{\mathrm{RU}}\right)\right),
\qquad w_t = 1 \text{ if } \mathrm{RU} = 0 .
$$

The curve number of class II is turned into a dry-soil number (class I) and a
wet-soil number (class III) (Chow, Maidment and Mays, 1988, eq. 5.5.6 and
5.5.7):

$$
\mathrm{CN}_\mathrm{I} = \frac{4.2\,\mathrm{CN}}{10 - 0.058\,\mathrm{CN}},
\qquad
\mathrm{CN}_\mathrm{III} = \frac{23\,\mathrm{CN}}{10 + 0.13\,\mathrm{CN}} .
$$

The retention $\sigma$ in mm is $s(x) = 25400/x - 254$ at each of the two
numbers, and moves linearly with the wetness:

$$
\sigma_t = s(\mathrm{CN}_\mathrm{I}) + \bigl[s(\mathrm{CN}_\mathrm{III}) - s(\mathrm{CN}_\mathrm{I})\bigr]\,w_t .
$$

The runoff is the SCS formula with an initial abstraction of $0.2\,\sigma_t$
(HELP, Schroeder et al., 1994):

$$
Q_t =
\begin{cases}
\dfrac{(P_t - 0.2\,\sigma_t)^2}{P_t + 0.8\,\sigma_t} & \text{if } P_t > 0.2\,\sigma_t,\\[1ex]
0 & \text{otherwise.}
\end{cases}
$$

The rain that infiltrates is $P_t - Q_t$. The runoff $Q_t$ is taken before the
soil sees the rain, so the soil gets less of it.

### 2. Bypass

A constant share $b$ of the infiltrating rain skips the soil. The rest is
added to the store:

$$
B_t = b\,(P_t - Q_t), \qquad
W_t = S_{t-1} + (1 - b)\,(P_t - Q_t).
$$

Here $b$ is {toml}`bypass_fraction|flow.sinks_sources.recharge.soil.bypass_fraction`.
$W_t$ is the water in the soil after the rain and before any evaporation.

### 3. Evapotranspiration

The soil evaporates at the full rate $k_c E_t$ while it holds more than
$\alpha\,\mathrm{RU}$. Below that, the rate falls linearly with the store. It
can never exceed what the soil holds:

$$
\rho_t = \min\!\left(1,\ \frac{W_t}{\alpha\,\mathrm{RU}}\right),
\qquad
\mathrm{ETR}_t = \min\bigl(W_t,\ k_c\,E_t\,\rho_t\bigr),
$$

with $\rho_t = 1$ if $\mathrm{RU} = 0$. The two symbols are
{toml}`alpha|flow.sinks_sources.recharge.soil.alpha` and
{toml}`kc|flow.sinks_sources.recharge.soil.kc`, and
{toml}`ru|flow.sinks_sources.recharge.soil.ru` is the capacity. In the code
$\alpha$ is the $1 - p$ of FAO-56 (Allen et al., 1998) and the $LP$ of HBV
(Seibert and Vis, 2012).

### 4. Overflow

What exceeds the capacity leaves the soil. Nothing else does:

$$
X_t = \max\bigl(0,\ W_t - \mathrm{ETR}_t - \mathrm{RU}\bigr),
\qquad
S_t = W_t - \mathrm{ETR}_t - X_t .
$$

### 5. Transit through the unsaturated zone

The overflow and the bypass enter one linear reservoir of time constant
$\tau$, {toml}`transit_time|flow.sinks_sources.recharge.soil.transit_time`.
The inflow $I_t = X_t + B_t$ is taken as constant over the day, and the
reservoir is integrated exactly over that day:

$$
R_t = \tau I_t + (R_{t-1} - \tau I_t)\,e^{-1/\tau},
\qquad
O_t = I_t - (R_t - R_{t-1}).
$$

$O_t$ is the water that reaches the water table. If $\tau = 0$, then
$O_t = I_t$ and $R_t = R_{t-1}$.

### 6. Routing of the curve-number runoff

The runoff $Q_t$ goes through the same exact reservoir, with the time
constant $\tau_q$, {toml}`runoff_time|flow.sinks_sources.recharge.soil.runoff_time`,
and its own store $C_t$. The routed runoff is called $Q^r_t$. If $\tau_q = 0$,
then $Q^r_t = Q_t$.

### 7. Delay of the curve-number runoff

A pure delay of $L$ days, {toml}`runoff_lag|flow.sinks_sources.recharge.soil.runoff_lag`,
follows. Write $L = n + \varphi$ with $n$ a whole number of days and
$0 \le \varphi < 1$. The delayed runoff is a linear interpolation between two
whole-day shifts:

$$
Q^L_t = (1 - \varphi)\,Q^r_{t-n} + \varphi\,Q^r_{t-n-1} .
$$

A day that falls before day 1 of the run reads zero, or, with
`spinup = "first_year"`, the days at the end of the last repeated first year,
which stand for the days before the run.
The delay is not a store: it moves water in time and keeps its volume, except
the part pushed beyond the last day of the run.

### 8. Fluxes per unit of column area

The stores above are per unit of unsealed area. The sealed share $f$,
{toml}`impervious_fraction|flow.sinks_sources.recharge.soil.impervious_fraction`,
gets no infiltration and no evaporation. The fluxes of the column are:

$$
\begin{aligned}
\text{recharge}_t &= (1 - f)\,O_t,\\
\text{ETR}^{\text{col}}_t &= (1 - f)\,\mathrm{ETR}_t,\\
\text{residual ETP}_t &= (1 - f)\,\bigl(k_c\,E_t - \mathrm{ETR}_t\bigr),\\
\text{runoff}_t &= f\,P_t + (1 - f)\,Q^L_t .
\end{aligned}
$$

The residual ETP is the demand $k_c E_t$ that the soil could not meet.

## Three days, by hand

The numbers below come from one call of the kernel function `soil_step` for
each day, with $\mathrm{RU} = 150$ mm, $\alpha = 0.6$, $k_c = 1$,
$f = b = \tau = 0$. The last day adds a curve number of 80 with $\tau_q = 0$.

| | Dry day | Overflow | Curve number |
|---|---|---|---|
| $S_{t-1}$ (mm) | 40 | 145 | 150 |
| $P_t$, $E_t$ (mm/day) | 0, 4 | 30, 3 | 30, 3 |
| What happens | $W = 40$ is below $\alpha\,\mathrm{RU} = 90$, so $\rho = 0.444$ | $W = 175$, evaporation 3, $175 - 3 - 150 = 22$ leaves | $w = 1$, $\sigma = 27.6$, $Q = 11.50$, then $W = 168.50$ |
| ETR (mm/day) | 1.78 | 3.00 | 3.00 |
| Recharge (mm/day) | 0 | 22.00 | 15.50 |
| Runoff (mm/day) | 0 | 0 | 11.50 |
| $S_t$ (mm) | 38.22 | 150 | 150 |
| Residual ETP (mm/day) | 2.22 | 0 | 0 |

On the third day, $30 = 3.00 + 15.50 + 11.50$: the balance closes with no
change of store.

## The balance closes

Over any run, per column and per day:

$$
P_t = \mathrm{ETR}^{\text{col}}_t + \text{recharge}_t + \text{runoff}_t
+ \Delta\bigl[(1 - f)(S + R + C)\bigr]_t + \Delta\Lambda_t ,
$$

where $\Lambda_t$ is the running total of runoff held back by the delay
({toml}`runoff_lag|flow.sinks_sources.recharge.soil.runoff_lag`). The
function `balance_residual` computes the difference between the two sides.
On a test series of 400 days of random rain and ETP, with three columns, with a sealed share, a bypass,
a transit time, a curve number and a delay all switched on, the largest
residual was $4 \times 10^{-14}$ mm.

## The starting state

With `spinup = "none"`, the soil starts full and the other stores empty:
$S_0 = \mathrm{RU}$, $R_0 = C_0 = 0$.

With `spinup = "first_year"`, the default, the first 365 days of rain and ETP
are run again and again, starting from that full soil. The loop stops when no
store of any column moves by $0.1$ mm or more over one repetition, or after 20
repetitions. The state at the end of the last repetition is $S_0$, $R_0$ and
$C_0$. If 20 repetitions are not enough, the run stops with an error. A run
shorter than 365 days is refused with this option.

## Columns and capacity classes

Without {toml}`data.soil_capacity`, each cell of the rain and ETP grid is one
column and the same RU applies to all. With it, the pixels of the raster in
each cell are sorted by capacity and cut into ten classes of equal pixel
count. Each class is a column, with a capacity
$\mathrm{RU} \times (\text{class mean} / \text{raster mean})$. The value
given in the file is therefore the mean capacity, and the raster only spreads
it. The basin value of any flux gives every cell the same weight, and every
class of a cell its share of the pixels.

## Assumptions

- The rain of a day reaches the soil before it evaporates, the same day. The
  evaporation stress of day $t$ is computed on the store after the rain.
- The rain and the ETP are constant over the day.
- All the water above RU leaves the soil as drainage. There is no
  saturation-excess runoff term in the kernel.
- The bypass is a constant share of the infiltrating rain, the same in every
  season.
- The unsaturated zone is one linear reservoir per column, with one time
  constant for the whole catchment.
- The sealed share receives rain and nothing else: it neither infiltrates nor
  evaporates, and its runoff is immediate.
- The curve-number runoff reads the wetness of the day before, not the one
  after the rain.
- Columns do not exchange water with each other.
- One value of $\alpha$, $k_c$, $f$, $b$, $\tau$, CN, $\tau_q$ and $L$ applies to
  the whole catchment and to the whole run. Only RU varies, through the
  capacity classes.
- The rain is one total grid: snow counts as rain on the day it falls. The
  file is refused unless `components = ["total"]`.

## Limits

- **No feedback from the aquifer.** The soil store never reads the water
  table. A shallow water table does not reduce the capacity. The only link
  back is the residual ETP, which MODFLOW 6 may draw from the water table
  (next section).
- **Daily forcing only.** The rain and the ETP must have one value per day
  and per cell, with no gap and no negative value, on a standard calendar,
  with the rain and the ETP on the same grid, in the CRS of the model. Otherwise the run stops
  before the reservoir is computed.
- **No groundwater memory.** The transit time is limited to 30 days, so that
  the slow response comes from MODFLOW 6 and not from this reservoir.
- **Ranges.** The file is refused outside these ranges: RU 0 to 1000 mm,
  $\alpha$ above 0 and at most 1, $k_c$ 0 to 2, $f$ and $b$ from 0 up to,
  not including, 1, $\tau$ 0 to 30 days, CN 30 to 98, $\tau_q$ 0 to 10 days,
  $L$ 0 to 5 days.
- **Curve number and delay.** $\tau_q$ and $L$ are read only when
  `curve_number` is set. A fractional delay spreads a one-day pulse over
  two days. The part of the delayed runoff that falls after the last day of
  the run is not represented.
- **First period.** A steady first stress period is refused, since it would
  hold the recharge of one day only.
- **No other runoff.** Water that leaves saturated ground is not a term of
  this model. In a run, it leaves through the drains of MODFLOW 6.

## Where the results go

The reservoir hands three daily grids to the rest of the run, in mm/day on the
cells of the rain grid.

- The **recharge** goes to the MODFLOW 6 recharge package. A file that also
  loads a recharge, through {toml}`data.types`, is refused.
- The **residual ETP** goes to the MODFLOW 6 evapotranspiration package, which
  draws it from the water table. The rate falls linearly to zero at
  {toml}`flow.sinks_sources.etp.extinction_depth` below the drain elevation of the cell.
  This needs `"etp"` in {toml}`flow.active_sinks_sources`.
- The **runoff** goes where a loaded runoff would go: the stream networks, the
  lakes, and the discharge that a calibration compares with the gauge. A file
  that also loads a runoff, through {toml}`data.types`, is refused, because
  the same water would be counted twice.

## Parameters of this page

The fields below are the ones that appear in the equations. Open a row for
its card.

```{hmp-params}
flow.sinks_sources.recharge.soil.ru
flow.sinks_sources.recharge.soil.alpha
flow.sinks_sources.recharge.soil.kc
flow.sinks_sources.recharge.soil.impervious_fraction
flow.sinks_sources.recharge.soil.bypass_fraction
flow.sinks_sources.recharge.soil.transit_time
flow.sinks_sources.recharge.soil.curve_number
flow.sinks_sources.recharge.soil.runoff_time
flow.sinks_sources.recharge.soil.runoff_lag
flow.sinks_sources.recharge.soil.spinup
```

A soil section that uses the curve-number branch. Its keys link to their card.

```{hmp-toml}
[flow.sinks_sources.recharge.soil]
ru = "150 mm"
alpha = 0.6
kc = 1.0
impervious_fraction = 0.02
bypass_fraction = 0.0
transit_time = "3 days"
curve_number = 78
runoff_time = "1 day"
runoff_lag = "0.5 days"
spinup = "first_year"
```

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.physics.hydrology.soil_reservoir
hydromodpy.simulation.soil_recharge
```

## In the code

| What | Where |
|---|---|
| The daily step and the balance | `hydromodpy/physics/hydrology/soil_reservoir/kernel.py` (`soil_step`, `run_soil_balance`, `balance_residual`) |
| The starting state | the same file, `spinup_state` |
| What a file may say, and its ranges | `hydromodpy/physics/hydrology/soil_reservoir/config.py` |
| Grids in, columns, grids out | `hydromodpy/simulation/soil_recharge.py` |

## References

- Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998). Crop
  evapotranspiration. FAO Irrigation and Drainage Paper 56.
- Chow, V.T., Maidment, D.R., Mays, L.W. (1988). Applied Hydrology.
  McGraw-Hill.
- Schroeder, P.R. et al. (1994). The Hydrologic Evaluation of Landfill
  Performance (HELP) Model: Engineering Documentation for Version 3.
  EPA/600/R-94/168b.
- Seibert, J., Vis, M.J.P. (2012). Teaching hydrological modeling with a
  user-friendly catchment-runoff-model software package. Hydrology and Earth
  System Sciences 16, 3315-3325. https://doi.org/10.5194/hess-16-3315-2012

## See also

- {doc}`../guides/recharge`: how to set up and check a run with the soil reservoir.
- {toml}`flow.sinks_sources.recharge.soil`: the section as a reference page.
- {doc}`index`: the other theory pages.
