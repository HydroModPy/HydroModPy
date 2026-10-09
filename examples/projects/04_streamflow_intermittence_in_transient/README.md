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

- `project.toml`: the frozen reference model, with all the figures.
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
hmp calibrate run_calibration.toml --check
hmp calibrate run_calibration.toml --list-phases
hmp run run_calibration.toml        # same for the other calibration files
hmp export nancon_step5_export --list
```

Run a file twice and nothing is computed the second time: the command names the first run
and stops. Edit the file and the new run is `<name>.v2`, next to the first. `hmp run --force`
computes an unchanged file again.

Step 3 reads BD Topage and Hub'Eau. It needs network access on the first launch, and the
answers are cached after that. So do `run_calibration_bdtopage.toml`,
`run_calibration_api_daily.toml` and `step6_soil_reservoir.toml` (SIM2 rain and ETP). The
composite and the BD Topage calibrations take about an hour each.

## From Python

The same files can be driven from a script. Each script finds the project from its own
location, so it runs from any folder, and it can be stepped through cell by cell (`# %%`) in
Spyder or VS Code.

1. `py1_run_and_plot.py`: runs `step4_transient.toml` with `hmp.run`, then draws a figure of
   its own, the seepage area of the catchment against the discharge.
2. `py2_edit_parameters.py`: loads `project.toml` as a Python object, changes K and Sy, runs
   the variant and compares it with the reference.
3. `py3_read_exports.py`: redraws a figure from the files of `share/` alone (GeoPackage,
   GeoTIFF, CSV, NetCDF), without importing HydroModPy. It needs the exports of
   `step5_export.toml`.
4. `py4_sweep_k.py`: five values of K on one `Project`, which builds the mesh once. The
   discharge does not tell the K values apart, the seepage area does.
5. `py5_catalog.py`: opens the catalog of the project, compares the scores of the runs,
   redraws a figure of the catalog at other dates and exports a state the TOML did not ask
   for.
6. `py6_monthly_maps.py`: the twelve months of 2002 on one sheet and the 36 months as a GIF,
   with the cells where the water table reaches the surface drawn one by one.

Scripts 5 and 6 read the run of `project.toml` without running it: run `hmp run project.toml`
first, or `py2_edit_parameters.py`, which runs it.

## Where the outputs are

Each file draws its figures and writes its exports. Step 1 declares three export blocks,
steps 2 to 4 inherit them and add more (`[[export__append]]`), and step 5 starts from an
empty list (`export__delete`). The calibration files write the exports of `project.toml` for
each promoted run. The API calibration has its own, dated 2019.

- figures: `runs/<name>/figures/`
- exports: `share/<name>/`
- figures of the scripts that compare several runs: `share/figures/`

`<name>` is the name of the run: the `[simulation] name` of the file you ran, for example
`nancon_step5_export`, followed by the name of the phase for a calibration in several phases.

The documentation walks through the six steps: <https://docs.hydromodpy.fr/>, Get started,
The staircase.
