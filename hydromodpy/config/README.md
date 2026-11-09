# `hydromodpy/config`

The root of the configuration. `HydroModPyConfig` is the one Pydantic model that
aggregates every section of a project TOML. Anything a user can write in a project
file must load through it and round-trip. This file is the map of the package:
what is here, which section is owned by which package, how a TOML becomes a
validated object, and where to add what.

The package is thin on purpose. Each section model lives next to the code it
configures. The composition root is the only place where the section types of
the other packages are imported together; every other layer refers to its own
section model, never to the root.

## Parts

| part | answers |
|---|---|
| `hydromodpy_config.py` | what is a whole project file? `HydroModPyConfig` (the root), `WorkflowConfig` (the `[workflow]` section), the loading entry points `from_toml`, `from_dict`, `from_json`, `from_snapshot`, and `ROOT_CONFIG`, the root class and its two migrations handed to the core helpers as an argument. The root builds its sections through `section_loader.py` and runs the rows of `CROSS_RULES`, so it holds no rule of its own |
| `check.py` | what is wrong in this document, and what is left to fill? `check(document, partial=True, inputs=False, base=None, bounds=None)` gives a list of `Diagnostic`, every one at once, section by section. It reads no file unless `inputs` is true. `CHECK_CODES` lists the 22 codes, and `phrase(code, lang)` reads the sentence of a code from `schema/phrases.toml`. `HydroModPyConfig.from_toml` is this check with `partial=False`, followed by the building of the root |
| `cross_checks.py` | which keys of a file spoil each other, and which does the flow solver of the run leave unread? `CROSS_RULES` is the table of every rule that reads several sections, one `CrossRule(rule, reads)` per row, named by its function and run in the order of the table. `reads` names the sections the rule needs, and a test holds it equal to what the function reads. The solver rows read the traits the file uses against the `supports` of the solver, a transport solver against the `requires` it names, and the rows of `CONTAMINATIONS`. They name no solver, so a plugin solver is checked like the shipped ones. The checks of the `[[export]]` names and of the dates of `[[export]]` and `[display]` are rows of the same table |
| `section_loader.py` | how is a raw document turned into validated sections? `SECTIONS` is the table of the root sections (loader, default, required or not), and `validate_sections` walks it and keeps every fault. The steps that run before it are here too: the old forms of a key, the retired sections, `[workspace]` by default, the calibration defaults. `from_toml` and `check` walk the same table, so they cannot disagree. The loaders (`load_standard_section`, `load_optional_section`, `load_geographic_section`) resolve paths against the project root and serve a TOML file and a mapping alike |
| `input_headers.py` | do the input files open, and do they hold their contract? `read_input_headers(sections, *, base, bounds)` opens the header of each raster or vector the document names, from a local path or from the final URL of a remote file through `/vsicurl/`, in a `rasterio.Env` of its own. Only `check(inputs=True)` imports it, because rasterio is slow to import |
| `sites.py` | the `[sites]` section as the TOML declares it, checked without reading any file, and `is_sites_project`. The plan of a campaign built from it lives in `project/launch/sites/` |
| `toml_examples.py` | `flow_examples(threshold, section_renderer)`, the commented example blocks of the dynamic `[flow.param.*]`, `[flow.bc.*]` and `[flow.sinks_sources.*]` tables. An app that writes the TOML template passes it to `generate_toml` |
| `config_migration.py` | how does a file written against an earlier schema still load? It applies the `document = "config"` rows of `schema/changes.toml` in the order of the file, and `RULES` holds the three functions a row names when it cannot say the whole change. `migrate_config_doc_on_load` rewrites the parsed payload in memory, with a warning for two minor versions and then a refusal with the new name. `fix_config_file` (called by `hmp doctor --fix-config <file>`) rewrites the file in place, and `migrate_sealed_config_doc` reads the frozen config of a run on disk in silence. The 175 keys and values only a pre-release of 2.0 wrote are listed in `prerelease_forms.txt` and refused with every such key at once, with the way to the doctor of a 2.0.x release. `apply_edition` fills a key a file leaves out with the default of the edition it writes |

`from hydromodpy.config import HydroModPyConfig` resolves the class lazily, so
importing the package loads no model.

## Sections of the root

One field of `HydroModPyConfig` per top-level TOML section. Required: `workflow`,
`workspace`, `geographic`. The others have a default or are optional.

| section | model | defined in |
|---|---|---|
| `[workflow]` | `WorkflowConfig` | `config/hydromodpy_config.py` |
| `[workspace]` | `WorkspaceConfig` | `core/workspace/config.py` |
| `[geographic]` | `GeographicConfig` | `catchment/preprocess/` |
| `[domain]` | `DomainConfig` | `model/domain/` |
| `[data]` | `DataManagersConfig` | `data/loading/config_schema.py` |
| `[flow]` | `FlowConfig` | `model/flow_config.py` |
| `[transport]` | `TransportConfig` | `model/transport/` |
| `[simulation]` | `SimulationConfig` | `solver/base/simulation_config.py` |
| `[solver]` | `SolverConfig`, with one settings table per flow solver (`[solver.modflow6]`, `[solver.modflow_nwt]`, `[solver.boussinesq]`), each checked by the `options` class of that solver | `solver/base/solver_config.py` |
| `[display]` | `DisplayConfig` | `display/config.py` |
| `[[export]]` | `ExportRequest` (a list) | `results/exporters/export_spec.py` |
| `[observation]` | `ObservationConfig` | `solver/base/observation_config.py` |
| `[overview]` | `OverviewConfig` | `display/overview/config.py` |
| `[mesh]` | `MeshConfig` | `mesh/mesh_config.py` |
| `[calibration]` | `CalibrationConfig` | `calibration/config.py` |
| `[spinup]` | `SpinupConfig` | `model/initial/spinup_config.py` |
| `[site]` | `SiteConfig` | `core/site/config.py` |
| `[sites]` | `SitesConfig` | `config/sites.py` |
| `[metrics]` | `MetricsConfig` | `results/metric_rule.py` |
| `[publication]` | `PublicationConfig` | `results/publication.py` |

`[workflow].mode` is one of `simulation`, `calibration`, `overview`
(`WorkflowMode`), and is optional: unset, the sections of the file say what
`hmp run` does (`workflow/dispatch.py`). A retired mode (`comparison`,
`testbed`) is refused with its replacement
(`RETIRED_WORKFLOW_MODES`). `[site]` and `[sites]` never coexist: a `[sites]`
project takes the site of each case from its table row.

A retired root section (`[analysis]`, `[batch]`, `[persistence]`, `[mesh_catchment]` and the
others) is refused by name with what replaces it. The ten of them are one table,
`RETIRED_SECTIONS`, read by `_from_payload` and by a direct `model_validate` alike.

The generated reference of the sections is the TOML reference of the
documentation; it is built from these models.

## Invariants of a section model

Each model honors the rules of the project:

- it derives from `HydroModelBase` (`core/config_kit/base.py`), which sets
  `extra="forbid"` and `validate_assignment=True`, so a typo in a key is refused;
- each field is `Annotated` with a `Profile` (`USER`, `DEV` or `EXPERT`, in
  `core/config_kit/profile.py`) and, for a physical quantity, with a unit alias of
  `core/units`;
- each field has a `Field` description, which is the text of its card in the
  reference.

## How a TOML becomes a config

```
hmp run file.toml
  -> HydroModPyConfig.from_toml(path)
       core/toml_io/loader.load_toml_with_base_config   follows base_config, merges, detects cycles
       config_migration.migrate_config_doc_on_load      earlier schema, in memory, file untouched
       (optional) profile check                         a field above the asked profile warns
       _from_payload(raw, base=<project root>)          core/toml_io/loader.config_base_dir
         the resolutions on a copy                      old forms, retired sections, [workspace] by default, calibration protocol and defaults, gauge
         validate_sections                              one loader per section, the walk of config/check.py, every fault kept
         build the root                                 name from the file name when [simulation].name is empty
         CROSS_RULES                                    every row once, in the order of the table
         raise the first fault                          the type and the exit code of today, carrying every diagnostic
```

The project root is the folder that holds `project.toml` at or above the file;
outside a project, the folder of the root file of the `base_config` chain. Every
relative path of every file of a project (`plan/<hash>/<case>.toml`,
`runs/<case>/config.toml`, `site_overrides/<site>.toml`) is read from it, so a
file two folders down names the same `path` of a `source = "file"` entry of
`[data]` as `project.toml` does.

`from_dict` takes the same road from a mapping, with `context="api"`, and so does
`from_json` when it is given a `base_dir`. Without one, `from_json` validates the
JSON payload as it is, with `model_validate_json`: no migration, no path
resolved, and a refusal is a Pydantic error. `from_snapshot` rebuilds a config
from the JSON snapshot stored with a run.

`[workspace].project_root` is never a key of a file: the loader sets it from
the location of the file (the environment variable `HMP_PROJECT_ROOT` wins);
an `api` payload defaults it to the base folder. A refusal leaves
`_from_payload` as a `ConfigValidationError` that names the section, never as a
bare Pydantic error. Its `details` hold one entry for every fault of the document,
and its type and its exit code are those of the first one.

A document can be checked before it is whole. `check(document, partial=True)` gives
a `to_fill` diagnostic for each required key not written yet, and runs a rule across
sections once every section it reads is complete. `partial=False` turns each
`to_fill` into an error and changes nothing else, and it is what a run asks for.

## A campaign: `[sites]` x `[sites.recipes]`

`project/launch/sites/expansion.expand_plan(project_root, config_path)` resolves one
case per (site, recipe): the site table (`[sites] table`, or the site catalog
of the workspace) rendered through `[sites.bind]`, `site_overrides/<site>.toml`,
the recipe's own keys, then `--set` and `HMP_SET_*`. Precedence, lowest first:
defaults < the base of the recipe < the rendered row < the site overlay < the
recipe's own keys (its file, its inline `set`, its row of `recipes_table`) <
`--set`. Each case is validated through `HydroModPyConfig.from_dict`, hashed
by `config_identity_hash` without `[workspace]`, and refused when a site scoped
key keeps a literal value (`project/launch/sites/site_scoped.py`). An error names its
cell: `sites.csv:37 column x_outlet -> geographic.catchment.x_outlet: ...`,
grouped over the cases it touches. `plan.write_plan_draft` writes the plan once
under `plan/<hash>/` through `results/plan_store.py`; `budget.plan_budget`
gives the numbers of `hmp run --dry-run`; `hmp.check` (`project/api.py`) is the one
check of `hmp config check` for a run, a calibration or a whole project, and it
gives each case of a `[sites]` project the diagnostic `sites_case`. A `[site]` alone is resolved against the site catalog of
the workspace by `data/sites/single_site.py`.

Cross-section rules of the root, the rows of `CROSS_RULES`, each refused with a
sentence:

- `data.inference_mode = "strict"` needs a non-empty `data.types`;
- a `domain.depth_model` of a raster kind reads `[data.substratum]`, which must
  be declared;
- a declared `[data.soil_capacity]` needs `[flow.sinks_sources.recharge.soil]`,
  and that soil reservoir is checked against what it reads and where it runs: the
  precipitation and ETP sections it needs, no loaded `recharge` or `runoff`, a
  declared `[simulation.time]`, and its spin-up;
- `[calibration]` needs a non-empty `flow.param_list`;
- the solver rows of `CROSS_RULES` come after those, and the rules of the soil reservoir, of the layers and of the mesh after them. Every key the file uses
  that the flow solver leaves out of `supports` (a boundary, a `[solver]`
  option, an initial state, the soil reservoir, flow barriers, layers, a K tensor)
  raises `IncompatibleCapabilitiesError`, with the key the file wrote and the
  solvers that honour it. A transport solver whose `requires` does not name the
  flow solver is refused, and so are the pairs of `CONTAMINATIONS`, a lake with
  a `spinup_cyclic` start for instance. The last two rows refuse a date or a name of
  `[[export]]` and `[display]` that the run could not honour. On a sealed run the
  rules that check the run only warn, which is the case of the solver rows, of the
  window of `[metrics]` and of the two export rows.

## Import rules

`config` imports `core`, `model`, `data`, `catchment`,
`solver`, `calibration`, `results` and `display`
(`tests/unit/architecture/layer_matrix.yaml`): every layer it composes, and
nothing above them. Only the root facade, `workflow`, `project` and `cli` import
it. A lower layer receives the root model or class as an argument, and
`calibration` loads configuration through `trial_pipeline()`.

## Where to add what

1. **A field in an existing section.** On that section's model, with a `Profile`,
   a unit alias when it is a quantity, and a description. The parameter
   reference is computed from the model at the next documentation build
   (`tools/docs/field_registry.py`). The committed JSON Schema,
   `docs/source/_static/hydromodpy-schema.json`, is compared with the model by
   `tests/unit/docs/test_docs_config_consistency.py`.
   `docs/source/contribute/architecture/how-to/add-a-config-field.rst` has the
   steps.
2. **A new top-level section.** A model in the package it configures, a field on
   `HydroModPyConfig`, and its row in `SECTIONS` of `section_loader.py`.
3. **A renamed or moved key.** A `[[migration]]` row of `schema/changes.toml`, so
   earlier files still load, with a test. A row names a function of `RULES` only
   when it cannot say the whole change. A retired key is refused by the model with
   the key to write: no migration carries it.
4. **A retired section.** One row of `RETIRED_SECTIONS` in `section_loader.py`,
   with the sentence that names the replacement.
5. **A cross-section rule.** One row of `CROSS_RULES` in `cross_checks.py`, with
   the sections it reads in `reads`, only when the rule needs two sections. A rule
   on one section belongs in that section's model. A rule that depends on the flow
   solver is not written by hand: the solver lists the trait in `supports`, and the
   solver rows of the same table refuse it.

## Reading path

1. `hydromodpy_config.py`: the fields of the root, then `_from_payload`.
   Then `check.py`, which walks the same sections and keeps every diagnostic.
2. `core/toml_io/loader.py` for the `base_config` chain.
3. `core/config_kit/profile.py` and `introspect.py` for the visibility model.
4. One section model, for example `model/flow_config.py`.
5. `schema/config_schema.py` for what is exported to frontends and IDEs.
