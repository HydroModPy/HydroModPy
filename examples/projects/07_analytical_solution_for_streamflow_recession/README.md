# Example 07: a hillslope that drains by recession, set against a closed-form solution

A flat hillslope, 1000 m long and one 20 m cell wide, over a flat substratum at 0 m, with a stream
on its west edge. A pulse of recharge of 33 mm/day fills the aquifer for 30 days, then 970 days
without recharge empty it through the stream. The discharge of the falling limb is compared with
the late-time solution of the non-linear Boussinesq equation. MODFLOW 6 solves the flow. A run takes
about 15 s.

## The files

- `project.toml`: the model, its figures and its exports.
- `py1_run_and_plot.py`: plays `project.toml` step by step in a `hmp.Lab`. It prints the mesh and
  the model as they are built and the K, Sy and thickness that MODFLOW 6 will read, solves, reads
  the water table of each day, keeps the model as a run and asks the run for three sections of
  the water table. It ends with the recession, computed from the budget of the run in numpy and
  drawn in two plots of its own.

The example reads no data file. The domain is built by `[geographic] source_mode = "synthetic"` and
the recharge is written in `project.toml`.

## Commands

From this folder:

```bash
hmp run project.toml
python py1_run_and_plot.py
hmp export hillslope_example_07 --list
```

Run the file twice and nothing is computed the second time. The script keeps a run of its own each
time it is played, so it writes the next version, `hillslope_example_07_v2`.

## The model

The ground is flat at 100 m and the base of the aquifer is flat at 0 m, so the aquifer is 100 m
thick. The grid is one row of 50 cells of 20 m. K is 0.33 m/day (3.82e-6 m/s), Sy is 0.01 and Ss
is 1e-5 m-1. The stream is a fixed head of 0 m on the west edge and the other edges are closed.
Every cell drains at the ground surface, with a conductance that follows K.

The run has 1000 stress periods of one day. The first one is steady, under the mean of the
recharge series, 0.99 mm/day, so the pulse starts from a water table in balance with it. The pulse
brings 33 mm/day on days 1 to 29 and nothing after. At 1 % of Sy it lifts the water table to the
ground over the eastern half of the hillslope, where the aquifer drains through the surface for a
few days. The series has one value per day, so `project.toml` lists the 1000 numbers, ten per
line.

The aquifer is one layer. MODFLOW 6 refuses a fixed head below the bottom of a cell, and a stream
head of 0 m, level with the base of the aquifer, lies below the bottom of every upper layer of a
stack. One layer is also the depth-integrated aquifer that the Boussinesq solution describes.

## The recession

The stream is a fixed head, not a drain, so the discharge series of the catchment is empty and
the flow of the stream is read in the budget, as the term `constant_head`. The script turns it
into a discharge per metre of stream drained from both banks, which is twice the flow of the
20 m strip divided by 20 m. After the pulse the discharge falls as -dQ/dt = a Q^b. The late-time
solution of Boussinesq (1904) gives b = 3/2 and

    a = 4.804 K^(1/2) L / (f A^(3/2))

for an aquifer of area A drained through a stream of length L, with K in m/day and the drainable
porosity f equal to Sy. Here L = 1 m and A = 2 x 1000 m2, the two banks. That gives
a = 3.09e-3 m^-3/2 day^-1/2.

The script leaves out the first 90 days, takes the step difference of each day and sets the 909
falling days against the line. The fitted exponent is 1.497. The mean gap of the simulated rate to
the line is +0.008 in log10, which is +1.9 % on a, and it is 0.08 at most, on the highest
discharges of the first days after day 90, when the water table is still near the ground and the
late-time form does not hold yet.

## What a run writes

- `runs/hillslope_example_07/figures/`: the section of the water table at the end of the pulse and
  on the last day, the water budget, and the closure error of the solver at each period. The
  closure error stays under 0.01 %.
- `runs/hillslope_example_07/exports/`: the water budget as CSV, and the water table and the
  seepage cells at the end of the pulse and at the end of the run as one UGRID NetCDF file, which
  opens in QGIS.
- `summary/`: the figures the script draws, outside the sealed run: the sections at days 30, 90 and
  300, the recharge and discharge in time, and the recession against the solution.
