# hydromodpy-forward-cascade

An independent two-reservoir cascade published through HydroModPy's
`hydromodpy.calibration.forward_model` entry-point group as
`two_reservoir_cascade`. HydroModPy does not import or name this distribution.

```bash
pip install -e forward_cascade
```

```toml
[calibration]
evaluator = "scored_forward_model"
forward_model = "two_reservoir_cascade"
method = "grid"

[calibration.parameters.k_fast]
path = "flow.properties.k_fast"
bounds = [0.025, 2.5]
transform = "log"

[calibration.parameters.k_slow]
path = "flow.properties.k_slow"
bounds = [0.005, 0.5]
transform = "log"
```

## What it is a proof of

Its sibling `hydromodpy-evaluator-reservoir` implements the evaluator port: it
returns a cost, so the wheel decides which quantity is compared and how it is
weighed. This distribution implements the forward-model port instead. It
returns named observables, and the criteria that score them are the
`[calibration.outputs]` and `[[calibration.objective_blocks]]` of the document.
Changing a metric or a weight is an edit to the file; the wheel is not rebuilt
and does not know it happened.

`cascade_calibration.toml` is a whole calibration written that way, used by the
CI job that installs this wheel beside HydroModPy in a clean environment.

## Model

Two linear stores in series, sampled daily over 30 days. The upper store empties
at `k_fast`; a fraction `f = 0.9` of its outflow feeds the lower store, which
empties at `k_slow`, and the rest reaches the outlet directly:

    S1(t) = S0 exp(-k1 t)
    S2(t) = f S0 k1 / (k2 - k1) * (exp(-k1 t) - exp(-k2 t))
    Q(t)  = (1 - f) k1 S1(t) + k2 S2(t)
    h(t)  = S2(t) / (A n)

`S` are storages in m3, `Q` the outlet flow in m3/day, `h` the head in m, `k`
the two coefficients in 1/day, `A = 1e7` m2 and `n = 0.155`. The direct fraction
is what makes the discharge tell the two coefficients apart: with `f = 1`,
exchanging them moves `Q` by 7e-12 on a scale of 3.3e4, so a document scoring
the outlet alone would have two equally good optima. The head is asymmetric
either way. The records in `cascade_calibration.toml` are this model at
`k_fast = 0.25 1/day` and `k_slow = 0.05 1/day`, which the transformed 3 by 3
grid contains exactly.

The document declares `project_root = "."`, so running it as it is writes its
session under `forward_cascade/`. Pass `--workspace` to put it elsewhere:

```bash
hmp calibrate forward_cascade/cascade_calibration.toml --workspace /tmp/cascade
```
