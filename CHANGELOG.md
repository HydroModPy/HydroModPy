# Changelog

All notable changes to this project will be documented in this file.

The format follows the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention
and this project adheres to [Semantic Versioning](https://semver.org/).

---

## About this file

This changelog lists every significant modification of the HydroModPy project,
from new features to fixes and internal updates.

Each release section includes the following standard categories:

- **Added** - for new features
- **Changed** - for updates in existing functionality
- **Deprecated** - for soon-to-be removed features
- **Removed** - for removed features or files
- **Fixed** - for any bug fixes
- **Security** - for security improvements

### How to update it

1. During development, document all notable changes under the **[Unreleased]** section.
2. When creating a new release (e.g., `v1.1.0`, `v2.0.0a1`, `v2.0.0b1`,
   or `v2.0.0rc1`), move that content into a new section named
   `## [vX.Y.Z] - YYYY-MM-DD` or the matching pre-release tag.
3. Keep the `[Unreleased]` section empty to start recording changes for the next release.

---

## [Unreleased]

## [v2.0.0rc1] - 2026-11-03

This is the first release candidate of 2.0.0. The notes below are for a reader who comes from
version 1 or from an alpha. The long development notes of the alphas are kept in
[Changes during the alphas](https://github.com/HydroModPy/HydroModPy/blob/main/docs/source/about/changes-during-the-alphas.md).

### What to do when you update

- Runs and sessions stored by an alpha are refused. Run them again with this version.
- A TOML file written for an alpha or for version 1 may use old keys. Run
  `hmp doctor --fix-config` on it. It rewrites the renamed keys and says what it changed.
- If you come from version 1, read `docs/source/get-started/from-v1.md`.
- The keys and commands that moved between versions are listed in the reference page
  `docs/source/reference/changes.md`, "What changed in the TOML". It is built from the models, so
  this file does not repeat the table.
- A file that does not say which calibration protocol it wants follows protocol 1.3.

### Added

- A page for users of version 1, with the table of old keys and commands.
- A `NOTICE` file with the licences of PyHELP and of the data, and `version` in `CITATION.cff`.
- JSON Schemas for `manifest.json`, `provenance.json` and the output of `hmp calibrate`.
- A sha256 for each file of a run. `hmp doctor` reports a sealed file that is missing or changed.
- `--format table|json|csv` on the commands that print a result, and a `HMPY.Exxx` code at the
  start of each error line.
- A transient Boussinesq run writes a `storage` budget term, so its domain budget closes.
- `hydromodpy_version_min` in `workspace.toml` is enforced.
- Checks of the MODFLOW binaries and of the HELP3O extension against a pinned sha256.
- `docs/source/about/versions.md` states what a version number may change.

### Changed

- The defaults of the soil reservoir change. `alpha` goes from 0.6 to 0.45, which means p = 0.55,
  the value of FAO-56 table 22 for cereals and maize. `flow.sinks_sources.etp.extinction_depth`
  goes from 1 m to 2 m, also for MODFLOW-NWT with a loaded ETP. A negative recharge routed to EVT
  keeps its 1 m, and a file that writes these keys reads as before.
- The soil reservoir gives each SAFRAN cell its share of the catchment in the basin mean it
  prints, and in the mean of the capacity classes. A run without a catchment polygon, or on a
  grid that misses it, still gives the cells the same weight. The grids handed to MODFLOW 6 do
  not change.
- Each stored format declares the oldest version that reads it. Every later 2.x reads every 2.0.0 run.
- A name can be renamed in a minor version. The old name keeps working for two minor versions.
- A calibration with no pin on the protocol follows 1.3: the map is cut to the catchment and
  the network is rasterised from the heads of the observed streams.
- A tie on the cost in the last phase of a search promotes the trial that the search answered.
- A date written on a stamp belongs to the period `(s, e]` that the stamp closes.
- A chain of TOML files that sets one key under an old and a new name keeps the value of the last file.
- `hmp.run` returns a `Run`, and a calibration goes through `hmp.calibrate`. Overrides go through
  `set=`. `Project.run` is now `Project.launch`. `hmp.__all__` holds the verbs, the main objects
  and the main exceptions. A name that left is refused with its new path.
- A boundary condition is active when its table is declared, and `enabled = false` turns it off.
  `active_bc` and `active_sinks_sources` are no longer written. Boussinesq and PETSc settings move
  to `[flow.runtime]`, and the discriminator is `kind` everywhere.
- On the command line, `-w` works on every verb, also before it. `hmp replay` is removed,
  `hmp test` is now `hmp dev test`, and `hmp campaign` holds the verbs of a plan of cases.
- A budget flux is negative when water leaves the aquifer, for every solver.
- A time series has a `source` column, `simulated` or `observed`, and the catchment row is named
  `catchment`. NetCDF and VTU write one variable with a layer dimension, so opening a NetCDF in
  QGIS needs `layer=` on the export.

### Removed

- The commands and flags that left before 2.0.0 have no alias. They are refused with a message.
- `catchment_mismatch` as it was. The old number is now called `basin_mismatch`.

### Fixed

- The citations of the soil reservoir are checked against the sources. The AMC I and III
  formulas now cite NEH-630, whose table they fit, the limits of `curve_number` point to the same
  handbook, and the default of `alpha` says it is a choice made here.
- The description of `curve_number` no longer says that the smoothing of SAFRAN explains a
  calibrated number above the table, which no source supports.
- The theory page of the soil reservoir now says that the retention of the curve number is not a
  store, where each piece comes from, how much the capacity moves the recharge, and what the
  bypass, the transit, the overflow and the extinction depth do to the low flows.
- A soil run on a steady first period now names `[flow.ic] kind`, and step 6 of example 04 uses
  the `kind` key and the `[flow.sinks_sources.etp]` table.
- The MODFLOW 6 `discharge` of a run with a lake and no SFR, the Boussinesq `discharge`, and the
  Boussinesq budget terms. The sizes are in Numbers.
- A network output whose `time` falls on a stamp, and a window that ends on a stamp.
- A calibration trial on a mesh wider than its catchment.

### Numbers

Every change below can move a stored number. Sizes come from example 04 unless another case is
named. Runs of older versions are not comparable on these quantities.

- Recharge the soil alone prints on example 04, 2015 to 2020, for a capacity of 50, 100, 150, 200
  and 250 mm. It was 443, 392, 356, 325 and 295 mm/year and is now 443, 389, 350, 315 and 280
  mm/year. Giving the cell that holds 83 % of the catchment its 83 % adds 7 to 9 mm/year, and the
  lower `alpha` takes back 7 to 24 mm/year.
- Discharge of step 6 of example 04 with K = 3.16e-5 m/s and Sy = 0.04, monthly, 2016 to 2020.
  NSE log goes from 0.903 to 0.932, KGE from 0.911 to 0.947, NSE from 0.904 to 0.929, the July to
  September bias from +0.022 to 0.000 m3/s, and the lowest monthly flow of 2019 from 0.183 to 0.151
  m3/s, for 0.153 gauged.
- MODFLOW 6 with a lake and no SFR, `discharge` over a three-month valley with a buffer. It was
  3.855e-05, 3.856e-05, 3.855e-05 m3/s and is now 0.100996, 0.143696, 0.087693 m3/s, about 2 600
  to 3 700 times more. The old number was the lake outlet alone. SFR and SFR with a lake do not
  move. MODFLOW-NWT cannot hold a lake.
- Boussinesq `discharge`, island of the test suite, three months. It was 4.2e-9, 9.6e-10 and
  4.2e-11 m3/s and is now 0.012709, 0.025505 and 0.010800 m3/s. MODFLOW 6 on the same mesh reads
  0.011417, 0.023888 and 0.009734 m3/s. Any score of a Boussinesq discharge changes with it.
- Boussinesq calibration trial on a mesh wider than its catchment. The old series was the domain
  sum, 2.0 times the published one on an island cut in half. It now equals the published one. With
  no buffer nothing moves.
- Boussinesq `budget/drain` and `budget/surface_excess` change sign, the size stays. The signed
  fields now close against the change of storage, to 3.7e-7 of the recharge on the steady period.
  They were off by 1.48 times the recharge.
- Boussinesq `residual` of `compare` on the island: -1.47e-05 m3/s before and -1.40e-09 after.
  Steady runs and the MODFLOW solvers do not move.
- A network output whose `time` falls on a stamp reads one period earlier. With
  `time = "2002-10-01"`, `distance_gap` goes from 86.32 to 79.08 m (-8.4 %), `D_optim` from 142.4
  to 139.2 m (-2.2 %) and the simulated network from 473 to 481 cells. A date inside a period does
  not move, so the date of the example, `2002-10-15`, gives the same numbers. On a daily run a
  date reads the day before.
- A window that ends on a stamp keeps one period fewer. `2001-01-01` to `2002-01-01` on a monthly
  run is 12 periods, it was 13. February 2000 reads 1 simulated value and 29 measurements, where
  it read 2 and 30.
- A tie on the cost in a last phase. On the shipped mesh, trials 13 and 14 tie at J = 0.8106 m
  and the promoted K goes from 8.058e-5 to 7.962e-5 m/s (-1.2 %). On 30 x 30 it goes from
  1.4678e-4 to 1.5034e-4 m/s (+2.4 %). A phase before the last does not move, so the K frozen by
  stage one does not move. A two-root bisection in a last phase now promotes the combined value
  that the report prints.
- The cut to the catchment under `heads`. On the shipped mesh and on 60 x 60 every K and cost is
  the same, and the heads examined fall from 154 to 29. On 30 x 30, J at the best trial goes from
  11.0 to 50.3 m. Under `crossing`, 3 mapped cells of 499 leave and J goes from 1.965 to 1.985 m.
- `catchment_mismatch` changes meaning on every run and enters no cost. On the shipped mesh of
  21 406 cells 0 becomes 0.37 %, and on 30 x 30 it becomes 11.0 %.
- The veto at 5 % now stops a run with no pin on a coarse mesh. It refuses Nancon on a grid of
  45 cells a side or fewer, on a Voronoi mesh of 400 m and on a grid of 120 a side.
- A file pinned on protocol 1.2 gives the same K, Sy, costs and arrays as the same file at the
  base with `observed_rasterization = "crossing"`, and 23 trials on 30 x 30. With `heads` written
  it takes 19.
- Protocol 1.3 options, for the record. `crossing` against the default `heads`: K +1.8 %, Sy -2.0 %,
  D_optim 114.0 against 104.1 m. `diagonal_neighbors = false` against D8: K -12.9 %, D_optim
  100.8 against 104.1 m, 662 mapped cells against 473. No default moves.
- Every cache key of a calibration changes once, so the trials of an earlier session are solved again.
- No number moves for MODFLOW 6 on example 04: the 55 arrays, 14640 rows of `timeseries`, 288 rows
  of `budgets` and the 11 scores (NSE 0.9345) are bit for bit the same. The comparator reads 213
  targets and no drift.
- No number moves for a run with no override, for a value override in the unit the file declares,
  or for the pinned MODFLOW release 23.0.

## [Earlier versions]

Every alpha and 0.x release is in
[Changes during the alphas](https://github.com/HydroModPy/HydroModPy/blob/main/docs/source/about/changes-during-the-alphas.md).
