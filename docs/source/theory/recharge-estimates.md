# Recharge estimated from the data

A `[recharge_estimates]` section asks for a range of recharge on the catchment, computed
from the loaded weather, gauge and piezometers before the solver runs. None of these numbers
enters the model. They bound the answer the way the ESPERE tool of the BRGM does (report
RP-69538-FR, Lanini et al. 2016), and the run's own recharge is set beside them, so one look
says whether the run sits inside what the data allow.

## What each method reads and gives

| Method | Reads | Gives, per calendar year |
|---|---|---|
| `turc` | rain and mean temperature | effective rainfall, Turc (1954) |
| `guttman_zuckerman` | rain | recharge, Guttman and Zuckerman (1995) |
| `kessler` | monthly rain | recharge, Kessler (1967) |
| `wallingford` | gauge | baseflow and baseflow index, Gustard et al. (1992) |
| `chapman_maxwell` | gauge | baseflow, Chapman and Maxwell (1996) |
| `eckhardt` | gauge | baseflow, Eckhardt (2005) |
| `wtf` | each piezometer, specific yield | recharge, Healy and Cook (2002) |
| `closing_factor` | gauge, the run's recharge and runoff | one factor, Abherve (2022), eq. 12 |

The weather is reduced to one basin series, the mean of the grid cells or of the stations.
The gauge is turned into mm/day over the catchment area. A gap of 3 days or less in the gauge,
5 days or less in a piezometer, is filled by a straight line, and a longer gap cuts the series.
A year counts when its series covers 90 % of its days. A method whose data is missing is
skipped with a sentence that says why.

## The formulas

Turc gives an effective rainfall $P_e = P\,(1 - 1/\sqrt{0.9 + (P/L)^2})$ with
$L = 300 + 25T + 0.05T^3$. The cube is the one of the method and of ESPERE 2.44, and the
manual of ESPERE prints a square by mistake. It is a rainfall that has not yet infiltrated,
and the table says so.

Guttman and Zuckerman give three straight lines of the yearly rain, $0.45(P - 180)$ under
600 mm, $0.88(P - 410)$ under 1000 mm, and $0.97(P - 463)$ from 1000 mm. ESPERE leaves a year of
exactly 1000 mm on no line. Under 180 mm the recharge is zero.

Kessler reads the share of the yearly rain that falls from January to April, corrected by how
wet the previous autumn was against the mean autumn, and turns it into a rate of infiltration
by the cubic of his abacus. The correction goes by steps of $|CPR|$ up to 0.70, then 15. ESPERE
leaves a gap between 0.70 and 0.71. The first year has no value.

The three filters split the daily discharge into a quick part and a baseflow, read as the
recharge that leaves the aquifer. Wallingford joins the smoothed minima of blocks of 5 days.
Chapman and Maxwell use one recession constant $k$, Eckhardt adds the largest share of
baseflow $\mathrm{BFI}_{max}$,

$$
Q_b(t) = \min\!\left(Q(t),\ \frac{(1 - \mathrm{BFI}_{max})\,k\,Q_b(t-1)
+ (1 - k)\,\mathrm{BFI}_{max}\,Q(t)}{1 - k\,\mathrm{BFI}_{max}}\right).
$$ (eq-eckhardt)

Unset, $k$ is read on the falling limbs of the gauge of 5 days or more, their first 2 days
dropped, and $\mathrm{BFI}_{max}$ is the largest yearly index of Wallingford, as ESPERE does.

The water table fluctuation multiplies the rises of the water table by the specific yield. With
`correction = "recession"` it adds to each rise the decline the rain interrupted: the daily
declines of the recession before it are fitted as an exponential of time and extended to the
start of the next one. ESPERE fits the logarithm of the raw elevation, so its answer moves with
the datum. Fitting the declines does not. The estimate is proportional to $S_y$, which the
section asks for.

The closing factor is the number that would scale the run's recharge and runoff onto the
gauged volume over their common days. Abherve (2022) multiplies the SURFEX recharge by it
before he calibrates on that same gauge. Here it is only printed, so a user who wants it copies
it into `factor` knowing what it does.

## The storage loop

With a soil reservoir and a gauge, the section also writes, month by month, the rain minus the
soil's ETR beside the gauged discharge. The figure `water_balance_loop` draws them: above the
1:1 line the catchment stores water, below it the aquifer drains, and the shape of the loop
reads the size of the store (Abherve 2022, section 2.2.3, after Schmidt et al. 2020).

## The soil laws and a loaded product, month by month

{toml}`recharge_estimates.soil_methods` runs each soil law of the soil reservoir on the same
rain, ETP, ru, crop coefficient, snow and sealed share as the run. Only the storage law changes.
A run without a soil section of its own gives the laws {toml}`recharge_estimates.soil`, with
its ru written, and never reads it. In a run whose soil computes the recharge,
{toml}`recharge_estimates.compare_loaded` loads {toml}`data.recharge` and {toml}`data.runoff`,
SIM2 DRAINC and RUNC for instance, and sets them aside before the model is bound, so the model
never receives them. Each law and the product give yearly recharge rows, which join the range
above, and monthly rows of recharge and runoff beside the run's own and beside the rain and the
ETP. The figure `recharge_signals` draws them month by month and `recharge_regime` draws their
mean year. One ru is not one soil, because the ru that closes the budget differs from law to
law: on the Nancon over 2015-2020 it is 187 mm with `fao56` and 376 mm with `dingman`.

These figures need no solve. `hmp run <file> --until prepare_solver` writes the run and its
tables in a minute or two, then `hmp show <run> --figure recharge_signals --to signals.png`
draws one.

## A steady run on a yearly formula

Turc, Guttman and Zuckerman and Kessler give one value a year, so they never force a transient
run. A steady run may take one as its rate with {toml}`data.recharge.formula`. The data step
runs the formula on each complete calendar year of the run, on the basin mean of the rain (and
of the temperature for Turc), and lays the mean over the years on the grid of the rain. Turc
gives an effective rainfall, which the run takes whole, so the drains do the share a RIPE would
do. A transient run, a soil section and a scenario beside the formula are refused.

## Where the results go

The run prints one block at the end of the data step, one line per method with its mean, its
range and its years. It writes the table `recharge_estimates`, one row per method, year and
quantity, and the figures `recharge_estimates` and `water_balance_loop` read it.

## Parameters of this page

```{hmp-params}
recharge_estimates.methods
recharge_estimates.chapman_maxwell
recharge_estimates.eckhardt
recharge_estimates.wtf
recharge_estimates.soil_methods
recharge_estimates.soil
recharge_estimates.compare_loaded
data.recharge.formula
```

```{hmp-toml}
# not checked: the section alone, without the data it reads
[recharge_estimates]
methods = "all"

[recharge_estimates.eckhardt]
bfi_max = 0.80

[recharge_estimates.wtf]
specific_yield = 0.05
```

## Checked by

```{hmp-tested-by}
hydromodpy.model.forcing.recharge_estimates
hydromodpy.model.forcing.recharge_estimates_run
hydromodpy.model.forcing.recharge_estimates_config
hydromodpy.model.forcing.recharge_computed
```

## In the code

| What | Where |
|---|---|
| The formulas | `hydromodpy/model/forcing/recharge_estimates.py` |
| The table of methods | `hydromodpy/model/forcing/recharge_estimators.py` (`ESTIMATORS`) |
| The steady rate of a formula | `hydromodpy/model/forcing/recharge_computed.py` |
| The section | `hydromodpy/model/forcing/recharge_estimates_config.py` |
| Loaded data in, rows out | `hydromodpy/model/forcing/recharge_estimates_run.py` |
| The figures | `hydromodpy/display/special/recharge_estimates.py`, `water_balance_loop.py`, `recharge_signals.py`, `recharge_regime.py` |

## See also

- {doc}`soil-reservoir`: the recharge the run computes itself.
- {doc}`forcing`: how a recharge reaches the periods of the model.
