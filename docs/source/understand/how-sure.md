# How sure is the model?

Not completely, and no groundwater model is. This page says where the doubt comes from, what
HydroModPy reports about it, and how to read a result with it in mind. The word for this doubt
is {term}`uncertainty`.

## Where the doubt comes from

- **The inputs.** The rain that reaches the water table, the relief, the position of the
  mapped streams and the flow measured at the gauge all carry errors. A model cannot be more
  precise than its inputs.
- **The parameters.** The {term}`hydraulic conductivity` K and the {term}`specific yield` Sy
  cannot be measured at the scale of a catchment. They are found by {term}`calibration`, and
  calibration does not give a single answer.
- **The structure.** The model is a simplification: in example 04, one layer of constant
  thickness, one value of K for the whole aquifer, a monthly step and cells of 75 m
  ({doc}`what-it-computes`). Two models with different simplifications can both look right.
- **The observations.** The mapped network holds only the reaches someone chose to draw, and a
  gauge has its own error.

## Several answers can look equally good

Example 04 shows it. When K varies, the simulated discharge at the outlet does not tell the
values apart, but the extent of the seepage does ({doc}`reading-results`). This is
{term}`equifinality`: different sets of parameters reproduce the observations about equally
well. A good fit to the discharge alone does not tell which set is right.

This is why HydroModPy can calibrate on several observations at once, such as the discharge and
the stream network, and why it reports a range beside each calibrated value instead of a single
number.

## What HydroModPy reports

**A range beside the calibrated value.** After the search, HydroModPy reports the range of
values that the search tried and that scored almost as well as the best one. It reads this range
off the trials already run. It is not a probability distribution: a probability needs an error
model on each observation, and the scores used here do not provide one. Three methods exist: a free
one that reads the trials already run, one that restarts the search from other starting points
and can find a second optimum, and one that disturbs each parameter a little to see which ones
trade off against each other. The {doc}`guide <../guides/calibration-uncertainty>` explains them.

A narrow range has two possible causes. The parameter may be well constrained, or the search may
never have tried far from the best value. The range alone does not tell which.

**An ensemble band.** When you run the same model many times with different parameters or
inputs, the `ensemble_band` figure draws the median of the runs and a band between two
percentiles of them. The wider the band, the less the runs agree. It shows the spread of the
runs that you chose to make, so it is a lower bound of the doubt, not a full measure of it. The
{term}`ensemble` is only as varied as you made it.

**Honest labels.** Under every figure of {doc}`reading-results`, a
{term}`reliability label <reliability label>` says whether the result was checked, calibrated or
only indicative.

## What example 04 does not show

Each figure of example 04 comes from one run. None carries a range or a band. The example is a
demonstration of how to read the outputs, and it does not claim the precision of a study.

## Reading a result with the doubt in mind

1. Ask what was calibrated. A result that the calibration sought is expected to look right.
2. Ask whether another set of parameters would give the same fit. If the report shows a range,
   look at its width.
3. Ask what the model leaves out ({doc}`what-it-computes`) and whether it matters for your
   question.
4. Prefer a comparison to an absolute value. The difference between two scenarios, run with the
   same inputs and assumptions, is more robust than either run alone.
5. Read the verification and the validation of the model ({doc}`what-validated-means`).

## Where to go next

- {doc}`what-validated-means`: what has been checked, and how.
- {doc}`../guides/calibration-uncertainty`: the ranges, method by method.
- {doc}`glossary`: the terms of this page.
