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
period held out, or a neighboring catchment. This is the test that counts for a prediction.
Example 04 contains none: the same years are used to calibrate and to look at the results, and
the figures say so. A study that relies on HydroModPy for a decision should include one.

The papers and the catchments where HydroModPy has been used are listed in
{doc}`../about/applications`.

### Peer review

The two-stage method of calibration used in example 04 is published and peer reviewed (Abhervé et
al., 2023, *Hydrology and Earth System Sciences*, 27, 3221-3239). The technical note that
describes the toolbox is published and peer reviewed too (Gauvain et al., 2026, *Hydrology and
Earth System Sciences*, 30, 5571-5592), but it describes version 1.0. The review did not cover
the code of version 2 that this site documents. A published method does not make a particular
run right, and a run is no more reliable for being made with a reviewed method.

## The label of a run

A sealed run also carries a {term}`run label`, one of four words computed when the run is read:
exploratory, calibrated, evaluated or failed. It follows rule 3 of `hydromodpy.results.validity_rules`.
A run promoted by a calibration session is calibrated only when a window was scored. That window is
a calibration period the seal records, the headline window of the run with at least one sample, or
the single state of a steady run whose cost the session read. A transient run promoted without any
of them is exploratory, with the reason "no scored window". A calibrated run scored on days the
calibration never saw is evaluated. A run whose solver did not converge is failed.

Each label comes with its reasons, in English or in French. A parameter that ended on a bound of
its range adds the reason "a parameter reached its bound", whatever the label. This does not change
the label, but it says that the search wanted to go further than the range allowed, so the value
found is a limit and not a best estimate. The method text of a run
(`hydromodpy.results.method.method_text`) writes the label, its rule, its reasons and the state of
each check, passed, failed or unknown.

## What this means for a decision

- A result labeled **Numerical check** is safe to read as a statement about the solver.
- A result labeled **Calibrated** shows that the calibration worked.
- A result labeled **Indicative** is a model output that no measurement has confirmed.
- None of the three labels is a validation. If a decision depends on a result, ask for a
  validation on data that the calibration did not see, and read {doc}`how-sure`.

## Where to go next

- {doc}`../theory/validation`: every test of the code against a reference.
- {doc}`how-sure`: how far a result can be wrong.
- {doc}`can-i-check-what-was-run`: how to check what produced a result.
