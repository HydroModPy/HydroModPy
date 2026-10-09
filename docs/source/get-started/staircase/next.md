# After the staircase

You ran the six steps, or enough of them. This page says where to go from there: your own
catchment, the calibration files of example 04, the six Python scripts, the daily model and
the Python API. Every file named here is already in your copy of example 04.

## Your own catchment

Keep the example open beside your project, and change one thing at a time.

1. Create the project: `hmp project new my_catchment`. It writes a `project.toml` and a
   `run_demo.toml` on a synthetic catchment, like the project `example` of the quick start.
   Run the demo first, to know the install is sound.
2. Put the outlet and a DEM under `[geographic.catchment]`, as `step1_minimal.toml` does.
   {doc}`../../guides/describe-a-catchment` draws the identity card of a catchment before
   any model exists, and costs seconds.
3. Bring the data: {doc}`../../guides/get-the-data` fetches rain, evapotranspiration, the
   river network and gauges from public services, and {doc}`../../guides/use-your-own-files`
   reads your own files. The smallest valid file of each section is on
   {doc}`../../reference/parameters/minimal-files`.
4. Grow the model one step at a time, as the staircase does: a steady run first, then
   time, then the forcing. Each file inherits the one before
   ({doc}`../../guides/inheritance`).

Public data come from French services (BD Topage, Hub'Eau, SIM2). For a catchment elsewhere,
the {doc}`list of data sources <../../reference/data-sources>` says what each one covers.

## The calibration files

Example 04 ships five files that calibrate the model of `project.toml`. Check one before you
run it: `--check` loads the file, prints what each phase will do and runs nothing.

```bash
hmp calibrate run_calibration.toml --check
hmp calibrate run_calibration.toml --list-phases
hmp run run_calibration.toml
```

| File | What it does |
|---|---|
| `run_calibration.toml` | K, then Sy, by the published protocol: K is moved until the simulated seepage network matches the mapped one, then Sy is read from the gauged hydrograph |
| `run_calibration_by_hand.toml` | The same calibration, written out as two phases |
| `run_calibration_composite.toml` | K and Sy together, the network and the hydrograph weighted. About an hour |
| `run_calibration_bdtopage.toml` | Two phases on BD Topage: K on the permanent and the full network, then Sy on the discharge. About an hour. Needs network |
| `run_calibration_api_daily.toml` | Every input from an API except the DEM, daily over 2015-2020. K takes five fixed values and each run is kept with its figures. Needs network |

The observed network and the gauge are targets: they score the model and are never an input
to it. {doc}`../../guides/calibrate` takes the task from the start,
{doc}`../../guides/calibrate-on-the-stream-network` explains the network criterion, and
{doc}`../../guides/calibration-uncertainty` reads what the result can and cannot say.

## The Python scripts

Six scripts sit next to the TOML files. Each finds the project from its own location, so you
can run it from any folder, or step through it cell by cell (`# %%`) in Spyder or VS Code.
They need the runs they read; the second column says which.

| Script | What it does | Needs |
|---|---|---|
| `py1_run_and_plot.py` | Runs `step4_transient.toml` with `hmp.run`, then draws a figure of your own: the seepage area of the catchment against the discharge | the example files |
| `py2_edit_parameters.py` | Loads `project.toml` as a Python object, changes K and Sy, runs the variant and compares it with the reference | the example files. Two runs of about a minute each |
| `py3_read_exports.py` | Redraws a figure from the exported files alone (GeoPackage, GeoTIFF, CSV, NetCDF), without importing HydroModPy | the exports of step 5 |
| `py4_sweep_k.py` | Five values of K on one `Project`, which builds the mesh once. The discharge does not tell the K apart, the seepage area does | the example files. Five runs of about a minute each |
| `py5_catalog.py` | Opens the catalog of the project, compares the scores of the runs, redraws a figure at other dates and exports a state the TOML did not ask for | a run of `project.toml` |
| `py6_monthly_maps.py` | The twelve months of 2002 on one sheet, and the 36 months as a GIF | a run of `project.toml` |

`hmp run project.toml` makes the run that scripts 5 and 6 read, and `py2_edit_parameters.py`
makes it too. The scripts are the starting point of your own: copy one and change it.

## The daily model

`run_daily.toml` is `project.toml` at a daily step, 1096 stress periods instead of 36. It
reads the daily series of the same catchment instead of the monthly ones. Count about thirty
times the solver time and the stored fields of the monthly run. It is the file to read when
you move from monthly to daily forcing. Step 6 is the other daily file, with a computed
recharge.

## The Python API

Everything the command line does is a function of `import hydromodpy as hmp`.
{doc}`../../guides/drive-from-python` runs a file, edits a configuration in memory, runs one
model many times and reads the results back as pandas and xarray objects. The
{doc}`reference of the Python API <../../reference/python/index>` lists every function, and the
{doc}`exceptions <../../reference/python/exceptions>` say what a script can catch.

## Find your way

| You want to | Go to |
|---|---|
| Know what a key does | {doc}`../../reference/parameters/index` |
| Write the results as files | {doc}`../../guides/export-results` |
| Find and compare runs | {doc}`../../guides/find-and-compare-runs` |
| Delete runs and rebuild the index | {doc}`../../guides/clean-and-reindex-runs` |
| Fix an error message | {doc}`../../guides/troubleshooting` |
| Read how the equations work | {doc}`../../theory/index` |
