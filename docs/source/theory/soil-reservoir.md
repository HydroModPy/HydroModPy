# The daily soil reservoir

The soil reservoir turns the daily rain and ETP of a grid into the recharge of a MODFLOW 6
run. It is a water balance with one store per column. The store fills with the rain, loses
water to the plants, and sends down what exceeds its capacity. This page gives the equations
of `hydromodpy/physics/hydrology/soil_reservoir/kernel.py`, what they assume and what they
leave out. Only MODFLOW 6 accepts the reservoir, so a file that declares
{toml}`flow.sinks_sources.recharge.soil` with another solver is refused. To set up a run, see
{doc}`step 6 of the staircase <../get-started/staircase/step6>`.

## The water path

```{raw} html
<figure class="hmp-theory-figure" style="margin:1.2rem 0">
<svg viewBox="0 0 820 400" role="img" aria-labelledby="soil-fig-title soil-fig-desc" style="width:100%;height:auto;max-width:820px;font-family:inherit;font-size:14px">
<title id="soil-fig-title">Water path through the daily soil reservoir</title>
<desc id="soil-fig-desc">Rain enters the soil store. The store loses water to evapotranspiration, at most kc times the ETP and less below alpha times RU, and its overflow becomes the recharge of MODFLOW 6. The demand the soil could not meet goes to the EVT package. Off by default: a curve number takes runoff from the rain, routes it and delays it, a bypass skips the store, a transit store delays the overflow, and a sealed share of the rain runs off at once.</desc>
<defs>
<marker id="soil-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="currentColor"/></marker>
</defs>
<g fill="none" stroke="currentColor" stroke-width="1.5">
<path d="M110 190 H340" marker-end="url(#soil-arrow)"/>
<path d="M460 190 H700" marker-end="url(#soil-arrow)"/>
<path d="M400 164 V96" marker-end="url(#soil-arrow)"/>
<path d="M490 70 H700" marker-end="url(#soil-arrow)"/>
</g>
<g fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="6 4">
<path d="M210 216 V310 H340" marker-end="url(#soil-arrow)"/>
<path d="M460 310 H500" marker-end="url(#soil-arrow)"/>
<path d="M600 310 H700" marker-end="url(#soil-arrow)"/>
<path d="M300 190 V250 H585 V216" marker-end="url(#soil-arrow)"/>
<path d="M65 216 V372 H750 V336" marker-end="url(#soil-arrow)"/>
</g>
<g fill="var(--pst-color-surface)" stroke="var(--pst-color-border)" stroke-width="1.5">
<rect x="20" y="164" width="90" height="52" rx="5"/>
<rect x="340" y="164" width="120" height="52" rx="5" stroke="var(--pst-color-primary)" stroke-width="2.5"/>
<rect x="310" y="44" width="180" height="52" rx="5"/>
<rect x="700" y="164" width="100" height="52" rx="5"/>
<rect x="700" y="44" width="100" height="52" rx="5"/>
</g>
<g fill="var(--pst-color-surface)" stroke="var(--pst-color-border)" stroke-width="1.5" stroke-dasharray="6 4">
<rect x="150" y="164" width="120" height="52" rx="5"/>
<rect x="530" y="164" width="110" height="52" rx="5"/>
<rect x="340" y="284" width="120" height="52" rx="5"/>
<rect x="500" y="284" width="100" height="52" rx="5"/>
<rect x="700" y="284" width="100" height="52" rx="5"/>
</g>
<g fill="currentColor" text-anchor="middle">
<text x="65" y="195">Rain P</text>
<text x="210" y="195">Curve number</text>
<text x="400" y="186">Soil store S</text>
<text x="400" y="66">Evapotranspiration ETR</text>
<text x="585" y="186">Transit</text>
<text x="585" y="204">store R</text>
<text x="750" y="186">Recharge N</text>
<text x="750" y="66">EVT</text>
<text x="400" y="306">Routing</text>
<text x="400" y="324">store C</text>
<text x="550" y="315">Delay L</text>
<text x="750" y="306">Runoff</text>
</g>
<g fill="var(--pst-color-text-muted)" text-anchor="middle" font-size="12">
<text x="400" y="204">capacity RU</text>
<text x="400" y="84">at most k<tspan dy="3" font-size="10">c</tspan><tspan dy="-3"> E, less below α RU</tspan></text>
<text x="750" y="204">MODFLOW 6</text>
<text x="750" y="84">MODFLOW 6</text>
<text x="750" y="324">to the discharge</text>
<text x="595" y="62">unmet demand</text>
<text x="500" y="182">X</text>
<text x="670" y="182">O</text>
<text x="305" y="182">P - Q</text>
<text x="220" y="262">Q</text>
<text x="445" y="244">bypass, share b</text>
<text x="400" y="366">sealed share f, at once</text>
</g>
</svg>
<figcaption class="hmp-muted" style="font-size:.9em">The solid boxes work in every soil run. The dashed boxes and paths are off by default, and each one starts when the file sets its key.</figcaption>
</figure>
```

::::{dropdown} Notation of this page
Every column of the reservoir is independent, so the column index is left out. $t$ is the day.
Stores are in mm of water per unit of unsealed area, and fluxes in mm/day. Every symbol of the
site is on {doc}`notation`.

```{hmp-notation}
```
::::

(soil-balance)=
## The daily balance

With the default values, a day has three steps. The rain reaches the soil first, so the water
in the soil before any evaporation is

$$
W_t = S_{t-1} + P_t ,
$$ (eq-soil-wet)

where $S_{t-1}$ is the store at the end of the day before. The soil evaporates at the full rate
$k_c E_t$ while it holds more than $\alpha\,\mathrm{RU}$. Below that level the rate falls
linearly with the store, and it can never exceed what the soil holds. The evapotranspiration
reads

$$
\psi_t = \min\!\left(1,\ \frac{W_t}{\alpha\,\mathrm{RU}}\right),
\qquad
\mathrm{ETR}_t = \min\bigl(W_t,\ k_c\,E_t\,\psi_t\bigr),
$$ (eq-soil-etr)

with $\psi_t = 1$ if $\mathrm{RU} = 0$. The water above the capacity leaves the soil, and the
rest stays for the next day:

$$
X_t = \max\bigl(0,\ W_t - \mathrm{ETR}_t - \mathrm{RU}\bigr),
\qquad
S_t = W_t - \mathrm{ETR}_t - X_t .
$$ (eq-soil-overflow)

With the default values, this overflow $X_t$ is the recharge $N_t$ of MODFLOW 6. The demand the
soil could not meet, $k_c E_t - \mathrm{ETR}_t$, is offered to the water table
({ref}`soil-results`).

The capacity {toml}`ru|flow.sinks_sources.recharge.soil.ru` is the water the roots can draw. It
belongs to the site, so it has no default. The soil map of Brittany gives 100 to 200 mm on
schist and granite {cite:p}`berthier2013`, and {cite:t}`dewandel2020` take 125 mm on the
catchment of example 04.

The share {toml}`alpha|flow.sinks_sources.recharge.soil.alpha` sets when the plants begin to
close their stomata. It is the $1 - p$ of FAO-56 {cite:p}`allen1998` and the $LP$ of HBV
{cite:p}`seibert2012`, and {cite:t}`manabe1969` has the same form with 0.75. The default 0.45 is
our choice. It means $p = 0.55$, the value of table 22 of FAO-56 for cereals and maize, with
0.60 for pasture.

The factor {toml}`kc|flow.sinks_sources.recharge.soil.kc` scales the loaded ETP. The value 1
assumes that the surface of this ETP looks like the site. The attribute dictionaries of SIM2
label its ETP Penman-Monteith, but we found no primary text of Météo-France that gives its
reference surface.

(soil-ru)=
## How much recharge, by capacity

The capacity moves the recharge more than any other parameter. A larger store keeps more of the
winter rain for the summer, when the plants take it back.

```{eval-rst}
.. plot:: theory/figures/soil_ru_response.py
   :alt: Mean annual recharge and evapotranspiration against the soil capacity, from 0 to 300 mm. Recharge falls from about 670 to 275 mm per year, evapotranspiration rises from about 235 to 630; the rain is 904 mm per year.

   Recharge and evapotranspiration against :math:`\mathrm{RU}`, from
   ``spinup_state`` and ``run_soil_balance`` on a synthetic six-year climate
   (904 mm of rain and 698 mm of ETP per year, the other keys at their
   defaults). The two curves sum to the rain over the run.
```

Example 04 prints the same ladder on the SIM2 rain and ETP of 2015 to 2020 over its catchment:

| $\mathrm{RU}$ (mm) | 50 | 100 | 150 | 200 | 250 |
|---|---|---|---|---|---|
| Recharge (mm/year) | 443 | 389 | 350 | 315 | 280 |

Over the same days the rain is 911 mm/year, the ETP 693 mm/year and the gauged discharge
327 mm/year. So the discharge alone does not fix the capacity.

## What the recharge represents

With the default values the reservoir has no runoff term. All the water above RU goes to the
water table, so this recharge is an effective rain. Its counterpart in SIM2 is the drainage plus
the runoff, DRAINC + RUNC. On the catchment of example 04, from October 1985 to July 2015, the
reservoir gives 308 mm/year and SIM2 gives 243 + 79 = 322 mm/year.

MODFLOW 6 then splits this water. Where the water table reaches the drain elevation, the water
leaves through the drain in the same period. Elsewhere it passes through the aquifer. So the
split between quick and slow flow comes from the aquifer parameters and the drains. On example
04 at the daily step, 2016 to 2020, with K = 3.16e-5 m/s and Sy = 0.04, the filter of Lyne and
Hollick (0.925, three passes) gives a baseflow index of 0.69 for the run and 0.67 for the gauge.
Across K from 1e-7 to 1e-4 m/s and Sy from 0.02 to 0.08, the index of the run goes from 0.03 to
0.81. {cite:t}`dewandel2020` impose the split at the surface instead, with 55 % of the effective
rain going to the aquifer on hard rock. Their share and this index are different quantities, so
the comparison says nothing of the path of the water.

A strong rain on a dry soil gives no quick flow in this model, because the soil takes it and the
plants use it later.

## The optional terms

In the code, a day runs the curve number, then the bypass, the evaporation and the overflow, the
transit, and at the end the routing and the delay of the runoff. The sealed share changes the
area that all of them apply to.

### Curve number

A part of the rain runs off before it reaches the soil. The key
{toml}`curve_number|flow.sinks_sources.recharge.soil.curve_number` starts this term, with a value
between 30 and 98. The runoff is the SCS formula of HELP {cite:p}`schroeder1994`, eq. 21, and
NEH-630 {cite:p}`nrcs2004`, eq. 10-1:

$$
Q_t = \frac{(P_t - 0.2\,\sigma_t)^2}{P_t + 0.8\,\sigma_t}
\quad \text{if } P_t > 0.2\,\sigma_t ,
\qquad Q_t = 0 \text{ otherwise.}
$$ (eq-soil-cn)

The retention $\sigma_t$, in mm, depends on the wetness of the soil the day before,

$$
w_t = \min\!\left(1,\ \max\!\left(0,\ \frac{S_{t-1}}{\mathrm{RU}}\right)\right),
\qquad w_t = 1 \text{ if } \mathrm{RU} = 0 .
$$ (eq-soil-wetness)

It moves linearly with $w_t$, from the retention of the dry number at $w_t = 0$ to the retention
of the wet number at $w_t = 1$. The file gives the class II number. The code derives
$\mathrm{CN}_I = 4.2\,\mathrm{CN} / (10 - 0.058\,\mathrm{CN})$ and
$\mathrm{CN}_{III} = 23\,\mathrm{CN} / (10 + 0.13\,\mathrm{CN})$, a fit about one number from
table 10-1 of NEH-630, and a number gives the retention $25400 / \mathrm{CN} - 254$. The straight
line is our choice. HELP uses other bounds {cite:p}`schroeder1994`, and SWAT uses a curve that
adds 2.54 mm at saturation {cite:p}`neitsch2011`. The ratio 0.2 stays because the tables of
numbers were built with it, although measured ratios are far lower {cite:p}`hawkins2002`.

The retention is no store, because no water sits in it and the balance never counts it. NEH-630
warns against reading it as the storage of the soil {cite:p}`nrcs2004`, p. 10-5. The term reads
the soil and never the water table, so it renders saturation runoff badly. The drains of
MODFLOW 6 already give that runoff and the term can count it twice, so it stays off by default.

### Bypass

Water can reach the water table through cracks, root channels and worm holes without wetting the
soil. The key {toml}`bypass_fraction|flow.sinks_sources.recharge.soil.bypass_fraction` gives this
flow as a constant share $b$ of the rain that infiltrates:

$$
B_t = b\,(P_t - Q_t), \qquad
W_t = S_{t-1} + (1 - b)\,(P_t - Q_t).
$$ (eq-soil-bypass)

The share stays the same in every season and every storm, and real preferential flow does not. A
calibrated bypass often stands in for the slow drainage that this store does not have
{cite:p}`ireson2013`. On the rain and ETP of example 04, 2015 to 2020, shares of 0.1 and 0.2 give
0.18 and 0.36 mm/day of recharge from July to September, for 0.000 without a bypass. So a bypass
rebuilds a summer floor, and it stays at 0 unless the site shows preferential flow.

### Transit through the unsaturated zone

The water can take time to cross the unsaturated zone. The key
{toml}`transit_time|flow.sinks_sources.recharge.soil.transit_time` sets the time constant $\tau$
of one linear reservoir, whose outflow is $R/\tau$. The inflow $I_t = X_t + B_t$ is constant over
the day and the code integrates the reservoir exactly:

$$
R_t = \tau I_t + (R_{t-1} - \tau I_t)\,e^{-1/\tau},
\qquad
O_t = I_t - (R_t - R_{t-1}),
$$ (eq-soil-transit)

where $O_t$ is the water that reaches the water table. A pulse leaves as a falling exponential,
and $\tau = 0$ gives $O_t = I_t$. The limit of 30 days leaves the slow response to MODFLOW 6. One
constant applies to the whole catchment, whatever the depth of the water table.

On example 04, 2016 to 2020, with K = 3.16e-5 m/s and Sy = 0.04, a delay of 5 days raises the NSE
of the daily discharge from 0.57 to 0.79 and moves the July to September bias from +0.006 to
+0.015 m3/s. A delay of 30 days, run at the monthly step, brings that bias from 0.000 to
+0.058 m3/s, so the summer floor comes back.

### Routing and delay of the runoff

The curve-number runoff goes through the same reservoir, with the time constant $\tau_q$ of
{toml}`runoff_time|flow.sinks_sources.recharge.soil.runoff_time` and its own store $C_t$. The
routed runoff is $Q^r_t$, and $\tau_q = 0$ gives $Q^r_t = Q_t$. A pure delay of $L$ days,
{toml}`runoff_lag|flow.sinks_sources.recharge.soil.runoff_lag`, follows. With $L = n + \varphi$,
where $n$ is a whole number of days and $0 \le \varphi < 1$, the delayed runoff reads

$$
Q^L_t = (1 - \varphi)\,Q^r_{t-n} + \varphi\,Q^r_{t-n-1} .
$$ (eq-soil-lag)

Both keys are read only with a curve number. They move the runoff in time and keep its volume,
apart from the part pushed beyond the last day of the run. A day before the first day reads zero,
or, with `spinup = "first_year"`, the end of the last repeated year.

### Sealed share

The key {toml}`impervious_fraction|flow.sinks_sources.recharge.soil.impervious_fraction` gives
the share $f$ of the area that is sealed. The rain on it runs off the same day, with no soil and
no evaporation. The stores above are per unit of unsealed area, so the fluxes of the column read

$$
\begin{aligned}
N_t &= (1 - f)\,O_t,\\
\text{ETR}^{\text{col}}_t &= (1 - f)\,\mathrm{ETR}_t,\\
\text{residual ETP}_t &= (1 - f)\,\bigl(k_c\,E_t - \mathrm{ETR}_t\bigr),\\
\text{runoff}_t &= f\,P_t + (1 - f)\,Q^L_t .
\end{aligned}
$$ (eq-soil-column)

A curve number fitted on a total runoff such as RUNC already holds the runoff of the sealed
ground, so $f$ stays at 0 with it. A mean of curve numbers does not replace $f$ either, because
the soil then keeps its whole area and its evapotranspiration.

## Three days, by hand

The numbers below come from one call of `soil_step` for each day, with
$\mathrm{RU} = 150$ mm, $\alpha = 0.45$, $k_c = 1$ and $f = b = \tau = 0$. The last day adds a
curve number of 80 with $\tau_q = 0$. Its store is full, so $w = 1$ and $\sigma$ is the retention
of the wet number, $\mathrm{CN}_\mathrm{III} = 90.2$.

| | Dry day | Overflow | Curve number |
|---|---|---|---|
| $S_{t-1}$ (mm) | 40 | 145 | 150 |
| $P_t$, $E_t$ (mm/day) | 0, 4 | 30, 3 | 30, 3 |
| What happens | $W = 40$ is below $\alpha\,\mathrm{RU} = 67.5$, so $\psi = 0.593$ | $W = 175$, evaporation 3, $175 - 3 - 150 = 22$ leaves | $w = 1$, $\sigma = 27.6$, $Q = 11.50$, then $W = 168.50$ |
| ETR (mm/day) | 2.37 | 3.00 | 3.00 |
| Recharge $N_t$ (mm/day) | 0 | 22.00 | 15.50 |
| Runoff (mm/day) | 0 | 0 | 11.50 |
| $S_t$ (mm) | 37.63 | 150 | 150 |
| Residual ETP (mm/day) | 1.63 | 0 | 0 |

(soil-closure)=
## The balance closes

Over any run, per column and per day,

$$
P_t = \mathrm{ETR}^{\text{col}}_t + N_t + \text{runoff}_t
+ \Delta\bigl[(1 - f)(S + R + C)\bigr]_t + \Delta\Lambda_t ,
$$ (eq-soil-closure)

where $\Lambda_t$ is the running total of runoff held back by the delay. The function
`balance_residual` computes the difference between the two sides. On 400 days of random rain and
ETP over three columns, with all the options on, the largest residual is under $10^{-13}$ mm.

(soil-start)=
## The starting state

With `spinup = "none"`, the soil starts full and the other stores empty. With
`spinup = "first_year"`, the default, the first 365 days run again and again from that full soil,
until no store moves by 0.1 mm or more over one repetition. The run stops with an error if 20
repetitions are not enough. A run shorter than 52 weeks is refused with this option, and a run of
364 days repeats those 364 days.

## Columns and capacity classes

Without {toml}`data.soil_capacity`, each cell of the rain and ETP grid is one column with the same
RU. With it, the pixels of the raster in each cell are sorted by capacity and cut into ten classes
of equal pixel count. Each class is a column of capacity
$\mathrm{RU} \times (\text{class mean} / \text{raster mean})$, so the value in the file stays the
mean capacity and the raster only spreads it. A capacity spread below the cell belongs to the
family of {cite:t}`moore2007`, and these classes are our choice. The basin value of a flux gives
each cell its share of the catchment, or the same weight without a catchment polygon.

## Where the pieces come from

The threshold balance and its overflow are the soil budget of {cite:t}`thornthwaite1957`, which
also gives a daily procedure and a start from a repeated year. SWB2 {cite:p}`westenbroek2018` has
the same order within a day and the same overflow, but it first takes a runoff from the rain.
GSFLOW {cite:p}`markstrom2008` is the closest published chain, with a daily threshold soil, a
preferential flow, a delay and the unused ETP passed to MODFLOW. It differs by its saturation
runoff and its feedback from the water table. We found no published model with this whole
assembly, and the search was not a systematic review.

## Assumptions

- The rain and the ETP are constant over the day.
- The rain falls before the soil evaporates, so the stress of a day reads the store after the rain.
- The curve number reads the wetness of the day before.
- Columns do not exchange water.
- One value of $\alpha$, $k_c$, $f$, $b$, $\tau$, CN, $\tau_q$ and $L$ holds for the catchment and the run.
- Snow counts as rain on the day it falls, and the file is refused unless `components = ["total"]`.

## Limits

- The soil never reads the water table, so a shallow water table does not reduce the capacity.
- The drainage stops at RU, where a real soil keeps draining slowly.
- The rain and the ETP need one value per day and per cell, with no gap and no negative value, on a standard calendar, on one grid, in the CRS of the model.
- A steady first stress period is refused, because it would hold the recharge of one day only.
- The SIM2 drainage jumps from 0.000 to 0.300 mm/day on 31 July 2015 over the catchment of example 04, so compare a recharge with it period by period. {cite:t}`lemoigne2020` do not explain this step.

(soil-results)=
## Where the results go

The reservoir hands three daily grids to the rest of the run, in mm/day on the cells of the rain
grid.

The recharge goes to the MODFLOW 6 recharge package. A file that also loads a recharge through
{toml}`data.types` is refused.

The residual ETP goes to the MODFLOW 6 evapotranspiration package, which draws it from the water
table. This needs a [flow.sinks_sources.etp] table. The rate falls linearly to zero at
{toml}`extinction_depth|flow.sinks_sources.etp.extinction_depth` below the drain elevation of the
cell. The default of 2 m is our choice, and this depth matters for the low flows. On example 04,
from 1 m to 2 m, the July to September bias of the discharge goes from +0.017 to 0.000 m3/s and the
lowest monthly flow of 2019 from 0.174 to 0.151 m3/s, for 0.153 gauged.

The runoff goes where a loaded runoff would go, to the stream networks, the lakes and the discharge
that a calibration compares with the gauge. A file that also loads a runoff through
{toml}`data.types` is refused, because the same water would count twice.

## Parameters of this page

The fields below are the ones that appear in the equations. Open a row for its card.

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
flow.sinks_sources.etp.extinction_depth
```

A soil section with every key and a curve number. Its keys link to their card.

```{hmp-toml}
[flow.sinks_sources.recharge.soil]
ru = "150 mm"
alpha = 0.45
kc = 1.0
impervious_fraction = 0.0
bypass_fraction = 0.0
transit_time = "3 days"
curve_number = 78
runoff_time = "1 day"
runoff_lag = "0.5 days"
spinup = "first_year"
```

## Checked by

The tests that import the code of this page. The box is generated, so a new test appears here on
the next build.

```{hmp-tested-by}
hydromodpy.physics.hydrology.soil_reservoir
hydromodpy.simulation.soil
```

## In the code

| What | Where |
|---|---|
| The daily step and the balance | `hydromodpy/physics/hydrology/soil_reservoir/kernel.py` (`soil_step`, `run_soil_balance`, `balance_residual`) |
| The starting state | the same file, `spinup_state` |
| What a file may say, and its ranges | `hydromodpy/physics/hydrology/soil_reservoir/config.py` |
| Grids in, columns, grids out | `hydromodpy/simulation/soil/` (`grids.py`, `columns.py`, `recharge.py`, `budget.py`) |

## See also

- {doc}`../get-started/staircase/step6`: a run with the soil reservoir.
- {toml}`flow.sinks_sources.recharge.soil`: the section as a reference page.
- {doc}`index`: the other theory pages.
