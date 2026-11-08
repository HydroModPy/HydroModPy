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
| `hydromodpy_config.py` | what is a whole project file? `HydroModPyConfig` (the root), `WorkflowConfig` (the `[workflow]` section), the loading entry points `from_toml`, `from_dict`, `from_json`, `from_snapshot`, the cross-section checks, and `ROOT_CONFIG`, the root class and its two migrations handed to the core helpers as an argument |
| `cross_checks.py` | which keys of a file does the flow solver of the run leave unread, and which pairs of keys spoil each other? It reads the traits the file uses against the `supports` of the solver, a transport solver against the `requires` it names, and the rows of `CONTAMINATIONS`. It names no solver, so a plugin solver is checked like the shipped ones |
| `section_loader.py` | how is one raw section turned into its model, with paths resolved against the project root? `load_standard_section`, `load_optional_section`, `load_geographic_section`. It serves a TOML file and a mapping alike |
| `sites.py` | the `[sites]` section as the TOML declares it, checked without reading any file, and `is_sites_project`. The plan of a campaign built from it lives in `project/launch/sites/` |
| `toml_examples.py` | `flow_examples(threshold, section_renderer)`, the commented example blocks of the dynamic `[flow.param.*]`, `[flow.bc.*]` and `[flow.sinks_sources.*]` tables. An app that writes the TOML template passes it to `generate_toml` |
| `config_migration.py` | how does a file written against an earlier schema still load? `migrate_config_doc_on_load` rewrites the parsed payload in memory; `fix_config_file` (called by `hmp doctor --fix-config <file>`) rewrites the file in place. `RENAMED_KEYS` lists the keys a file wrote under an old name: a load warns, or refuses a key of `[calibration]`, the doctor renames them, and `migrate_sealed_config_doc` renames them on read in the frozen config of a run on disk. A network output moves across its tables `map`, `model` and `verdict`, which a rename row cannot do, so `_rewrite_the_network_outputs` writes it, for the doctor and for a sealed read, from the rows of `CALIBRATION_RENAMES` |
| `export_checks.py` | the checks of `[[export]]` names and of the dates of `[[export]]` and `[display]` against the run (`check_export_variables`, `check_time_selectors`), run by step 0 and by `hmp config check` (`project/check.py`) |

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
         expand the calibration protocol
         refuse retired sections and unknown top-level sections
         parse [workspace] first                        its data folder serves every other section
         one loader per section                         relative paths resolved against the project root
         model_validate on the root                     cross-section checks run here
         name from the file name when [simulation].name is empty
```

The project root is the folder that holds `project.toml` at or above the file;
outside a project, the folder of the root file of the `base_config` chain. Every
relative path of every file of a project (`plan/<hash>/<case>.toml`,
`runs/<case>/config.toml`, `site_overrides/<site>.toml`) is read from it, so a
file two folders down names the same `dem_init_path` as `project.toml` does.

`from_dict` takes the same road from a mapping, with `context="api"`, and so does
`from_json` when it is given a `base_dir`. Without one, `from_json` validates the
JSON payload as it is, with `model_validate_json`: no migration, no path
resolved, and a refusal is a Pydantic error. `from_snapshot` rebuilds a config
from the JSON snapshot stored with a run.

`[workspace].project_root` is never a key of a file: the loader sets it from
the location of the file (the environment variable `HMP_PROJECT_ROOT` wins);
an `api` payload defaults it to the base folder. A refusal leaves
`_from_payload` as a `ConfigValidationError` that names the section, never as a
bare Pydantic error.

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
gives the numbers of `hmp run --dry-run`; `check.check_project` is the one
check of `hmp config check` for a run, a calibration or a whole project
(`project/check.py`). A `[site]` alone is resolved against the site catalog of
the workspace by `data/sites/single_site.py`.

Cross-section checks of the root (`_check_cross_section_coherence`), each refused
with a sentence:

- `data.inference_mode = "strict"` needs a non-empty `data.types`;
- a `domain.depth_model` of a raster kind reads `[data.substratum]`, which must
  be declared;
- a declared `[data.soil_capacity]` needs `[flow.sinks_sources.recharge.soil]`,
  and that soil reservoir is checked against what it reads and where it runs: the
  precipitation and ETP sections it needs, no loaded `recharge` or `runoff`, a
  declared `[simulation.time]`, and its spin-up;
- `[calibration]` needs a non-empty `flow.param_list`;
- `cross_checks.check_against_the_solver` runs last. Every key the file uses
  that the flow solver leaves out of `supports` (a boundary, a `[solver]`
  option, an initial state, the soil reservoir, flow barriers, layers, a K tensor)
  raises `IncompatibleCapabilitiesError`, with the key the file wrote and the
  solvers that honour it. A transport solver whose `requires` does not name the
  flow solver is refused, and so are the pairs of `CONTAMINATIONS`, a lake with
  a `spinup_cyclic` start for instance. On a sealed run each refusal only warns.

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
   `HydroModPyConfig`, and its entry in `section_loaders` of `_from_payload`.
3. **A renamed or moved key.** A rule in `config_migration.py`, so earlier files
   still load, with a test. A retired key is refused by the model with the key
   to write: no migration carries it.
4. **A retired section.** One row of `RETIRED_SECTIONS` in `hydromodpy_config.py`,
   with the sentence that names the replacement.
5. **A cross-section rule.** `_check_cross_section_coherence`, only when the rule
   needs two sections; a rule on one section belongs in that section's model. A
   rule that depends on the flow solver is not written here. The solver lists the
   trait in `supports`, and `cross_checks.py` refuses it.

## Reading path

1. `hydromodpy_config.py`: the fields of the root, then `_from_payload`.
2. `core/toml_io/loader.py` for the `base_config` chain.
3. `core/config_kit/profile.py` and `introspect.py` for the visibility model.
4. One section model, for example `model/flow_config.py`.
5. `schema/config_schema.py` for what is exported to frontends and IDEs.
