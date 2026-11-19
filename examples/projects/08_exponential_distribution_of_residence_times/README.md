# Example 08: the exponential distribution of residence times

A synthetic hillslope, 1000 m long, 20 m wide and 10 m thick, over a flat substratum. A uniform
recharge of 1 mm/day feeds it and a stream on its west edge drains it. Steady state, one particle
in each cell, tracked until it leaves. MODFLOW 6 solves the flow and its particle tracking PRT
follows the water. A run takes about 5 s.

## The files

- `project.toml`: the model, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` step by step in a `hmp.Lab`. It prints the domain
  and the mesh as they are built, and the six layers MODFLOW 6 will read with the K of each. It
  solves and sets the water table against the Dupuit parabola, keeps the model as a run, prints
  its water budget, and sets the travel times of the particles against the exponential law of a
  single well-mixed store, in a plot of numbers computed from the run.

The domain is built from the grid written in `project.toml`, so the example needs no data file.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp export hillslope_example_08 --list
```

Run the file twice and nothing is computed the second time. The script keeps a run of its own
each time it is played, so it writes the next version, `hillslope_example_08_v2`.

## The model

The ground is flat at 10 m and the base of the aquifer is flat at 0 m. The grid has 100 columns
of 10 m and two rows. K is 15 m/day, 15000 times the recharge, Sy is 0.1 and the porosity of the
particles is 0.1. The stream is a fixed head of 5 m on the west edge, and the other edges are
closed. The water that reaches the ground drains there, but the water table stays under it.

MODFLOW 6 refuses a fixed head under the bottom of its cell, and the stream stands at 5 m. So
the top layer takes the upper half of the aquifer, which is the half the water table moves in,
and five layers of 1 m share the half below.

For a flat aquifer under a uniform recharge R, the Dupuit equation gives a water table
h(x)^2 = h0^2 + R x (2 L - x) / K. It reaches 9.57 m at the divide and the model gives 9.54 m,
with no gap larger than 7 cm along the section.

## The particles

PRT tracks forward only. One particle starts in each cell of the box and travels with the flow
until it reaches the stream. Its travel time is the time its water needs to go from the cell where
it entered to the stream. The two particles that start in the cells of the stream leave at once
and are dropped, so 198 remain.

A single well-mixed store of volume V that gets a flow Q empties as exp(-t / tau), with
tau = V / Q. For the aquifer, tau = n h / R, with n the porosity, h the mean saturated thickness
and R the recharge. It is 2.24 years, and the mean travel time of the particles is 2.23 years. The
density of the travel times follows exp(-t / tau) from t/tau = 0.1 to 4. Under t/tau = 0.1 it
stands above the law, because the particles that start close to the stream leave before they have
crossed the aquifer. The median is 1.40 years, 0.63 of the mean, where an exponential law gives
0.69. The slowest particle leaves after 13 years.

## What a run writes

- `runs/hillslope_example_08/figures/`: the water table in a section from the stream to the
  divide, and the share of the particles still in the aquifer after a time t, against the
  exponential law.
- `runs/hillslope_example_08/exports/`: the water budget as CSV and the particle tracks as
  GeoPackage, one line per particle with its travel time in years.
- `summary/`: the figure the script draws, outside the sealed run.
