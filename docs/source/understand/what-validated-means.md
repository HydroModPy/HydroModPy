# What "validated" means here

The word *validated* is used loosely. In this documentation it has a narrow meaning. This page
separates four kinds of evidence, because they do not answer the same question.

## Four kinds of evidence

| Evidence | The question it answers | What it does not answer |
|---|---|---|
| **Numerical verification** | Does the code solve the equations it claims to solve? | Whether the equations describe your catchment. |
| **Calibration** | Can the parameters be tuned so that the model reproduces the observations? | Whether the model would predict anything it was not tuned on. |
| **Validation** | Does the calibrated model reproduce measurements it has not seen, on another period or on another catchment? | Whether it holds under conditions unlike all those tested. |
| **Peer review** | Have independent experts read the method and found it sound? | Whether a given run is right. |

### Numerical verification

HydroModPy checks its solvers against references that do not come from HydroModPy: a
closed-form solution, a published MODFLOW 6 example, a manufactured solution, or a parameter that
a calibration must find again. Each check is a test, run in continuous integration, and
{doc}`../theory/validation` lists every one with the reference it uses and the threshold it must
stay under. On the maps of {doc}`reading-results`, the label {bdg-success}`Numerical check`
refers to this kind of evidence, for instance the closure of the water budget.

### Calibration

A calibration adjusts parameters until the results look like observations. When a calibrated
result agrees with those observations, the agreement is what the calibration looked for. It is
not independent evidence. The label {bdg-info}`Calibrated` says so.

### Validation

A validation compares the model with measurements that the calibration did not use, such as a
period held out, or a neighbouring catchment. This is the test that counts for a prediction.
Example 04 contains none: the same years are used to calibrate and to look at the results, and
the figures say so. A study that relies on HydroModPy for a decision should include one.

The papers and the catchments where HydroModPy has been used are listed in
{doc}`../about/applications`.

### Peer review

The two-stage method of calibration used in example 04 is published and peer reviewed (Abhervé et
al., 2023, *Hydrology and Earth System Sciences*, 27, 3221-3239). The technical note that
describes the toolbox itself is a preprint on EGUsphere: it has not been peer reviewed. A
published method does not make a particular run right, and a run is no more reliable for being
made with a reviewed method.

## What this means for a decision

- A result labelled **Numerical check** is safe to read as a statement about the solver.
- A result labelled **Calibrated** shows that the calibration worked.
- A result labelled **Indicative** is a model output that no measurement has confirmed.
- None of the three labels is a validation. If a decision depends on a result, ask for a
  validation on data that the calibration did not see, and read {doc}`how-sure`.

## Where to go next

- {doc}`../theory/validation`: every test of the code against a reference.
- {doc}`how-sure`: how far a result can be wrong.
- {doc}`can-i-check-what-was-run`: how to check what produced a result.
