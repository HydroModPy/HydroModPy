# Changelog

All notable changes to HydroModPy are listed here, newest first. The file follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

Each release lists what was added, changed, deprecated, removed, fixed or secured. Under
`Numbers` it also lists every change that moves a stored or printed number, with its size.

During development, write each change under `[Unreleased]`, in a line or two that a user can act
on. At a release, rename that section to `## [vX.Y.Z] - YYYY-MM-DD` and open a new empty
`[Unreleased]`. The long development notes of 2.0.0 are kept in
`docs/source/about/changes-during-the-alphas.md`.

<!-- releases start here -->

---

## [Unreleased]

### What to do when you update

- A run or a session stored by a pre-release (2.0.0a5 and earlier) is refused. Run it again with this version.
- A file with a key that only a pre-release wrote is refused. The message names the current name of each such key the file holds. This version does not rewrite the file, so edit it with that list. `hydromodpy/config/prerelease_forms.txt` holds the forms.
- `hmp doctor --fix-config` still rewrites the keys that load with a warning.
- A Python name or an hmp command that left is refused with the call that replaces it. tests/unit/architecture/surface/removed_names.tsv lists them.
- If you come from version 1, read `docs/source/get-started/from-v1.md`. The keys and commands that moved are listed in `docs/source/reference/changes.md`, "What changed in the TOML".
- A file that does not say which calibration protocol it wants follows protocol 1.3.
- A run written by an earlier version keeps its label. A [[bug]] row of hydromodpy/schema/changes.toml labels exploratory only the runs whose quantities it names.

### Added

- `config.resolved.toml` writes `edition`, the set of defaults the run used, `"2.0"` today. A resolved file without it reads as edition 2.0. A file may write `edition` at its root, and a value this version does not serve is refused with the editions it serves.
- The register of changes is listed on a generated page, `docs/source/reference/changes-register.md`, one table per kind of row.
- `python -m tools.changes_changelog` writes the `Numbers` block of `CHANGELOG.md` between two comments from the register, and exits with 1 when the block differs.
- `tools/docs/snapshots/fields-2.0.0.json`, so the page of TOML changes compares that snapshot with the tree.
- `[solver.modflow_nwt]` and `[solver.boussinesq]` take `wall_clock_limit_s`, the wall-clock budget of one trial of a parallel calibration, as MODFLOW 6 does with `[solver.modflow6.runtime] mf6_api_timeout_s`. Unset, a trial keeps the built-in 14400 s.
- A flow adapter declares `face_flow` among what it writes, and the GWT one declares `concentration/*`.
- A transport whose flow does not write `face_flow` is refused when the file is read, with the flow solvers that write it.
- `[simulation.results] keep_face_flows = true` under a flow solver that does not write `face_flow` is refused when the file is read, with the flow solvers that write it.
- `[simulation.results] keep_face_flows` keeps the flow between each pair of connected cells under MODFLOW 6 and MODFLOW-NWT, as `face_flow` with `connection_cells`.
- `Project.gc()` and `hmp catalog gc` measure the project and remove the scratch of dead attempts, what the earlier attempts of sealed runs hold beside their `outcome.json`, the products past the cap that the dry run lists, and the field store of kept trials that reached the project more than 90 days ago, all but the best; `--trial-fields-days` sets the age. The mesh of a trial stays for its replay, a session with no single best keeps every trial, and a project whose `project.toml` does not read is collected from its tree with its product store left as it is.
- MODFLOW 6 and MODFLOW-NWT write `face_flow`, one value per connection of two active cells and positive from the smaller flat index to the larger, with `connection_cells`, the two cells of each connection. The diagonal of MODFLOW 6 `FLOW-JA-FACE` is never kept.
- Series names have the shape `time` in the field registry, and a backend declares the series it writes in `writes`. The linear reservoir declares `discharge`, `reservoir_storage` and `budgets`, and writes the unit the registry gives, `m` for the stored depth.
- source = "url" for the data variables read from one file. https, or http with a sha256. The URL only fills the data cache, and the run reads the file.
- `hydromodpy.model.supports` holds the closed set of traits a solver backend lists in `supports`: the boundary kinds,
  the fields of `ModelOptions` and the initial states `head_rule`, `steady_start`, `cyclic_start` and `prior_state`.
- `solver.sink_fill = true`, `solver.drain_band_depth_m` and `solver.drain_conductance_floor_m2_s` away from their
  defaults, and `[flow.sinks_sources.etp]` are refused under Boussinesq, which reads none of them.
- A transport run behind a steady start whose heads did not converge stops with `SolverDivergedError`, where it used
  to start with a warning. The replay of a sealed run still warns.
- MODFLOW 6 can rerun a solved model for a new K or Sy. It copies the input files of the solved run, rewrites only NPF
  and DRN for K, STO for Sy, and the file of the properties, and the result is bit-identical to a new build. A start
  from a steady or cyclic solve, a change that turns XT3D on or off, a change of the drain cells, other binaries or
  another shared forcing folder still rebuild.
- `[solver.boussinesq] exchange_mesh` names a mesh bundle folder that the Boussinesq solver reads as its cells, with
  their conductivity and storage. It is a developer option for the validation cases. A relative path is read from the
  folder of the TOML file.
- The `catchment` mesh engine meshes the catchment as one polygon cell, for a global model. It
  declares the `lumped` capability, and a solver that accepts any planar engine does not read
  it.
- `MeshRequest` carries the catchment outline. The planner fills it for a lumped engine only,
  so the hash of every other request is unchanged.
- The `center_kind` attribute of a mesh can say `interior_point`, the center of the one cell of
  the `catchment` engine, a point inside it from shapely's `point_on_surface`.
- The terrain port accepts the conditioning method `"provided"`, and
  `ConditionedDem.provided(path)` wraps a DEM that another tool conditioned. Both engines route
  it like any conditioned DEM, and `condition_dem` refuses it with `TerrainRequestError`. The
  port does not check that the DEM has no depression.
- `hmp run`, `hmp calibrate`, `hmp spinup`, `hmp export`, `hmp data get` and `hmp campaign array`
  take `--credentials PATH`, `--allow-host HOST` (repeatable) and `--max-download-bytes N`, and
  the command builds the `Environment` of the call out of them.
- The Python verbs `run`, `calibrate`, `spinup` and `export`, and `Project`, `open_project` and
  `Project.launch`, take `environment=`, an `Environment` from `hydromodpy.project.environment`;
  `None` keeps the default, so a run with it does exactly what it did before.
- A `credentials.toml` file outside any project, with one `[[host]]` block per address prefix
  and a password written in clear or read from a file, chosen for a destination by its longest
  matching prefix.
- A source whose declared host is not allowed by the bounds of the call is refused before any
  connection, with the refusal naming the option or argument that widens the list.

- `Model.native_recharge` carries the forcing at the step of its source, in m/s, cut to the window of the run, beside the period view the meshed backends read.
- The field registry holds the station series of `timeseries.parquet` as descriptors of shape `time`: the catchment series, the lake and reach states, and the rates that land in m3 s-1; `VARIABLE_UNITS` is read there no more.
- A solver backend can read the recharge at the step of its source, not only the mean of each period.
- A solver backend whose native step is shorter than a period of the time grid is refused when the document is read.
- The linear_reservoir solver backend, a global model on the one-cell catchment mesh, solved exactly on every piece of constant recharge. It starts from the steady state of its recharge, and a negative recharge is refused.
- A document that writes [flow.param] or [domain.depth_model], or calibrates one of their entries, is refused under a solver backend that reads no aquifer property, such as linear_reservoir.
- A calibration protocol states the observables its stages read. A backend that declares one of them unavailable is reported as unsupported, and a backend that no case of the repository runs is reported as expected to work but untested.
- The export vocabulary lists the simulated series `lak_connection` and `reservoir_storage`, which the time-series registry now holds.
- `hydromodpy.config.check.check(document, partial=True)` checks a whole or a partial configuration section by section and returns every `Diagnostic` at once: the dotted path, a stable code, a severity (`error`, `warning` or `to_fill`) and what the validator said. A required key that is not written yet is `to_fill`. The phrase of each code is in `hydromodpy/schema/phrases.toml`, in English and in French.
- `hmp.check(source, partial=True, inputs=False, environment=None)` checks a project file or a document from Python and returns its list of `Diagnostic`. On a file it gives the line of each key, and once the file has no error and nothing left to fill it adds the findings of the calibration preflight.
- `hmp config check --partial` checks a draft, where a missing required key is `to_fill` and refuses nothing. `--inputs` reads the header of each input file, of every case of a `[sites]` project too, and `--lang fr` writes the phrases in French.
- `hmp.check(..., inputs=True)` reads the header of each input file the document names. A local file is opened in a rasterio `Env` of the call. A URL goes through the head-only resolution of `core.io.fetch` under the bounds of the call, then GDAL reads the final URL by `/vsicurl/`, so GDAL never sees the first URL, and a URL without bounds is refused. A DEM must declare a projected CRS in metres, a square pixel and a grid that is not rotated, and the outlet must fall on a valid cell.
- `hmp run` accepts a `.json` request, the serialized form of `RunRequest` (schema `hydromodpy.request.v1`), and takes `--base`, the folder its relative paths are read from. A Docker run is the same command inside the image.
- `hmp.run`, `hmp.calibrate` and `hmp.spinup` take a dict or JSON text with `base=`, through the same loader as a TOML file, and `Project(config, base=)` does the same.
- `hmp.calibrate` and `Project.calibrate` take `force=`. Without it, a calibration that a completed session of its case and of the same solution key answers gives back the report of that session, read from its folder, `extra["identical_to"]` naming it, and nothing runs. `hmp run` on a calibration file does the same and says so, and `hmp run --force` searches again.
- `hmp project new` creates `inputs/` and `configs/` in the project.
- A product store under `.hmp/products/` keeps the meshes and the output of the soil reservoir, keyed by what they read and by the code that computes them. A run, a resume and the trials of a calibration ask it first.
- `[workspace] products_cap_mb` caps the store, 5000 by default. The oldest products go first, never one a running attempt cites.
- A run writes `products.json`, the products it read in order, when its solver step is prepared. A verb called after a run never rewrites it.
- A stored product that cannot be read is discarded and built again. A resume whose cited product is gone builds and stores it under the key of its current inputs.
- `[[data.dem.sources]]` takes `state = "conditioned"` for a DEM another tool filled or breached. HydroModPy skips its own conditioning, still computes the D8 directions and the accumulation, and refuses an aggregation, a crossing notch or a conditioning method beside it.
- A DEM declared conditioned that keeps cells with no lower neighbour gives a warning with their count, and the run store records it.
- The DEM is checked before the terrain chain: a projected CRS in metres, a grid that is not rotated, square pixels within 1 %, a cell size from 1 to 250 m, elevations from -500 to 9000 m, and an outlet on a valid cell.
- `hmp stop REF` and `hmp.stop(ref)` ask a running run or calibration session to stop, by the flag `.hmp/stop.json` of its folder. The run reads it between two steps, between two runs of its plan, and, through libmf6 or Boussinesq, between two time steps. An executable is never killed, so the stop waits for the end of its solve. A stopped run ends `aborted` with `StopRequested`, its process exits with 130, and `hmp run --resume` takes it up from the step it stopped in.
- A calibration session stops when `<session>/.hmp/stop.json` appears, between two batches of trials, and ends aborted with the date of the request as its error. Reopening the session removes the flag.
- `[simulation.time] window_length` cuts a long transient run into windows that end on a stress period end, and `window` picks one or plays them all. Each window is a sealed run named `<name>_w<k>` that starts from the final state of the one before, recorded as its input `initial_state`. A resume names the chain or the window that stopped, with or without the file, and the frozen `config.toml` of a window replays it from that input.
- Every run writes `final_state/`, its last heads, lake stages and SFR reach stages in double precision, sealed with the run. A restart and the next window read it first.
- Every run writes `profile.json`, the time and memory of each step, solve, figure and export, with the age of the process and what was rebuilt from an earlier attempt or read from the project store. A run stopped through its flag keeps the profile of what it did.
- `hmp catalog show` prints a Profile block read from `profile.json` (total time, start-up, solve of each run of the plan, three longest steps, what was reused), and `show_simulation` returns it under the `profile` key. A run of a pre-release says it has no profile and prints the solve time of its seal.
- The README of a sealed run says what a replay costs, read from `profile.json`.
- `hmp replay REF` and `hmp.replay(ref)` play a sealed run or a published copy again and class it: bit when every value hashes the same in double precision, deviation otherwise. `--strict` refuses a deviation.
- The seal of a run gives the digest of the values of every field, every column of a quantity and the final state, taken in double precision before a field is rounded for storage.
- An `[[export]]` block takes `deliver_to`, local or UNC folders or files and `ftp://`, `ftps://` or `sftp://` addresses (sftp through the `sftp` extra, with `host_fingerprint`). Once the run is sealed each file is copied there through `<name>.part`, three attempts each, and every address is checked before the run computes.
- `hmp export <run> --deliver` and `hmp.export(run, deliver=True)` send again what is not delivered, and every file whose bytes changed since.
- A resumed delivery checks each destination against the allowed hosts and folders as the run does, gives a `failed` line for a refused one, and warns of a clear `ftp://` password.
- A file of `exports/` that cannot be read gives a `failed` delivery line without sha256 or bytes, and `hmp export <run> --deliver` exits 1.
- A calibration delivers the promoted run of each case, only once the session is `completed`, and logs a warning when it delivers nothing.
- The refusal of an address no `[[host]]` block answers advises a `prefix` with the port of the address.
- An `sftp://` `key_file` may hold an ed25519, ECDSA or RSA private key.
- `session.json` names, for each phase, the options, the seed, the seed of each restart and the libraries of its optimizer, in an optional `optimizer` block. A `session.json` of a pre-release has none and still reads.
- The trial frame of a session (`Session.trials`) gains `batch`, `rule`, `window`, `solve_s` and `reused`, and `Session.profile()` sums where the search spent its time, by step and by `reused`.
- The method text of a run, `hydromodpy.results.method.method_text`, and its label sentence, `label_text`, in English and in French. The text has five paragraphs: the run, its data with each licence, its calibration, its quality with each check passed, failed or unknown, and its limits. Every sentence is a row of `phrases.toml`.
- A sealed run keeps `mesh/open_water` and `mesh/catchment_cells` beside the mean recharge it already kept. They are the open water and the outline cells the stream criterion read.
- `hydromodpy.results.derive.views.budget_over(run, term, polygon=None, *, crs=None, split=False, name=None)` totals a per-cell budget term over the catchment or any polygon, per time step. With `split=True` it gives the inflow and the outflow, each element counted on its own. A field in m3/s stored per cell outside `budget/`, such as `release_flux`, is summed the same way.
- `TERM_FAMILIES` and `family_terms` of `hydromodpy.core.budget.terms`, so `budget_over(run, "storage")` sums `storage_ss` and `storage_sy` under MODFLOW 6 and reads `storage` under MODFLOW-NWT and Boussinesq.
- `inflow_outflow` of `hydromodpy.core.budget.flux`, the one split of a per-cell budget into inflow and outflow.
- `hmp show SESSION` prints the summary of a calibration session: the trials by status, the best trial, the bounds it reached, why the search stopped and the path of its report. A run goes to `hmp catalog show`.
- `hmp calibrate` writes the report of each session directory it leaves, `sessions/<s>/report/`. `hmp calibrate --no-report` and `hmp.calibrate(..., report=False)` skip it, and a report that fails warns without failing the calibration.
- The seal of a data overview writes `tables.parquet/data_inventory.parquet` and lists the loaded inputs in `inputs.json`. Its stats card, station table and page are drawn from those rows.
- `Run.read`, `Run.table`, `Run.figure` and `Run.show`; `Session` and `RunSet` get `table`, `figure` and `show`. A figure is drawn by the renderer the object was opened with.
- `to_dict` on `StatusReport`, `PlanDraft`, `PublishedProject`, `PublishedLine`, `SpinupResult`, `InstallReport`, `ExampleEntry` and `Comparison`, and two returned types, `CalibrationPlan` and `DoctorReport`.
- `hmp ls --disk` lists runs and sessions from their directories, `hmp ls --plan` says where a `[sites]` plan stands, `hmp show` reads a profile (`--profile`), a cell (`--point`), a ranking (`--rank`), a figure (`--figure`), a report (`--report`) and a sealed table (`--table`), `hmp config figures` lists the figures, and `hmp catalog trash REF` moves a run to the trash.
- `hydromodpy_server`, a thin HTTP layer on the verbs, outside the wheel. It serves one space per organisation, runs each run in its own process, takes a file upload into the project inputs, and needs an authenticating proxy in front. `python -m hydromodpy_server --root ROOT` starts it, and the Docker image carries it.
- A run played inside the HydroModPy image seals the image tag and digest in `provenance.json`, and a replay in another image names the digest change in its lineage. The image installs every extra and the solver binaries at build time, and keeps the versions of its build in `/opt/hmp/constraints.txt`.
- A run refuses a field or a table that its backend does not declare in `writes`, and a simulated series that the series registry does not describe.
- `cutoff_wall_flow`, `groundwater_level`, `groundwater_depth`, `water_level` and `lake_level` have their series descriptor and unit.
- The page of each package lists its modules with the first line of their docstring, generated when the docs are built (directive `hmp-module-table`). A module without a docstring fails the strict build.
- A science map links each theory page to the modules that compute it, their unit tests and the validation cases, read from the pages and the tests when the docs are built (directive `hmp-science-map`). A theory page without a `hmp-tested-by` block, or a prefix in it that is not a module, fails the strict build.
- One how-to page, `plug-into-a-port`, lists every port with what a plugin declares, how it registers and the tests that cover it, read from the registries (directive `hmp-port-table`).
- `python -m tools.docs.check_readmes` computes the permitted READMEs from the layer matrix and the registries, and refuses any other README under `hydromodpy/`, a README that is too long, a bullet with a bold label, a dash used as punctuation, a closing summary or French.
- `python -m tools.docs.check_refs` also checks that a repository path between backticks in a README of a package or on a contributor page exists.
- The README of a run says what the run does not give: a change in time on a steady run, the state inside a stress period otherwise, the flow between cells unless `keep_face_flows` is set, and a residence time without particle tracking. It gives that setting only when the solver of the run writes the flow and the run is not a kept calibration trial.
- The main CI plays the scenarios in parallel, gates the line and branch coverage of each sub-package of `hydromodpy` from one table, `tools/ci/coverage_floors.toml`, checked by `tools/ci/coverage_floors.py`, and on each push proves that the test functions a change removes lose no covered line, branch or killed mutant of their modules. The table replaces the 45 coverage report lines and the four coverage jobs of the main CI.
- `tools/ci/proof.py` with `select`, `prove`, `range` and `week`: it picks the test functions a change removes and the tests that stand for them, then runs `tools/ci/removal_proof.py check` to prove that no line, branch or killed mutant of their modules is lost. A change that also edits `hydromodpy/` is refused. A push is proved commit by commit against each parent, a pull request as one change.
- `python tools/ci/local.py list|run` replays the Linux, Python 3.13 steps of the CI workflows on a local machine. It plays each identical test command once, lists every other step as not played locally with its reason, and writes one log per step and a `status` file.
- Weekly jobs replay the frozen MODFLOW 6 gmsh run with one and four BLAS threads and keep its field-scale gaps and the processor as an artifact, prove the test removals of the week at the package scope, and play every Windows proof, the server path and two runs in two processes on Windows.
- The Docker image is published on each version tag to `ghcr.io/hydromodpy/hydromodpy`, with `latest` only outside pre-releases, and a small run plays and replays at the bit inside each image the CI builds.
- Contributors: `tests/regression/frozen_documents/v2.0.0-pre/` keeps the documents of a pre-release that `frozen_runs` does not hold (publication, install index, plan, lockfile, sidecars, data caches, trial series, the six documents of a sealed job, site catalog), written on a synthetic island by `python -m tools.freeze_documents`, and a test reads each one with the readers of this version.
- A page for users of version 1, with the table of old keys and commands.
- A `NOTICE` file with the licences of PyHELP and of the data, and `version` in `CITATION.cff`.
- `hydromodpy_version_min` in `workspace.toml` is enforced.
- A sha256 for each file of a run. `hmp doctor` reports a sealed file that is missing or changed.
- `--format table|json|csv` on the commands that print a result, and a `HMPY.Exxx` code at the start of each error line.
- JSON Schemas for `manifest.json`, `provenance.json` and the output of `hmp calibrate`.
- A transient Boussinesq run writes a `storage` budget term, so its domain budget closes.
- `[calibration] validation_window = {start, end}` keeps dates apart from the search. Each trial is also scored on them, under `validation.cost`. The promoted run stores the period and the score in `checks.calibrated_by`.
- `[metrics] window` minus the validation window is the default calibration window. A validation window that overlaps it, leaves a bound open or has no dated record is refused by name.
- `Project.calibrate()` takes `protocol`, `case`, `resume`, `dry_run`, `workspace`, `project`, `project_label`, `metric_fn` and `objective` by name on every route. `dry_run=True` returns the plan.
- `flow.sinks_sources.recharge.factor` multiplies the recharge in force. The default of 1 changes nothing. A calibration reaches it as `recharge.factor`, searched in log space between 0.5 and 2.
- `vka` can be calibrated under MODFLOW 6 as `[calibration.parameters.vka]`, in log space. It is not offered when the project declares `Kv`.
- `hmp campaign promote CASE` without `--trial` lists the five best completed trials. `hmp config targets` shows the search space, the draw and the default bounds of each target.
- `hmp check` refuses `normal` sampling on `lhs` and `optuna`, and a calibrated recharge factor when the run has no recharge to multiply.

### Changed
- The register of changes is `hydromodpy/schema/changes.toml`, read by `hydromodpy/schema/changes.py`. It lists each bug fix and each rule that moves a number, each default that moves with an edition, and each key that moves. The migration of a configuration is its rows of `document = "config"`, the label of a run reads its bugs, and the `Numbers` section of this changelog is generated from it. `hydromodpy/results/known_issues.toml` is removed.
- `[[simulation.process]] type`, which `hmp init` of a pre-release wrote, loads with a warning under its name `kind` and is refused from 2.2.0.
- `hmp run --frozen` no longer counts as a difference a key that the sealed `config.resolved.toml` does not write, when the replay holds it at its default. `lineage.drift` of a rerun lists such keys under `new_at_default`.
- A known bug of a data source declasses only the runs whose `config.toml` declares that source, through the token `source@<section>_<source>`. The three Hub'Eau bugs of a pre-release name `source@hydrometry_hubeau`, so a run that declares no Hub'Eau hydrometry keeps its label.
- `label_of` and `labelled_identity` of `hydromodpy.results.run_identity` take the folder of the run, whose `config.toml` says the sources the run declared.
- The refusals of calibration keys, `flow.param` ids, `[export]` tables, `[flow.bc.<family>.<id>]` tables and sgrid keys of a pre-release of 2.0 name every key with its current name and say that this version does not rewrite the file. `renamed_to` of `hydromodpy.calibration.config` takes the old key first.
- The refusal of a key only a pre-release wrote carries one fault per key in `details`, each with its JSON pointer, and the file in `source`.
- The sidecar reader applies the rows of `schema/changes.toml` marked `document = "sidecar"` instead of renaming `custom` to `file` in code.
- A transport backend receives the frozen `Model` of its flow, its options, the run slot of its flow and the `SolverRun` of that flow, through `build(model, options, slot, upstream=())`. It no longer reads the setup, the configuration or the run store.
- MODFLOW-NWT writes its flow-transport link file when a later run of the plan reads `face_flow`, and no longer looks for a run named `mt3dms` in the plan.
- The concentration of a transport run is stored under `concentration/<species>`, named by `spc_name`. Runs written by a pre-release still read.
- The calibration catalog lists the calibrable options of the backend that runs. `vka` is found that way.
- Every data source that goes to the network now does it under the bounds of the call, with its allowed hosts, byte ceiling and timeout: OpenStreetMap, EU-Hydro, BD Topage, SHOM, the two crossings sources, Hub'Eau piezometry, water quality and intermittency, and the area check of the gauge. Before, each opened a client under the default bounds.
- `hydromodpy.data.sites.importers.rows_from_hubeau` takes `bounds`, the bounds of the call for the station search and the BD Topage snap.
- The setup step resolves every [data] file and url source under the bounds of the call before the run is named, so allowed_roots holds for every section and not only for the DEM.
- Lake geometry, abacus and bathymetry are read by their data readers and bound by lake id again, and a cutoff wall or flow barrier line_path is read from the project root.
- GeographicConfig.from_outlet, from_dem and from_polygon lose their ignored dem argument.

- Every download goes through hydromodpy.core.io.fetch, with a client made for each call and the bounds of the call: allowed hosts, a byte cap of 2 GiB by default, and no private address unless the host is allowed by name. Redirections are followed by hand and checked at each hop.
- source = "custom" is now source = "file" in every [[data.<variable>.sources]]. hmp doctor --fix-config rewrites it, and a sealed run reads it.
- A relative path is read from the project root only. A bare file name is no longer looked up in the workspace data folder, and a path that starts with a URL scheme is refused.
- The lake and wall files are read by hydromodpy.data, and the binders of hydromodpy.model receive geometries and tables.
- `hydromodpy.analysis.compare` is now `hydromodpy.project.compare`, and `hydromodpy.examples` is now
  `hydromodpy.project.examples`. The rows behind `hmp example list` and `show` are `hydromodpy.project.examples.rows`.
- `masstransfer` of MODFLOW-NWT moved to `hydromodpy.solver.modflow_nwt.mt3dms.masstransfer`.
- `hydromodpy.solver.modflow_nwt.modpath._resolvers` is now the public module
  `hydromodpy.solver.modflow_nwt.modpath.resolvers`.
- The code behind `hmp catalog`, `data`, `lock`, `privacy`, `project`, `viz` and `workspace` moved from
  `hydromodpy.cli._workers` into the package each verb serves (`results.catalog.listing`, `results.catalog.liveness`,
  `results.catalog.privacy`, `results.catalog.indexer`, `results.catalog.federation`, `data.request.cache_verbs`,
  `data.workspace.folders`, `project.lock`, `display.catalog_figures`). The old paths are gone. Every command prints
  and exits as before.
- `find_workspace`, `find_data_workspace` and `find_workspace_root` moved from `hydromodpy.cli.helpers` to
  `hydromodpy.core.workspace.resolve`. `path_size` moved to `hydromodpy.core.io.filesystem`, `project_root_at` and
  `sites_project_root` to `hydromodpy.core.state.result_dirs`, and `remove_for_good` to `hydromodpy.results.trash`.
- `hmp run script.py` now says to run the script with `python`.
- `hmp dev test`, `hmp dev run-script` and `hmp dev examples` left the wheel. In a source checkout, run
  `python -m tools.dev test`, `python -m tools.dev run-script` or `python -m tools.dev examples manifest`. `hmp dev`
  answers with the new form.
- `hydromodpy.model` is new. It holds what a solver receives: `domain` (from `spatial.domain` and `spatial.lake_bed`,
  whose modules are now `model.domain.lake_bed_abacus` and `lake_bed_regrid`), `properties` (from `spatial.field`, with
  `physics.flow.physical_properties` and `property_ids`, and `solver.base.properties` now
  `model.properties.property_table`), `forcing` (from `spatial.forcing` and `physics.forcing`, with `physics.base.forcing`
  now `model.forcing.dated_forcing`, `physics.flow.time_forcing` now `model.forcing.time_forcing` and
  `physics.hydrology.synthetic.forcing` now `model.forcing.synthetic`), `boundaries` (the boundary conditions and the
  binders of `physics.flow`, with `binders.payloads` now `model.boundaries.binder_payloads`), `sinks_sources`, `initial`
  (`physics.flow.initial_conditions` as `initial.config`, `solver.base.initial_conditions` as `initial.heads`, and
  `simulation.spinup_config`), `time` (`regime`, `history_contract`), `soil` (`physics.hydrology.soil_reservoir` and
  `simulation.soil`) and `transport`.
- `Flow` is now in `hydromodpy.model.flow`. `FlowConfig` and its TOML loader are one module,
  `hydromodpy.model.flow_config`, which also holds `from_toml_section`, `normalize_bc_payloads` and
  `resolve_forcing_paths`. `physics.contracts`, `physics.base.payloads`, `physics.base.process_spatial`,
  `physics.flow.runtime_config` and `physics.flow.toml_examples` are modules at the top of `hydromodpy.model`.
- `hydromodpy.physics` and `hydromodpy.simulation` are gone, with every name their package files exported. Import a name
  from the module that defines it. `hmp.physics` and `hmp.simulation` no longer open a package.
- The plan, the planner, the plan runner and the `[simulation]` models moved from `hydromodpy.simulation` to
  `hydromodpy.solver.base`: `plan`, `planner`, `runner`, `transport_runs`, `simulation_config` (was `planning.config`),
  `observation_config` and `results_config`.
- `simulation.post_run` is now `hydromodpy.workflow.steps.run_outputs`, `simulation.catchment_aggregation` is
  `hydromodpy.results.derive.catchment_aggregation`, and `simulation.observation_ingest` is
  `hydromodpy.data.ingest.observations`.
- `spatial.geographic.structure_binders` is now `hydromodpy.model.domain.structure_binders`. `hydromodpy.spatial` no
  longer exports `Domain`, `DomainConfig` and `FieldParam`.
- The schema exported for a bare model class is named after its new module, for example
  `urn:hmp:schema:model.properties.physical_properties.FlowPhysicalProperties`.
- The config schema digest that a lockfile records changes once, because two descriptions name a module that moved.
  `hmp lock verify` reports it and still passes.
- `hydromodpy.mesh` is new. It holds what `hydromodpy.spatial.mesh` held: the mesh request and the `[mesh]` config, the
  planner, the engines, the cells and the exchange formats. Import `hydromodpy.spatial.mesh.<module>` as
  `hydromodpy.mesh.<module>`. `planning`, `engines`, `cells`, `io` and the modules at the top keep their names.
- The mesh objects moved from `hydromodpy.spatial.mesh.model` to `hydromodpy.mesh.planar` (`HydroMesh`,
  `PlanarCellMesh`, `CellType`, the geometry, the quality report and the regular grid), so the folder no longer reads
  like `hydromodpy.model`.
- `watershed_cell_mask` moved from `hydromodpy.spatial.geographic.delineated_catchment` to
  `hydromodpy.mesh.cells.in_polygons`, next to the cell mask it calls.
- `hydromodpy.spatial` no longer exports `CellBlock`, `CellType` and `HydroMesh`. Import them from
  `hydromodpy.mesh.planar.hydro_mesh` and `hydromodpy.mesh.planar.cell_types`.
- The entry-point group of mesh engines is still `hydromodpy.mesh.engine`.
- `hydromodpy.catchment` is new. It holds what was left of `hydromodpy.spatial` once `model` and `mesh` had their own
  package: `terrain`, `delineation`, `drainage` and `administrative`, unchanged inside, and the geographic pipeline in
  three parts. `algorithms` was `spatial.geographic.core`, and also holds `dem_metadata`, `geographic_paths` and
  `river_network_config`. `synthetic` was `spatial.geographic.synthetic`, with `synthetic_config`. `preprocess` is the
  rest of `spatial.geographic` (configuration, cache, pipeline, store ingestion, subbasin, regional flow job), with
  `pipeline_steps`. So `hydromodpy.spatial.geographic.core.pipeline_steps` is now
  `hydromodpy.catchment.preprocess.pipeline_steps`, and `hydromodpy.spatial.geographic.synthetic_config` is now
  `hydromodpy.catchment.synthetic.synthetic_config`.
- `RasterSupport`, `Surface`, `PreparedSurfaceSampler` and the geology source protocol are now in
  `hydromodpy.catchment.raster_support`, `surface`, `surface_sampling` and `protocols`. `spatial.job_inputs` is now
  `hydromodpy.model.domain.job_inputs`, next to the `domain-build` worker.
- `hydromodpy.spatial` is gone, with every name its package file exported. Import a name from the module that defines
  it. `hmp.spatial` no longer opens a package.
- `hydromodpy.catchment.terrain` no longer re-exports the terrain port. Import `TerrainEngine`, `CappedBreach` and the
  other port names from `hydromodpy.catchment.terrain.port`, and the two engines from `numpy_engine` and
  `whitebox_engine`. The entry-point group of terrain engines is still `hydromodpy.terrain.engine`.
- The bundled `departement.gpkg` moved with `administrative` to `hydromodpy/catchment/administrative/`.
- The solver backends read a frozen `hydromodpy.model.model.Model`: the geometry, the properties as profiles, the
  boundaries, the recharge, the ETP, the wells, the lakes, the SFR networks, the barriers, the start state, the time and
  four `[solver]` options. The `prepare_solver` step builds it once per run with `model_from_flow` and puts it on
  `setup.model`. `Modflow6`, `ModflowNwt` and `Boussinesq` keep it in `inputs` and never change it.
- `Modflow6` and `ModflowNwt` no longer take the geographic object, and their `pre_processing(model, options)` takes the
  `Model` in place of the flow, the domain and the cell mesh. `Boussinesq(model=..., runtime=...)` reads the `Model`
  and the `[flow.runtime]` options.
- `Flow` loses the fifteen Boussinesq settings it copied from `[flow.runtime]` (`runtime_backend`,
  `surface_interaction_model`, `partition_release_depth_m`, `runtime_max_iterations`, `runtime_tol_residual_inf`,
  `runtime_tol_state_update_inf`, `vi_substeps_per_period`, `vi_substep_on_failure`, `vi_max_adaptive_substeps`,
  `ts_vi_steps_per_period`, `ts_vi_adapt`, `ts_vi_dt_min_fraction`, `ts_vi_dt_max_fraction`, `ts_vi_type`,
  `ts_vi_snes_type`) and the unread `initial_condition_types` and `boundary_condition_application_domains`. Boussinesq
  reads `[flow.runtime]`.
- The start of a run is one of five records of `hydromodpy.model.initial.state`: `HeadRule`, `SteadyStart`,
  `CyclicStart`, `PriorState` and `SolvedState`. The models of the steady start and of a spin-up cycle are
  `steady_variant` and `cycle_variant` of `hydromodpy.model.model`, which return a new model. They replace
  `steady_flow_copy_for_initialization`, `cyclic_flow_copy_for_initialization`,
  `flow_uses_steady_state_initial_condition`, `flow_uses_cyclic_spinup` and `resolve_head_initial_condition`.
- `hydromodpy.model.initial.config` and `spinup_config` are one module, `hydromodpy.model.initial_config`. It also holds
  the `[flow.ic]` strategy readers (`initial_state_of`, `steady_state_strategy_of`, `cyclic_spinup_strategy_of`), which
  leave `hydromodpy.model.initial.heads`. `heads.py` keeps the numpy kernels and gains `restart_start_heads`.
- The soil reservoir modules other than the kernel move to `hydromodpy.model.forcing`: `soil.config`, `soil.columns`,
  `soil.grids`, `soil.recharge` and `soil.budget` are now `forcing.soil_config`, `soil_columns`, `soil_grids`,
  `soil_forcing` and `soil_budget`. `hydromodpy.model.soil` keeps `kernel`.
- The earlier run that `flow.restart_from` names is read once, before the solve, by
  `hydromodpy.results.storage.prior_state`. A run solved on another mesh is refused there with the same message as
  before, and the lake stages of the restart come from the `PriorState` of the model. `verify_restart_mesh`,
  `read_restart_lake_stages` and `read_final_head` move there from
  `hydromodpy.solver.modflow6.builders.initial_conditions`, with `written_step` and `reoriented_rows` from
  `hydromodpy.solver.modflow6.support.written_grid`, which is gone.
- `map_flow_properties`, `resolve_flow_property_arrays`, `require_positive_conductivity` and `require_positive_storage`
  take `profiles=` instead of `flow=`. A per-cell property override is set with `Model.with_properties`, which refuses a
  name that sets no property, and a `properties` key in the per-run overrides of the run context is refused by name.
- `ensure_flow` moves from `hydromodpy.solver.base.runner` to `hydromodpy.workflow.steps.data`. The runner no longer
  builds a `Flow`, and a flow run without the `Model` of the `prepare_solver` step stops with a `ConfigError` that names
  the step.
- `build_preprocess_options`, `require_cell_mesh` and `run_flow_model` read `setup.model` instead of `setup.flow`,
  `setup.domain`, `setup.cell_mesh` and `cfg.solver`. `channel_tree_for_run` takes the `ChannelRasters` that
  `channel_rasters_for_run` chooses, `run_basin` and the catchment functions take a `CatchmentGeometry`,
  `networks_route_drainage` takes a `Model`, `resolve_first_period_steady` takes `model=` and `step_persist_params` takes
  the parameter profiles of the `Model` instead of a `Flow`.
- The MODPATH and MT3DMS models read the DEM grid and the catchment polygon from `Model.geometry` through the MODFLOW-NWT
  solver. `get_geographic` of `hydromodpy.solver.modflow_nwt.modpath.resolvers` is replaced by `get_raster` and
  `get_catchment`.
- The auxiliary steady solve of MODFLOW 6 and MODFLOW-NWT always starts from the top of the model. It started 0.01 m
  below the top when `[flow.runtime]` set `backend = "petsc"` and `surface_interaction_model = "vi_obstacle"`, two
  Boussinesq settings. See the recipe `modflow_steady_start_ignores_boussinesq_runtime` of `changes.toml`.
- Every plugin surface (solver backends and extractors, data sources, mesh and terrain engines, trial evaluators,
  forward models) resolves through one registry class, `hydromodpy.core.plugin_registry.PluginRegistry`, with the calls
  `register`, `get` and `names`. A registry keys a class on one or more of its attributes joined by `_`, and an
  entry-point name is compared with that join and never split. The seven entry-point groups keep their names.
- Each registry module exposes its registry object and no module function: `solvers` and `extractors` in
  `hydromodpy.solver.base.registry`, `data_sources` in `hydromodpy.data.source.registry`, `mesh_engines` in
  `hydromodpy.mesh.registry`, `terrain_engines` in `hydromodpy.catchment.terrain.registry`, `evaluators` in
  `hydromodpy.calibration.evaluation.registry` and `forward_models` in
  `hydromodpy.calibration.evaluation.forward_registry`. Write `mesh_engines.get(name)`, `terrain_engines.create(name)` or
  `evaluators.register(cls)` where the module functions `get`, `create`, `register`, `unregister` and `load_plugins`
  were called, `mesh_engines.names()` for `list_*_ids()`,
  `mesh_engines.names(shipped_only=True)` for `builtin_*_ids()`, `name in mesh_engines.names()` for
  `is_registered(name)`, and `evaluators.get(name).evaluator_id` for `resolve_id(name)`.
- A solver backend declares on its adapter class `name`, `process_type`, `accepted_meshes`, `geometry`, `writes`,
  `reads`, `supports`, `options`, `category`, `native_step`, `mutable` and `requires`. `solver_name` becomes `name`,
  `capabilities` is split into `writes` and `supports`, and the category moves from the extractor to the adapter. The
  registry refuses a backend that lacks one of them or declares one with the wrong type, and names it.
- An unknown solver key raises `SolverInputError` instead of `KeyError`.
- The category a run records in its manifest is the one its solver backend declares. The shipped backends keep theirs,
  and a third-party backend records its own where it recorded none.
- The refusals of `flow.restart_from` and of a cyclic spin-up read the traits `prior_state` and `cyclic_start` in the
  `supports` of the backend, and their message names the trait.
- `primary_solver_for_simulation` of `hydromodpy.workflow.steps.prepare_solver.facts` is now
  `primary_run_for_simulation` and returns the process type with the solver.
- The solver catalog of the reference shows what each backend declares (category, grid, meshes, what it writes and the
  traits it supports) in place of the capability names.
- `solver.backend` is a string, the name of a registered flow solver, for example `solver.backend = "modflow6"`. The
  table form `[solver.backend] kind = "..."`, and `kind = "custom"` with `name`, still loads with a warning, and
  `hmp doctor --fix-config` rewrites it. An unknown name is refused with the names this installation serves. A run under a
  plugin solver no longer lists `solver.backend` among its experimental keys.
- The settings of a flow solver are written under `[solver.<name>]`: `[modflow6]` is now `[solver.modflow6]`,
  `[modflownwt]` is now `[solver.modflow_nwt]` and `[flow.runtime]` is now `[solver.boussinesq]`. The old tables load
  with a warning, and `hmp doctor --fix-config` moves them. A plugin solver gets its own table, checked by its options
  class. A run sealed with the old tables reads back in silence, and `hmp run --frozen` compares them where they are
  now.
- `config.resolved.toml` holds the settings table of the flow solver the run used and the tables the file wrote, not
  the table of every shipped solver. A table of a solver that did not run counts for no drift on a replay.
- A name in `[[simulation.process]] solvers` is refused when the file is read if no solver of that process serves it,
  with the names this installation serves.
- A key the chosen flow solver does not honor is refused when the file is read, from the supports the solver declares,
  and the refusal names the solvers that honor it. A sealed run still reads and only warns. The K tensor, the
  pass-through cells of `[domain.layers]` and a layering under Boussinesq are now refused with
  `IncompatibleCapabilitiesError`, like a boundary, a restart or a soil reservoir the solver does not read.
- A transport solver is refused when the file is read if its `requires` does not name the flow solver of the run, with
  the flows it follows. A MODFLOW 6 flow with MODPATH or MT3DMS used to be refused only when the plan was built.
- An unknown key of `[flow.bc]` is refused with the seven boundaries the table holds, `drainage` included.
- The metric names a file may write come from one table, `hydromodpy.core.scoring.metric_table.METRIC_SPECS`. The
  names accepted do not change. `METRIC_SENSE` and `MetricSense` moved there from
  `hydromodpy.results.catalog.constants`, `METRIC_NAMES` of `hydromodpy.results.metric_rule` became `RUN_METRIC_NAMES`
  there, and `LOG_METRICS`, `DIMENSIONLESS` and `CLIPPED_METRICS` became flags of the table rows.
- `calibration.evaluator`, `calibration.forward_model`, `mesh.engine` and `geographic.terrain_engine` are refused with
  one sentence that names the key, the value and the names this installation serves.
- A solver backend is called through `validate`, `build`, `run`, `extract` and `cleanup`. It receives a frozen `Model`,
  its options and a `RunSlot` that names its folder, its run name, its solver binaries, whether to stop before the
  solve, and the folder of the forcing files a calibration trial shares. `execute` is gone, and `RunExecutionResult` is
  now `SolverRun`, with `primary_model` renamed `solver_model` and `solver_output_dir` renamed `output_dir`.
- `extract` receives a `Retention` of `hydromodpy.results.storage.kept`, built from `keep_per_cell_budget` and
  `keep_solver_files`, instead of keywords read from its signature. The extractor port `OutputAdapter` moved to
  `hydromodpy.solver.base.adapter_protocol`, and an extractor answers `extract(solver_run, store, retention)`. The
  dry-cell sentinels of MODFLOW-NWT come from its own options, and the start date and the vertical layout from the
  `Model` of the run.
- `extract_observables(ctx, store, requests)` of a flow adapter is now `observables(solver_run, requests)`,
  `locate_cell` and `top_active_layer` take the `SolverRun`, and `declared_observables` receives the ids of the active
  conditions of `[flow]` instead of the configuration.
- The runner of a plan records one `SolverRun` per run in `execution.solver_runs`, which replaces `models_by_run_id` and
  `output_dirs_by_run_id`. A consumer reads the product of its run as `RunContext.solver_run`, and a transport run reads
  its flow run as `RunContext.upstream`.
- A calibration trial asks for its run name, its stop before the solve and its forcing folder through a typed
  `SlotRequest` on the setup, which replaces `setup.flow_runtime_overrides`. The solver no longer recognises a trial by
  the name of its folder. `TrialSandbox.flow_overrides` is now `TrialSandbox.slot_request()`.
- The flow adapters moved to `solver/<backend>/adapter.py` for `modflow6`, `modflow_nwt` and `boussinesq`, and
  `solver/boussinesq/adapters/` is gone. The transport adapters stay in `adapters/`.
- The Boussinesq settings class `FlowRuntimeConfig` of `hydromodpy.model.runtime_config` is now `BoussinesqOptions` of
  `hydromodpy.solver.boussinesq.options`, the table `[solver.boussinesq]`. `FLOW_RUNTIME_KEYS` now lives in
  `hydromodpy.model.flow_config`.
- The Boussinesq scratch folder is named after the run like the other backends, so parallel calibration trials each get
  their own folder. Its extractor writes the diagnostics of the variational inequality solve into the diagnostics folder
  of the run store when it extracts.
- The auxiliary steady solve and the spin-up cycles of MODFLOW 6 solve in a slot derived from the run, with its binaries
  and its shared forcing folder.
- A resumed run puts back one `SolverRun` per solver folder it recorded, and a missing solver output folder raises
  `NothingThereError`. A per-cell budget that `keep_per_cell_budget = false` leaves out raises `ConfigError`.
- `hmp catalog rerun` calls `hydromodpy.project.dispatch.rerun.rerun_config` directly.
- `engine_accepted` moves from `hydromodpy.mesh.port` to `hydromodpy.mesh.registry` and
  resolves the engine itself.
- The terrain port is shorter. `require_batch`, `require_rank_preserving`,
  `require_snap_method` and `require_untransformed` are folded into `require_delineable` and
  `require_stream`, and the refusals of an engine are `require_conditioning`,
  `require_accumulation`, `require_stream` and `require_delineable`. A refusal keeps its
  exception class, and some messages are shorter. `terrain.port` has no `__all__`.
- `get_whitebox_backend`, `clear_whitebox_backend_cache`, `resolve_delineation_backend` and
  `backend_has_callables` are defined in `hydromodpy.catchment.delineation`. The classes
  `WhiteboxWorkflowsBackend`, `WhiteboxRasterBackend`, `WhiteboxFlowBackend` and
  `WhiteboxDelineationBackend` are no longer attributes of that package. Import them from
  `hydromodpy.catchment.delineation.whitebox_workflows_backend`.
- The channel tree and the per-cell discharge routing move from
  `hydromodpy.solver.modflow_common` to `hydromodpy.catchment.drainage.channel_tree` and
  `hydromodpy.catchment.drainage.routing`. `project_channel_tree` is split in two:
  `channel_exits` reads the cell numbers of the pixels of A, and `pin_channel` reads the active
  columns and the lakes of a backend. `upstream_area` takes the cell areas and returns the
  areas with the largest drainable share, in place of `upstream_area_m2`.
  `channel_rasters_for_run` moves to `hydromodpy.model.domain.geometry`.
  `routing_graph_for_model` and `flat_cell_index` move to
  `hydromodpy.solver.modflow_common.observable_extraction`.
- `Model.geometry.channel_exits` carries the river network A read on the mesh cells.
  `prepare_solver` reads it once, when the river network step ran or an SFR network was
  delineated from A and the three rasters exist.
- `build_solver_mesh_descent` takes `channel_exits` in place of `channel_tree`.
  `channel_exits_for_build` of `hydromodpy.solver.modflow_common.flow_directions` replaces
  `channel_tree_for_run`: it keeps the rule of a build (A off, no folder, rasters missing, or
  an SFR network that needs A) and returns the exits of the `Model`, and a `Model` that did not
  read an A the build needs is refused.
- Every data source is a class of the DataSource port, registered under its section and its name,
  for example `data_sources.get("hydrometry", "hubeau")`. Hub'Eau, SIM2, Explore2, IGN, BRGM, SHOM,
  BD TOPO, ROE and the two computed sources join the three river networks, and the `SOURCES`
  tables of the variable managers are gone.
- A result of the files kind carries `FileRecord` entries (path, sha256, state, nodata, origin)
  instead of bare paths, and a source that declares no selector accepts a request with neither an
  extent nor stations.
- `hosts` is read on the source instance, and a shipped source reads its hosts from
  `hydromodpy.schema.sources` instead of writing its own copy.
- The entry-point name of a plugin data source is `<section>_<source_id>`, as for solver
  backends, and the installed member of a data request resolves its name among the plugin
  source ids, refusing an ambiguity by naming the keys.
- Hydrometry, piezometry, water quality and intermittency download the same observations as
  before through the four Hub'Eau source classes, and `[site] gauge` takes its station sources
  from the `station_ids` selector a source declares instead of a fixed list of names.
- Meteorological and hydrogeological grids (SIM2, Explore2) and computed sources
  (SyntheticRecharge, ConstantSeaLevel, ShomSeaLevel) conform to the DataSource port and are
  registered under the common plugin registry.
- The IGN DEM source reads the nodata of the raster header into the `FileRecord` it returns, and
  the crossings sources write their own downloaded GeoPackage under the request directory, page
  by page.
- A geology fetch without any extent is refused by name, where `brgm_1m` used to serve the whole
  national map. The national file stays reachable through `fetch_brgm_1m`.
- Every export format is a class of the export port, registered in
  `hydromodpy.results.exporters.registry.export_formats`. `[[export]].format` and
  `hmp export --as` take a registered name and refuse an unknown one with the list.
- The figure registry is `hydromodpy.display.figure_registry.figures`, read from the generated
  table `hydromodpy/display/figure_table.py` (`python -m tools.figure_table`). The `register`
  decorator is gone, and a `[display]` section is checked without importing a figure module.
- A files fetch result declares records, the number of records its source wrote, and an answer
  whose one file holds nothing is read as empty by the request engine.
- A source that declares `period_need = "optional"` serves a request that carries no period. The
  computed recharge, the constant sea level and SHOM answer without a window, and SHOM falls back
  to the start and end dates its section declares.
- The trial pipeline of calibration is a Protocol of eight methods in
  `hydromodpy.calibration.runners.trial`, installed once by
  `hydromodpy.project.trial_pipeline.fill_trial_pipeline` and carried to each
  worker process of a parallel search as the dotted path of that installer.
- The TOML template, the JSON schema export, the field validator and the TOML loader take the
  root configuration as an argument (`generate_toml(root=...)`, `editor_schema(model_cls)`,
  `validate_field(path, value, root=...)`, `load_toml_with_base_config(path, root=...)`).
  With `root=None` the loader reads a file the way it is written.
- The dynamic flow example blocks of the TOML template moved from
  `hydromodpy.model.toml_examples` to `hydromodpy.config.toml_examples` (the
  function `flow_examples`), passed to `generate_toml`.
- `Run.hydromodpy_config` needs a run opened by `hmp.open` or by a Project. Catalog, `open_run_dir`
  and `Session` take `read_config`, the function that validates a sealed snapshot.
- Calibration methods resolve through the shared plugin registry,
  `hydromodpy.calibration.optim.optimizer.optimizers`. A third-party method joins through the
  new entry-point group `hydromodpy.calibration.optimizer`. Each method declares its options
  class on its adapter, and the `CalibrationMethodConfig` union is gone.
- `calibration.method`, the method of a phase, `steady_method` and `transient_method` are checked
  when the file is read. An unknown name is refused with the names this installation serves.

- A mesh engine declares the line families it ignores. With the catchment engine, [mesh.families] carries the five, the river trace is not asked for it, and the planner names the skip in the mesh notes. A family an ignored engine writes with a value other than `none` is refused at read, so is a point method for the recharge or the ETP under a lumped mesh, and a mesh engine deduction of the run is written in the resolved config when every engine the backend accepts meshes a lumped catchment.
- Without `[mesh] engine`, a global backend that accepts only lumped engines takes that engine, and the resolved config writes it.
- The wall-clock limit of a trial is now the optional property `wall_clock_limit_s` of the backend's options table, read beside the options the backend declares.
- A flow process entry without solvers reads the default of solver.backend, and the run template of a scaffolded project names no backend.
- The index takes the category of a solver from the run manifest. The index schema goes to 11, so an older index is rebuilt.
- `Run.grid` answers for a global model, from its one-cell mesh.
- The watershed identity card writes the backend name as the run recorded it.
- The four transport tables lose their `parameters` level: `[transport.modflow6gwt.parameters]`, `[transport.modflow6prt.parameters]`, `[transport.mt3dms.parameters]` and `[transport.modpath.parameters]` become `[transport.modflow6]`, `[transport.modflow6_prt]`, `[transport.mt3dms]` and `[transport.modpath]`. `hmp doctor --fix-config` and a sealed read lift them, with the `_days` particle times. `[transport.modflow6_prt]` and `[transport.modpath]` stay experimental.
- The catchment preprocessing takes the DEM as a `dem_path` argument: `prepare_geographic_run`, `build_geographic_runtime_context`, `CatchmentDelineation`, the geographic cache fingerprint and the cache manifest. The fingerprint of a cache written before changes, so a cached tree is rebuilt once.
- The data overview takes its DEM from `[[data.dem.sources]]`. Without a DEM source it is refused with "No [data.dem] source configured".
- `HydroModPyConfig.model_validate` of a mapping that declares `[[data.dem.sources]]` accepts `kind = "dem"` with no validation context, as the file loader does.
- `hmp run` on a calibration or an overview file passes the `Environment` of the call (credentials, `--allow-host`, `--max-download-bytes`) through the dispatcher. `run_calibration` and `run_overview` check it against the folder of the file before they run, and `None` means `Environment.default()`.
- The data variables serve `source = "file"` and `source = "url"` through one dispatch of `SourceTable`. The hydrography `file` source no longer reaches the network fetch.
- The generic `file` and `url` sources refuse a selector they do not declare, or a period they cannot serve, before they read anything.
- The Geoplateforme download goes through `hydromodpy.core.io.fetch`, which owns the retries. It no longer resumes a stale `.part` file.
- `get_json` and `paginate_json` of the Hub'Eau client take a client. With `client=None` they open one for the call under the default bounds.
- `NativeSeries` carries one more edge than values, and the last edge is the end of the run. A step that starts before the run is cut at its start, so no water from before the run is counted.
- The linear reservoir declares `writes = ("timeseries", "budgets")`, the two tables it fills. Its `locate_cell` and `top_active_layer` follow the `CellLocator` port.
- The old names `CustomCrossingsSource`, `CustomDemSource`, `CustomGeologySource`, `CustomLakeAbacusSource`, `CustomLakeBathymetrySource`, `CustomLakeGeometrySource`, `CustomLayerBaseSource`, `CustomSoilCapacitySource` and `CustomSubstratumSource` of `hydromodpy` are refused with their `File...Source` replacement.
- A configuration that fails to load names every fault it holds, not only the first. The type of the error and the exit code are those of the first fault, as before.
- Every HydroModPy error that refuses a document carries its diagnostics, and `to_dict()` lists them under `details` with their pointer, code and severity, not only `ConfigValidationError`.
- The checks of the `[[export]]` names and of the dates of `[[export]]` and `[display]` run when the file is loaded, with the other rules between sections. They give the same messages, the same `ConfigError` and the same exit code 14. A sealed run only warns of them, as it does of the checks against the solver. Step 0 of a run given a `HydroModPyConfig` already built runs every rule between sections on it again, so a section changed after the load is still refused before the solve.
- Two `[[export]]` blocks that write one file are refused at load only when the file does not depend on the name of the run. A `file` that takes the name of a group of fields or series of the run, such as `<run>_fields.nc`, is refused by the export before that block writes anything, and the earlier file is kept.
- The rules between sections of a project file are the rows of `CROSS_RULES` in `hydromodpy.config.cross_checks`, each with the sections it reads. The refusals and their sentences are those of the validators of `HydroModPyConfig` they replace, and the first refusal is raised in the same order.
- `hmp config check --format json` writes `{"ok": ..., "diagnostics": [...], "workspace": [...]}`, each diagnostic with its pointer, code, severity, detail and a phrase in the language of `--lang`. The keys `kind`, `n_cases`, `summary`, `errors`, `warnings` and `experimental_keys` are gone. The number of cases of a `[sites]` project is printed by `hmp run --dry-run`.
- `hmp doctor --fix-config` reads the retired keys from the check codes, and says which old forms it cannot rewrite.
- `preflight_calibration`, `preflight_launch` and `refuse_what_the_preflight_refuses` give `Diagnostic` objects of code `calibration_preflight` in place of `PreflightFinding`, which is removed. The key sits in `path` as a dotted key such as `calibration.parameters.K`, and the text that followed a key in brackets, a phase name or the word bounds, opens `detail`. The refusal of a launch carries its error diagnostics in `ConfigError.diagnostics`, with the same message.

- The modules of the data variables are `variable.py`, and their classes end in `Variable` instead of `Manager`. `hydromodpy.data.managers`, which was private, is `hydromodpy.data.families`, and `DataManagersRuntimeLoader` is `DataLoader`. The old module path of a variable is refused with the new one named.
- `hydromodpy.lock` records the source, the product and the licence of each input, and the user files the configurations declare, the cases of the current plan of a `[sites]` project included (schema `hydromodpy.lock.v2`). It has no `[binaries]` and no `file_mtime`. A lockfile `hydromodpy.lock.v1` is refused. Write it again with `hmp data lock`.
- `hmp lock update` is now `hmp data lock`, and `hmp lock verify` is `hmp data lock --check [--strict]`. The old forms are refused with the new one named.
- `hmp data prune` never removes a file that a sealed run, a kept trial or a lockfile cites, and names it. It reads the digests from the runs of every project of the workspace, and it removes nothing when the inputs of a run or a lockfile cannot be read. The guarantee is held by `hydromodpy.project.data_cache.prune_data`.
- A cached file whose size or date changed is fetched again only when its sha256 changed, so a copy of a workspace by `cp` no longer fetches its files again.
- A data request, and a call of a DEM, geology or crossings variable without a data folder, no longer cache a download under the user cache of the machine. The file goes under the data folder of the call, `data/` of a project without a workspace, and a call that has none is refused with a sentence that says so. The user cache (`HMP_CACHE_HOME`) holds no input data any more, only the solver binaries, the downloaded examples and the code fingerprints.
- A file of the user is read where it lies and is no row of the data cache. A copy made from it goes under `data/blobs/<variable>/file/` (it was `blobs/<variable>/custom/`) and has no sidecar. The sidecar a user writes beside such a file may name only its source and its licence.
- In frozen mode, a user file that `hydromodpy.lock` does not pin by path and digest is refused when it is read.
- A station chronicle is written beside its name and renamed in place under the file lock of its station, so two cases of a `[sites]` launch that fetch one station leave one file and one sidecar.
- The machine output of `hmp data ls` is `hmp.data.ls.v2`. It has no `id`, `file_mtime`, `is_custom` or `file_path`, and gains `product`, `path` and `license`.
- `hmp data restore` puts the files and their sidecars into `data/` of the workspace by default, not `data/imported/`.
- `hmp workspace clean --data-cache` removes `data/blobs` and the data cache database of a pre-release with its journal and lock. It never removes the sidecars or the files they describe.
- The geology legend of the catchment report falls back on the GeoPackages of the BRGM in the data folder of the run, no longer in the user cache.
- Two runs are identical when their request, the digest and state of every input, the code, the solver binaries and the numeric packages agree. The address of a URL and the path of a file no longer count. A run that a pre-release would have skipped runs once again.
- `identity.config_hash` of a seal and the hash of a calibration session now hold the solution key (request, inputs, code, solver binaries, numeric packages).
- A configuration given as a dict or JSON text needs `base=`, and the current folder is never used. JSON text is read as a file is, with the same refusals.
- `HMP_PROJECT_ROOT` is no longer read. Pass `-w`, `--base` or `base=` instead.
- Project and run names follow one rule: lower case letters, digits, `_` and `-`, forty characters at most, no doubled `_` and no name Windows reserves. A name written otherwise is refused with the name to write. A name the code makes from a file stem, a validation case or a site and a recipe is folded to it.
- A run claims its directory first, then writes `request.json` and `config.toml`, resolves its inputs and writes its request id in `outcome.json`, and only then looks for an identical completed run. A run given back as identical leaves no directory behind, and `if_exists = "fail"` is read after that search.
- A run asked to resume whose configuration changed since its checkpoint is refused with `ResumeError`, which names the sections that moved. A plain relaunch under the same name starts over.
- `outcome.json` of a calibration session omits `request_id` while it has none.
- `hmp run` names the run of a file without `[simulation].name` from the file name, as the API does (`run_unnamed.toml` gives `unnamed`).
- `--set export=[]`, a top-level section given without a dot, is applied as a path again.
- `outcome.json` carries `request_id` once the inputs of an attempt are resolved, and a retry whose request changed starts over. A retry that is given back as identical puts back what the attempt before it was asked.
- `config.toml` of a run is written once, at the claim, so a run that fails before the mesh can be resumed. `config.resolved.toml` is written by the prepare step.
- `hmp spinup`, `hmp calibrate`, `hmp config check` and `hmp config targets` take the project `-w` names as their base by argument, and `hmp run` also takes `--base`. `-w` and `--base` are passed to the sub-processes that run a case.
- A plan names its cases after the site and the recipe folded to a run name. Two cases that fold to one name, or a name over forty characters, refuse the plan.
- `hmp report catchment` accepts `-w` and does not read it. The runs it starts take the project of their own file.
- `hmp calibrate` with `--set`, `--overlay` or `--case` reads the changed document once and writes no copy of the file. `--dry-run`, `--list-phases` and `--expand` read its `[calibration]` section only, as they read the file.
- `hmp.check` takes `base=`, and a document in memory is refused without one.
- Validation run names are forty characters at most.
- `hmp run --format json` gives the mesh summary of a run that built a mesh in `result` again, as a pre-release did.
- The documentation describes the run request, the base of relative paths, `request.json`, the request id in `outcome.json`, the claim at the start of a run, the run name rule and the Docker command.
- Every mesh engine goes through the store, not only the triangle engine. A mesh cached by a pre-release under `.hmp/mesh_cache/` is no longer read and can be deleted.
- A calibration trial that does not change the soil parameters no longer runs the soil reservoir again.
- `hydromodpy.mesh.cache` is `hydromodpy.mesh.stored`.
- `hmp publish --package --with mesh` copies the mesh products the runs cite into `products/` of the package, and `hmp project import` installs them under `.hmp/products/`. The `mesh_cache/` of a package written by a pre-release is skipped and counted.
- The conditioned DEM, its directions and its accumulation are a product of the store under `.hmp/products/`, shared by the runs of a project. A resume reads them from the store and delineates the catchment again.
- `hydromodpy.catchment.preprocess.geographic_cache` is `hydromodpy.catchment.preprocess.geographic_tree`, and `hydromodpy.data.schemas.dem` is `hydromodpy.catchment.terrain.dem_contract`.
- The regional chain routes a DEM declared conditioned as it is, and `dem_correc_type` reads `provided`. The solver still fills its own grid template with `fill`, because a conditioned DEM brought to a coarser grid has depressions again.
- `hmp run --resume` refuses a run whose request changed since it stopped, an input or the state of a window included. A plain `hmp run` starts it over. When the configuration changed, the refusal names the sections that moved.
- The two fixes of a restart, the head read in double precision and the lake stage carried by a cyclic spin-up, declass a run of a pre-release only when it started by `[flow] restart_from` or by a cyclic spin-up beside a lake. Every other run of a pre-release keeps its label.
- The frozen data mode is an argument of the run, no longer a state of the process, so two runs of one process no longer share it.
- The wall time of the solve is no longer a row of `metrics.parquet` nor of the seal. It is `SolverRun.solve_s`, a solve line of `profile.json`, and the pipeline state no longer carries `wall_seconds`. The campaign summary and the catchment report read it from `profile.json`, and from the seal or `metrics.parquet` for a run of a pre-release.
- MODFLOW 6: a run that restarts from another one, and each window of a chain, starts from the head in double precision (binary start array), and its lake and reach stages are written with all their digits. Heads move by about 1e-9 m and lake stages by up to 5e-9 m.
- MODFLOW 6: a cyclic spin-up starts each cycle from the final lake stage of the cycle before, the main run starts from the last cycle, and the loop settles only when the lake stages have settled with the heads. A lake under `spinup_cyclic` is no longer refused.
- MODFLOW 6 with SFR storage: the stage of each reach at the end of a run is kept in `final_state/` and given back to the next run or window as `INITIALSTAGES`.
- A run and a job write one seal, manifest_version 4, with a profile. A seal of a pre-release is refused with its sentence.
- The identity block carries solution_key, request_id and solver instead of config_hash, in the seal and in every file that leaves a run. simulation.parquet no longer has a config_hash column.
- A replay no longer refuses a moved default nor warns only on another solver binary: both go in its lineage, with the class of the replay.
- `hmp run <run>/config.toml --frozen` no longer replays a run; use `hmp replay <run>`.
- The results modules manifest, record, run_identity and checks live under `hydromodpy.results.record`, and lineage under `hydromodpy.schema`. `hydromodpy.results.identity` stays where it was.
- The value digests of a seal cover `simulation.parquet` and `parameters.parquet` too, and leave out the solve-time row of `metrics.parquet`, which is a wall clock.
- A replay of a run sealed by a pre-release lists the `final_state/` arrays and the `mesh/open_water` and `mesh/catchment_cells` masks that version did not write under `added` without classing the replay as a deviation, and reads its flat `concentration` as the one species of the replay.
- A difference a replay cannot measure (two shapes, two NaN masks, a zero norm) is written with null measures and its reason, never as `Infinity`. A seal is strict JSON.
- A replay that read the mesh sealed beside its source seals those bytes in its own `mesh/`, and a sealed mesh whose bytes no longer match its seal is rebuilt. A run with a sealed mesh is still found identical to a later request, and can still be shared.
- A job seal of a later or an earlier `manifest_version` is refused with the sentence that says to upgrade or to run again.
- The RO-Crate view gives each property value of a run its own `@id`, as the RO-Crate library requires.
- Each line of `published.jsonl` says `kind = "copy"` or `"delivery"` (`hydromodpy.published.v2`); a line written by a pre-release is refused.
- `hmp publish` removes `deliver_to` from `config.toml` and `config.resolved.toml` of a copy; `exports/index.json` no longer records it; `deliver_to` is refused in a `[sites]` project.
- `trials.jsonl` writes one line per event, schema `hydromodpy.trial.v3`: `proposed` when the optimizer asks, `finished` with the cost, its components, the rule and window they were scored under, and the time of each step, `linked` when the trial becomes a run. A reader keeps the highest event of each trial. A journal of a pre-release still reads.
- A calibration trial that moves only K or Sy reruns the previous trial of its lane through MODFLOW 6 `rerun` instead of building the model again. The cost is the same to the last bit.
- Each `trial_series/*.parquet` file carries `hmp.schema_version = hydromodpy.trial_series.v1` and `hydromodpy_version` in its footer. A file without the key reads as v1, the form written by a pre-release.
- `TrialOutcome` takes an optional `profile`, the time of each step of the trial.
- A calibration writes the scored series of every trial by default (`persist_trial_series` is true).
- `hmp init` writes `edition = "2.0"` in the `project.toml` of the example project.
- A kept calibration trial keeps only the budget terms of its criterion and draws no figure; the best of an earlier phase keeps what the project asks.
- `hmp campaign promote <case> --trial N` solves a kept trial again when `hmp catalog gc` removed its fields, and leaves its folder under the session.
- A run is skipped only for an identical run of its level or above.
- The four criterion modules of `results/derive/stream` (`network`, `extent`, `heads`, `geometry`) and `calibration/metrics/downslope_network` are now `hydromodpy.catchment.stream_network.{network,extent,heads,geometry,cost}`. The visible-flow words and the provenance codes of a validity map are in `hydromodpy.core.scoring.stream_defaults`.
- `routed_discharge` and the private flood of the descent are gone. `route_release_to_discharge` and `priority_flood` of `hydromodpy.catchment.drainage` are the one routing and the one flood.
- Rule 6 of the repository now holds `catchment/stream_network` and `core/scoring`, with a table of exceptions that can only shrink.
- The stream criterion reads each of its inputs once, through `hydromodpy.results.derive.stream.criterion_inputs`. A figure drawn from a run takes the solver centers, the open water, the outline and the mean recharge the trial scored, so it draws the partition behind the reported number. A run that kept no mean recharge, or no `mesh/open_water`, is refused with a sentence that says to replay it, or to set `tau_specific_ratio = 0`.
- `frac_minimal_outside_maximal` in the trial journal is read on the scored cells, inside the catchment, active and off open water. With 1 % of open water it goes from 0.6883 to 0.6842. No value of `metrics.parquet` changes.
- `StoredBasin` is a frozen dataclass read by one function, `basin_of_group`, for the run views and for the catchment aggregation alike.
- `hydromodpy.results.score` is the one pairing of a simulated series with its observations: `pair`, `score`, `score_metric`, `score_timeseries`, `read_timeseries`, `calibration_rules` and `score_run_under_its_rule`. The calibration trial and the sealed run both call it, so they pair the same series bit for bit. `score`, `score_run` and `HEADLINE_METRICS` leave `hydromodpy.results.metric_rule`, which keeps the rule and score types.
- A run a session promoted gains in `metrics.parquet` one set of rows per calibration period of its seal, with `window_role = calibration` and `metric_rule_version`, written before the seal. The headline rows do not change.
- `calibrated_by` in the seal gains `rule`, the metric rule version of the cost, and `components`, the parts of that cost without the validation cost. The block keeps `hydromodpy.checks.v2`.
- Labels follow rule 3. A promoted run is calibrated or evaluated only when a window was scored: a calibration period, the headline window with enough samples, or the state of a steady run with a finite cost. A transient run promoted without one is exploratory, with the reason `no_scored_window`. A parameter on a bound adds the reason `bound_reached` to any label. `LabelResult.causes` holds coded reasons with an English and a French sentence, and `LabelResult.reasons` gives the English ones.
- The licence of a run is the roll-up of the licences of its `inputs.json` entries, each read from the sidecar of its file. A loaded record no longer takes the licence of its provider by slug. A checkpoint written by an earlier build, whose `facts.json` holds `licence_sources`, is refused.
- `phrases.toml` also holds the label, label reason and check state phrases, and `hydromodpy.schema.phrases` is its one reader, with the languages in `LANGS`.
- The project index `.hmp/index.duckdb` is written by one process at a time under `.hmp/index.duckdb.lock`, in DuckDB blocks of 16 KiB. Opening a project builds a missing or older index instead of refusing. `metrics.metric_name` is now `metrics.metric` in the index, the catalog rank output (now `hmp.catalog.rank.v2`) and the pair comparison, and `cases.bytes` holds the size of each directory, measured again when `figures/`, `exports/` or `report/` gains a file. A sealed run no longer fails when another process holds the index lock or the index does not open: it warns, names `hmp catalog reindex` and is read from its directory. A read of a `Project` never waits for a writer of the index: it opens the published index at once, and opens it again when another process rebuilt it since. `hmp catalog show` lists the copies of a run.
- The ledger of `figures/` and `exports/` is locked on every system, without `fcntl`, and a record whose lock was taken back meanwhile is refused instead of written. A stale lock is taken back by one process at a time and only when it is still the file judged stale, so a fresh lock is never removed.
- `hmp publish` takes the results (`fields.zarr`, `tables.parquet`, `final_state/`), the inputs with `INSTALL.toml`, the sealed mesh and `products.json` along by default and writes `.zenodo.json` beside the RO-Crate. `--without results` and `--without inputs` leave them out; `--with` goes with `--package` only and is refused for a copy. `publish` and `publish_project` carry both by default, and `publish_project` returns a `PublishedProject` with its copies and the runs it left out.
- `hmp publish` refuses a replay that is not classed bit, and `hmp publish .` leaves it out and names it under `left_out`.
- `hmp publish` of a run with its inputs prints `hmp replay <copy> -w <project>` as the line that replays the copy.
- `Project.publish` takes no `with_` any more: a summary carries no results and no inputs.
- The trash warns only for a run that has published copies; a delivery alone does not count.
- The catchment series count the inflow and the outflow of each element (layer, cell) on its own, where they summed the layers of a cell first. The discharge does not move (register entry `basin_budget_split_per_element`).
- A plan keeps its cases and the cells of their sites in `plan/<hash>/cases.csv` beside `plan.json` (schema `hydromodpy.plan.v2`), where a pre-release wrote `sites.parquet` and `cases.parquet`. The hash of a plan now starts from its schema, so every project gets a new hash. A plan of a pre-release is refused with the command that writes it again, `hmp project plan`.
- The eight modules of `hydromodpy/project/launch/sites/` are one module, `hydromodpy.project.launch.plan`, with the same public names. `BindingError` and `TableError` are now `SitesProjectError`.
- A column of the sites table named like a column the plan writes for each case (`case_id`, `recipe`, `config_hash`, `config_path`) is refused with the name to change.
- `cost_margin.root_interval` of `hydromodpy.calibration.optim` takes a mapping from the search variable to its cost instead of a list of pairs.
- The runoff warnings of a calibration discharge and of the catchment series are logged at each call, so a calibration logs them once per trial.
- Figures and data exports of a run are written after its seal and carry the label of the day. The steps end with `derive`, `export`, `seal`, `display`.
- The footer of a figure reads `<label>, rule <n>, <date>` after the site, period and version, and `unlabelled` for a directory without a seal.
- A figure or an export that fails after the seal leaves the run sealed and `completed`. The command exits with the display or export error and names `hmp viz show` or `hmp export`.
- A figure declares its subject, `run`, `session` or `runset`. A session figure asked for on a run draws the session that promoted it. `hmp.figure` takes a run, a session or a set of runs, and `hmp viz list` shows the subject, so the JSON output of `viz list` and `viz list run` is at version 2.
- The calibration figures (convergence, trace, landscape, pairplot, trial distribution, objective surface, progress, bisection bracket trace, parameter cost profile, downslope distance crossing, matching card) draw a `Session`, and `ensemble_band` draws a `RunSet`. The y label of `calibration_convergence` reads `cost`, the name of the cost column of the trial journal.
- A figure handed an object of the wrong kind, a run for a session figure or a list of runs for `ensemble_band`, is refused with a sentence that says what to pass, and a session figure refuses a session that recorded no trial before drawing. The subject is never listed as an option of a figure.
- `hmp report catchment RUN [--overview RUN] [--preset research|management] [--lang en|fr] [--station ID] [--strict]` reads a sealed run. `report.json` replaces `block_report_manifest.json` and `block_report_postflight.json`, and the JSON output of the command is at version 2 (`html_report`, `report_json`, `missing`).
- `hmp.report` and `hmp report render` write the session report through `hydromodpy.project.report.report_session`.
- The session report is written for a session of several cases and when a best run does not open. A table lists each case with its best run, and a best run that does not open is named there with the reason. The figures of the best run of each case are drawn, named `<case>_<figure>.png` when the session holds several cases.
- `hmp show SESSION` and the session report print again the project, the cost name, the best run, the stop note, the start, the end and the duration of the session.
- The management sheet takes its headline score from the seal (`record.score`), not from the first row of `metrics.parquet`. Its table and figure titles, its headings and its frame are in the language of the sheet, and the sample count is an integer. The score tables of the reports say the window of each score.
- The method block of a report shows the label once. The research report lists again the reference configuration, the geological codes of the catchment, the reference segments, the DEM extraction threshold, the forcing origin and the four comparison figures of the reference and the DEM network.
- The data overview page shows again the workflow, period, workspace, catchment area and definition, the hydrography objects, sources and period, a station count per family, the mean recharge, the pumping, the wells, the sources of the hydrography and of the recharge, the series of piezometry, intermittency and water quality, and the paths of its files.
- The data identity card of the overview counts each station once. A station that gives one record per parameter, in water quality most of all, used to count once per record.
- The report engine removes from `figures/` only the copies it made on a former call, listed under `copied` in `report.json`. A figure already in `figures/` stays in place, and a copy never overwrites a file it did not write.
- `hydromodpy` exposes fifteen typed verbs and five objects. Every verb takes text, numbers, paths or mappings and returns a value with `to_dict`, a path or diagnostics. The verbs live in `hydromodpy.project.api`.
- `hmp.run` returns the `RunOutcome` of the run; `RunOutcome.open()` gives the `Run`.
- A verb never looks for a project above the working directory; a name is read in `workspace=`, else the reference is a path.
- `hmp ls`, `hmp show`, `hmp diff` and `hmp check` read and check. `hmp catalog ls`, `show`, `diff`, `point` and `rank`, `hmp viz`, `hmp report`, `hmp config check`, `hmp project show` and `status` are refused with the command that replaces them.
- An exception carries its category, and `hmp` maps the category to its exit code. No exit code changes.
- `Comparison.table` gives the headline scores of the compared runs side by side, and replaces `compare_pair`.
- The project log `.hmp/logs/hydromodpy_debug.log` is written by each run as a second sink of its context, rotates at 8 MiB and keeps three old files. `LogManager.set_simulation_log` and `setup_simulation_log` are gone.
- `hydromodpy.display.style.apply_theme` is replaced by `theme_rc(name)` and `themed(name)`, and `hydromodpy.display.runs.matplotlib_backend` by `rendering(theme)`; both hold a render lock for the length of one render.
- Importing `hydromodpy` sets `PROJ_DATA` once, for the CLI and for Python alike.
- `hydromodpy.project` imports nothing. `Project` is read in `hydromodpy.project.facade`, `ProjectRunner` in `hydromodpy.project.runner` and the accessors of a project in `hydromodpy.project.accessors`.
- `hmp.results` and the other packages no longer open from the top level; `import hydromodpy.results` gives them.
- The help of `hmp run --resume` names the window form `<chain>_w<N>`.
- `hmp check` and `hmp.check` collect the warnings of the sections per call, in a sink that belongs to the calling thread, so two checks in two threads, or a check beside a run, keep their own warnings and never change the warning filters of the process. A warning of a third-party library raised during a check is no longer a diagnostic and follows the filter of the process. A check of a whole document of example 04 takes about 8 ms warm instead of about 10 ms.
- A lake writes the storage term of its water balance as the series `lake_storage`, negative when the lake volume rises as in MODFLOW 6. The name `storage` now names only the budget field of the aquifer. No value changes.
- A lake that still writes `stageinit` is refused with a sentence that names `initial_stage`, the key that replaces it.
- MODFLOW 6 PRT refuses a flow model whose TDIS declares a token that is not a time unit, as the readers of a run do, instead of reading its times in seconds. A model that declares no unit still runs in seconds.
- The port tests live in `tests/ports/`, one file per port registry, and the refusal tables in `tests/refusals/`. The solver port test builds, solves and extracts every shipped flow on every mesh engine it accepts, plays every transport behind its flow, and builds every boundary a flow supports. A missing solver binary is a skip unless `HMP_REQUIRE_BINARIES` is set. The figure port test holds every figure to its contract: when `unavailable_reason` says nothing, the figure draws or raises `FigureNotApplicable`.
- The architecture gates of `tests/unit/architecture/` are folded into `test_layers.py`, `test_run_path.py` and `test_surfaces.py`.
- Seven modules over 1,500 lines are cut by concept, and a name is read from the module that defines it, with no re-export left behind. `hydromodpy.calibration.config` keeps `CalibrationConfig` and moves its terms to `config_terms`, the matching network to `config_network`, the outputs to `config_outputs`, the protocol, parameter and objective blocks to `config_objective` and the phases, uncertainty and aggregate to `config_phases`. `hydromodpy.calibration.preflight` moves the report lines and `finding` to `preflight_report`, the network checks to `preflight_network` and the search helpers to `preflight_searches`. `hydromodpy.calibration.runners.staged_runner` moves its tables and method sentences to `staged_report`, and `runners.search` moves the journal extras to `search_record`. `hydromodpy.config.cross_checks` moves the trait uses and the solver refusals to `config.solver_supports`. `hydromodpy.results.zarr_store.zarr_writer` moves the writes of the mesh, descent, topography, time, CRS and geographic raster to `geometry_writer`, and `write_array` is its public name. `hydromodpy.solver.modflow6.build` hands the recharge, drain, constant head, well, lake, flow barrier, SFR and mover steps to the modules of `builders/` that build their package (`build_recharge_and_evt`, `build_drains`, `build_constant_heads_and_wells`, `build_lakes`, `build_flow_barriers`, `build_sfr`, `build_mover_and_output`, `build_storage_package`), and `write_sidecar` lives in `builders/sidecar.py`.
- `hydromodpy.results.derive.stream` is now `hydromodpy.results.derive.stream_network`. `hydromodpy.cli.helpers` is cut by concept into `hydromodpy.cli.exit_codes` (the exit codes, `exit_code_for`, `fail`, `refuse`, `confirm`), `hydromodpy.cli.refs` (the workspace, the project and the TOML file a command is given), `hydromodpy.cli.conventions` (verbosity and the `--overlay` and `--set` overrides, beside the parent parsers) and `hydromodpy.cli.profiling`. In `hydromodpy.data.common`, `geo_helpers`, `unit_helpers` and `io_helpers` are now `geometry`, `units` and `files`. `hydromodpy.solver.modflow_common.flow_adapter_helpers` is cut into `flow_run` (options, build, run, read back, final state) and `listing` (the listing file, the budget discrepancies and the XT3D hint). No module is named with manager, handler, provider, service or helper any more.
- A package `__init__.py` no longer re-exports a name, and the seven lazy `__getattr__` of `config`, `core`, `core.units`, `data`, `results`, `solver.boussinesq` and `solver.modflow_nwt` are gone. Import a name from the module that defines it. A few of the paths that changed: `hydromodpy.results.run.view` for `Run`, `hydromodpy.results.catalog.facade` for `Catalog`, `hydromodpy.config.hydromodpy_config` for `HydroModPyConfig`, `hydromodpy.core.time.window` and its neighbours for the names of `core.time`, `hydromodpy.core.units.quantities`, `time`, `parse` and `types` for the names of `core.units`, `hydromodpy.core.workspace.config` for `WorkspaceConfig`, `hydromodpy.solver.modflow_nwt.nwt.nwt_solver` for `ModflowNwt`. The facade `hydromodpy` is unchanged.
- The code that stood in the command line modules is now in the library, under public names. `hydromodpy.project.runner.resume_target` reads the frozen configuration of `hmp run --resume REF`. `hydromodpy.project.data_cache.verify_frozen_inputs` (and `FrozenVerificationError`) checks the lockfile of `hmp run --frozen`. `hydromodpy.results.storage.attempt.close_attempt_of_process` closes the attempt of a process that died. `hydromodpy.project.doctor` holds the rows of `hmp doctor` (`build_report`, `probe_workspace`, `probe_toml_workspace`, `probe_result_storage`, `cross_catalog_checks`, `lifecycle_checks`, `prt_checks`, `findings_of`, `refusal_of`). `hydromodpy.project.show.show_target` and `Target` name what a reference of `hmp show` is. `hydromodpy.results.catalog.listing.list_runs` and `simulation_facts` read the runs of `hmp ls` and the facts of `hmp show`. `hydromodpy.project.compare.compare_folder` names the folder of `hmp diff --to`. `hydromodpy.project.report.regen_run` writes again what the ledgers of a run record. `hydromodpy.results.export.publish.campaign_members` and `replay_line` serve `hmp publish`. `hydromodpy.results.record.manifest.replay_of_run` reads the replay block of a seal. `hydromodpy.project.calibrate.route_calibration` is the one place that checks the environment, reads the declared phases, refuses an unknown phase and runs the preflight for `hmp run`, `hmp calibrate` and `Project.calibrate`, and `promote_trial` is the library call behind `hmp campaign promote`. `calibration_plan` takes `source=` and `case=` for a configuration held in memory. The commands print the same text and the same JSON as before.
- `hmp completion SHELL` prints the script of argcomplete, which asks `hmp` for its commands each time you press TAB. `hmp completion --argcomplete` is refused with this form. The listing commands (`hmp ls --plan`, `site ls`, `project log`, `workspace list`, `data ls`) take their columns from `OUTPUTS` of `hydromodpy/cli/output.py`, which gains `print_table`, `table_cell` and `row_fields`. `fill_trial_pipeline` is no longer called by `hmp` itself: each library entry that reads the trial pipeline fills it (`route_calibration`, `promote_trial`, `rerun_config`).
- Fifteen thin variables of `hydromodpy.data.variables` are four flat modules, and their classes keep their names. `hydromodpy.data.variables.sim2_series` holds wind, humidity, runoff, soil moisture and temperature, `forcing_series` holds radiation, ETP and precipitation, `lake_series` holds lake levels, inflow, outflow and withdrawal, `user_rasters` holds soil capacity, substratum and layer base. `from hydromodpy.data.variables.wind.config import WindConfig` is now `from hydromodpy.data.variables.sim2_series import WindConfig`, and the same for the `variable` module and the other fourteen.
- `DataManagersConfig` is now `hydromodpy.data.loading.config_schema.DataConfig`, `SUPPORTED_DATA_MANAGER_TYPES` is `DATA_VARIABLES` and is derived from `VARIABLE_SPECS`, and the JSON schema of the `[data]` section names `DataConfig` in its `$defs`. The run messages say "Data variable" and "Failed to load data variable" in place of "Data manager". The published description of the `data-request@1` process carries the same `$defs` rename and the new descriptions, so the fingerprint of its `data` input moves, and its version stays 1.0.0 because it accepts and refuses the same documents.
- `VARIABLE_SPECS` is the one registry of the 28 data variables. It holds the columns of the folder `data/<variable>/` (`category`, `kind`, `unit`, `label`, `file_prefix`), and `hydromodpy.data.workspace.scaffold.VARIABLES` with its own `VariableSpec` are gone. `hydromodpy.data.workspace.scaffold.variable_folders()` lists the folders.
- A type that had one implementation is now that class, and the module that only held its Protocol or ABC is gone. `Figure` is `BaseFigure`. `CatalogBackend` (`hydromodpy.results.catalog.ports`) is `DuckDBBackend` of `hydromodpy.results.catalog.adapters.duckdb`, so `Catalog.backend` is typed `DuckDBBackend`. `SimulationStore` (`hydromodpy.results.catalog.protocol`) is `RunStore` of `hydromodpy.results.storage.run_store`. `DomainLike` and `FlowModelLike` (`hydromodpy.solver.base.protocols`) are `Domain` of `hydromodpy.model.domain.domain`, and `Modflow6` or `ModflowNwt` for the flow run. `FieldDiscretization` is `WeightedAverageFieldDiscretization`. `ProcessSpatial` (`hydromodpy.model.process_spatial`) is folded into `Flow`, so a new process no longer subclasses it. `BoussinesqRuntimeBackend` is the runtime module itself, `BoussinesqForcingSolver` is `Boussinesq` and `SupportsHasField` is `Run`.
- Conventions written once. `coerce_length_series_to_m` and `forcing_units` live in `hydromodpy.core.units.quantities` and the MODFLOW 6 and MODFLOW-NWT builders read them there. `ITMUNI_TO_SECONDS` of the MODFLOW-NWT pre-processing gives way to `seconds_per_itmuni`, and the particle `_DAYS_PER_UNIT` to `factor_to_seconds(unit) / SECONDS_PER_DAY`, so an unknown ITMUNI code or tracking unit now raises the `ValueError` of `core.units` where it used to count as 1. `SECONDS_PER_DAY` of `hydromodpy.results.derive.recession` is read from `hydromodpy.core.units.quantities`. `naive_utc` of `hydromodpy.results.derive.time_alignment` is `naive_timestamp` of `hydromodpy.core.time.period_aggregation`. `run_edges` of `hydromodpy.display.figures._instant` is `run_period_edges` of `hydromodpy.results.derive.time_alignment`. `CUSTOM_PROVIDERS` of `hydromodpy.project.exchange.share` is `USER_PROVIDERS` of `hydromodpy.results.export.project_package`, and `USER_PROVIDERS` of `hydromodpy.workflow.replay_checks` is `REPLAYED_FILE_PROVIDERS`.
- The MODFLOW 6 relay `resolve_flow_property_arrays` of `hydromodpy.solver.modflow6.support.property_mapping` is gone: call the one of `hydromodpy.solver.modflow_common.property_mapping` with `properties=MODFLOW6_PROPERTIES`, which gives the flat arrays `build.py` reads. The titles of the matching card show the stage name with spaces, `Stage 1 - root search`.
- On Windows a project folder longer than 99 characters is refused by `hmp project new`, run claims and name reservations before anything is created, because a project writes paths up to 160 characters below it and MODFLOW 6 and DuckDB open none longer than 259.
- The solver binaries are looked up in the folder `HMP_BIN` names when it is set, for every run, the MODFLOW 6 library included, and `hmp install-binaries` without `--to` fills that folder. A run never downloads into it.
- The hard links of the launcher lease, of a replay from a copy and of the sealed mesh fall back to a copy that never overwrites, on every system.
- A geographic feature file and a MODFLOW 6 output keep their names on every system. The length is held by the project folder check.
- The path destination of a delivery writes through extended-length paths on Windows.
- A Boussinesq run names its solver folder and the `model_name` of its solver summary after the simulation, as the MODFLOW backends do, where a pre-release wrote `flow_main__boussinesq`. No value of a result changes.
- Each package and each port of `hydromodpy` has one short README, checked by `python -m tools.docs.check_readmes`. Sixty folder READMEs left, and what they said moved to the package pages or to the module docstrings.
- A docs page names a TOML key only through the `toml` role, so the card generated from the model is the one place that gives its default and unit.
- The docs no longer send a file that only a pre-release of 2.0 wrote to `hmp doctor --fix-config`. Such a file is refused, and the message names every such key it holds with its current name. This version does not rewrite the file.
- The tests index lists the real folders of `tests/` as tiers: `scenarios`, `refusals`, `ports` and `processes` join, `contract` leaves.
- Pytest markers `whitebox` and `windows` replace the hand-written lists of Whitebox test files and the Windows `skipif`; `HMP_REQUIRE_WINDOWS` turns a skipped Windows test into a failure.
- The `test` extra asks `coverage[toml]>=7.10`, which `patch = ["subprocess"]` and the removal proof need.
- 6 122 unit test functions leave `tests/unit`, 73 637 lines of 336 027, and no file is removed. Each line and each branch of the library that one of them ran is still run by at least two other unit tests, and the unit suite covers the same 116 419 lines and 31 569 branches as before. A test that compares a number within a tolerance, a test named for a sign, a unit, a sentinel, a budget or an analytical solution, and the last test of a file stay whatever the coverage says. Equal coverage is not equal detection: two tests that run the same lines with different values do not check the same thing.
- The unit tests are rewritten so that one file tests one source module and reads from top to bottom: a docstring that says what the module computes with its units, the small physical cases, the tables of cases with one row per case, the refusals last. `tests/unit` goes from 262 390 to 236 605 lines and from 1 335 to 1 274 files. Of the 9 855 test functions left, 1 571 keep a name of more than seven words, against 10 861 of 16 805 before, the `class Test...` wrappers go from 659 to 10 and the files named after a sentence from 105 to 5. Every case still runs (19 033 against 18 672) and the unit suite covers 116 425 lines and 31 570 branches, 6 lines and 1 branch more than before. The docs, the Boussinesq smoke scripts and `tests/TOLERANCES.md` name the new files.
- The Boussinesq regression goldens refresh `final_recharge_rate_m_s`, the final recharge of a run, because the cells with a fixed head carry no recharge: the mean moves from 3.4722e-08 to 3.3854e-08 m/s on the fast strip (6 cells of 240) and from 1.15741e-08 to 1.14294e-08 m/s on the divide case (3 cells of 240). The comparison of that field is relative now. The fix is the row voronoi_nwt_boussinesq_fixes_2026_10_09 of hydromodpy/schema/changes.toml.
- `hmp publish` no longer ships a station registry (`<variable>_custom_LOC.csv`) as a file of the package. The rows the run read still travel as stations and are merged, so importing into a workspace that already holds its own registry no longer refuses with HMPY.E809.
- Soil reservoir defaults: `alpha` goes from 0.6 to 0.45 (FAO-56 table 22, cereals and maize). `flow.sinks_sources.etp.extinction_depth` goes from 1 m to 2 m. A file that writes these keys reads as before.
- The soil reservoir gives each SAFRAN cell its share of the catchment in the basin mean it prints. Without a catchment polygon, cells keep equal weight. The grids given to MODFLOW 6 do not change.
- Each stored format declares the oldest version that reads it. Every later 2.x reads every run of this version.
- A calibration with no pin on the protocol follows 1.3. The map is cut to the catchment and the network is rasterized from the heads of the observed streams.
- A tie on the cost in the last phase of a search promotes the trial that the search answered.
- A date written on a stamp belongs to the period `(s, e]` that the stamp closes.
- A calibration goes through `hmp.calibrate`. Overrides go through `set=`. `Project.run` is now `Project.launch`. A name that left is refused with its new path.
- A boundary condition is active when its table is declared, and `enabled = false` turns it off. Boussinesq and PETSc settings are written under `[solver.boussinesq]`, and the discriminator is `kind` everywhere.
- On the command line, `-w` works on every verb, and `hmp campaign` holds the verbs of a plan of cases.
- A budget flux is negative when water leaves the aquifer, for every solver.
- A time series has a `source` column (`simulated` or `observed`), and the catchment row is named `catchment`.
- NetCDF and VTU write one variable with a layer dimension. Opening a NetCDF in QGIS needs `layer=` on the export.
- With `parallel` above 1, trials of a HydroModPy search run in worker processes that last, not in threads. A script that calibrates this way needs the `if __name__ == "__main__":` guard. A `metric_fn` must be defined at the top level of a module.
- `[solver.modflow6.runtime] mf6_api_timeout_s` now limits one whole trial of a parallel search. The default stays 2400 s, so a longer trial now ends `crashed`.
- With `parallel` above 1, grid, Latin hypercube and random searches feed one queue of workers, and the progress bar moves as each trial ends. `multistart` restarts run side by side. `linearized` derivatives run in workers.
- `scipy_de` accepts `parallel` above 1 and scores a whole generation at once. Optuna `tpe` counts trials in flight as the worst cost so far. At `parallel = 1` nothing changes.
- Calibration refuses old keys of `[calibration]` and names the new one, for example `scoring_window`, `max_iter`, `tolerance` and `roptim_max`.
- Changing the validation window starts a new cache scope and session. A file without the key keeps its cache keys.
- `Project.calibrate()` names its case like `hmp calibrate` (`[simulation] name`, else the project file stem), so both share one session and `resume` finds it. A call with phases writes `sessions/<case>.toml`, overwritten by the next call.
- The preflight refuses a minimiser on one parameter scored on two network bounds of positive weights. It also refuses a steady network-only search that moves K and the recharge factor, and `factor` beside `[flow.sinks_sources.recharge.soil]`.
- The preflight warns when `distance_gap` enters a cost beside another parameter or metric, and when two roots lie more than half a decade apart. Bisection needs every block to publish a signed residual.
- A raw residual cost in a unit, such as an RMSE in m3/s, beside pure-number costs is refused unless `normalize_cost = true`. `sampling = "normal"` is refused by the Optuna engine.
- A run stores the series at each observed station under the station id. A gauge the mesh cannot place is listed as unscored with a warning. `hmp.read(run, "head")` or a lake stage with several stations needs `station=`.
- `hmp run` ends a calibration with the same lines as `hmp calibrate`, which now prints units. `hmp calibrate --dry-run` shows the widest `parallel` of the phases.
- A `[sites]` campaign that holds a calibration can run up to 8 solves side by side without `--force`, up from 2.
- Several modules of `hydromodpy.core`, `project` and `workflow` moved to the layer that uses them. A plugin that imports one of them from its old path must follow it. The public names of `hydromodpy.__all__` do not move.
- Example 04 `run_calibration_api_daily.toml` calibrates on 2016-2018 and validates on 2019-2020. The composite example scores its network block on `distance_mean`.
- The layer matrix of `tests/unit/architecture` no longer grants 20 import edges that no code uses, nor the `calibration -> display` tolerance. Its rows go from the lowest layer to the highest, and a test keeps them so.
- Contributors: fourteen scripts of `tools/` that nothing called, five of them broken, left the repository. Script coverage runs through one wrapper, `tools/ci/coverage_runner.py`, and now measures the examples package. The contributor docs name one environment, `hydromodpy-dev`.
- Contributors: the data tests live in `tests/unit/data/`, laid out like the package, and `tests/unit/data_managers/` is gone. The SIM2 grid configs share one base and the lake chronicle configs another, with the `[data]` schema unchanged. `attach_read_only` lives once, in `hydromodpy.core.io.db_retry`.
- The calibration session report draws the best run with the registered figures, lake level included, and names each image after its figure, for example `hydrograph_sim_obs.png` instead of `best_obs_vs_sim.png`.
- The `reporting` layer is gone. The campaign summary is `hydromodpy.results.export.campaign_summary`, and `hydromodpy.analysis.comparison.compare` is now `hydromodpy.project.compare`.
- `hydromodpy.schema.config_schema` replaces `hydromodpy.config.schema_export` and `hydromodpy.schema.export`. The plan of a `[sites]` project moved to `hydromodpy.project.launch.plan`, the check behind `hmp check` to `hydromodpy.project.api.check`, the resolution of a `[site]` to `hydromodpy.data.sites.single_site`, `MetricsConfig` to `hydromodpy.results.metric_rule` and `PublicationConfig` to `hydromodpy.results.publication`. No row of the layer matrix cites a row below it any more.
- Contributors: `-q`, `-v` and `--debug` set the console level once in `cli/main.py`, so a new command no longer calls `apply_verbosity`.
- Contributors: one registry, `hydromodpy.core.plugin_registry`, serves the evaluator, forward-model, terrain and mesh engines. `calibration/runners/cli_runner.py` is split into `document.py`, `session_scope.py` and `search.py`.
- The recession cloud and the Brutsaert-Nieber coefficient moved to `hydromodpy.results.derive.recession`, `particle_travel_years` to `hydromodpy.results.run.particles`, and the metric CRS helpers to `hydromodpy.core.io.crs`. `hydromodpy.display.maps.geo` is a single module, and `GeoFigureMixin` is gone. Figures draw the same pixels.
- The drain conductance helper that every solver shares is in `hydromodpy.solver.base`, and the Boussinesq catalogs are in `boussinesq/catalog.py`. The MODFLOW 6 build runs as named steps, its solver options live in `modflow6/builders/solver_options.py`, the LAK builder is split in several modules and `modflow6.builders` no longer re-exports names. No input file and no result changes.
- Contributors: `hmp_log_records` is a fixture of `tests/conftest.py`, and `tests/_helpers/transport_guard.py` and `tests/validation/helpers/petsc.py` hold helpers that several test folders used to copy.
- `Catalog.read_geographic_feature`, `list_geographic_features` and `read_geographic_metadata` read the run directory instead of the index, and `Catalog.query_timeseries`, `query_budget` and `query_mass_balance` read through the run. `SimulationZarr` binds the writes and reads of the store as its methods. `record_derived_file` moved to `hydromodpy.results.ledger`. Run files are unchanged.
- `Catalog.load_dataset` builds its cohort with `Catalog.find` and shares the parameter pivot and the field stack of `RunSet`, and returns the same dataset. `DatasetLoader` is replaced by `hydromodpy.results.catalog.dataset_loader.load_dataset`.
- The version is 2.0.0, set in `pyproject.toml`, `CITATION.cff` and `hydromodpy/core/version.py`.
- A key or a table that only a pre-release wrote is refused, and the message names every such key the file holds. The one that still loads is `type` in `[[simulation.process]]`, with a warning, and `hmp doctor --fix-config` writes `kind`. The rule of two minor versions holds for a TOML key or table changed from 2.0.0 on. A name of Python, an `hmp` command or a flag that left in 2.0.0 or earlier has no alias and is refused with a message that names its new form. The alias with a `FutureWarning` holds for a change from 2.2.0 on. The warning of an old form no longer states a delay.
- The two irregular-mesh runs of example 06 (`run_selune_mf6_irregular.toml` and `run_vire_mf6_irregular.toml`) use the current keys. They resolve to the same configuration.

### Removed

- The keys and values that only a pre-release of 2.0 wrote no longer load. A file or a sealed run that holds one is refused with every such key it holds, each with its current name, and this version does not rewrite the file. The 175 forms are listed in `hydromodpy/config/prerelease_forms.txt`, which leaves in 2.2.0.
- `model_legacy_keys` and `model_retired_keys` of `HydroModelBase`, `CALIBRATION_RENAMES` of `hydromodpy.calibration.config`, `OLD_PROPERTY_IDS` and `NEVER_READ_IDS` of `hydromodpy.model.properties.property_ids`. A key only a pre-release of 2.0 wrote is refused, with its current name.
- `hydromodpy.model.transport.transport.Transport` and the `transport` member of the run setup. The transport solvers read their table directly.
- geographic.catchment.dem_init_path. Declare the DEM as [[data.dem.sources]] with source = "file". A file that still writes it is refused, `hmp doctor --fix-config` writes the `[[data.dem.sources]]` row, and a sealed run config still reads it.
- hmp data check and hydromodpy.data.workspace.custom_scan.
- hydromodpy.core.io.http_client and hydromodpy.core.io.pinned_download. Use hydromodpy.core.io.fetch.
- PyHELP, the Picard solver of Boussinesq, the TIFF maps of MODFLOW-NWT, the MODPATH post-processing and the job
  chain moved to `hydromodpy_annex/`, which is not in the wheel. `ModflowNwt.post_processing`,
  `Modpath.post_processing` and `Modpath.filt_processing` are gone; call `run_post_processing`, `write_shapefiles` and
  `filter_pathlines` of the annex. `hydromodpy.physics.hydrology.pyhelp` and the chain names of `hydromodpy.schema.job`
  are gone.
- `hmp dev manage` is gone. It is refused with `python -m hydromodpy_server --root ROOT`, the HTTP server of the repository.
- `is_boundary_condition_active` and `active_side_dirichlet_boundary_ids` of
  `hydromodpy.model.boundaries.boundary_condition_registry` are gone. A backend reads `Model.boundaries`.
- The solver functions `get_solver_adapter`, `get_extractor`, `get_extractor_instance`, `capabilities`,
  `accepted_meshes`, `list_pairs`, `list_extractor_pairs`, `pairs_for_process`, `required_bindings`, `is_supported`,
  `is_adapter`, `known_process_types`, `register_extractor` and `load_extractor_plugins` of
  `hydromodpy.solver.base.registry`, and `MeshReadingAdapter` and `missing_adapter_members` of
  `hydromodpy.solver.base.adapter_protocol`, are gone. Use `hydromodpy.solver.base.registry.solvers` and `extractors`.
- `hydromodpy.core.contracts.solver_registry` is gone. The callers read `hydromodpy.solver.base.registry` directly.
- `missing_class_members` of `hydromodpy.data.source.port` is gone. `data_sources.register()` refuses a class
  member that is absent or `None`.
- `builtin_ids`, `list_ids`, `is_registered` and `resolve_id` of `PluginRegistry` are gone, with the module functions
  `list_source_ids`, `builtin_source_ids`, `list_engine_ids`, `builtin_engine_ids`, `list_evaluator_ids`,
  `builtin_evaluator_ids`, `list_model_ids`, `builtin_model_ids`, `is_registered`, `resolve_id` and
  `resolved_engine_id`. Use `names()`, `names(shipped_only=True)`, `x in names()` and `get(x).<id attribute>`.
- `RESTART_CAPABILITY` and `CYCLIC_SPINUP_CAPABILITY` of `hydromodpy.config.hydromodpy_config` and
  `SURFACE_EXCESS_CAPABILITY` of `hydromodpy.workflow.steps.planning` are gone with the capability names they held.
- `Modflow6Backend`, `ModflowNwtBackend`, `BoussinesqBackend`, `CustomBackend`, `SolverBackendConfig`,
  `BUILTIN_BACKENDS`, `backend_for_solver`, `solver_name_of_backend` and `SolverConfig.validate_registry` of
  `hydromodpy.solver.base.solver_config`; the `runtime` field of `FlowConfig`; `validate_registry` of the process
  models of `hydromodpy.solver.base.simulation_config`.
- The columns `supported_backends` and `backend_packages` of `FlowBoundaryDefinition`,
  `supported_boundary_ids_for_backend` and `FlowBoundaryBackend` of
  `hydromodpy.model.boundaries.boundary_condition_registry`, and `layering_refusal` of
  `hydromodpy.solver.boussinesq.solver_contract`. A solver says what it builds through its `supports`.
  `BoundaryConditionBundle.unsupported_active_ids(backend)` is now `active_ids_outside(supports)`.
- `RunResult`, `STOP_BEFORE_THE_SOLVE`, `post_run_results`, `resolve_run_model_name`, `resolve_base_model_name` and
  `flow_model_name`, and the re-exports of `hydromodpy.solver`, `hydromodpy.solver.base` and
  `hydromodpy.solver.modflow6.adapters`. The run name is chosen once by the runner.
- `PRIVATE_TRIAL_RECHARGE_KEY` and `TRIAL_RECHARGE_DIRNAME` of `hydromodpy.solver.modflow6.builders.recharge`. The
  calibration sandbox names the forcing folder of a trial.
- `hydromodpy.results.run.rerun_contract` and `ProjectRerunProvider` of `hydromodpy.project.dispatch.rerun`.
- `resolve_mesh_bundle` of `hydromodpy.solver.boussinesq.flow_to_boussinesq_adapter`, the mesh summary key
  `output_exchange_bundle_dir` and `SetupContext.mesh_bundle`. A mesh bundle comes from the `exchange_mesh` option.
- `hydromodpy.catchment.delineation.registry` (`get_backend`, `register_backend`,
  `available_backends`, `clear_backend_cache`) and the `kind` argument of
  `get_whitebox_backend`. `get_whitebox_backend()` returns the one Whitebox environment of the
  process, and a caller passes another backend by argument.
- `get_whitebox_backend` and `clear_whitebox_backend_cache` of
  `hydromodpy.catchment.delineation.whitebox_workflows_backend`.
- `last_largest_drainable_share`, a module value written during a run. `upstream_area` returns
  the value.
- The `SOURCES` tables, `SourceContext`, and the legacy helper factories (`sim2_source`,
  `explore2_source`) of the variable managers across precipitation, etp, temperature, wind,
  humidity, radiation, soil_moisture, runoff, recharge, and oceanic are gone.
- `hydromodpy.data.source` no longer re-exports names. Import each name from the module that
  defines it.
- `hydromodpy.data.source.registry.get_serving` is gone. A source is registered under the
  section that asks for it, so a class of another payload kind cannot be named by that section
  any more; the two hydrography seams that still check the kind read the declaration of the
  class they resolved.
- STAC and the standalone PROV view leave the wheel for `hydromodpy_annex`. `format = "stac"`
  and `"prov"` are refused unless `hydromodpy_annex` can be imported. RO-Crate stays, with its
  PROV activities.
- `hydromodpy.results.export` no longer re-exports names. Import each name from the module that
  defines it.
- `FigureSpec.required_solvers` and the `required_solvers` column of `hmp viz list` are gone.
  No figure set them.
- `hydromodpy.display` no longer re-exports names. Import each name from the module that
  defines it.
- `hydromodpy.bootstrap` and the providers it installed. The library needs no start-up call, and
  a calibration fills its own trial pipeline, in each worker process too.
- `register_optimizer`, `available_optimizers` and `typed_methods`. Use `optimizers.names()` and
  an entry point or an in-tree path.
- `Catalog.from_toml`, `Catalog.from_json` and `Catalog.from_dict`. Use `hmp.open` on the
  project, or `Catalog.from_workspace(HydroModPyConfig.from_toml(path).workspace)`.
- `GeologyField.from_dict` and `GeologyField.from_toml` of
  `hydromodpy.model.properties.geology_field` are gone. Build a field on its own with
  `geology_field_from_config` and `geology_field_from_toml` of
  `hydromodpy.data.variables.geology.io`.
- `hydromodpy.catchment.protocols`, which registered the geology data source, is gone.
  `geology_lines` of `hydromodpy/mesh/planning` takes `read_vector`, the reader of one vector
  geology map, as an argument passed by the caller.

- `[calibration].forward_model` and the `ForwardModel` port are removed. A global model is a solver backend: name it by `solver.backend` and calibrate it with the pipeline evaluator.
- The solver aliases mf6 and nwt of `hmp catalog ls --solver` are gone. Write the full backend name.
- `hydromodpy.schema.validate_field` and `hydromodpy.schema.ValidationResult`: `check(document, partial=True)` replaces them. `hydromodpy.schema` re-exports nothing, so `export_full_schema`, `build_config_meta` and `build_field_validators` are imported from `hydromodpy.schema.config_schema`.
- `hydromodpy.config.export_checks`: its two checks are rows of `CROSS_RULES` in `hydromodpy.config.cross_checks`. `require_site_for_real_catchment` and `REAL_CATCHMENT_DEFINITIONS` moved there from `hydromodpy.config.hydromodpy_config`.
- `hmp config validate-field`, which had no handler. Use `hmp config check --partial`, or `hmp.check` from Python.
- `hydromodpy.project.check` (`check_project`, `CheckReport`), replaced by `hydromodpy.project.api.check`, which returns a list of `Diagnostic`.
- The data cache database `data/cache.duckdb` and `hydromodpy.data.registry`. The sidecar next to each fetched file is the cache entry. A data folder that still holds a `cache.duckdb` of a pre-release is refused with a sentence that names `hmp workspace clean --data-cache`.
- The private data cache of each case of a `[sites]` launch. A case writes its files and their sidecars in the shared data folder, one station at a time under a file lock.
- `hmp data add`. A user file goes under `inputs/` and is named by a `source = "file"` block, and an ASC raster is converted when it is read. `hydromodpy.data.ingest.convert_timeseries_csv_to_parquet` and `hydromodpy.data.request.cache_verbs.add_data_entry` leave with it.
- `hydromodpy.project.lock`. Its verbs are `lock_data`, `verify_data_lock` and `prune_data` in `hydromodpy.project.data_cache`, and `hydromodpy.data.request.cache_verbs.prune_data_cache` leaves for `prune_data`.
- `HMP_AUTO_MIGRATE` and `HMP_DATA_CACHE_PRIVATE`.
- `hydromodpy.core.contracts.data_cache_backend`, `DATA_CACHE_FILENAME`, `RUN_DATA_CACHE_FILENAME` and `data_cache_path_for` of `hydromodpy.core.state.layout`, and `CACHE_INDEX` of `hydromodpy.schema.sources`. The data cache has no database.
- The temporary `.hmp_effective_*.toml` copy that `--set` and `--overlay` wrote beside the file, and `hydromodpy.cli.effective_toml`, whose parts live in `hydromodpy.config.loading` and `hydromodpy.cli.helpers`.
- `run_dirname`, `MAX_DIRNAME_LEN` and `RunNameTooLongError`, replaced by `check_name` and `MAX_NAME_LENGTH` of `hydromodpy.core.state.names`.
- `[geographic] reuse_existing_outputs` and `[geographic] reg_fold`. A file that writes them is refused with the replacement to write, and a sealed config drops them in silence.
- `hydromodpy.results.geographic_cache`, which nothing called.
- `hydromodpy.catchment.preprocess.regional_flow_job`, which nothing called once `reg_fold` left. To share a conditioned DEM between projects, declare `state = "conditioned"` on its `[data.dem.sources]` entry.
- `HANDOFF_PRODUCTS` of `hydromodpy.solver.base.adapter_protocol`; `face_flow` is a name of the field registry.
- `hydromodpy.results.fit_metrics`. Its functions are in `hydromodpy.results.score`.
- The `LANGUAGES` constant of `hydromodpy.config.check`. The languages are `LANGS` in `hydromodpy.schema.phrases`.
- The lineage kind `published`: a copy has no seal of its own and names its source in `PUBLICATION.json`.
- `hydromodpy.results.derive.views.catchment_total`. Use `budget_over(run, term)`.
- The field `storage_change`, which no solver wrote. Read the storage with `budget_over(run, "storage")`.
- `figures/`, `exports/` and `report/` from the artifact list of `manifest.json`, and the figure asset of the STAC view of a run.
- The `session_id` option of the calibration figures (a `Session` is one session), the figure options `SessionId` and `TrialsSessionId`, and the objective series that `calibration_convergence` read from the station `_calibration`.
- The report TOML of `hmp report catchment` and the flags `--run-overview`, `--run-simulation`, `--context-only`, `--report-only`, `--stream-run-logs` and `--strict-figure-postflight`, with their `--no-` forms. Write `hmp run`, then `hmp report catchment RUN`. The preset `generic` is refused.
- `SessionReportData` and `load_session_report_data` of `hydromodpy.calibration.report`, `step_render_calibration_report`, and `CATCHMENT_PRESETS` of `hydromodpy.cli.commands.report`. The summary of a session is `hydromodpy.results.session.summary`, its report `hydromodpy.project.report.report_session`.
- The modules `hydromodpy.display.report_blocks`, `hydromodpy.display.catchment_report`, `hydromodpy.display.calibration_report`, `hydromodpy.display.overview.web` and `hydromodpy.workflow.steps.calibration`. The report engine is `hydromodpy.display.report` (`engine`, `pages`, `presets`) and its caller `hydromodpy.project.report`. An import of an old path is refused with the new one.
- The variable `HMP_OVERVIEW_HTML_REVIEW_LEVELS`. The review pages of a data overview are always written.
- `hmp.figure`, `hmp.report`, `hmp.calibration_phases`, `hmp.compare_pair`, `hmp.example_add`, `hmp.example_list`, `hmp.example_show` and `hmp.Workspace`. Each is refused with the call that replaces it. `hmp.read`, `hmp.index` and `hmp.Catalog` stay at the top level beside the fifteen verbs, because the runs of a pre-release are read through them.
- `AmbiguousReferenceError`, `SimulationNotFoundError`, `CatalogError`, `RunNotSealedError`, `FieldNotFoundError`, `ComparisonCaseError` and `ComparisonReferenceError` at the top level. Each is refused with the module that defines it, where it stays.
- `hydromodpy.results.catalog.facade.compare_pair`, use `compare([a, b]).table`.
- The `HMP_RUN_SCRATCH` environment variable. The scratch folder of a run lives in a context variable and a calibration worker receives it in its payload.
- `forget_old_forms_told` and the memory of the old forms already told are gone from `hydromodpy.core.config_kit.base`. The old form of a key is a `ConfigKeyRenamedWarning` shown once per file and key by the default filter of Python, so a script that wants to see it again sets the filter to `always`.
- The lazy attribute access of the packages listed under Changed: `import hydromodpy.core; hydromodpy.core.WorkflowContext` and the like no longer resolve.
- The static completion scripts of `hmp completion bash`, `zsh` and `fish`, and the option `hmp completion --argcomplete` (refused, with `hmp completion SHELL`).
- Eleven functions that nothing called: `bbox_contains`, `filter_locations_by_bbox` and `nearest_location` of `hydromodpy.data.common.geometry`, `parse_loc_filename` and `write_parquet` of `hydromodpy.data.common.files`, `get_conversion_factor` of `hydromodpy.data.common.units`, `check_required_columns` of `hydromodpy.data.contracts.completeness`, `iter_chronicle_files` of `hydromodpy.data.ingest.tables`, `parse_atom_entries` of `hydromodpy.data.variables.dem.apis.geoplateforme_download`, `default_geology_data_source` of `hydromodpy.data.variables.geology.io` and `build_zone_class_index_on_dataframe` of `hydromodpy.data.variables.geology.processing`.
- Names no code, no example and no document reads, with their tests: `flow_products_from_paths`, `build_river_mesh_trace_from_vector`, `DEM_correcflow_analysis`, `flow_persistence`, `traits_of`, `is_valid_field_metadata`, `load_field_param_toml`, `reproject_coord`, `reproject_shp`, `mask_by_dem`, `reproject_tif`, `from_workspace_relative`, `is_under_workspace`, `to_workspace_uri`, `observable_time_method`, `plot_lake_abacus_comparison`, `rasterize_points`, `make_piecewise_constant_daily_qin`, `normalize_initial_condition_payload`, `normalize_boundary_condition_payload`, `normalize_sink_source_payload`, `elapsed_seconds_for_time_keys`, `step_end_elapsed_seconds_from_payload`, `list_rows`, `config_option_for`, `missing_field_options`, `release_flux_network_overlap_metrics`, `release_flux_network_distance_metrics`, `resolve_source_runs`, `verify_fingerprint`, `python_value_type`, `write_schemas`, `sources_by_publisher`, `solve_backward_euler_step`, `solve_steady_state`, `dsmooth_positive_thickness_dh`, `smooth_clip_01`, `resolve_surface_interaction_model`, `rate_of`, the MODFLOW 6 `ensure_solver_routing_context`, `boundary_start_value`, `lake_definitions_for_bedleak`, `managed_bin_dir`, `resolve_run_output`, `topological_cohorts` and `restore_seepage_raster_from_store`. The unused methods `set_parameters_from_config` and `set_initial_conditions` of `ProcessSpatial` go with it.
- The Windows-only hashing of long vector layer names and of MODFLOW 6 output names. `hydromodpy.results.zarr_store.zarr_schema.windows_long_path` is gone, use `hydromodpy.core.io.filesystem.native_io_path`, and `WINDOWS_SOLVER_PATH_LIMIT` is gone, use `hydromodpy.core.io.filesystem.WINDOWS_PATH_LIMIT` (no alias). `death_is_proven` was born in 4.20 in `hydromodpy.core.state.host`, so it takes no line.
- The French meeting notes under `docs/_dev_notes/AquiFR_integration/` and the old class diagram `docs/class_diagrams/architecture_condensee_corrigee.png` left the repository.
- `catchment_mismatch` as it was. The old number is now called `basin_mismatch`.
- A network output can no longer score against `geographic.river_network`, because the DEM-derived network is no observation. `hmp doctor --fix-config` says to write `map.complete = "data.hydrography"` or a vector file.
- `hydromodpy.core.Workspace`, which never resolved. Use `Workspace` from `hydromodpy.project.accessors`. `hydromodpy.core.io.crs.haversine_km` is gone, use `hydromodpy.data.common.geometry.haversine_km`.
- The B0 network and transient case left the package for `validation_cases/calibration/network_transient_b0/`.
- Helpers that nothing called: the re-export modules at the root of `physics/hydrology/pyhelp/`, `apply_simulation_time_to_flow_wells`, `apply_simulation_time_to_flow_boundary_conditions`, `SimulationPlan.is_empty` and the `Transport.update_*_parameters` helpers.
- Modules that nothing called: `modflow_common/recharge_evt_routing.py`, `boussinesq/assembly/residual_facade.py` and `boussinesq/forcing_resolution.py`.
- The unused `balanced` option and the `streambed_top` and `streambed_connection` arguments of `write_mesh`.

### Fixed

- A run or a replay started by `hmp run`, by `hydromodpy.run` or by the server works in a scratch folder of its own, `.hmp/scratch/<run>.p<pid>/`, as a run started from a `Project` already did. Two runs of one project at the same time wrote the same `.hmp/scratch/_preprocessing/geographic/` files and one of them could fail on a shapefile the other was writing.
- `tools/ci/removal_proof.py` refuses a set of mutants that mutmut did not finish to write, and waits longer for a larger set. A module with no mutant file was counted as proved at no cost, and a cut generation could leave a mutated module empty, which made every test set that imports it fail at collection. A module whose tests fail with no mutant is now set aside before any mutant is played, in `plan` and in `check`, and `tools/ci/proof.py` reports it as a loss. The plan logs its progress by tenths. A mutant counts as killed only when the kept tests end with a red test that the run names. A timeout, a crash or a run with no named red test proves nothing, and the tests it would have let go are put back. The warm runner flushes the output of each run, which it lost before, so a kill names its test.
- A published run whose document names its data by a relative path such as `../../data/rain.nc` keeps that
  path. The redaction of absolute paths took the `/` after `..` for a root and wrote `..<absolute path>`, so
  `hmp catalog rerun` of the shared copy refused the document.
- A shared run that reads its stations from a user file brings the station row in `INSTALL.toml` again. The row
  was looked up under the provider name `file` while the data file carries `custom`, so the copy failed on a
  missing station.
- `hmp replay` of a published copy that was killed once no longer makes every later replay of that copy fail with
  `FileExistsError`. The folder it left in `.hmp/replay/` is removed once its process is gone, and a second replay of
  the same copy into the same project while the first one runs is refused with a write conflict.
- A local delivery whose destination file is a symbolic link replaces the link again, as before, and no longer the
  file it points to.
- On Linux and macOS a `PermissionError` on a lock file, a launcher lease or a folder rename is raised at once again, as before. Only Windows tries again, for up to 310 ms.
- A lock file put back by a copy, on a volume without hard links, stays with its holder, which can still renew and
  release it. A lock file now carries a `token` drawn at each take.
- A file linked or copied by `link_or_copy` keeps the dates of its source when it is copied, as `shutil.copy2` did.
- The temporary folder of a product written on a host whose name holds dots is swept once its writer is dead, and no
  longer only after a day.
- On Windows, a JSON document or the project index published while a reader holds the old file is tried again for up
  to 310 ms before the error is raised.
- A run with `zone_partic = "seepage_clip"` stopped with a KeyError since the outputs of the solver are extracted after every run. MODPATH now builds the seepage raster from the heads of its flow run, with the seepage rule of the run store, and finds those heads under the NWT name of a run whose name holds spaces.
- Hub'Eau clients report dropped stations via report_dropped instead of silently ignoring empty chronicles.
- Hub'Eau product QIXM discharge conversion (l/s to m3/s).
- The steady start of a transient Boussinesq run with the `petsc` backend and `ts_vi_obstacle` used to stop with `AttributeError`. It runs again, with `regularized_partition` for the auxiliary solve, as in 2.0.0a5.
- A `flow.restart_from` given as a run name or a sim_id is now read on a resume and in a calibration trial, as it is on
  a first run. Before, only a path worked there.
- The frozen config of a run whose catchment reads its DEM from `[[data.dem.sources]]` validates again.
- MODPATH and MT3DMS build their deck again, and the `seepage_clip` release raster reads the water table cell by cell.
- `hmp run --frozen` replays a station that answered nothing. `hydromodpy.lock` pins it as an input with `empty = true` and no sha256, and an empty answer the lockfile does not pin is refused. Before, every such station was refused, because the lockfile could not pin it.
- The root search of a calibration keeps one cost per point of its search variable, so a point that failed and was solved when asked again no longer breaks the interval around the root.
- The catchment series and the calibration discharge keep no module state between runs. A reused id of an earlier context no longer silenced the runoff warning of a new one.
- The matching card names the unit of a parameter from the session journal first, so `K (m/s)` instead of `K (-)`.
- Two runs in two threads of one process write each its own run.log, keep each its own scratch folder, and no run saves or restores the warning filters of the process.
- A figure render no longer switches the matplotlib backend or leaves a style in rcParams, so two renders in two threads of one process draw each its own style; figures are drawn without pyplot, and pyplot is kept only for quicklook and for the window that `[display] show` opens.
- `hmp check` no longer crashes on a `[flow.param.<id>]` table that has no `[flow.param.<id>.field]` section. The model refuses it as a value error with the same sentence, so `check` reports it like any other refusal.
- `hydrograph_sim_obs`, `scatter_one_to_one`, `recession_power_law` and `residuals` raise `FigureNotApplicable` when the run holds no observation, no shared timestamp or no falling limb, so a run with `on_error = "raise"` skips them with the reason instead of stopping.
- `calibration_landscape`, `calibration_pairplot` and `calibration_objective_surface` raise `FigureNotApplicable` when the session sampled too few parameters, too few finite trials or collinear trials. A malformed `parameters=` argument is still a `ValueError`.
- `simulated_active_network_reference_overlay` reports a run without a reference hydrographic network as unavailable instead of raising `KeyError`.
- On Windows, promoting a kept trial and importing a published run no longer fail on the reserved folder, and a calibration worker ends together with the solver it started.
- `hmp replay` no longer refuses with HMPY.E210 a run that read station files from a user folder (hydrometry,
  piezometry, intermittency, and the grid families read from a CSV folder). The run now pins the location file
  beside each series in `inputs.json`. A run stored before this fix stays refused, and the refusal names the
  remedy: `hmp data lock` for a pin of `hydromodpy.lock`, a new `hmp run` for a pin of `inputs.json`.
- The validation launcher makes the `path_file` of a forcing series absolute, as it does for `path` and `*_path`, so the tide and the two linearized transient cases find their forcing CSV from the output folder.
- A project whose DEM comes from a `[data.dem]` source alone, with no `dem_init_path`, opens again.
- The MODFLOW 6 `discharge` of a run with a lake and no SFR, the Boussinesq `discharge` and the Boussinesq budget terms. Sizes are in Numbers.
- A network output whose `time` falls on a stamp, and a window that ends on a stamp, now read the right period.
- The soil reservoir citations are checked against the sources. The description of `curve_number` no longer claims an explanation that no source supports.
- `load_to_numpy` reports a GeoTIFF without a CRS instead of raising `AttributeError`. `load_to_xarray` labels the real axes after a reprojection to degrees.
- `select_within_polygon_points` now filters the grid. PyHELP ERA5 preprocessing with `nearest_filter=False` receives only the points inside the polygon.
- Unit types such as `LengthMeters` give a pydantic `ValidationError` for a boolean, a list or a table without `value`. A TOML error in a later `[[table]]` block points at that block.
- `Project.calibrate()` refuses `method`, `max_trials`, `save_runs`, `seed`, `outputs`, `objective_blocks` and `phases` when the calibration comes from a file. `resume=True` works on the programmatic routes.
- `Project.calibrate` without phases honours `uncertainty.method = "linearized"` and returns `parameter_uncertainty`. A phased calibration from a project in memory no longer fails when a phase overrides the regime.
- `hmp doctor --fix-config` reads inherited files for the timestep, `start_datetime` and `[site] gauge`. It keeps the weights of each map and refuses dotted-key network outputs with a clear message.
- A sealed run config with `roptim_max` other than 2 reads and replays. Two parameters on one path, `path` with `target`, and `mode = "scale"` on a zero value are refused at load.
- A worker that dies marks its trial `crashed` and the search goes on. A stuck `mf6` is killed with its worker. Ctrl-C or SIGTERM at `parallel` above 1 ends the solves at once.
- Warnings say a value reached a bound only when it is on it. A minimiser on one parameter and two bounds is refused only for signed residuals. A calibration that scores different blocks in different phases is accepted.
- The `calibration_progress` figure of a staged calibration shows the value a phase froze, so the best run reads `K = 7.96e-05 m/s` instead of `K = nan`.
- A retired root section such as `[modflow]` is refused by its sentence when a mapping is validated directly, as it already was in a TOML file. `hmp check` no longer lists a `ResourceWarning` among the warnings of a file.
- The Hub'Eau client no longer lists `HmnJ`, a product the API refuses, and the `product` example shows `HIXnJ`.
- An interrupted `hmp run`, `hmp calibrate` or `hmp spinup` prints `Interrupted.` like every other command, still with exit code 130.
- A mesh or terrain engine registered by hand can no longer take the id of a built-in engine that is not imported yet. The calibration preflight writes a window bound with its time when it is not at midnight, like the scoring.
- The parameter cost profile reads search bounds stored as JSON text, like the calibration progress card. The Piper, Schoeller and Stiff diagrams refuse an unreadable source with the same message.
- `import_zarr_field` refuses a field store whose schema version is outside the read window, like every other reader. A NetCDF export refuses a time step outside the axis of a field rebuilt on read instead of wrapping it. The STAC, RO-Crate and PROV views written outside a run directory are written atomically, and a NetCDF export no longer uses a fixed temporary file name.
- `RunSet.to_xarray` warns about a run whose field store cannot be opened instead of skipping it silently. `Catalog.describe`, `variables`, `metrics` and `stations` no longer hide errors other than a missing table or view of the index.
- A bisection search no longer stops with `TypeError` when a cut point whose solve failed is asked again and solves. Intervals from other curves are unchanged.
- `manifest.json` gives the sha256 of `fields.zarr`, and `hmp doctor` reports a field store changed since the seal. A seal written before has none and still reads. The STAC and RO-Crate views give no checksum for the store, because it is a directory and not a file.
- The matching card of a calibration now reads the unit of K from the session journal (`bounds.<name>.units`) before the session config, so its axis no longer shows `K (-)` when the journal says `m/s`.

### Security

- `Pillow` now starts at 13.0.0, the first version with the 2026 security fixes.

### Numbers

<!-- numbers:begin -->
- Hub'Eau product QIXM (monthly maximum instantaneous discharge) was read as a water level in m, with the l/s value unconverted. It is now a discharge in m3/s, 1000 times smaller. QixM, which Hub'Eau does not serve and which returned no observation, is read as QIXM.
- With station_ids and max_stations both set, Hub'Eau hydrometry loaded only the first max_stations named stations that had data and never said so. max_stations now counts only the stations a search over the extent finds, and every named station is loaded.
- Hub'Eau cache looked up cached series without product in the cache key. An entry whose product differed answered anyway.
- A stress-period stamp was compared with the observed value at the stamp instead of the mean of the period it closes, so discharge scores (NSE, KGE, RMSE) of these runs are not comparable with later ones.
- MF6 wells and sides were placed on the triangulation instead of the Voronoi dual cells, MODFLOW-NWT stored one slice per time step and read a wrong budget, and Boussinesq ignored the steady first period, the bed thickness of drains, the recharge rule of fixed-head cells and the sub-steps; fixed between c14c1b4c6 and 48d7db46e.
- The MODFLOW 6 DISV took the ground as its top, so the top layer had an uneven thickness and heads under a varying thickness were off by 0.16 to 0.31 m on the Nancon; the DISV now carries a computation top, fixed between b1fa87021 and ec7f8de88.
- A run started from flow.restart_from read the last head of the earlier run as stored, rounded to 2^-17 under the compact precision, up to 0.8 mm on 100 m of head. It now reads final_state, in double precision.
- The cyclic spin-up carried the heads from one cycle to the next and restarted every lake from its initial_stage, so the lake never settled. Each cycle now starts from the final stage of the previous one.
- The auxiliary steady solve that sets the initial heads of a MODFLOW 6 or MODFLOW-NWT run with [flow.ic] kind = "steady_state" always starts from the top of the model. It used to start 0.01 m below the top when [flow.runtime] set backend = "petsc" and surface_interaction_model = "vi_obstacle", two Boussinesq settings that MODFLOW does not use. Only that combination changes, by the order of the head closure of the auxiliary solve (at least 1e-3 m for MODFLOW 6, headtol, 1e-4 m by default, for NWT); no example, reference or validation case uses it.
- The start head of a run that restarts from another one is written to MODFLOW 6 as a double precision binary array, and its lake stages with all their digits, no longer rounded as text. Heads move by about 1e-9 m and lake stages by up to 5e-9 m.
- MODFLOW 6 with SFR storage: a run that restarts from another one, and each window of a chain, gives each reach the stage it ended on as INITIALSTAGES, read from final_state, where the reach used to start from the stage the package computes. On a two-window chain the head of window 2 moves by about 1e-4 m, and the chain then differs from the run in one piece by 6e-10 m. A source run of a pre-release of 2.0 has no final_state, and its reaches start as before.
- The catchment series and budget_over count the inflow and the outflow of each element (layer, cell) on its own, as the extractors do, where the catchment series summed the layers of a cell first. A drain only leaves the aquifer, so the discharge does not move: 0 on the six reference runs and on two runs of example 04, all one layer. On a multilayer run the inflow and the outflow of a term whose sign changes between layers move, and their difference does not.
- The catchment series and budget_over drop a non-finite element (layer, cell) alone, where a pre-release dropped the whole cell when one of its layers held a NaN, so the discharge of a multilayer run whose drain cell holds a NaN in one layer now counts its finite layers. A time step with no finite element under the weights gives NaN, where a pre-release gave 0, and a family such as storage is NaN on a step where one of its terms is NaN. A run of one layer with finite fluxes does not move: 0 on the six reference runs.
- The root interval of a bisection counts in n_trials and n_within the distinct points of the search variable that solved, where a pre-release counted the solved trials, so a point solved twice counts once and keeps its first cost. 0 cases out of 3,000 searches move.
<!-- numbers:end -->

Sizes come from example 04 unless another case is named. Runs of a pre-release are not comparable on these quantities.

- Soil recharge on example 04, 2015 to 2020, for a capacity of 50, 100, 150, 200 and 250 mm. It was 443, 392, 356, 325 and 295 mm/year and is now 443, 389, 350, 315 and 280 mm/year.
- Discharge of step 6 of example 04 (K = 3.16e-5 m/s, Sy = 0.04). NSE log goes from 0.903 to 0.932, KGE from 0.911 to 0.947 and NSE from 0.904 to 0.929. The July to September bias goes from +0.022 to 0.000 m3/s.
- MODFLOW 6 with a lake and no SFR, `discharge` over a three-month valley with a buffer. It was about 3.855e-05 m3/s and is now 0.087693 to 0.143696 m3/s, 2 600 to 3 700 times more. The old number was the lake outlet alone. SFR runs do not move.
- Boussinesq `discharge` on the test island, three months. It was 4.2e-9, 9.6e-10 and 4.2e-11 m3/s and is now 0.012709, 0.025505 and 0.010800 m3/s. MODFLOW 6 on the same mesh reads 0.011417, 0.023888 and 0.009734 m3/s.
- Boussinesq calibration trial on a mesh wider than its catchment. The old series was 2.0 times the published one on an island cut in half. It now equals it. With no buffer nothing moves.
- Boussinesq `budget/drain` and `budget/surface_excess` change sign, the size stays. The signed fields now close against the change of storage, to 3.7e-7 of the recharge on the steady period. Steady runs and the MODFLOW solvers do not move.
- A network output whose `time` falls on a stamp reads one period earlier. With `time = "2002-10-01"`, `distance_gap` goes from 86.32 to 79.08 m and `D_optim` from 142.4 to 139.2 m. A date inside a period does not move.
- A window that ends on a stamp keeps one period fewer. `2001-01-01` to `2002-01-01` on a monthly run is 12 periods, it was 13.
- A tie on the cost in a last phase. On the shipped mesh the promoted K goes from 8.058e-5 to 7.962e-5 m/s (-1.2 %). On 30 x 30 it goes from 1.4678e-4 to 1.5034e-4 m/s (+2.4 %).
- The cut to the catchment under `heads`. On the shipped mesh every K and cost is the same, and the heads examined fall from 154 to 29. On 30 x 30, J at the best trial goes from 11.0 to 50.3 m.
- `catchment_mismatch` changes meaning and enters no cost. On the shipped mesh of 21 406 cells 0 becomes 0.37 %, and on 30 x 30 it becomes 11.0 %.
- Every cache key of a calibration changes once, so the trials of an earlier session are solved again.
- No number moves for MODFLOW 6 on example 04 (the 55 arrays, `timeseries`, `budgets` and the 11 scores, NSE 0.9345), nor for a run with no override.
- A Python calibration without phases and with a `linearized` width now pays one model run per parameter plus one at the optimum. Search results and costs are unchanged.
- Example 04 calibrated Sy goes from 0.04411 to 0.04296 and `1 - nse_log` from 0.083976 to 0.083988, with two solves less. K does not move. `calibration.precision` now writes a relative `fatol`.
- `run_calibration_api_daily.toml` ranks its five K on 2016-2018 instead of 2016-2020. The size of the change was not measured.
- At `parallel` above 1 trial costs are equal to the last digit, with 63 trials checked at widths 2, 4 and 8 on example 04. Peak memory at width 8 is 6.5 GiB.
- `scipy_de` at width 4 needs more evaluations than at width 1 for the same late precision, up to 1.5 to 5 times, and wins when solves dominate. `tpe` with `constant_liar` is neutral at width 2 and better from 4.

## [v2.0.0a5] - 2026-10-13

This alpha adds a daily soil reservoir for the recharge, a new way to draw the observed network from its heads, and a computational top for MODFLOW 6. It also removes the burn of the mapped network into the DEM and fixes many Boussinesq and validation errors.

### Added
- `[flow.sinks_sources.recharge.soil]` computes the recharge from a daily soil reservoir fed by the rain and the ETP, instead of the SIM2 drainage. It works with MODFLOW 6 only. Main keys: `ru` (required, calibratable as `soil.ru`), `alpha`, `kc`, `impervious_fraction`, `bypass_fraction`, `transit_time`, `spinup`.
- `hmp run <file> --until load_data` checks the soil alone. It prints the budget in mm/year and the recharge for `ru` from 50 to 250 mm, and writes no run. The section refuses what would count water twice and says what to write instead.
- Soil reservoir options: `curve_number` adds a runoff in the manner of HELP, with `runoff_time` and `runoff_lag`. All are calibratable and off by default. `[data.soil_capacity]` spreads `ru` over ten classes inside each SAFRAN cell. Example 04 gains `step6_soil_reservoir.toml`.
- `[geographic.catchment].dem_resolution` aggregates the DEM to a coarser cell size (for example `"75 m"`) before anything is delineated. A value finer than the DEM pixel is refused.
- `observed_rasterization = "heads"` draws the mapped network from its heads only, so the path of a field, a ditch or a rectified reach no longer counts as model error. Each trial publishes `n_heads`, `n_heads_lost`, `head_snap_p90_m` and `heads_trace_near_map_share`. The figure `observed_network_heads_map` shows the result.
- The dam foot of a lake with a declared spillway is a forced head of the heads rule. It comes from the model, never from the observed map, and is counted in `n_forced_heads`.
- `source = "explore2"` for `[data.precipitation]` and `[data.etp]` reads a local DRIAS Explore2 NetCDF.
- `[[data.dem.sources]] source = "ign_geoplateforme_dem"` takes `dataset = "rge-alti"`, the RGE ALTI at 5 m (default) or 1 m. Large requests are refused with their size.
- `[data.crossings]` lists roads, railways (BD TOPO), ROE obstacles or a custom file. `[geographic.crossings]` notches the generated river network at each road, railway or bridge crossing, except where a dam or weir is declared.
- `[geographic.bed_regularization]` makes the channel bed of the model top never rise downstream. It is off by default and serves both DRN and SFR.
- `[geographic] dem_correc_type = "capped_breach"` conditions the routing DEM with a bounded breach (`max_depth` 0.5 m, `max_distance` 200 m). `fill` stays the default.
- `[modflow6.sgrid.top_sampling] mode = "zonal"` now also works on a structured grid coarser than its DEM.
- Calibration: `method = "lhs"` (Latin hypercube, sized by `method_options.n_samples`, `max_iter = "auto"` budgets exactly `n_samples`). `extinction_depth`, `impervious_fraction`, `runoff_lag` and the depth profile `K.characteristic_depth` can be calibrated.
- `[calibration] persist_trial_series = true` writes the simulated and observed series of every scored trial under `sessions/<name>/trial_series/`. It is off by default.
- `hmp calibrate --check` refuses an `observes` station that no data source lists and a scoring window with no date of the run (exit 14). It warns when `da_mh_gp` is scored on a metric other than `rmse`.
- `hmp config resolve FILE` prints the TOML a `base_config` chain resolves to. The directive `key__merge = [...]` merges a list of tables with the inherited one.
- `hmp config schema --editor [--out FILE]` writes a JSON Schema for editors. It accepts `base_config`, `__append`, `__delete`, `__merge` and quantities with units.
- `hmp viz show --opt NAME=VALUE` sets any figure option. Every figure takes `title` and `show_run_name`.
- `hmp catalog import --as NAME` names the project of an imported run.
- Python API: `hmp.run(path, name=...)` names a run from a TOML path. `hmp.read(run, field, time=...)` takes a date, `"first"`, `"last"` or an integer. `hmp.read(run, "particles")` returns the particle paths. The `sfr_reaches` table has a `downstream` column.
- `flow.partition_release_depth_m` sets the depth scale of the regularized partition of the Boussinesq solver (0.05 m by default).
- Exit code 23: a testbed or regional lab with a failed case ends with `FailedCasesError`, after writing every artifact.
- `[context.geology] path` in a catchment report names the geological map for the legend.
- Validation: new cases `stream_depletion_glover_balmer_2d`, `hantush_recharge_mound_2d` and `linearized_unconfined_boundary_periodic_1d`, new variants `modflow6_voronoi` and `boussinesq_local`, and a nightly PETSc job. The Validation page shows the measured value, threshold and error maps of each case.
- Documentation: Understand pages, a glossary, reference pages for calibratable parameters, minimal files, exceptions and exit codes, and a Get started quick start. Every `hmp` command shows an example in `--help`. The data-source registry states each licence.

### Changed
- A run keeps its whole per-cell budget by default, storage terms included. The developer key `[simulation.results] keep_per_cell_budget = false` keeps only what the run's figures, exports and outputs read. A calibration that saves runs keeps the whole budget for the best run only.
- `[simulation.results.derived]` and `[simulation.results.budget]` are dropped on load with one line. `hmp doctor --fix-config` removes them from the file. Every derived field is now rebuilt on read.
- MODFLOW 6 reads a computational top, so every top-layer cell has the same thickness. Under Newton, a thickness that varied between cells gave too low a transmissivity. Package elevations, initial heads and the stored run keep the ground.
- `observed_rasterization` now defaults to `"heads"`. Write `"crossing"` to reproduce the rule of the paper.
- Every MODFLOW 6 and MODFLOW-NWT build makes the descent D, and every flow path reader follows it. D is stored in `fields.zarr/mesh/descent_*` and read by `Run.descent`. Boussinesq also stores D for a raster run.
- A steady run (`flow_regime = "steady"`) is one stress period over the whole `[simulation.time]` window, whatever `step_value` says.
- A list of tables in a child TOML replaces the inherited list. Write `key__merge = [...]` to merge tables or `key__append` to extend.
- `solver.backend` follows the flow process of `[[simulation.process]]` when the file does not set it. Two different names are refused.
- `flow.runtime_backend` defaults to `"auto"`. Boussinesq runs the dense `local` engine up to 400 cells and `scipy_sparse` above. An explicit `local` or `scipy` on a larger mesh stops with `IncompatibleCapabilitiesError`.
- MODFLOW-NWT defaults to the chi-MD linear solver (`linmeth = 2`). With GMRES a stiff recession could be accepted as converged with a frozen head. `fluxtol` is now in m3/s, with a default of 500 m3/day.
- `[modflownwt.sgrid.top_sampling] mode = "zonal"` needs `channel_source = "none"`.
- The run identity that decides whether `hmp run` skips an identical completed run now covers every input file hash and the package version, and no longer the run name. `hmp.run(cfg)` without `name=` uses `[simulation] name` and skips an identical run like `hmp run`. `force=True` computes it again.
- `hmp.run` raises `CatalogError` when the catalog cannot be opened after a finished run. `hmp.calibrate(path)` returns a `CalibrationReport` for a file without phases (`return_report=False` gives the dict).
- A pipeline step failure exits with the code of its cause (16 for data, 15 for solver) instead of 1.
- The NSE on log discharge is named `nse_log` everywhere. `hmp catalog reindex` renames stored rows, and `@best:log_nse` is refused.
- `@best`, `@worst` and `Catalog.best/worst/rank` follow the direction of the metric. A metric with no declared direction is refused.
- Under `coverage_policy = "warn"` or `"ignore"`, a period before the first sample takes that sample instead of stopping the run.
- `hmp config check` refuses a type in `data.types` without its `[data.<type>]` section. `[testbed]` and `hmp report catchment` files refuse unknown keys (exit 14 for the report).
- `hmp data get <variable>` without `--source` takes the one source that downloads.
- A calibration that samples a recharge parameter writes the RCHA of each trial in its own folder and removes it with the trial.
- Example 21 loses the burn and the top conditioning keys. Every calibration of example 21 must be redone.
- A negative numeric `first_clim` is refused when `negative_to_evt` is false.
- The reports and figures of the comparison, network, overview and catchment pages are written in English.
- The technical note is cited as HESS 30, 5571-5592 (2026).

### Removed
- `[geographic.enforce_streams]`, the burn of the mapped network into the routing DEM, with its drift check and download. A file that declares it is refused. The geographic cache changes for every project, so each rebuilds its geographic tree once.
- `[geographic.snap_streams]` and everything built for it. A file that declares it is refused.
- `[modflow6.sgrid] condition_top`, `condition_top_epsilon`, `network_safety_net` and `max_channel_lowering_m` (and their `[modflownwt.sgrid]` copies). The solver top is never conditioned. `rectify_on_mesh` no longer needs `condition_top`.
- `stream_threshold_km2` and `stream_threshold_cells` of `[flow.sinks_sources.sfr.<id>]`. SFR traces its reaches on the network whose threshold is in `[geographic.river_network]`.
- `diagonal_neighbors` of point and cell calibration outputs. The network outputs keep it.
- The top-level `[persistence]` table. Write `[simulation.results.persistence]` or `[calibration.persistence]`.
- `calibration.outputs.<name>.cell_id`, which every run refused. Use `row` and `col`, or `support = "point"` with `x` and `y`.
- `transport.modpath.parameters.track_dir = "custom"`, `fill_method` of the CSV forcings, the `id` of `[data.lake_bathymetry]` and `[data.lake_geometry]`, and several site_selection keys. Each is refused with what to write.
- The one-way pass that lowered the downstream top of SFR reaches, by up to 29.8 m.
- The `geology_field` keyword of `discretize_fieldparam_on_sgrid`. Use `support_field`.
- The user guide pages of the documentation. Old URLs redirect to the matching reference, Understand or Theory page.

### Fixed
- Time steps: a stress period cut into steps now stores the head of its last step and every flux as the length-weighted mean of its steps, for MODFLOW 6, MODFLOW-NWT and Boussinesq. A run of one step per period is unchanged. A MODFLOW 6 run with a lake or stream network and several steps per period no longer fails at extraction.
- A transient Boussinesq run now solves its first period at steady state (`flow.first_period_steady`, true by default), stamps each period at its end, and honors `simulation.time.substeps_per_period` with every engine.
- A Boussinesq cell with an imposed head takes no recharge and no surface release. A well or drain on such a cell does nothing, as in MODFLOW, and the run warns. Heads are unchanged.
- The default Boussinesq surface closure released water far below the ground. It now follows the depth of the water table with `flow.partition_release_depth_m`.
- Boussinesq derives an undeclared drain conductance as `K * cell_area / solver.drain_bed_thickness_m`, like MODFLOW. Its `budget/constant_head` field is now signed positive into the aquifer.
- With `grid_dual = "voronoi"` (default on a Gmsh mesh), MODFLOW 6 places wells, side boundaries and the stream boundary on the Voronoi cells it solves. Before, a run could stop on an out-of-range cell or put a well in the wrong cell.
- The channel mask of the zonal top covered the whole catchment. A zonal run now gets a higher top on its hillslopes.
- The water budget of a MODFLOW-NWT run is read, so a calibration threshold on the budget now applies to it.
- `first_clim` sets the rate of every steady stress period and no other, under all three solvers.
- `simulation.time.coverage_policy` applies to every forcing record. A record that ends early stops the run under the default `"error"`.
- A forcing record whose time index is not in nanoseconds took the last sample for every period. It now takes its own samples.
- A forcing value written with its unit (`'100 m**3/day'`) is no longer scaled a second time by `units`. Lake and SFR rainfall and evaporation are read as rates in length per time. A negative lake rainfall, evaporation, runoff, inflow or withdrawal is refused.
- A calibration of `flow.sinks_sources.recharge.values` reads its bounds in the unit of `recharge.units`, not in m/s.
- `hmp run` now skips an identical completed run as documented. A resume in another process no longer stops on a changed workspace fingerprint.
- A data variable in `[data]` that cannot be loaded stops `hmp run` with exit code 10, 14 or 16, where it used to be logged with exit code 0. `hmp run --frozen` stops with exit 16 on a missing lock entry, cache miss or digest mismatch for every variable.
- A custom DEM, geology file or river network without a CRS is refused (exit 16) with the command that writes one. It used to be labeled EPSG:2154 or EPSG:4326.
- A side, ocean or stream constant head below the bottom of its cell stops the run before the solver, for MODFLOW 6 and MODFLOW-NWT.
- `hmp calibrate` prints the calibrated values, their interval and the cost for a file without phases. `--list-phases` prints one line for the single search.
- `hmp dev rank` works again. `hmp catalog watch` no longer shows live runs as `[STALE]`, and a run stopped by Ctrl+C or SIGTERM is marked `failed`.
- `nse_seasonal` and `reservoir` scored NaN on a monthly series. The summary columns `nse`, `kge`, `rmse` and `r2` of `v_simulation_summary` were empty for runs scored on discharge.
- Network and seepage figures render again on a run with several layers, and `sfr_longitudinal_profile`, `difference_map` and `side_by_side` are repaired.
- A run on an unstructured mesh keeps its K, Sy and Ss fields under `derived/` again.
- Wells declared without `"wells"` in `flow.active_sinks_sources` are refused by `hmp config check`. A mesh along the rivers without a `[geographic.river_network]` threshold is refused with the key to set.
- Runs recorded before the new refusals rerun and resume again, because their stored configuration is migrated when read.
- Validation references and thresholds were corrected for the drainage, island, pumping, Brutsaert and Ogata-Banks cases. Their errors now compare what the model computes.

### Numbers
- MODFLOW 6 heads change on every model whose thickness varies (`flat_substratum`, `raster_substratum`, `raster_thickness`, a zonal top). The head RMSE against MODFLOW-NWT on the Nançon was 0.16 to 0.31 m before. MODFLOW 6 calibrations made on such geometries are not comparable. Example 04 is unchanged.
- Soil reservoir on the Nançon, daily 2015-2020: the KGE of the gauged discharge goes from 0.65 (SIM2 drainage) to 0.79 (`ru = 150 mm`). The mean yearly recharge stays within 3 % of the SIM2 drainage plus runoff.
- Descent D: on example 04 the gauge cell now drains 99.89 % of the catchment, against 0.17 % on the former face graph.
- Boussinesq: heads of the first period of a transient run now differ from MODFLOW 6 by 0.23 m (RMSE) on the natural-mesh test, against 2.6 m. On the natural basin the exported recharge matches MODFLOW 6 to 1e-8, where it was 13.1 % above the forcing. The pumping of a well on a fixed-head side reads 1000 m3/day, not 2000.
- The default Boussinesq closure lost 3.6 % of the recharge of a water table 10 m under the top of a 60 m aquifer. It now loses 2e-9 at 1 m depth.
- Zonal top on the Flume Voronoi mesh: the channel mask now holds 4,197 pixels instead of 146,384. The weekly Flume v2 run no longer converges with its solver settings.
- Example 21 with the breach routing DEM: 97.92 % of the catchment drain cells routed to the river (99.62 % with the burn), outlet discharge 1.127 m3/s (1.147).
- MODFLOW-NWT with GMRES could report a budget off by 200 %. With chi-MD the recession is computed again.
- `capped_breach` against `fill`: the catchment moves by less than 0.1 %, and the agreement with BD Topage moves by 1.74 points on example 04 and 1.22 points on the 25 m Nançon DEM.
- Per-cell budget on the six-year daily Nançon run (21,406 cells): 299 MB, 3.7 times the head. The seepage mask reads in 0.3 s instead of 9.4 s.
- Network heads rule on the Flume Voronoi run: one piece of 5078 cells to the outlet, where `"crossing"` left 1989 pieces.
- Stored values: the budget and derived fields of a stress period cut into steps are now the period mean. A run of one step per period is bit for bit unchanged.

## [v2.0.0a4] - 2026-09-29

This alpha makes stored results smaller and calibration promotion faster.

### Changed
- Time-varying fields are stored in float32 with a rounded mantissa. This is the default
  (`[simulation.results.persistence] field_precision = "compact"`). Use `"exact"` to keep float64.
- A calibration promotes a trial from the solve it already ran. It no longer writes the inputs and
  solves again. The promoted run is the same bit for bit and carries the tag `promoted_from_trial:<N>`.
- Flow-state figures read a field over a range of timesteps with the store opened once
  (`results.run.geographic.field_range`, `field_steps`).
- The CLI banner draws each letter whole in its own color.
- Every file of example 04 draws more figures and writes exports to `share/<run>/` with `[[export]]`
  blocks. The composite calibration draws a cost profile and a distance crossing against K.

### Fixed
- The scan of `data/<variable>/` removes an orphan sidecar when its data file is gone. A sidecar with
  a stated licence or notes is kept. `hmp data check` tells which case applies.
- A calibration whose gauge comes from an API cache promotes its runs again. It failed on the second
  launch because a station location held numpy values the catalog could not write as JSON.

### Numbers
- Compact storage costs at most 2**-17 of the value, under 1 mm on a 130 m head. The NSE of example 04
  moves by 7e-8. A daily 6-year run goes from 1375 to 397 MB and a monthly one from 16 to 5.5 MB.
- The 15 figures of a daily example 04 run render in 17 s instead of about 2 min, with the same pixels.
- A promotion on the daily API grid of example 04 saves about 7 min of solve.


## [v2.0.0a3] - 2026-09-29

This alpha fixes concurrent runs, parallel calibration and several wrong budgets and figures.

### Changed
- On a terminal, a console log line starts with a glyph for its level: `✗` error, `!` warning,
  `›` milestone, `·` debug. A pipe keeps the `[WARNING]` labels.

### Fixed
- Several runs of one project can run at once. Each run or calibration session works in its own
  `.hmp/scratch/<config>.p<pid>/`. Before, concurrent runs lost each other's files.
- A calibration whose promotion fails now exits 21 (`CalibrationError`) from `hmp run` and
  `hmp calibrate`. It used to print "done" and exit 0.
- `hmp example add 04` merges its stations into `data/<variable>/<variable>_custom_LOC.csv`. Without
  them the hydrometry, recharge and runoff loads failed. Existing rows stay unless you pass `--force`.
- `parallel` alone now runs calibration trials side by side, and a phase takes the `[calibration]`
  `parallel` and `batch_size` unless it sets its own. `scipy_nelder_mead` and the root search use it.
- `flux_timeseries`, `water_budget` and the testbed budget metrics read one budget zone, the
  catchment or the domain. They used to sum both and count the catchment water twice.
- The calibrated discharge adds a gridded runoff such as SIM2 with `extent = "watershed"`. The
  objective scored the drain alone against the total gauged flow and pushed K to the lower bound.
- Every run a calibration promotes keeps its watershed, and a network output whose `time` is a date
  is redrawn at that date. Both used to make the promotion or its figures fail.
- A figure that does not apply raises `FigureNotApplicable`, and the batch skips it with its reason.
- Calibration figures read the session journal, mark the returned trial and carry axis units. The
  `rise` option of `parameter_cost_profile` is removed.
- A GeoPackage or Shapefile export of `simulated_active_network` holds the active cells only.
- `hydromodpy.__version__` reads the checkout's `pyproject.toml`, and `Run completed` prints the run
  duration. The `if_exists = "replace"` help now describes what `replace` does.

### Numbers
- A budget that summed both zones drew 1.68 m3/s of recharge for 1.09 on the domain and 0.59 on the
  catchment. It now reads one zone.
- On the Nancon bounds, a root search at `parallel = 4` takes 6 rounds (20 solves) instead of 15,
  and two roots take 8 rounds (26) instead of 24. With `parallel = 1` the search is unchanged.
- On the composite of example 04, 8 trials at `parallel = 4` take 278 s for 695 s of solves.


## [v2.0.0a2] - 2026-09-28

This alpha adds a general `[[export]]` mechanism and a two-bound, transient network calibration.

### Added
- `[[export]]`: one block per export request (`variables`, `time`, `period`, `format`, `folder`,
  `file`, `crs`, `resolution`, `layer`, `nodata`). The format follows the data. `format` also takes
  `package`, `stac`, `rocrate` and `prov`.
- `hmp export SIM_REF [variables...]` takes the same options. `--list` prints what a run can export.
  The catchment, mapped networks, `watershed_dem`, the water budget and `simulated_active_network`
  are exportable.
- `[display] time` and a per-figure `time` name the instant a map draws, as a date, `first` or `last`.
  `hmp.figure(..., time=...)` and `hmp viz show --time` take it too.
- A network calibration output takes an ISO date in `time`, and `normalize_cost = true` on
  `distance_gap` and `distance_mean` divides by the validity length.
- A network output takes a minimal (permanent) map beside the maximal one, as a file
  (`minimal_stream_geometry_path`) or with `minimal_observed_network = "data.hydrography"`.
- The transient two-bound mode `[calibration.outputs.<name>.extent]` scores a maximal and a minimal
  extent per calendar year. The bisection closes one root per bound and returns their weighted
  geometric mean (`weights`). `max_iter = "auto"` budgets both roots.
- `validity_length` on a network output, `"auto"` or a length such as `"150 m"`, sets the Eq. 4 bound.
- `[geographic.snap_streams]` (`off` by default, `diagnose`, `apply`) moves the mapped network onto
  the talwegs of the criterion graph, with two figures that show what moved.
- Figures `network_extent_bounds_map` and `hydrographic_network_permanence`. A calibration ends with
  a short recap and writes `methods.md`.

### Changed
- `optimizer_kwargs` is now `method_options` and `*_engine_options` are `*_method_options`. The
  per-figure `timestep` is now `time`. Old names load, and `hmp doctor --fix-config` rewrites them.
- An old `[export]` table or `[[export.artifacts]]` loads as `[[export]]` blocks.
- `[geographic].dem_correc_type` defaults to `"fill"` instead of `"breach"`. A file that writes
  `"breach"` keeps it.
- `matching_hydrographic_network` is version 1.2, and a pin on 1.1 is refused.
- With both maps, a one-state network output is scored on the minimal map, and the maximal map is
  published as a validation outside the cost. roptim is always Doptim / h_obs.
- Promoted calibration runs are named `<simulation name>_<phase>`.
- `hmp config template` without `--modules` writes every module, `[calibration]` included.

### Removed
- `hmp data export`, `hmp data export-package` and `hmp catalog export`. Use `hmp export`.
- The `[export]` format toggles, `output_dir` and `[[export.artifacts]]`.
- `roptim_max`. Loading drops `roptim_max = 2` and refuses other values.
- `geometry_from_run`. Use `network_maps_from_run`.

### Fixed
- `hmp calibrate --check` names an option a phase-two method refuses before phase one spends its budget.
- `flux_timeseries` draws each flux over its own period instead of one period late.
- Exported NetCDF files carry the mesh size and ACDD metadata. The simulated discharge is exported
  under `catchment` instead of `_catchment`.
- A station read back from the data cache keeps its variable. A Hub'Eau gauge was lost from the
  second run on. A station named in `station_ids` survives the watershed mask.
- An IGN BD ALTI DEM sets its sea to nodata, so the breach step can route it.

### Numbers
- The default `dem_correc_type = "fill"` changes the DEM, so calibration results move. The renames
  change every calibration `params_hash` once.

## [v2.0.0a1] - 2026-09-28

Version 2 rebuilds HydroModPy around a project TOML, the `hmp` command line and a catalog of runs.
It adds lakes, streams and flow barriers in MODFLOW 6, a calibration engine and a data layer.
This first alpha adds the stream-network calibration.

### Added
- MODFLOW 6 Lake (LAK) with stage, bathymetry abacus and bed leakance, a bathymetry raster that
  lowers the cell bottoms under a lake, and `variable = "lake_level"` for calibration.
- Streamflow Routing (SFR) with water movers (MVR) that feed a lake, and horizontal flow
  barriers (HFB) such as a dam cutoff wall.
- A top-level `[export]` section, `domain_extent` (`box`, `watershed_buff`, `watershed`) and a
  mesh `lake_refinement` block.
- `geographic.catchment.buff_area = "N%"` enlarges the catchment by N per cent, as in
  Abherve et al. (2023). A distance reads `"150.0 m"`. `from_outlet` and `from_polygon` default to `"10%"`.
- A raster substratum. `[data.substratum]` holds one raster in meters, read by the depth models
  `kind = "raster_substratum"` and `kind = "raster_thickness"`. Both take `offset` and
  `min_thickness`. The raster must cover every cell of the domain.
- The aquifer geometry can be calibrated with `[calibration.parameters.thickness]` and
  `[calibration.parameters.substratum_elevation]`. `hmp config targets` lists what is available.
- Stream-network calibration reports more. Each trial publishes `d_sat_m`. A search on K alone also
  gives `k_over_r`, `k_optim_m_s`, `t_over_r_m` and `t_optim_m2_s`. The report gives the Eq. 4
  verdict (`roptim_verdict`), the final `bracket` of a bisection and whether the search converged.
- Network outputs take `observed_rasterization`. The default `"crossing"` scores J = 0 for a model
  that reproduces the map. `"touch"` replays older sessions.
- A phase declares `regime = "steady"` or `"transient"` instead of overriding the time grid. It also
  takes its own `uncertainty` keys, and `objective_blocks` accepts a table of shares.
- `hmp calibrate` prints the share of the cost each objective block took. On the example 04
  by-hand session, the best trial takes 37 % hydrograph and 63 % network.
- `hmp calibrate --list-phases` shows the method, uncertainty width and objective blocks of each
  phase. `hmp calibrate FILE --expand` prints what a protocol unfolds into.
- `snap_radius` on a discharge output of `support = "point"` or `"cell"` moves the gauge onto the
  most accumulated cell within that radius. It is off by default.
- `hmp data get` serves data without a project, from a request file or from
  `hmp data get <variable> --bbox ... --crs ... --out DIR`. It writes one file per variable and
  source, plus a `request.json` with sha256, CRS, box and period. The `data-request` process
  (`hmp process run data-request --job DIR`) is its job form.
- Figures `recession_power_law`, `residence_time_distribution`, `mass_balance_error` and
  `concentration_boxplot`, and six calibration figures such as `calibration_convergence`.
- The twelve v1 examples run again in the current format.

### Changed
- `hmp run <calibration.toml>` now runs real MODFLOW simulations. `save_runs = "best_n"` promotes
  only the best trials to full runs.
- `[simulation].run_id` and `on_collision` are refused. Use `[simulation].name` and
  `[simulation].if_exists`, which now defaults to `version`. `hmp doctor --fix-config FILE.toml`
  migrates the old keys.
- Unstructured MODFLOW 6 grids now build a Voronoi/PEBI dual by default, with about half the cells.
  Set `grid_dual = "triangle"` for the old grid. MODFLOW-NWT and Boussinesq are unaffected.
- Raster, VTU and shapefile auto-export now writes the last timestep. Set `[export].times = "first"`
  for the old behavior.
- `method` no longer defaults to `grid`. Calibration picks `bisection` for one log-space parameter
  scored by signed network distances, `scipy_nelder_mead` otherwise. `optimizer_kwargs` need `method`.
- `max_iter` and `steady_max_iter` default to `"auto"`, the worst-case count of a bisection. A
  search that hits `max_iter` gets one extension of half its budget. If still open, it is reported
  not converged, freezes nothing, and a phase that depends on it is refused.
- A network output reads one state, `time = "last"` or `"first"`. `"all"` and date lists are refused.
- The network criterion descends D8 by default (`diagonal_neighbors = true`) and reads one surface.
  Each trial publishes `catchment_mismatch`.
- `[calibration.uncertainty]` `tolerance` and `mode` follow what is scored. A network-only phase
  gets one mesh cell. Other phases get 5 % of the best cost.
- `objective=` must be a `module.path:callable`. Any other value is refused at entry. In Python
  mode, give the metric in `objective_blocks=[...]`.
- `[[data.hydrography.sources]] source = "bdtopage"` now downloads every reach. The old layer
  missed 441 of 694 km over the upper Ille. `typename` is ignored with a warning, and older
  BD Topage downloads are not served again.
- A NetCDF export writes one variable per layer (`<var>_layer<N>` above one layer) so that QGIS
  can read it. `import_netcdf_fields` stacks the layers back.
- `simulation.time.substeps_per_period` stays at 1. One step per period moves monthly discharge by
  4 to 28 % against a refined run, and a discharge calibration absorbs it into the parameters.

### Removed
- `hmp migrate`, `reference_values` in calibration protocols and the `hydromodpy.optimizer`
  entry-point group. Pass your own `Optimizer` to `CalibrationEngine(optimizer=...)`.
- `[modflownwt.tgrid]` and chronicle-driven stress periods (`genmtd = "from_chron"`, per-period
  `ntsp`/`tsmult`). `hmp doctor --fix-config` drops the section.
- `geographic.bottom_path`. `hmp doctor --fix-config` moves it to `[[data.substratum.sources]]`.
- The `data-fetch` process. `data-request` replaces it and serves every `[data]` variable. Its
  report is `outputs/request.json`, and a chain links `extent.mask`.
- The sources `hubeau-piezometry`, `ign-bdalti` and `sim2-precipitation`. Use their `[data]` section.
- `DataManagers` and the analytical mock evaluator. Custom metrics use `objective = "module.path:fn"`.
- `[[testbed.variant]]` and `[[testbed.variant_from_catalog]]`, with the outputs `variant_id`,
  `variant_label` and `variant_count`. Use `[[testbed.case]]` and `case_id`, `case_label`, `case_count`.
- The Chèze lake project `19_cheze_reservoir` and the `new_to_sort` projects leave `examples/`.

### Fixed
- A stress-period stamp is the end of its period. Fluxes are now compared with the mean of the
  previous period and states at the stamp. Fit metrics, scores and figures follow.
- MODFLOW 6 adaptive time stepping hit the wrong stress period and ignored the requested
  sub-stepping. RMSE against the erfc closed form falls from 0.0481 m to 0.0035 m.
- MODPATH times from MODFLOW-NWT were labeled days but stored in seconds. Travel times and
  residence-time figures were off by a factor 86400.
- Geology is requested over the buffered box. A zero or non-finite K on an active cell is refused
  with its cause.
- The data cache no longer depends on where `hmp` starts. `hmp data prune`, `remove` and
  `check --fix` delete what they should, and orphan sidecars show in `hmp data check`.
- The BD Topage download no longer drops pages after the first short one, and the hydrography
  cache no longer serves an answer fetched for another question.
- `hmp data export` accepts per-cell budget fields such as `drain` and `recharge`.
- A NetCDF export loads in QGIS in EPSG:2154. Re-exporting onto an open file no longer truncates it.
- The PyHELP NetCDF export uses `recharge` and loads. A custom gridded source passes only its variable.
- A phase that lists an already calibrated parameter starts from the frozen value, on `cma_es` and
  `scipy_nelder_mead`. The later phase wins and the report names it re-opened.
- `hmp example add 04` works again, and `hmp viz show --output X` says it wrote `X.png`.
- `hmp list` can run beside `hmp run` because `SimulationCatalog` retries on DuckDB lock errors.

### Numbers
- Discharge NSE of the stored example 04 run moves from 0.531 to 0.665, and the stage-two
  `nse_log` from 0.595 to 0.731, because of the end-of-period stamp. A monthly run on the Nancon
  was off by 0.167 m3/s on average through the daily product, on a mean of 0.97 m3/s.
- Unstructured MODFLOW 6 heads and budgets change with the Voronoi default. Rebuild calibration caches.
- With `buff_area = "N%"` on the Nancon, the margin falls from 825 m to 150 m and the box domain
  from 151.9 to 120.4 km2.
- MODFLOW-NWT particle travel times and residence times change by a factor 86400.
- The geographic cache rebuilds once, and the uncertainty width leaves the params hash, so
  calibration caches rebuild once.

---

## [v1.0.0] - 2026-08-10

First stable release of HydroModPy, and the version described in the technical
note submitted to *Hydrology and Earth System Sciences*
([EGUsphere preprint](https://doi.org/10.5194/egusphere-2026-868)). This is the
reference cited by the paper. The `v1.0` branch stays open for `1.0.X` bug fixes
so the paper link always points to a working release, while feature development
continues on `main` as HydroModPy v2.

Install the maintained paper version with `pip install "hydromodpy==1.0.*"`,
which resolves to the latest `1.0.X` patch and never upgrades to the v2 series.

### Added
- First PyPI release published from GitHub, with MODFLOW, MODPATH and MT3D-USGS binaries bundled in the wheel.
- Release pipeline on GitHub Actions: tag/version guard, build, `twine check --strict`, PyPI Trusted Publishing (OIDC) and a GitHub release carrying the changelog notes.
- Weekly cross-platform install and example smoke tests on Linux, Windows, macOS x86 and macOS arm, for Python 3.11 to 3.13.
- Multi-version documentation served at <https://docs.hydromodpy.fr/v1.0/>, rebuilt on every push to the `v1.0` branch.

### Changed
- Repository, issues and CI moved from GitLab to GitHub.
- Documentation moved from ReadTheDocs to GitHub Pages under the `docs.hydromodpy.fr` domain.
- README leads with the pip installation path; authors, affiliations and title aligned with the preprint.
- Upper pin on `numpy` (`<2.5`) for `pysheds` compatibility, and `dask` added for multi-file xarray merges.
- Development status classifier raised to `5 - Production/Stable`.

### Fixed
- MODPATH particle flux is sampled with `rasterio` instead of `whitebox`.
- Interactive matplotlib backend detected through `backend_registry`.
- Watershed object is rebuilt when the stored pickle cannot be read.
- Transport and PyHELP examples run headless, without user interaction.

### Removed
- GitLab CI pipeline and ReadTheDocs configuration.

---

## [v0.3.5] - 2026-01-28
### Changed
- Pinned pandas to `<3.0` across pip/conda install files and docs to avoid breaking changes from pandas 3.0.

---

## [v0.3.4] - 2026-01-04
### Added
- Added `install/requirements-docker-light.txt` for pip-only Docker/server installs without IDE or visualization dependencies.
- Added optional Dask handling in SIM2 (chunked xarray only when Dask is available).

### Changed
- HydroModPy now loads display modules only when display features are invoked.
- Dockerfile updated for a light production flow using pip requirements.

### Fixed
- Improved PROJ database detection and fallback (including rasterio data dirs) to reduce `proj.db` layout errors in containers.

---

## [v0.3.3] - 2025-12-03
### Added
- Lightweight conda environment option (`env_hydromodpy_light.yml`) and matching light dependency set in `pyproject.toml` for setups without VTK or Jupyter kernels.

### Changed
- Replaced the former `downslope` helper with `masstransfer` as the single surface routing engine.
- Standardized raster reads on `imageio.v2` and removed deprecation warnings.
- Refactored SIM2 processing for leaner memory use.
- Simplified vedo imports in visualization routines and centralized PyHELP imports inside `watershed_root`.
- HELP3O loading now retries/resolves paths more reliably during PyHELP runs.
- Replace 'imageio' by 'rasterio' to resolve deprecation.

### Fixed
- Pandas warnings in PyHELP CSV ingestion and daily output aggregation (removed deprecated args and axis-based groupby).
- Multiprocessing pools in PyHELP now use a spawn context to avoid fork-in-multithreaded warnings on Python 3.11-3.13.

### Removed
- `hydromodpy.modeling.downslope` module (functionality consolidated into `masstransfer`).

---

## [v0.3.2] - 2025-11-28
### Changed
- Reworked SIM2 workflow: coarse clip without reprojection to trim inputs, resample on that reduced dataset, then final clip/mask with reprojection for clean outputs without wasted time or RAM.
- `disk_clip` now accepts `.shp`, `.gpkg`, and `.geojson`, and SIM2 filename parsing keeps the full variable name before `_SIM2_`.

### Fixed
- `toolbox.load_to_xarray` reprojects when `dst_crs` is provided even without a mask, matching the new SIM2 flow and avoiding extra memory use.
- SIM2 resampling preserves encodings and applies masking with the reprojected DEM consistently.

---

## [v0.3.1] - 2025-11-14
### Changed
- Installation guide reorganized with ready-made command recipes, dual YAML options (runtime vs editable), and clearer guidance for conda-versus-pip setups.
- README now flags v0.3.1 as the stable release and the conda YAMLs pin Python 3.11-3.13 explicitly.
- Add spyder package to the conda environment for users of that IDE.

### Fixed
- `pyproject.toml` now lets setuptools auto-discover all `hydromodpy*` packages so `pip install hydromodpy` (and ReadTheDocs builds) no longer fail if optional submodules such as `hydromodpy.modeling.gr4j` are absent from the current branch.
- Pinned NumPy to >= 2.0 and restricted supported Python to >= 3.11, < 3.14 to avoid incompatibilities with other packages.

---

## [v0.3.0] - 2025-11-06
### Compatibility
- Runtime baseline jumps from Python 3.8.10 to the Python 3.11-3.13 series. Tested on Linux, macOS, and Windows.

### Added
- Logging system with `LogManager` class (replaces all `print()` statements).
- GitHub Actions pipeline for automated builds and PyPI publication.
- Single cross-platform conda environment file (`environment-conda.yml`) for Linux, macOS, and Windows.
- Automatic download of HELP3O binaries on first use (no Fortran compiler needed).
- `MANIFEST.in` for packaging executables, examples, and documentation.
- Pin `PROJ_DATA` and `PROJ_LIB` to the active pyproj data folder to avoid stale `proj.db` files.
- Override external `PROJ_DATA` paths that leave the environment or miss `proj.db` so the environment copy always loads (problem often caused by gdal).
- `pyhelp` CLI now exports `PYHELP_WORKDIR` and `help_example.py --workdir` to stop the Windows crash on Example 10.

### Changed
- Renamed package from `src` to `hydromodpy` following standard Python conventions.
- Replaced GDAL with rasterio for pip-only installation (tested with Python 3.13).
- First version available via `pip install hydromodpy`.
- Conda installation now fully automatic with single environment file (with only conda-forge channels, no pip dependencies).
- Updated all imports in examples (00-11) from `src` to `hydromodpy`.
- PyHELP now downloads pre-compiled binaries instead of requiring Fortran compilation.
- Logging supports three modes: "dev" (DEBUG), "verbose" (INFO), "quiet" (WARNING).
- Replaced deepdish with pickle for serialization.

### Removed
- Platform-specific environment files (`env_pyhelp-0.1_windows.yml`, `environment-crossplatform-3119.yml`).
- Fortran compilation requirements for PyHELP.
- Unused FTP-AQUIFER utility scripts.
- Hard-coded GDAL dependencies.
- Removed obsolete third-party packages (e.g., hydroeval, deepdish) to ensure compatibility with Python 3.11+.

### Fixed
- Normalized example folder names.
- Cross-platform file path handling.
- Suppressed verbose logging from third-party libraries (matplotlib, flopy, etc.).
- PROJ data synchronization in PyHELP NetCDF writer.
- macOS HELP3O binary extraction.

---

## [v0.2.0] - 2025-11-05
### Added
- Added MT3D-USGS support with new `Mt3dms`, `Masstransfer`, and `watershed.transport` modules, included Example 09, and provided executables for Linux, macOS, and Windows.
- Added the GR4J rainfall-runoff calibration toolbox with scripts, figures, and sample data under `src/modeling/gr4j`.
- Added the PyHELP land-surface coupling (API, CLI, preprocessing) together with Example 10 resources and a Windows-only environment file.
- Added Example 11 to run the full workflow from scratch without plots.
- Added the `test/01_test_non-regression` suite and reference outputs for regression testing.
- Added yearly intermittency plus MT3D seepage concentration and accumulated mass to the timeseries exports.
- Added platform-specific conda environment files for HydroModPy 0.1.

### Changed
- Updated `modflow.py` to support elevation-driven decay parameters, optional EVT extinction depth, and creation of the LMT link file when using MT3DMS.
- Updated the hydraulic configuration so it keeps the new decay settings and `exdp` value.
- Updated `modpath.py` particle seeding to center start points, respect `model_folder`, and align forward and backward runs.
- Expanded the `watershed_root` workflow with transport functions, a calibration results folder, MT3DMS helper modules, and the PyHELP preprocessing function.
- Improved `timeseries` handling so recharge and runoff accept scalars, series, or dicts while exposing the new MT3D metrics.
- Updated geographic and hydrography helpers to fall back on existing DEM rasters and clip optional stream inputs.

### Fixed
- SIM2 climate ingestion now uses the current Météo-France variable names and units and exposes the soil drought index.
- Watershed visualizations restore the DEM color bar, scale bar, and labeled watershed overlay.
---

## [v0.1.0] - 2025-10-31
### Added
- **First official release** of the HydroModPy package.
- Established the initial project structure for hydrological/hydrogeological modeling workflows.
- Defined the versioning convention following **Semantic Versioning (vX.Y.Z)**.

---

[Unreleased]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0...dev
[v2.0.0]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0a5...v2.0.0
[v2.0.0a5]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0a4...v2.0.0a5
[v2.0.0a4]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0a3...v2.0.0a4
[v2.0.0a3]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0a2...v2.0.0a3
[v2.0.0a2]: https://github.com/HydroModPy/HydroModPy/compare/v2.0.0a1...v2.0.0a2
[v2.0.0a1]: https://github.com/HydroModPy/HydroModPy/compare/v1.0.0...v2.0.0a1
[v1.0.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.5...v1.0.0
[v0.3.5]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.4...v0.3.5
[v0.3.4]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.3...v0.3.4
[v0.3.3]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.2...v0.3.3
[v0.3.2]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.1...v0.3.2
[v0.3.1]: https://github.com/HydroModPy/HydroModPy/compare/v0.3.0...v0.3.1
[v0.3.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.2.0...v0.3.0
[v0.2.0]: https://github.com/HydroModPy/HydroModPy/compare/v0.1.0...v0.2.0
[v0.1.0]: https://github.com/HydroModPy/HydroModPy/releases/tag/v0.1.0
