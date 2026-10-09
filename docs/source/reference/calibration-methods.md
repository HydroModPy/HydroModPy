---
description: Every calibration method with its options and defaults, and every metric with its formula, read from the registries of the code.
---

# Calibration methods and metrics

Every search method a calibration file can name, and every metric an objective block can
score with. Both lists are read from the code at each build: the optimizer registry, the
options model and the declared traits of each engine, the metric kernels and their formulas.
Why the objective is built this way is in
{doc}`../theory/calibration/inverse-problem-formulation`.

(calibration-methods)=
## Methods

A file names a method with {toml}`calibration.method`, or per phase with
{toml}`calibration.phases.method`. Left unset, the search gets the first method whose
conditions it meets: `hmp calibrate FILE --list-phases` prints the choice and the reason, for
each phase or for the one search of a file without phases. A name that is not registered is refused when the file loads, with the list of the names that
are.

```{hmp-calibration-methods}
```

(calibration-metrics)=
## Metrics

An objective block names one metric with {toml}`calibration.objective_blocks.metric`. The
search always minimises a cost: the Cost minimised column gives how the score of each metric
enters it. In the formulas of a metric that reads a series, $s_t$ is the simulated value and
$o_t$ the observed one at the same date, over the $n$ dated pairs the scoring window keeps. A
metric that reads a network defines its own terms under its formula.

```{hmp-calibration-metrics}
```
