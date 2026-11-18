# Example 04: flow intermittence in the Nançon catchment

The Nançon catchment (Ille-et-Vilaine), simulated with MODFLOW 6. The example shows how the
seepage network grows in winter and shrinks in summer, and how K and Sy are calibrated on
the mapped network and on the gauged discharge.

## The files, in order

Each step inherits another one (`base_config`) and writes only what changes. Step 3 is a
variant of step 2 on API data. Step 4 starts again from the local data of step 2. Step 6
starts again from `project.toml`.

1. `step1_minimal.toml`: steady state, local DEM, one K, one mean recharge.
2. `step2_local_data.toml`: adds the mapped network and the gauge, as local files.
3. `step3_api_data.toml`: the same data, taken from the BD Topage and Hub'Eau APIs.
4. `step4_transient.toml`: monthly transient run 2000-2002, observed recharge and runoff.
5. `step5_export.toml`: every export format, one `[[export]]` block per format.
6. `step6_soil_reservoir.toml`: daily run 2015-2020, with the recharge computed by a soil
   reservoir from the SIM2 rain and ETP. The ETP the soil did not meet is taken from the
   water table.

Around the steps:

- `project.toml`: the frozen reference model, with all the figures. Its `[site]` names the
  catchment and its gauge, `NANCON`: every station source and every calibration file reads
  the gauge from there, so no station is written twice. The recharge and the runoff are the
  SIM2 means over the catchment. January 2000 is solved in steady state under its own
  recharge, then the run goes on month by month. Its `[metrics]` window, 2001-2002, is where
  every run is scored, and 2000 is spin-up.
- `run_daily.toml`: the same model at a daily step.
- `run_calibration.toml`: calibration of K, then Sy, by the published protocol.
- `run_calibration_by_hand.toml`: the same calibration, written as two phases.
- `run_calibration_composite.toml`: K and Sy together, with the network and the hydrograph
  weighted.
- `run_calibration_bdtopage.toml`: a two-phase calibration on BD Topage. K on the two bounds
  of the extension, the permanent network and the full network, then Sy on the discharge.
- `run_calibration_api_daily.toml`: everything from APIs except the DEM (BD Topage, Hub'Eau,
  SIM2), daily 2015-2020. K takes five fixed values and each run is kept with its figures.

## Commands

From this folder, after `pip install --pre hydromodpy` (the `--pre` is needed while version 2
is published as `2.0.0aN`; without it pip installs version 1, which cannot read these files):

```bash
hmp run step1_minimal.toml          # then step2 to step5
hmp run step6_soil_reservoir.toml --until load_data   # the soil alone: budget in mm/year, no run written
hmp check run_calibration.toml        # every problem at once, for any file
hmp calibrate run_calibration.toml --list-phases
hmp run run_calibration.toml        # same for the other calibration files
hmp export nancon_step5_export --list
```

Run a file twice and nothing is computed the second time: the command names the first run
and stops. Edit the file and the new run is `<name>_v2`, next to the first. `hmp run --force`
computes an unchanged file again.

Step 3 reads BD Topage and Hub'Eau. It needs network access on the first launch, and the
answers are cached after that. So do `run_calibration_bdtopage.toml`,
`run_calibration_api_daily.toml` and `step6_soil_reservoir.toml` (SIM2 rain and ETP). The
composite and the BD Topage calibrations take about an hour each.

## From Python

`py1_run_and_plot.py` plays `project.toml` one step at a time in a `hmp.Lab`. It finds the
project from its own location, so it runs from any folder, and it can be stepped through cell
by cell (`# %%`) in Spyder or VS Code.

After `load_data` it draws the recharge and the runoff, and after
`prepare_solver` the mesh on the relief. It then gives Sy three values, 0.001, 0.05 and 0.3,
and keeps a run for each: `nancon_sy_small`, `nancon_intermittence_mf6` (the Sy of the file,
so the run of `project.toml`) and `nancon_sy_large`. With Sy = 0.001 the water table moves by
metres in a month, and MODFLOW 6 needs four time steps per month to converge. For each run the
script prints the months when the catchment seeps the least and the most, with the NSE of the
discharge, and draws the seepage cells and a section of the water table for these two months,
the share of the 36 months each cell seeps, the discharge against the gauge, and the seepage
share of the catchment over time. It takes about five minutes. Played again, it writes the
next version of each run, `_v2`.

## Where the outputs are

Each file draws its figures and writes its exports. Step 1 declares three export blocks,
steps 2 to 4 inherit them and add more (`[[export__append]]`), and step 5 starts from an
empty list (`export__delete`). The calibration files write the exports of `project.toml` for
each promoted run. The API calibration has its own, dated 2019.

- figures: `runs/<name>/figures/`
- exports: `runs/<name>/exports/`
- what a run is and how it went: `runs/<name>/README.md`, `outcome.json`, `manifest.json`
- what it read and how it spent its time: `products.json`, `profile.json`, `request.json`
- the state a restart or the next window starts from: `final_state/`, and `mesh/` when its
  engine caches a mesh
- a calibration: its trials under `sessions/<name>/`, its best trial promoted to
  `runs/<name>/`
- figures the script draws: `summary/figures/`

`<name>` is the name of the run: the `[simulation] name` of the file you ran, for example
`nancon_step5_export`. A second run of an edited file is `<name>_v2`.

The documentation walks through the six steps: <https://docs.hydromodpy.fr/>, Get started,
The staircase.
