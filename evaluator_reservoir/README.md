# hydromodpy-evaluator-reservoir

An independent linear-reservoir evaluator published through HydroModPy's
`hydromodpy.calibration.evaluator` entry-point group as `reservoir_recession`.
HydroModPy does not import or name this distribution.

```bash
pip install -e evaluator_reservoir
```

```toml
[calibration]
evaluator = "reservoir_recession"
method = "grid"

[calibration.parameters.k]
path = "flow.properties.k_aquifer"
bounds = [1e-6, 1e-2]
transform = "log"

[calibration.parameters.porosity]
path = "flow.properties.porosity"
bounds = [0.01, 0.3]
```

## Model

The forward model is a draining linear reservoir:

\[
S(t) = S_0 \exp(-kt), \qquad Q(t) = kS(t), \qquad h(t) = \frac{S(t)}{A n}.
\]

`S` is storage in m3, `Q` is discharge in m3/day, `h` is water head in m,
`A` is the reservoir area in m2, `k` is the recession coefficient in 1/day,
and `n` is dimensionless porosity. The observation time is 30 days. Over the
example bounds, `k <= 0.01 1/day < 1/t`, so discharge increases strictly with
`k`; together, head and discharge select a unique optimum on the declared grid.
The evaluator uses fixed observations from `k = 1e-4 1/day` and `porosity =
0.155`, so the 3 by 3 transformed grid contains the exact zero-cost solution.
