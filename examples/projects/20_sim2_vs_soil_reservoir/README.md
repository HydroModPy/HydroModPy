# Example 20: SIM2 against a soil reservoir

Two Breton catchments, the Nançon at Lécousse and the Flume at Pacé, from their outlet
coordinates alone, with every input from a public service: BD ALTI at 25 m for the DEM, BD
Topage for the network, Hub'Eau for the gauge, SIM2 for the climate. Each catchment runs with
the SIM2 drainage and runoff, then with the recharge and the runoff of a soil reservoir on the
SIM2 rain and ETP. Both run monthly, weekly and daily. One calibration on the discharge and the
extent of the network finds K and Sy for SIM2, and K, Sy and the soil capacity together for the
soil reservoir. A script draws the recharge and the runoff of any set of runs on one page.

## The files

- `common.toml`: the model, common to both catchments, with the SIM2 drainage and runoff. The
  model runs on a 150 m grid.
- `nancon.toml`, `flume.toml`: what belongs to one catchment, its outlet, its gauge and a
  starting K. These are the files to run.
- `soil.toml`: an overlay, the soil reservoir instead of the SIM2 drainage and runoff, with
  every other key it can take in comments.
- `calibration.toml`: an overlay, K and Sy in transient on the discharge and the network.
- `calibration_soil.toml`: an overlay, the same calibration with the soil capacity, and every
  other soil key that can calibrate in comments.
- `compare_recharge.py`: the page, `comparison.html`, and its table, `comparison.csv`.

## Commands

From this folder, in a HydroModPy workspace. A run takes its name from `--case`, and the script
reads that name.

The two forcings on one catchment, by the month:

```bash
hmp run nancon.toml --case nancon-sim2_month
```

```bash
hmp run nancon.toml --overlay soil.toml --case nancon-soil_month
```

A daily or a weekly run sets the step. A week needs a last day on a step boundary:

```bash
hmp run nancon.toml --case nancon-sim2_day --set simulation.time.step_value="1 day"
```

```bash
hmp run nancon.toml --case nancon-sim2_week --set simulation.time.step_value="7 days" --set simulation.time.end_datetime=2020-12-26
```

The calibrations:

```bash
hmp run nancon.toml --overlay calibration.toml --case nancon-calibration_sim2
```

```bash
hmp run nancon.toml --overlay soil.toml --overlay calibration_soil.toml --case nancon-calibration_soil
```

Then the page, with every run of the folder or the ones you name:

```bash
python compare_recharge.py
```

```bash
python compare_recharge.py "nancon-*" "*_month"
```

The first run needs network access and downloads a few hundred megabytes, the DEM of each
department a catchment touches and the SIM2 grids. The downloads are cached after it.

## Adapting it

A new catchment is a copy of `nancon.toml` with its own outlet and gauge.

`compare_recharge.py` takes any folder of runs, with `--runs`, and reads a run by its name,
`<site>-<recipe>`. It needs no key of this example. Its recharge is what MODFLOW 6 received
over the catchment and its runoff is what the simulated discharge holds above the drains, so
SIM2, a soil reservoir or a loaded file all read the same way.
