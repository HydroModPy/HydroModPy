# Time alignment of outputs and observations

A run writes one value per stress period. An observation chronicle has its own
dates. Before a simulated value and an observed one can be compared, both must
mean the same thing on the same interval. This page gives the one convention
every reader of a run follows: **a stamp closes its period**. A flux read at a
stamp is the mean over the period before it; a state is the value at the stamp.
How the inputs are put on the periods is on {doc}`forcing`.

::::{dropdown} Notation of this page
```{hmp-notation}
```
::::

(alignment-stamp)=
## A stamp closes its period

The periods are the intervals $[b_k, b_{k+1})$ of {eq}`eq-period-edges`. Every
solver stamps a period at its end: the time axis of a run is the start of the run
plus the elapsed solver time. January 2000 of a monthly run is stamped
2000-02-01. A steady run over 2000 to 2002 has one period, stamped 2003-01-01.
The stamp of period $k$ is therefore $b_{k+1}$.

What a stamp stands for depends on the quantity. The rule is read from the CF
`cell_methods` of the field in the field registry of the code, or, for a
calibration variable the field registry does not hold, from a table of the
code. A name that nothing declares is a mean.

| Method | Quantity | The value stamped $b_{k+1}$ stands for |
|---|---|---|
| `mean` | recharge, drain and seepage fluxes, discharge, runoff, lake inflow and outflow | the mean of the flux over $[b_k, b_{k+1})$ |
| `point` | head, water table elevation and depth, seepage mask, lake level and volume, soil stores | the state at the instant $b_{k+1}$ |

For a steady first period, the head is the equilibrium under the forcing of that
period, stamped at its end.

```{eval-rst}
.. plot:: theory/figures/forcing_stamp.py
   :alt: Two panels over four monthly periods. Top, a daily flux and the mean of each period drawn over the period and marked at its end stamp. Bottom, a daily head and the value read at each end stamp.

   A flux (top) and a state (bottom) on four monthly periods, read by
   ``period_mean_on_index`` and ``period_point_on_index``. The flux of a stamp is
   the mean of the period that ends there. The state is read at the stamp, here
   on a window centred on it because the daily record is finer than the run.
```

In the code: `time_method_for`.

(alignment-observations)=
## An observation on the periods

An observation is put on the periods by the same rule, so a simulated value and
an observed one mean the same thing. Observations are stamped at the start of
what they average: a daily mean at its day, a monthly mean at its month start.

**A mean quantity.** Period $k$ takes the mean of the observations stamped in
$[b_k, b_{k+1})$. A period with none takes the last observation stamped at or
before $b_k$ when the interval that observation stands for covers the whole
period:

$$
b_{k+1} \leq t_h + \Delta t_o ,
$$ (eq-observation-reach)

where $t_h$ is the stamp of that observation and $\Delta t_o$ the step of its
chronicle. That is a monthly mean on a daily run. Otherwise the period has no
value, and a gap in the chronicle stays a gap.

**A state.** A chronicle finer than the run is averaged on a window centred on
the stamp, reaching halfway to the neighbouring stamps. A chronicle as coarse as
the run, or coarser, gives the sample nearest the stamp, within the step of the
run. Averaging a state over $[b_k, b_{k+1})$ would compare it with a value half a
period earlier.

**A steady period.** One stamp does not say where the period starts. The scorer
takes the start of the first period from the time grid of the run, so a steady
discharge is compared with the mean of the gauge over the window of the run, not
with its last day. A steady head is still read at its stamp.

In the code: `observed_on_periods`.

(alignment-derived)=
## A series derived on the periods

A series the run derives from a forcing, such as the catchment discharge built
from a drain budget plus the runoff ({ref}`forcing-runoff`), takes the mean of
the samples of each period and holds no value: a period with no sample is a gap,
never the previous value. This is the one difference with an observation of the
same kind. On the daily record of 1, 3 and 5 mm/day for January, February and
March with the days of February removed, the three periods read 1, a gap, and 5.

In the code: `period_mean_on_index`.

## Assumptions

- A stamp closes its period: a flux is a period mean, a state is a value at the
  stamp.
- An observation is stamped at the start of what it averages.
- An observation of a mean quantity stands for one step of its chronicle.

## Limits

- **A chronicle with gaps** has a step taken from the median of its spacings: a
  period beyond that step after the last observation stays empty.
- **A state between two coarse stamps** is not interpolated: it takes the
  nearest sample within the step of the run, or no value.

## Checked by

The tests that import the code of this page. The box is generated: a new test
appears here on the next build.

```{hmp-tested-by}
hydromodpy.core.time.period_aggregation
hydromodpy.core.time.time_method
hydromodpy.results.derive.time_alignment
```

## In the code

| What | Where |
|---|---|
| The stamp convention, mean and point rules | `hydromodpy/core/time/period_aggregation.py` |
| The method of each quantity | `hydromodpy/core/time/time_method.py`, `hydromodpy/results/derive/time_alignment.py` |
| Runoff added to a drain budget | `hydromodpy/calibration/metrics/series.py` |

## See also

- {doc}`forcing`: how the inputs are put on the periods.
- {doc}`calibration/inverse-problem-formulation`: the scores that compare the
  aligned series.
- {doc}`../guides/time-and-initial-state`: the window and the first period.
